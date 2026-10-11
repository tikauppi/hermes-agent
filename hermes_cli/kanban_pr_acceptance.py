"""Exact-head GitHub acceptance for explicitly declared PR tasks.

Network work happens outside SQLite transactions. The lifecycle owner persists
receipts only after rechecking the captured run/status/contract under its lock.
"""
from __future__ import annotations

import json
import re
import subprocess
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import quote

_REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
_PR = re.compile(r"https://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/pull/([1-9][0-9]*)")
_API_BASE = "https://api.github.com"
_MAX_RESPONSE_BYTES = 16 * 1024 * 1024
_MAX_PAGES = 20


class _GitHubApiError(Exception):
    def __init__(self, classification: str):
        super().__init__(classification)
        self.classification = classification


def validate_contract(value: str | None) -> str:
    if value is None or value == "local-only":
        return "local-only"
    if not isinstance(value, str) or not (_REPO.fullmatch(value) or _PR.fullmatch(value)):
        raise ValueError("completion_contract must be local-only, OWNER/REPO, or an exact GitHub PR URL")
    return value


def _token() -> str:
    # The kanban worker runs under a profile. Read that profile's scoped secret
    # before falling back to gh's credential store; never pass a token in argv.
    from hermes_cli.config import get_env_value

    token = get_env_value("GITHUB_TOKEN") or get_env_value("GH_TOKEN")
    if token:
        return token
    try:
        result = subprocess.run(
            ["gh", "auth", "token"], stdin=subprocess.DEVNULL, capture_output=True,
            text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        result = None
    if result is not None and result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    raise _GitHubApiError("unauthorized")


def _http_classification(status: int) -> str:
    return {401: "unauthorized", 403: "forbidden", 404: "not_found"}.get(status, "infra")


def _graphql_classification(errors: list) -> str:
    kinds = {
        str(error.get("type") or (error.get("extensions") or {}).get("type") or "").upper()
        for error in errors if isinstance(error, dict)
    }
    if kinds & {"UNAUTHORIZED", "UNAUTHENTICATED"}:
        return "unauthorized"
    if "FORBIDDEN" in kinds:
        return "forbidden"
    if "NOT_FOUND" in kinds:
        return "not_found"
    return "infra"


def _request(url: str, token: str, query: str | None = None) -> tuple[Any, str | None]:
    body = None if query is None else json.dumps({"query": query}).encode("utf-8")
    request = urllib.request.Request(
        url, data=body, method="POST" if body is not None else "GET",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "hermes-kanban-pr-acceptance",
            **({"Content-Type": "application/json"} if body is not None else {}),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = response.read(_MAX_RESPONSE_BYTES + 1)
            if len(payload) > _MAX_RESPONSE_BYTES:
                raise _GitHubApiError("infra")
            return json.loads(payload), response.headers.get("Link")
    except urllib.error.HTTPError as exc:
        # Do not read or persist the response body: private-repo errors can
        # contain organization details and authentication diagnostics.
        raise _GitHubApiError(_http_classification(exc.code)) from None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, UnicodeError):
        raise _GitHubApiError("infra") from None


def _next_link(link: str | None) -> str | None:
    if not link:
        return None
    for part in link.split(","):
        match = re.fullmatch(r'\s*<([^>]+)>;\s*rel="([^"]+)"\s*', part)
        if match and match[2] == "next":
            if not match[1].startswith(_API_BASE.rstrip("/") + "/"):
                raise _GitHubApiError("infra")
            return match[1]
    return None


def _api(endpoint: str, *, query: str | None = None, paginate: bool = False) -> Any:
    token = _token()
    url = f"{_API_BASE.rstrip('/')}/{endpoint.lstrip('/')}"
    if not paginate:
        value, _ = _request(url, token, query)
        if isinstance(value, dict) and value.get("errors"):
            raise _GitHubApiError(_graphql_classification(value["errors"]))
        return value
    pages = []
    for _ in range(_MAX_PAGES):
        value, link = _request(url, token)
        pages.append(value)
        url = _next_link(link)
        if url is None:
            return pages
    raise _GitHubApiError("infra")


def collect_acceptance(contract: str, published_pr: str | None) -> dict:
    receipt = {"ok": False, "classification": "missing", "head_sha": None,
               "pr_url": published_pr, "checks": [],
               "recovery": "Fix required failures, rerun infrastructure checks or wait, then retry completion. "
                           "Use kanban_block if human input is needed; receipts remain on the task event log."}
    try:
        declared = _PR.fullmatch(contract)
        url = contract if declared else published_pr
        match = _PR.fullmatch(url or "")
        if not match or (not declared and match[1] != contract) or (declared and published_pr and published_pr != contract):
            receipt["detail"] = "Supply metadata.published_pr matching the persisted completion contract."
            return receipt
        repo, number = match[1], int(match[2])
        receipt["pr_url"] = url
        owner, name = repo.split("/")
        query = '''{repository(owner:%s,name:%s){pullRequest(number:%d){headRefOid baseRefName state
            baseRef{branchProtectionRule{requiredStatusChecks{context app{databaseId}}}}}}}''' % (
                json.dumps(owner), json.dumps(name), number)
        pr = _api("graphql", query=query)["data"]["repository"]["pullRequest"]
        sha, branch = pr["headRefOid"], pr["baseRefName"]
        receipt["head_sha"] = sha
        if not re.fullmatch(r"[0-9a-f]{40}", sha) or pr["state"] not in {"OPEN", "MERGED"}:
            raise ValueError("PR is closed or current head is unavailable")
        protection = (pr.get("baseRef") or {}).get("branchProtectionRule") or {}
        required: set[tuple[str, int | None]] = {
            (r["context"], (r.get("app") or {}).get("databaseId"))
            for r in protection.get("requiredStatusChecks", [])
        }
        rules = _api(f"repos/{repo}/rules/branches/{quote(branch, safe='')}?per_page=100", paginate=True)
        for page in rules:
            for rule in page:
                if rule["type"] == "required_status_checks":
                    required.update((r["context"], r.get("integration_id"))
                                    for r in rule["parameters"]["required_status_checks"])
        receipt["required"] = [{"context": c, "app_id": a} for c, a in sorted(required, key=str)]
        if not required:
            receipt["detail"] = "No repository-required checks are configured; explicitly use a local-only contract for non-CI tasks."
            return receipt
        pages = _api(f"repos/{repo}/commits/{sha}/check-runs?per_page=100&filter=latest", paginate=True)
        runs = [run for page in pages for run in page["check_runs"]]
        if len({r["id"] for r in runs}) != pages[0]["total_count"]:
            raise ValueError("Incomplete check-run pagination")
        statuses = [{**s, "sha": sha} for page in _api(f"repos/{repo}/commits/{sha}/statuses?per_page=100", paginate=True) for s in page]
        outcomes = []
        for context, app_id in sorted(required, key=str):
            matching = [r for r in runs if r["name"] == context and
                        (app_id in (None, -1) or r["app"]["id"] == app_id)]
            # A legacy status can satisfy an unpinned context, but never a check pinned to an app.
            legacy = [s for s in statuses if s["context"] == context] if app_id in (None, -1) else []
            selected = matching + ([max(legacy, key=lambda s: s["id"])] if legacy else [])
            if not selected:
                outcomes.append("missing")
                receipt["checks"].append({"name": context, "classification": "missing", "head_sha": sha})
            for check in selected:
                is_run = "conclusion" in check
                outcome = check.get("conclusion") if is_run else check["state"]
                classification = _classify(check, sha, outcome, is_run)
                outcomes.append(classification)
                receipt["checks"].append({"name": context, "id": check["id"],
                    "url": check.get("html_url") or check.get("target_url"),
                    "head_sha": check.get("head_sha", check.get("sha")),
                    "classification": classification, "conclusion": outcome})
        # Re-read after all pages: old-head successes are never transferable.
        current = _api(f"repos/{repo}/pulls/{number}")
        provenance_ok = (
            current.get("number") == number
            and current.get("html_url") == url
            and (current.get("base") or {}).get("repo", {}).get("full_name") == repo
        )
        if (not provenance_ok or current["head"]["sha"] != sha
                or current["base"]["ref"] != branch
                or (current["state"] == "closed" and not current.get("merged"))):
            receipt.update(classification="stale", detail="PR head/base changed while collecting evidence; retry.")
            return receipt
        receipt["classification"] = next((x for x in outcomes if x != "success"), "missing" if not outcomes else "success")
        receipt["ok"] = receipt["classification"] == "success"
        return receipt
    except _GitHubApiError as exc:
        detail = {
            "unauthorized": "GitHub API authentication is missing or rejected; configure a profile-scoped token and retry.",
            "forbidden": "GitHub API denied required acceptance evidence; repository permission or plan policy may block collection.",
            "not_found": "GitHub API did not expose the declared PR or required policy; verify private-repository visibility and the contract.",
            "infra": "GitHub acceptance evidence is unavailable or incomplete; retry the authenticated API collection.",
        }[exc.classification]
        receipt.update(classification=exc.classification, detail=detail)
        return receipt
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError, IndexError):
        # Never persist gh stderr (credentials/host details); the failed phase is actionable.
        receipt.update(classification="infra", detail="GitHub acceptance evidence unavailable or incomplete; check gh authentication/API access and retry.")
        return receipt


def _classify(check: dict, sha: str, outcome: str | None, is_run: bool) -> str:
    if check.get("head_sha", check.get("sha")) != sha:
        return "stale"
    if is_run and check.get("status") != "completed":
        return "pending"
    if outcome is None:
        return "infra"
    return {"success": "success", "failure": "failure", "error": "infra", "pending": "pending"}.get(outcome, "infra")

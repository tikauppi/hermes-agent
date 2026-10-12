"""Exact-head GitHub acceptance for explicitly declared PR tasks.

Network work happens outside SQLite transactions. The lifecycle owner persists
receipts only after rechecking the captured run/status/contract under its lock.
"""
from __future__ import annotations

import http.client
import json
import re
import urllib.error
import urllib.request
from typing import Any, NamedTuple, NoReturn
from urllib.parse import quote, urlsplit

_REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
_PR = re.compile(r"https://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/pull/([1-9][0-9]*)")
_API_BASE = "https://api.github.com"
_MAX_RESPONSE_BYTES = 16 * 1024 * 1024
_MAX_PAGES = 20
_GITHUB_RECEIPT_PATH = re.compile(
    r"/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/(?:"
    r"actions/runs/[1-9][0-9]*(?:/job/[1-9][0-9]*)?"
    r"|commit/[0-9a-fA-F]{40}/checks)"
)


class _TrustedAcceptanceBinding(NamedTuple):
    head_sha: str
    base_ref: str
    required_checks: frozenset[tuple[str, int]]


_TRUSTED_ACCEPTANCE_BINDINGS = {
    "https://github.com/tikauppi/THESEUS/pull/25": _TrustedAcceptanceBinding(
        head_sha="c0a7d0d5bf1a69bf8e0968caf5343350d43d1d83",
        base_ref="integration/126-canonical-s121-s123-full-vue-recovery",
        required_checks=frozenset({("build-test", 15368)}),
    ),
}


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
    # The profile-owned .env file is the sole approved credential source.
    # Ambient variables and global credential helpers can belong to another profile.
    from hermes_cli.config import load_env

    scoped = load_env()
    token = scoped.get("GITHUB_TOKEN") or scoped.get("GH_TOKEN")
    if token:
        return token
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
    except (
        urllib.error.URLError,
        http.client.HTTPException,
        TimeoutError,
        json.JSONDecodeError,
        UnicodeError,
    ):
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


def _sanitize_provider_url(value: Any) -> str | None:
    """Return only canonical GitHub check/status links safe for receipts."""
    if not isinstance(value, str) or not value or not value.isascii():
        return None
    if any(
        character.isspace() or ord(character) < 0x20 or ord(character) == 0x7F
        for character in value
    ):
        return None
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return None
    dot_segment = any(
        segment and not segment.strip(".") for segment in parsed.path.split("/")
    )
    if (
        parsed.scheme != "https"
        or parsed.netloc not in {"github.com", "github.com:443"}
        or parsed.hostname != "github.com"
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
        or "%" in parsed.netloc
        or "%" in parsed.path
        or "\\" in parsed.netloc
        or "\\" in parsed.path
        or dot_segment
        or not _GITHUB_RECEIPT_PATH.fullmatch(parsed.path)
    ):
        return None
    return f"https://github.com{parsed.path}"


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


def _schema_error() -> NoReturn:
    raise _GitHubApiError("infra")


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_positive_int(value: Any) -> bool:
    return _is_int(value) and value > 0


def _is_sha(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-fA-F]{40}", value) is not None


def _is_check_name(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip()) and all(0x20 <= ord(c) != 0x7F for c in value)


def _is_branch_name(value: Any) -> bool:
    return (
        isinstance(value, str) and bool(value) and not value.startswith(("/", "."))
        and not value.endswith(("/", ".", ".lock")) and ".." not in value and "@{" not in value
        and "//" not in value and not any(c.isspace() or c in "~^:?*[\\" or ord(c) < 0x20 for c in value)
    )


def _graphql_pr(payload: Any) -> dict:
    data = payload.get("data") if isinstance(payload, dict) else None
    repository = data.get("repository") if isinstance(data, dict) else None
    pr = repository.get("pullRequest") if isinstance(repository, dict) else None
    if not isinstance(pr, dict) or not _is_sha(pr.get("headRefOid")) or not _is_branch_name(pr.get("baseRefName")) or pr.get("state") not in {"OPEN", "CLOSED", "MERGED"}:
        _schema_error()
    base_ref = pr.get("baseRef")
    if base_ref is not None:
        protection = base_ref.get("branchProtectionRule") if isinstance(base_ref, dict) else None
        if not isinstance(base_ref, dict) or (protection is not None and not isinstance(protection, dict)):
            _schema_error()
        if protection is not None:
            checks = protection.get("requiredStatusChecks")
            if not isinstance(checks, list):
                _schema_error()
            for check in checks:
                app = check.get("app") if isinstance(check, dict) else None
                database_id = app.get("databaseId") if isinstance(app, dict) else None
                if not isinstance(check, dict) or not _is_check_name(check.get("context")) or (app is not None and (not isinstance(app, dict) or (database_id is not None and not _is_positive_int(database_id)))):
                    _schema_error()
    return pr


def _rules_pages(payload: Any) -> list[list[dict]]:
    if not isinstance(payload, list):
        _schema_error()
    for page in payload:
        if not isinstance(page, list):
            _schema_error()
        for rule in page:
            if not isinstance(rule, dict) or not _is_check_name(rule.get("type")):
                _schema_error()
            if rule["type"] == "required_status_checks":
                parameters = rule.get("parameters")
                checks = parameters.get("required_status_checks") if isinstance(parameters, dict) else None
                if not isinstance(checks, list):
                    _schema_error()
                for check in checks:
                    integration_id = check.get("integration_id") if isinstance(check, dict) else None
                    if not isinstance(check, dict) or not _is_check_name(check.get("context")) or (integration_id is not None and not _is_positive_int(integration_id)):
                        _schema_error()
    return payload


def _check_run_pages(payload: Any) -> list[dict]:
    if not isinstance(payload, list) or not payload:
        _schema_error()
    statuses = {"queued", "in_progress", "completed", "waiting", "requested", "pending"}
    conclusions = {"action_required", "cancelled", "failure", "neutral", "success", "skipped", "stale", "timed_out"}
    for page in payload:
        if not isinstance(page, dict) or not _is_int(page.get("total_count")) or page["total_count"] < 0 or not isinstance(page.get("check_runs"), list):
            _schema_error()
        for run in page["check_runs"]:
            app = run.get("app") if isinstance(run, dict) else None
            if not isinstance(run, dict) or not _is_positive_int(run.get("id")) or not _is_check_name(run.get("name")) or not _is_sha(run.get("head_sha")) or not isinstance(app, dict) or not _is_positive_int(app.get("id")) or run.get("status") not in statuses or (run.get("conclusion") is not None and run.get("conclusion") not in conclusions) or (run.get("status") == "completed" and run.get("conclusion") is None):
                _schema_error()
    return payload


def _status_pages(payload: Any) -> list[list[dict]]:
    if not isinstance(payload, list):
        _schema_error()
    for page in payload:
        if not isinstance(page, list):
            _schema_error()
        for status in page:
            if not isinstance(status, dict) or not _is_positive_int(status.get("id")) or not _is_check_name(status.get("context")) or not _is_sha(status.get("sha")) or status.get("state") not in {"error", "failure", "pending", "success"}:
                _schema_error()
    return payload


def _current_pr(payload: Any) -> dict:
    head = payload.get("head") if isinstance(payload, dict) else None
    base = payload.get("base") if isinstance(payload, dict) else None
    repository = base.get("repo") if isinstance(base, dict) else None
    if not isinstance(payload, dict) or not _is_positive_int(payload.get("number")) or not isinstance(payload.get("html_url"), str) or payload.get("state") not in {"open", "closed"} or not isinstance(head, dict) or not _is_sha(head.get("sha")) or not isinstance(base, dict) or not _is_branch_name(base.get("ref")) or not isinstance(repository, dict) or _REPO.fullmatch(repository.get("full_name") or "") is None:
        _schema_error()
    if payload["state"] == "closed" and not isinstance(payload.get("merged"), bool):
        _schema_error()
    return payload


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
        pr = _graphql_pr(_api("graphql", query=query))
        sha, branch = pr["headRefOid"], pr["baseRefName"]
        receipt["head_sha"] = sha
        if not _is_sha(sha) or pr["state"] not in {"OPEN", "MERGED"}:
            raise ValueError("PR is closed or current head is unavailable")
        protection = (pr.get("baseRef") or {}).get("branchProtectionRule") or {}
        required: set[tuple[str, int | None]] = {
            (r["context"], (r.get("app") or {}).get("databaseId"))
            for r in protection.get("requiredStatusChecks", [])
        }
        rules = _rules_pages(
            _api(f"repos/{repo}/rules/branches/{quote(branch, safe='')}?per_page=100", paginate=True)
        )
        for page in rules:
            for rule in page:
                if rule["type"] == "required_status_checks":
                    required.update((r["context"], r.get("integration_id"))
                                    for r in rule["parameters"]["required_status_checks"])
        binding = _TRUSTED_ACCEPTANCE_BINDINGS.get(url or "")
        if binding is not None:
            if sha != binding.head_sha or branch != binding.base_ref:
                receipt.update(
                    classification="stale",
                    detail="PR head/base does not match the trusted acceptance binding; retry.",
                )
                return receipt
            required = set(binding.required_checks)
        receipt["required"] = [{"context": c, "app_id": a} for c, a in sorted(required, key=str)]
        if not required:
            receipt["detail"] = "No repository-required checks are configured; explicitly use a local-only contract for non-CI tasks."
            return receipt
        pages = _check_run_pages(
            _api(f"repos/{repo}/commits/{sha}/check-runs?per_page=100&filter=latest", paginate=True)
        )
        runs = [run for page in pages for run in page["check_runs"]]
        if len({r["id"] for r in runs}) != pages[0]["total_count"]:
            raise ValueError("Incomplete check-run pagination")
        status_pages = _status_pages(
            _api(f"repos/{repo}/commits/{sha}/statuses?per_page=100", paginate=True)
        )
        statuses = [status for page in status_pages for status in page]
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
                check_receipt = {"name": context, "id": check["id"],
                    "head_sha": check.get("head_sha", check.get("sha")),
                    "classification": classification, "conclusion": outcome}
                safe_url = _sanitize_provider_url(
                    check.get("html_url") if is_run else check.get("target_url")
                )
                if safe_url is not None:
                    check_receipt["url"] = safe_url
                receipt["checks"].append(check_receipt)
        # Re-read after all pages: old-head successes are never transferable.
        current = _current_pr(_api(f"repos/{repo}/pulls/{number}"))
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
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        receipt.update(classification="infra", detail="GitHub acceptance evidence unavailable or incomplete; check the profile-scoped token/API access and retry.")
        return receipt


def _classify(check: dict, sha: str, outcome: str | None, is_run: bool) -> str:
    if check.get("head_sha", check.get("sha")) != sha:
        return "stale"
    if is_run and check.get("status") != "completed":
        return "pending"
    if outcome is None:
        return "infra"
    return {"success": "success", "failure": "failure", "error": "infra", "pending": "pending"}.get(outcome, "infra")

"""Lifecycle invariants using real SQLite and a local authenticated GitHub API."""
import copy
import http.client
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest

from hermes_cli import kanban_db as kb
from hermes_cli import kanban_pr_acceptance as acceptance
from hermes_cli.kanban_db_connect import connect


@pytest.fixture
def github(tmp_path, monkeypatch):
    state = {
        "conclusion": "success",
        "head": "a" * 40,
        "reads": 0,
        "requests": [],
        "source": "check_run",
        "provider_url": "https://github.com/acme/repo/actions/runs/42",
        "required": [{"context": "required", "app": {"databaseId": 1}}],
        "current_state": "open",
    }

    class Handler(BaseHTTPRequestHandler):
        def _reply(self, value, status=200, headers=None):
            self.send_response(status)
            for key, header_value in (headers or {}).items():
                self.send_header(key, header_value)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(value).encode())

        def _authorize(self):
            if self.headers.get("Authorization") != "Bearer test-token":
                self._reply({"message": "unauthorized"}, 401)
                return False
            return True

        def do_POST(self):
            if not self._authorize():
                return
            state["requests"].append(("POST", self.path))
            if self.path != "/graphql":
                self._reply({"message": "not found"}, 404)
                return
            if state.get("http_status"):
                self._reply({"message": "redacted by collector"}, state["http_status"])
                return
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
            assert "pullRequest(number:7)" in body["query"]
            value = {"data": {"repository": {"pullRequest": {
                "headRefOid": state["head"], "baseRefName": "main", "state": "OPEN",
                "baseRef": {"branchProtectionRule": {"requiredStatusChecks": state["required"]}},
            }}}}
            self._reply(value)

        def do_GET(self):
            if not self._authorize():
                return
            state["requests"].append(("GET", self.path))
            parsed = urlparse(self.path)
            sha = state["head"]
            if "/rules/branches/" in parsed.path:
                value = []
            elif "/check-runs" in parsed.path:
                run = {
                    "id": 42,
                    "name": "required",
                    "head_sha": sha,
                    "app": {"id": 1},
                    "status": "in_progress" if state["conclusion"] in {"pending", None} else "completed",
                    "conclusion": None if state["conclusion"] == "pending" else state["conclusion"],
                    "html_url": state["provider_url"],
                }
                if state.get("stale"):
                    run["head_sha"] = "b" * 40
                runs = [] if state.get("missing") or state["source"] == "legacy" else [run]
                page = int(parse_qs(parsed.query).get("page", ["1"])[0])
                if page == 1:
                    optional = [{**run, "id": 1000 + i, "name": "optional", "conclusion": "skipped"}
                                for i in range(100)]
                    next_url = f"http://127.0.0.1:{server.server_port}{parsed.path}?per_page=100&page=2"
                    self._reply(
                        {"total_count": 100 + len(runs), "check_runs": optional},
                        headers={"Link": f'<{next_url}>; rel="next"'},
                    )
                    return
                value = {"total_count": 100 + len(runs), "check_runs": runs}
                if state.get("race"):
                    state["race"]()
                if state.get("head_change"):
                    state["head"] = "b" * 40
            elif "/statuses" in parsed.path:
                value = [] if state["source"] == "check_run" else [{
                    "id": 43,
                    "context": "required",
                    "sha": sha,
                    "state": state["conclusion"],
                    "target_url": state["provider_url"],
                }]
            elif "/pulls/" in parsed.path:
                value = {
                    "number": 7,
                    "html_url": "https://github.com/acme/repo/pull/7",
                    "head": {"sha": sha, "repo": {"full_name": "acme/repo"}},
                    "base": {"ref": "main", "repo": {
                        "full_name": "other/repo" if state.get("provenance") else "acme/repo"}},
                    "state": state["current_state"],
                }
                if state.get("omit_current_state"):
                    value.pop("state")
                if "current_merged" in state:
                    value["merged"] = state["current_merged"]
            else:
                self._reply({"message": "not found"}, 404)
                return
            self._reply(value)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(acceptance, "_API_BASE", f"http://127.0.0.1:{server.server_port}", raising=False)
    profile_home = tmp_path / "home"
    profile_home.mkdir()
    (profile_home / ".env").write_text("GITHUB_TOKEN=test-token\n")
    monkeypatch.setenv("HERMES_HOME", str(profile_home))
    kb.init_db()
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_token_uses_only_profile_scoped_env_file(tmp_path, monkeypatch):
    profile_home = tmp_path / "profile"
    profile_home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(profile_home))
    monkeypatch.setenv("GITHUB_TOKEN", "ambient-github-token")
    monkeypatch.setenv("GH_TOKEN", "ambient-gh-token")
    monkeypatch.setenv("GH_HOST", "ambient.example")
    calls = []

    def unexpected_gh(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("gh credential fallback must not run")

    monkeypatch.setattr("subprocess.run", unexpected_gh)

    with pytest.raises(acceptance._GitHubApiError) as excinfo:
        acceptance._token()

    assert excinfo.value.classification == "unauthorized"
    assert calls == []

    (profile_home / ".env").write_text("GITHUB_TOKEN=scoped-test-token\n")
    assert acceptance._token() == "scoped-test-token"


@pytest.mark.parametrize(
    ("error_type", "args"),
    (
        (http.client.BadStatusLine, ("synthetic-secret",)),
        (http.client.IncompleteRead, (b"synthetic-secret", 64)),
        (http.client.RemoteDisconnected, ("synthetic-secret",)),
        (http.client.LineTooLong, ("synthetic-secret",)),
    ),
)
def test_malformed_http_protocol_is_redacted_infra_receipt(monkeypatch, error_type, args):
    monkeypatch.setattr(acceptance, "_token", lambda: "synthetic-token")

    def malformed_response(*unused_args, **unused_kwargs):
        raise error_type(*args)

    monkeypatch.setattr(acceptance.urllib.request, "urlopen", malformed_response)

    receipt = acceptance.collect_acceptance(
        "acme/repo", "https://github.com/acme/repo/pull/7"
    )

    assert receipt["ok"] is False
    assert receipt["classification"] == "infra"
    assert "synthetic" not in json.dumps(receipt)


def test_current_pr_array_root_is_redacted_infra_instead_of_escaping(monkeypatch):
    sha = "a" * 40

    def fake_api(endpoint, *, query=None, paginate=False):
        if query is not None:
            return {"data": {"repository": {"pullRequest": {
                "headRefOid": sha,
                "baseRefName": "main",
                "state": "OPEN",
                "baseRef": {"branchProtectionRule": {"requiredStatusChecks": [
                    {"context": "required", "app": {"databaseId": 1}},
                ]}},
            }}}}
        if "/rules/branches/" in endpoint:
            return [[]]
        if "/check-runs" in endpoint:
            return [{"total_count": 1, "check_runs": [{
                "id": 42,
                "name": "required",
                "head_sha": sha,
                "app": {"id": 1},
                "status": "completed",
                "conclusion": "success",
            }]}]
        if "/statuses" in endpoint:
            return [[]]
        if "/pulls/7" in endpoint:
            return []
        raise AssertionError(endpoint)

    monkeypatch.setattr(acceptance, "_api", fake_api)

    receipt = acceptance.collect_acceptance(
        "acme/repo", "https://github.com/acme/repo/pull/7"
    )

    assert receipt["ok"] is False
    assert receipt["classification"] == "infra"
    assert "GitHub acceptance evidence" in receipt["detail"]


@pytest.mark.linux_only
@pytest.mark.parametrize(
    ("state", "merged"),
    (("open", None), ("closed", True)),
)
def test_current_pr_rest_state_enum_accepts_supported_values(github, state, merged):
    github["current_state"] = state
    if merged is not None:
        github["current_merged"] = merged

    receipt = acceptance.collect_acceptance(
        "acme/repo", "https://github.com/acme/repo/pull/7"
    )

    assert receipt["ok"] is True
    assert receipt["classification"] == "success"


@pytest.mark.linux_only
@pytest.mark.parametrize(
    ("case", "state", "omit_state"),
    (
        ("empty", "", False),
        ("unknown", "CANARY_UNTRUSTED_STATE", False),
        ("wrong-casing", "Open", False),
        ("null", None, False),
        ("number", 7, False),
        ("boolean", True, False),
        ("missing", "open", True),
    ),
)
def test_current_pr_rest_state_enum_rejects_malformed_evidence_without_terminal_mutation(
    github, case, state, omit_state, caplog
):
    github["current_state"] = state
    github["omit_current_state"] = omit_state
    contract = "https://github.com/acme/repo/pull/7"

    with connect() as conn:
        tid = kb.create_task(conn, title=f"state-{case}", completion_contract=contract)
        claimed = kb.claim_task(conn, tid)
        assert claimed is not None
        run_id = claimed.current_run_id

        assert not kb.complete_task(
            conn,
            tid,
            expected_run_id=run_id,
            metadata={"published_pr": contract},
        )
        task = kb.get_task(conn, tid)
        assert task is not None
        rows = conn.execute(
            "SELECT kind, payload FROM task_events WHERE task_id=? ORDER BY id", (tid,)
        ).fetchall()

    receipts = [json.loads(payload) for kind, payload in rows if kind == "pr_acceptance"]
    assert task.status == "running"
    assert task.current_run_id == run_id
    assert all(kind != "completed" for kind, _ in rows)
    assert len(receipts) == 1
    assert receipts[0]["ok"] is False
    assert receipts[0]["classification"] == "infra"
    assert "GitHub acceptance evidence" in receipts[0]["detail"]
    assert "CANARY_UNTRUSTED_STATE" not in json.dumps([tuple(row) for row in rows])
    assert "CANARY_UNTRUSTED_STATE" not in caplog.text


def _acceptance_payloads():
    sha = "a" * 40
    return {
        "graphql": {"data": {"repository": {"pullRequest": {
            "headRefOid": sha,
            "baseRefName": "main",
            "state": "OPEN",
            "baseRef": {"branchProtectionRule": {"requiredStatusChecks": [
                {"context": "required", "app": {"databaseId": 1}},
            ]}},
        }}}},
        "rules": [[]],
        "checks": [{"total_count": 1, "check_runs": [{
            "id": 42,
            "name": "required",
            "head_sha": sha,
            "app": {"id": 1},
            "status": "completed",
            "conclusion": "success",
        }]}],
        "statuses": [[]],
        "current": {
            "number": 7,
            "html_url": "https://github.com/acme/repo/pull/7",
            "head": {"sha": sha},
            "base": {"ref": "main", "repo": {"full_name": "acme/repo"}},
            "state": "open",
        },
    }


def _payload_api(payloads):
    def fake_api(endpoint, *, query=None, paginate=False):
        if query is not None:
            return payloads["graphql"]
        if "/rules/branches/" in endpoint:
            return payloads["rules"]
        if "/check-runs" in endpoint:
            return payloads["checks"]
        if "/statuses" in endpoint:
            return payloads["statuses"]
        if "/pulls/7" in endpoint:
            return payloads["current"]
        raise AssertionError(endpoint)

    return fake_api


_REST_SCHEMA_INVALID_CASES = (
    ("current-array", "current", []),
    ("current-null", "current", None),
    ("current-string", "current", "CANARY_UNTRUSTED"),
    ("current-number", "current", 7),
    ("current-bool", "current", True),
    ("current-empty", "current", {}),
    ("current-missing-head", "current", {
        "number": 7,
        "html_url": "https://github.com/acme/repo/pull/7",
        "base": {"ref": "main", "repo": {"full_name": "acme/repo"}},
        "state": "open",
    }),
    ("current-wrong-head", "current", {
        "number": 7,
        "html_url": "https://github.com/acme/repo/pull/7",
        "head": [],
        "base": {"ref": "main", "repo": {"full_name": "acme/repo"}},
        "state": "open",
    }),
    ("current-wrong-base", "current", {
        "number": 7,
        "html_url": "https://github.com/acme/repo/pull/7",
        "head": {"sha": "a" * 40},
        "base": "CANARY_UNTRUSTED",
        "state": "open",
    }),
    ("current-wrong-repository-identity", "current", {
        "number": 7,
        "html_url": "https://github.com/acme/repo/pull/7",
        "head": {"sha": "a" * 40},
        "base": {"ref": "main", "repo": {"full_name": ["CANARY_UNTRUSTED"]}},
        "state": "open",
    }),
    ("rules-wrong-page", "rules", [{}]),
    ("rules-missing-type", "rules", [[{}]]),
    ("rules-wrong-required-checks", "rules", [[{
        "type": "required_status_checks",
        "parameters": {"required_status_checks": "CANARY_UNTRUSTED"},
    }]]),
    ("checks-wrong-page", "checks", [[]]),
    ("checks-wrong-list", "checks", [{"total_count": 1, "check_runs": None}]),
    ("checks-wrong-run", "checks", [{"total_count": 1, "check_runs": [[]]}]),
    ("checks-missing-identity", "checks", [{"total_count": 1, "check_runs": [{
        "id": 42,
        "head_sha": "a" * 40,
        "app": {"id": 1},
        "status": "completed",
        "conclusion": "success",
        "untrusted": "CANARY_UNTRUSTED",
    }]}]),
    ("checks-wrong-app", "checks", [{"total_count": 1, "check_runs": [{
        "id": 42,
        "name": "required",
        "head_sha": "a" * 40,
        "app": "CANARY_UNTRUSTED",
        "status": "completed",
        "conclusion": "success",
    }]}]),
    ("statuses-wrong-page", "statuses", [{}]),
    ("statuses-wrong-entry", "statuses", [["CANARY_UNTRUSTED"]]),
    ("statuses-missing-identity", "statuses", [[{
        "id": 43,
        "sha": "a" * 40,
        "state": "success",
        "untrusted": "CANARY_UNTRUSTED",
    }]]),
)


@pytest.mark.linux_only
@pytest.mark.parametrize(("case", "endpoint", "malformed"), _REST_SCHEMA_INVALID_CASES)
def test_rest_schema_invalid_evidence_fails_closed_without_terminal_mutation(
    github, monkeypatch, caplog, case, endpoint, malformed
):
    payloads = _acceptance_payloads()
    payloads[endpoint] = copy.deepcopy(malformed)
    monkeypatch.setattr(acceptance, "_api", _payload_api(payloads))
    contract = "https://github.com/acme/repo/pull/7"

    with connect() as conn:
        tid = kb.create_task(conn, title=f"schema-{case}", completion_contract=contract)
        claimed = kb.claim_task(conn, tid)
        assert claimed is not None
        run_id = claimed.current_run_id

        assert not kb.complete_task(
            conn,
            tid,
            expected_run_id=run_id,
            metadata={"published_pr": contract},
        )
        task = kb.get_task(conn, tid)
        assert task is not None
        rows = conn.execute(
            "SELECT kind, payload FROM task_events WHERE task_id=? ORDER BY id", (tid,)
        ).fetchall()

    receipts = [json.loads(payload) for kind, payload in rows if kind == "pr_acceptance"]
    assert task.status == "running"
    assert task.current_run_id == run_id
    assert all(kind != "completed" for kind, _ in rows)
    assert len(receipts) == 1
    assert receipts[0]["ok"] is False
    assert receipts[0]["classification"] == "infra"
    assert "GitHub acceptance evidence" in receipts[0]["detail"]
    assert "CANARY_UNTRUSTED" not in json.dumps([tuple(row) for row in rows])
    assert "CANARY_UNTRUSTED" not in caplog.text


@pytest.mark.linux_only
def test_rest_schema_allows_additional_fields_without_persisting_them(github, monkeypatch):
    payloads = _acceptance_payloads()
    for value in payloads.values():
        if isinstance(value, dict):
            value["untrusted"] = "CANARY_UNTRUSTED"
    payloads["rules"][0].append({"type": "advisory", "untrusted": "CANARY_UNTRUSTED"})
    payloads["checks"][0]["untrusted"] = "CANARY_UNTRUSTED"
    payloads["checks"][0]["check_runs"][0]["untrusted"] = "CANARY_UNTRUSTED"
    payloads["current"]["head"]["untrusted"] = "CANARY_UNTRUSTED"
    payloads["current"]["base"]["repo"]["untrusted"] = "CANARY_UNTRUSTED"
    monkeypatch.setattr(acceptance, "_api", _payload_api(payloads))

    receipt = acceptance.collect_acceptance(
        "acme/repo", "https://github.com/acme/repo/pull/7"
    )

    assert receipt["ok"] is True
    assert receipt["classification"] == "success"
    assert "CANARY_UNTRUSTED" not in json.dumps(receipt)


_SAFE_PROVIDER_URL = "https://github.com/acme/repo/actions/runs/42"
_PROVIDER_URL_CASES = (
    ("query", f"{_SAFE_PROVIDER_URL}?access_token=CANARY_QUERY", _SAFE_PROVIDER_URL),
    ("fragment", f"{_SAFE_PROVIDER_URL}#CANARY_FRAGMENT", _SAFE_PROVIDER_URL),
    ("query-fragment", f"{_SAFE_PROVIDER_URL}?key=CANARY_QUERY#CANARY_FRAGMENT", _SAFE_PROVIDER_URL),
    ("explicit-https-port", f"https://github.com:443/acme/repo/actions/runs/42?CANARY_PORT", _SAFE_PROVIDER_URL),
    (
        "job-path",
        "https://github.com/acme/repo/actions/runs/42/job/7?CANARY_JOB",
        "https://github.com/acme/repo/actions/runs/42/job/7",
    ),
    (
        "commit-checks-path",
        f"https://github.com/acme/repo/commit/{'a' * 40}/checks?CANARY_CHECKS",
        f"https://github.com/acme/repo/commit/{'a' * 40}/checks",
    ),
    ("empty-port", "https://github.com:/acme/repo/actions/runs/42?CANARY_EMPTY_PORT", None),
    ("literal-dot-segment", "https://github.com/../repo/actions/runs/42?CANARY_DOT", None),
    ("encoded-dot-segment", "https://github.com/%2e%2e/repo/actions/runs/42?CANARY_DOT_ENCODED", None),
    (
        "double-encoded-dot-segment",
        "https://github.com/%252e%252e/repo/actions/runs/42?CANARY_DOT_DOUBLE",
        None,
    ),
    ("wrong-host", "https://ci.invalid/acme/repo/actions/runs/42?CANARY_WRONG_HOST", None),
    ("userinfo-spoof", "https://github.com@ci.invalid/acme/repo/actions/runs/42?CANARY_USERINFO", None),
    ("embedded-credential", "https://CANARY_CREDENTIAL@github.com/acme/repo/actions/runs/42", None),
    ("unsupported-scheme", "http://github.com/acme/repo/actions/runs/42?CANARY_SCHEME", None),
    ("malformed", "https://[github.com/CANARY_MALFORMED", None),
    ("malformed-authority", "https:///github.com/acme/repo/actions/runs/42?CANARY_AUTHORITY_MISSING", None),
    ("missing", None, None),
    ("encoded-authority", "https://github.com%40ci.invalid/acme/repo/actions/runs/42?CANARY_AUTHORITY", None),
    ("encoded-host", "https://github%2ecom/acme/repo/actions/runs/42?CANARY_HOST_ENCODING", None),
    ("encoded-path", "https://github.com/acme/repo/actions/%72uns/42?CANARY_ENCODING", None),
    ("unsafe-port", "https://github.com:444/acme/repo/actions/runs/42?CANARY_UNSAFE_PORT", None),
    ("invalid-port", "https://github.com:not-a-port/acme/repo/actions/runs/42?CANARY_INVALID_PORT", None),
    ("control-character", "https://github.com/acme/repo/actions/runs/42\x1f?CANARY_CONTROL", None),
    ("delete-control-character", "https://github.com/acme/repo/actions/runs/42\x7f?CANARY_DELETE", None),
    (
        "ambiguous-backslash",
        "https://github.com\\@ci.invalid/acme/repo/actions/runs/42?CANARY_AMBIGUOUS",
        None,
    ),
)


def _configure_provider_url_case(github, source, provider_url):
    github.update(
        conclusion="success",
        head="a" * 40,
        source=source,
        provider_url=provider_url,
        required=[{"context": "required", "app": {"databaseId": 1} if source == "check_run" else None}],
    )


@pytest.mark.linux_only
@pytest.mark.parametrize("source", ("check_run", "legacy"))
@pytest.mark.parametrize("sink", ("returned_receipt", "sqlite_event"))
@pytest.mark.parametrize(("case", "provider_url", "expected_url"), _PROVIDER_URL_CASES)
def test_provider_urls_are_sanitized_before_receipt_persistence(
    github, caplog, source, sink, case, provider_url, expected_url
):
    _configure_provider_url_case(github, source, provider_url)

    if sink == "returned_receipt":
        receipt = acceptance.collect_acceptance(
            "acme/repo", "https://github.com/acme/repo/pull/7"
        )
        persisted = []
    else:
        with connect() as conn:
            tid = kb.create_task(
                conn, title=f"url-{source}-{case}", completion_contract="acme/repo"
            )
            assert kb.complete_task(
                conn,
                tid,
                metadata={"published_pr": "https://github.com/acme/repo/pull/7"},
            )
            assert kb.get_task(conn, tid).status == "done"
            rows = conn.execute(
                "SELECT kind, payload FROM task_events WHERE task_id=? ORDER BY id",
                (tid,),
            ).fetchall()
        receipt = next(
            json.loads(payload) for kind, payload in rows if kind == "pr_acceptance"
        )
        persisted = [(kind, json.loads(payload)) for kind, payload in rows]

    assert receipt["ok"] is True, (source, sink, case)
    check = next(item for item in receipt["checks"] if item["name"] == "required")
    if expected_url is None:
        assert "url" not in check
    else:
        assert check["url"] == expected_url

    serialized_receipt = json.dumps(receipt)
    serialized_events = json.dumps(persisted)
    assert "CANARY_" not in serialized_receipt
    assert "CANARY_" not in serialized_events
    assert "CANARY_" not in caplog.text
    if provider_url is not None and expected_url is None:
        assert provider_url not in str(receipt)
        assert provider_url not in serialized_receipt
        assert provider_url not in serialized_events
        assert provider_url not in caplog.text


@pytest.mark.linux_only
def test_failed_preflight_persists_no_completion_or_unsafe_event(github, monkeypatch, caplog):
    canary = "CANARY_FAILED_PREFLIGHT"

    def malformed_response(*unused_args, **unused_kwargs):
        raise http.client.BadStatusLine(canary)

    monkeypatch.setattr(acceptance.urllib.request, "urlopen", malformed_response)
    with connect() as conn:
        tid = kb.create_task(conn, title="failed-preflight", completion_contract="acme/repo")
        assert not kb.complete_task(
            conn, tid, metadata={"published_pr": "https://github.com/acme/repo/pull/7"}
        )
        assert kb.get_task(conn, tid).status != "done"
        rows = conn.execute(
            "SELECT kind, payload FROM task_events WHERE task_id=? ORDER BY id", (tid,)
        ).fetchall()

    assert all(kind != "completed" for kind, _ in rows)
    assert canary not in json.dumps([(kind, json.loads(payload)) for kind, payload in rows])
    assert canary not in caplog.text


@pytest.mark.parametrize(
    ("case", "producer", "status", "conclusion", "expected_classification", "expected_ok"),
    (
        ("success", 15368, "completed", "success", "success", True),
        ("failure", 15368, "completed", "failure", "failure", False),
        ("pending", 15368, "in_progress", None, "pending", False),
        ("skipped", 15368, "completed", "skipped", "infra", False),
        ("missing", None, None, None, "missing", False),
        ("stale", 15368, "completed", "success", "stale", False),
        ("unavailable", 15368, "completed", "success", "infra", False),
        ("wrong-app", 1, "completed", "success", "missing", False),
        ("wrong-head", 15368, "completed", "success", "stale", False),
        ("wrong-base", 15368, "completed", "success", "stale", False),
    ),
)
def test_f6_scoped_binding_requires_trusted_head_and_build_test_app(
    monkeypatch, case, producer, status, conclusion, expected_classification, expected_ok
):
    expected_head = "c0a7d0d5bf1a69bf8e0968caf5343350d43d1d83"
    observed_head = "d" * 40 if case == "wrong-head" else expected_head
    expected_base = "integration/126-canonical-s121-s123-full-vue-recovery"
    observed_base = "main" if case == "wrong-base" else expected_base
    contract = "https://github.com/tikauppi/THESEUS/pull/25"

    def fake_api(endpoint, *, query=None, paginate=False):
        if query is not None:
            return {"data": {"repository": {"pullRequest": {
                "headRefOid": observed_head,
                "baseRefName": observed_base,
                "state": "OPEN",
                "baseRef": {"branchProtectionRule": {"requiredStatusChecks": [
                    {"context": "build-test", "app": {"databaseId": 1}},
                ]}},
            }}}}
        if "/rules/branches/" in endpoint:
            return [[]]
        if "/check-runs" in endpoint:
            if case == "unavailable":
                raise acceptance._GitHubApiError("infra")
            runs = [] if producer is None else [{
                "id": 42,
                "name": "build-test",
                "head_sha": "b" * 40 if case == "stale" else observed_head,
                "app": {"id": producer},
                "status": status,
                "conclusion": conclusion,
                "html_url": "https://github.com/tikauppi/THESEUS/actions/runs/42",
            }]
            return [{"total_count": len(runs), "check_runs": runs}]
        if "/statuses" in endpoint:
            return [[]]
        if "/pulls/25" in endpoint:
            return {
                "number": 25,
                "html_url": contract,
                "head": {"sha": observed_head},
                "base": {
                    "ref": observed_base,
                    "repo": {"full_name": "tikauppi/THESEUS"},
                },
                "state": "open",
            }
        raise AssertionError(endpoint)

    monkeypatch.setattr(acceptance, "_api", fake_api)

    receipt = acceptance.collect_acceptance(contract, contract)

    assert receipt["classification"] == expected_classification
    assert receipt["ok"] is expected_ok
    if case == "wrong-app":
        assert receipt["required"] == [{"context": "build-test", "app_id": 15368}]


@pytest.mark.linux_only
def test_pr_completion_requires_authenticated_current_required_evidence(github):
    with connect() as conn:
        for conclusion in ("failure", "pending", "cancelled", "timed_out", "action_required", "neutral", "skipped", None, "success"):
            github.update(conclusion=conclusion, head="a" * 40)
            tid = kb.create_task(conn, title="Publish", completion_contract="acme/repo")
            ok = kb.complete_task(conn, tid, metadata={"published_pr": "https://github.com/acme/repo/pull/7"})
            assert ok is (conclusion == "success")
            task = kb.get_task(conn, tid)
            assert (task.status == "done") is ok
            receipts = [json.loads(r[0]) for r in conn.execute(
                "SELECT payload FROM task_events WHERE task_id=? AND kind='pr_acceptance'", (tid,))]
            assert receipts and receipts[-1]["head_sha"] == "a" * 40
            if not ok:
                assert task.status in {"running", "ready", "blocked", "review"}
                assert "retry" in receipts[-1]["recovery"]
                assert receipts[-1]["checks"][0]["id"] == 42
        for fault in ("missing", "stale", "head_change", "provenance"):
            github.update(conclusion="success", head="a" * 40)
            github[fault] = True
            tid = kb.create_task(conn, title=fault, completion_contract="acme/repo")
            assert not kb.complete_task(conn, tid, metadata={"published_pr": "https://github.com/acme/repo/pull/7"})
            assert kb.get_task(conn, tid).status != "done"
            github.pop(fault)
        github["required"] = []
        tid = kb.create_task(conn, title="no policy", completion_contract="acme/repo")
        assert not kb.complete_task(conn, tid, metadata={"published_pr": "https://github.com/acme/repo/pull/7"})
        receipt = json.loads(conn.execute(
            "SELECT payload FROM task_events WHERE task_id=? AND kind='pr_acceptance' ORDER BY id DESC", (tid,)).fetchone()[0])
        assert receipt["classification"] == "missing"
        assert receipt["required"] == []
        github["required"] = [{"context": "required", "app": {"databaseId": 1}}]
        for status, classification in ((401, "unauthorized"), (403, "forbidden"), (404, "not_found")):
            github["http_status"] = status
            tid = kb.create_task(conn, title=classification, completion_contract="acme/repo")
            assert not kb.complete_task(conn, tid, metadata={"published_pr": "https://github.com/acme/repo/pull/7"})
            receipt = json.loads(conn.execute(
                "SELECT payload FROM task_events WHERE task_id=? AND kind='pr_acceptance' ORDER BY id DESC", (tid,)).fetchone()[0])
            assert receipt["classification"] == classification
            assert "redacted" not in json.dumps(receipt)
        github.pop("http_status")
        # Omission and a sibling repository cannot downgrade the stored declaration.
        tid = kb.create_task(conn, title="publish", completion_contract="acme/repo")
        assert not kb.complete_task(conn, tid, summary="local green")
        assert not kb.complete_task(conn, tid, metadata={"published_pr": "https://github.com/other/repo/pull/7"})
        before = len(github["requests"])
        local = kb.create_task(conn, title="local", completion_contract="local-only")
        assert kb.complete_task(conn, local, summary="https://github.com/acme/repo/pull/7 is background context")
        assert len(github["requests"]) == before


@pytest.mark.linux_only
def test_acceptance_receipts_and_terminal_write_share_run_ownership(github):
    with connect() as conn:
        for conclusion in ("success", "failure"):
            tid = kb.create_task(conn, title="race", completion_contract="acme/repo")
            owner = kb.claim_task(conn, tid)
            run_id = owner.current_run_id

            def reclaim():
                with connect() as rival:
                    assert kb.block_task(rival, tid, reason="Reassigned during acceptance")
                    assert kb.unblock_task(rival, tid)
                    github["replacement"] = kb.claim_task(rival, tid).current_run_id

            github.update(conclusion=conclusion, race=reclaim)
            assert not kb.complete_task(conn, tid, expected_run_id=run_id,
                                        metadata={"published_pr": "https://github.com/acme/repo/pull/7"})
            assert kb.get_task(conn, tid).current_run_id == github["replacement"]
            assert github["replacement"] != run_id
            assert kb.get_task(conn, tid).status != "done"
            assert conn.execute(
                "SELECT count(*) FROM task_events WHERE task_id=? AND kind='pr_acceptance'", (tid,)
            ).fetchone()[0] == 0
            github.pop("race")


def _semantic_payloads(case):
    payloads = _acceptance_payloads()
    graphql_pr = payloads["graphql"]["data"]["repository"]["pullRequest"]
    run = payloads["checks"][0]["check_runs"][0]
    if case == "legacy-wrong-head":
        graphql_pr["baseRef"]["branchProtectionRule"]["requiredStatusChecks"] = [
            {"context": "required", "app": None},
        ]
        payloads["checks"] = [{"total_count": 0, "check_runs": []}]
        payloads["statuses"] = [[{
            "id": 43,
            "context": "required",
            "sha": "b" * 40,
            "state": "success",
        }]]
    elif case == "legacy-malformed-head":
        graphql_pr["baseRef"]["branchProtectionRule"]["requiredStatusChecks"] = [
            {"context": "required", "app": None},
        ]
        payloads["checks"] = [{"total_count": 0, "check_runs": []}]
        payloads["statuses"] = [[{
            "id": 43,
            "context": "required",
            "sha": "CANARY_UNTRUSTED_SHA",
            "state": "success",
        }]]
    elif case == "legacy-unknown-state":
        graphql_pr["baseRef"]["branchProtectionRule"]["requiredStatusChecks"] = [
            {"context": "required", "app": None},
        ]
        payloads["checks"] = [{"total_count": 0, "check_runs": []}]
        payloads["statuses"] = [[{
            "id": 43,
            "context": "required",
            "sha": "a" * 40,
            "state": "CANARY_UNTRUSTED_STATE",
        }]]
    elif case == "empty-required-name":
        graphql_pr["baseRef"]["branchProtectionRule"]["requiredStatusChecks"][0]["context"] = ""
        run["name"] = ""
    elif case == "invalid-rule-context":
        payloads["rules"] = [[{
            "type": "required_status_checks",
            "parameters": {"required_status_checks": [{
                "context": "\x1f",
                "integration_id": None,
            }]},
        }]]
    elif case == "empty-base-ref":
        graphql_pr["baseRefName"] = ""
        payloads["current"]["base"]["ref"] = ""
    elif case == "invalid-check-head":
        run["head_sha"] = "CANARY_UNTRUSTED_SHA"
    elif case == "unknown-check-status":
        run["status"] = "CANARY_UNTRUSTED_STATUS"
    elif case == "unknown-check-conclusion":
        run["conclusion"] = "CANARY_UNTRUSTED_CONCLUSION"
    elif case == "completed-without-conclusion":
        run["conclusion"] = None
    elif case == "zero-check-id":
        run["id"] = 0
    elif case == "negative-check-id":
        run["id"] = -1
    elif case == "string-check-id":
        run["id"] = "42"
    elif case == "bool-check-id":
        run["id"] = True
    elif case == "zero-app-id":
        run["app"]["id"] = 0
    elif case == "malformed-graphql-head":
        graphql_pr["headRefOid"] = "CANARY_UNTRUSTED_SHA"
    else:
        raise AssertionError(case)
    return payloads


_SEMANTIC_INVALID_CASES = (
    ("legacy-wrong-head", "stale"),
    ("legacy-malformed-head", "infra"),
    ("legacy-unknown-state", "infra"),
    ("empty-required-name", "infra"),
    ("invalid-rule-context", "infra"),
    ("empty-base-ref", "infra"),
    ("invalid-check-head", "infra"),
    ("unknown-check-status", "infra"),
    ("unknown-check-conclusion", "infra"),
    ("completed-without-conclusion", "infra"),
    ("zero-check-id", "infra"),
    ("negative-check-id", "infra"),
    ("string-check-id", "infra"),
    ("bool-check-id", "infra"),
    ("zero-app-id", "infra"),
    ("malformed-graphql-head", "infra"),
)


@pytest.mark.parametrize(("case", "classification"), _SEMANTIC_INVALID_CASES)
def test_semantic_evidence_rejections_are_redacted_before_policy_evaluation(
    monkeypatch, caplog, case, classification
):
    monkeypatch.setattr(acceptance, "_api", _payload_api(_semantic_payloads(case)))

    receipt = acceptance.collect_acceptance(
        "acme/repo", "https://github.com/acme/repo/pull/7"
    )

    assert receipt["ok"] is False
    assert receipt["classification"] == classification
    assert "CANARY_UNTRUSTED" not in json.dumps(receipt)
    assert "CANARY_UNTRUSTED" not in caplog.text


@pytest.mark.linux_only
@pytest.mark.parametrize(("case", "classification"), _SEMANTIC_INVALID_CASES)
def test_semantic_evidence_rejections_cannot_complete_disposable_task(
    monkeypatch, caplog, case, classification
):
    contract = "https://github.com/acme/repo/pull/7"
    monkeypatch.setattr(acceptance, "_api", _payload_api(_semantic_payloads(case)))

    with connect() as conn:
        task_id = kb.create_task(conn, title=f"semantic-{case}", completion_contract=contract)
        claimed = kb.claim_task(conn, task_id)
        assert claimed is not None
        assert not kb.complete_task(
            conn,
            task_id,
            expected_run_id=claimed.current_run_id,
            metadata={"published_pr": contract},
        )
        task = kb.get_task(conn, task_id)
        events = conn.execute(
            "SELECT kind, payload FROM task_events WHERE task_id=? ORDER BY id", (task_id,)
        ).fetchall()

    receipts = [json.loads(payload) for kind, payload in events if kind == "pr_acceptance"]
    assert task is not None
    assert task.status == "running"
    assert all(kind != "completed" for kind, _ in events)
    assert len(receipts) == 1
    assert receipts[0]["ok"] is False
    assert receipts[0]["classification"] == classification
    assert "CANARY_UNTRUSTED" not in json.dumps([tuple(event) for event in events])
    assert "CANARY_UNTRUSTED" not in caplog.text


@pytest.mark.parametrize("status", ("queued", "in_progress", "waiting", "requested", "pending"))
def test_known_nonterminal_check_run_statuses_remain_pending(monkeypatch, status):
    payloads = _acceptance_payloads()
    payloads["checks"][0]["check_runs"][0].update(status=status, conclusion=None)
    monkeypatch.setattr(acceptance, "_api", _payload_api(payloads))

    receipt = acceptance.collect_acceptance(
        "acme/repo", "https://github.com/acme/repo/pull/7"
    )

    assert receipt["ok"] is False
    assert receipt["classification"] == "pending"


_MISSING_APP = object()
_APP_IDENTITY_CASES = (
    ("empty-app", {}, "required", 1, "infra", False),
    ("null-database-id", {"databaseId": None}, "required", 1, "infra", False),
    ("missing-app", _MISSING_APP, "required", 1, "infra", False),
    ("wrong-app-object-type", "CANARY_UNTRUSTED_APP", "required", 1, "infra", False),
    ("database-id-wrong-primitive", {"databaseId": "CANARY_UNTRUSTED_ID"}, "required", 1, "infra", False),
    ("database-id-zero", {"databaseId": 0}, "required", 1, "infra", False),
    ("database-id-negative", {"databaseId": -1}, "required", 1, "infra", False),
    ("wrong-positive-app-id", {"databaseId": 2}, "required", 1, "missing", False),
    ("correct-positive-app-id", {"databaseId": 1}, "required", 1, "success", True),
    ("correct-check-name-wrong-producer", {"databaseId": 1}, "required", 2, "missing", False),
    ("malformed-producer-valid-check", {"databaseId": "CANARY_UNTRUSTED"}, "required", 1, "infra", False),
    ("valid-producer-wrong-check-name", {"databaseId": 1}, "other", 1, "missing", False),
    ("explicitly-unrestricted-producer", None, "required", 1, "success", True),
    ("producer-bound-required-check", {"databaseId": 1}, "required", 1, "success", True),
)


def _app_identity_payloads(app, check_name, run_app_id):
    payloads = _acceptance_payloads()
    required = payloads["graphql"]["data"]["repository"]["pullRequest"]["baseRef"]
    required = required["branchProtectionRule"]["requiredStatusChecks"][0]
    if app is _MISSING_APP:
        required.pop("app")
    else:
        required["app"] = app
    run = payloads["checks"][0]["check_runs"][0]
    run["name"] = check_name
    run["app"] = {"id": run_app_id}
    return payloads


@pytest.mark.parametrize(
    ("case", "app", "check_name", "run_app_id", "classification", "expected_ok"),
    _APP_IDENTITY_CASES,
)
def test_graphql_required_check_app_identity_matrix_fails_closed_before_policy_evaluation(
    monkeypatch, caplog, case, app, check_name, run_app_id, classification, expected_ok
):
    monkeypatch.setattr(
        acceptance, "_api", _payload_api(_app_identity_payloads(app, check_name, run_app_id))
    )

    receipt = acceptance.collect_acceptance("acme/repo", "https://github.com/acme/repo/pull/7")

    assert receipt["ok"] is expected_ok, case
    assert receipt["classification"] == classification, case
    assert "CANARY_UNTRUSTED" not in json.dumps(receipt)
    assert "CANARY_UNTRUSTED" not in caplog.text


@pytest.mark.linux_only
@pytest.mark.parametrize(
    ("case", "app", "check_name", "run_app_id", "classification", "expected_ok"),
    _APP_IDENTITY_CASES,
)
def test_graphql_required_check_app_identity_matrix_cannot_bypass_disposable_completion(
    monkeypatch, caplog, case, app, check_name, run_app_id, classification, expected_ok
):
    contract = "https://github.com/acme/repo/pull/7"
    monkeypatch.setattr(
        acceptance, "_api", _payload_api(_app_identity_payloads(app, check_name, run_app_id))
    )

    with connect() as conn:
        task_id = kb.create_task(conn, title=f"app-identity-{case}", completion_contract=contract)
        claimed = kb.claim_task(conn, task_id)
        assert claimed is not None
        assert kb.complete_task(
            conn,
            task_id,
            expected_run_id=claimed.current_run_id,
            metadata={"published_pr": contract},
        ) is expected_ok
        task = kb.get_task(conn, task_id)
        events = conn.execute(
            "SELECT kind, payload FROM task_events WHERE task_id=? ORDER BY id", (task_id,)
        ).fetchall()

    receipts = [json.loads(payload) for kind, payload in events if kind == "pr_acceptance"]
    assert task is not None
    assert task.status == ("done" if expected_ok else "running"), case
    assert any(kind == "completed" for kind, _ in events) is expected_ok, case
    assert len(receipts) == 1
    assert receipts[0]["ok"] is expected_ok
    assert receipts[0]["classification"] == classification
    assert "CANARY_UNTRUSTED" not in json.dumps([tuple(event) for event in events])
    assert "CANARY_UNTRUSTED" not in caplog.text

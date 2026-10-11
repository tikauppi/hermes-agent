"""Lifecycle invariants using real SQLite and a local authenticated GitHub API."""
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
                    "status": "in_progress" if state["conclusion"] == "pending" else "completed",
                    "conclusion": state["conclusion"],
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
                    "state": "open",
                }
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


_SAFE_PROVIDER_URL = "https://github.com/acme/repo/actions/runs/42"
_PROVIDER_URL_CASES = (
    ("query", f"{_SAFE_PROVIDER_URL}?access_token=CANARY_QUERY", _SAFE_PROVIDER_URL),
    ("fragment", f"{_SAFE_PROVIDER_URL}#CANARY_FRAGMENT", _SAFE_PROVIDER_URL),
    ("query-fragment", f"{_SAFE_PROVIDER_URL}?key=CANARY_QUERY#CANARY_FRAGMENT", _SAFE_PROVIDER_URL),
    ("explicit-https-port", f"https://github.com:443/acme/repo/actions/runs/42?CANARY_PORT", _SAFE_PROVIDER_URL),
    ("wrong-host", "https://ci.invalid/acme/repo/actions/runs/42?CANARY_WRONG_HOST", None),
    ("userinfo-spoof", "https://github.com@ci.invalid/acme/repo/actions/runs/42?CANARY_USERINFO", None),
    ("embedded-credential", "https://CANARY_CREDENTIAL@github.com/acme/repo/actions/runs/42", None),
    ("unsupported-scheme", "http://github.com/acme/repo/actions/runs/42?CANARY_SCHEME", None),
    ("malformed", "https://[github.com/CANARY_MALFORMED", None),
    ("missing", None, None),
    ("encoded-authority", "https://github.com%40ci.invalid/acme/repo/actions/runs/42?CANARY_AUTHORITY", None),
    ("encoded-path", "https://github.com/acme/repo/actions/%72uns/42?CANARY_ENCODING", None),
    ("unsafe-port", "https://github.com:444/acme/repo/actions/runs/42?CANARY_UNSAFE_PORT", None),
)


def _configure_provider_url_case(github, source, provider_url):
    github.update(
        conclusion="success",
        head="a" * 40,
        source=source,
        provider_url=provider_url,
        required=[{"context": "required", "app": {"databaseId": 1 if source == "check_run" else None}}],
    )


@pytest.mark.linux_only
@pytest.mark.parametrize("source", ("check_run", "legacy"))
@pytest.mark.parametrize(("case", "provider_url", "expected_url"), _PROVIDER_URL_CASES)
def test_provider_urls_are_sanitized_in_returned_receipt(
    github, caplog, source, case, provider_url, expected_url
):
    _configure_provider_url_case(github, source, provider_url)

    receipt = acceptance.collect_acceptance(
        "acme/repo", "https://github.com/acme/repo/pull/7"
    )

    assert receipt["ok"] is True, case
    check = next(item for item in receipt["checks"] if item["name"] == "required")
    if expected_url is None:
        assert "url" not in check
    else:
        assert check["url"] == expected_url
    assert "CANARY_" not in json.dumps(receipt)
    assert "CANARY_" not in caplog.text


@pytest.mark.linux_only
@pytest.mark.parametrize("source", ("check_run", "legacy"))
@pytest.mark.parametrize(("case", "provider_url", "expected_url"), _PROVIDER_URL_CASES)
def test_provider_urls_are_sanitized_in_sqlite_acceptance_event(
    github, caplog, source, case, provider_url, expected_url
):
    _configure_provider_url_case(github, source, provider_url)

    with connect() as conn:
        tid = kb.create_task(conn, title=f"url-{source}-{case}", completion_contract="acme/repo")
        assert kb.complete_task(
            conn, tid, metadata={"published_pr": "https://github.com/acme/repo/pull/7"}
        )
        assert kb.get_task(conn, tid).status == "done"
        rows = conn.execute(
            "SELECT kind, payload FROM task_events WHERE task_id=? ORDER BY id", (tid,)
        ).fetchall()

    receipt = next(json.loads(payload) for kind, payload in rows if kind == "pr_acceptance")
    check = next(item for item in receipt["checks"] if item["name"] == "required")
    if expected_url is None:
        assert "url" not in check
    else:
        assert check["url"] == expected_url
    serialized_events = json.dumps([(kind, json.loads(payload)) for kind, payload in rows])
    assert "CANARY_" not in serialized_events
    assert "CANARY_" not in caplog.text


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

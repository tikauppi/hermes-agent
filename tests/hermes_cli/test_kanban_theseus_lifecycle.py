from __future__ import annotations

import inspect
import base64
import itertools
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import model_tools
from hermes_cli import kanban_db as kb
from hermes_cli import kanban_db_connect as kbc
from hermes_cli import kanban_db_dispatch as kbd
from hermes_cli import kanban as kc
from hermes_cli import kanban_theseus_lifecycle as glh
from hermes_cli.kanban_authority_verifier import AuthorityVerifier
from tests.hermes_cli import kanban_lifecycle_authority_harness as authority_harness


_TEST_AUTHORITY_KEY = Ed25519PrivateKey.generate()
_TEST_AUTHORITY_ISSUER = "synthetic-r5-lifecycle-issuer"
_TEST_AUTHORITY_KEY_ID = "synthetic-r5-key-1"
_TEST_APPROVER = "synthetic-r5-approver"
_TEST_ARCHITECT = "synthetic-r5-architect"
_TEST_NONCES = itertools.count(1)
_TEST_AUTHORITY = authority_harness.SyntheticAuthority(
    AuthorityVerifier(
        trusted_keys={
            (_TEST_AUTHORITY_ISSUER, _TEST_AUTHORITY_KEY_ID):
                _TEST_AUTHORITY_KEY.public_key().public_bytes_raw()
        },
        authorized_principals={
            (_TEST_AUTHORITY_ISSUER, _TEST_APPROVER): frozenset({"approver"}),
            (_TEST_AUTHORITY_ISSUER, _TEST_ARCHITECT): frozenset({"architect"}),
        },
    )
)


def _signed_authority(
    conn,
    task_id: str,
    *,
    action: str,
    evidence_type: str,
    principal: str,
    principal_role: str,
    run_id: int = 0,
    stop_token: str = "none",
    issued_at: int = 100,
    expires_at: int = 150,
    overrides: dict | None = None,
) -> str:
    metadata = glh.package_metadata(conn, task_id)
    assert metadata is not None
    payload = {
        "version": 1,
        "algorithm": "Ed25519",
        "issuer": _TEST_AUTHORITY_ISSUER,
        "key_id": _TEST_AUTHORITY_KEY_ID,
        "principal": principal,
        "principal_role": principal_role,
        "evidence_type": evidence_type,
        "action": action,
        "scope": glh.AUTHORITY_SCOPE,
        "package_id": metadata["package_id"],
        "task_id": task_id,
        "run_id": run_id,
        "stop_token": stop_token,
        "code_sha": metadata["candidate_sha"],
        "issued_at": issued_at,
        "expires_at": expires_at,
        "nonce": f"synthetic-r5-{next(_TEST_NONCES):08d}",
    }
    payload.update(overrides or {})
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    return json.dumps(
        {
            "payload": payload,
            "signature": base64.b64encode(_TEST_AUTHORITY_KEY.sign(canonical)).decode("ascii"),
        },
        sort_keys=True,
    )


def _approve(conn, task_id: str, *, expires_at: int = 150, evidence: str | None = None):
    evidence = evidence or _signed_authority(
        conn,
        task_id,
        action="record_terminal_approval",
        evidence_type="terminal_approval",
        principal=_TEST_APPROVER,
        principal_role="approver",
        expires_at=expires_at,
    )
    return authority_harness.approve(
        conn, task_id, authority_evidence=evidence, authority=_TEST_AUTHORITY
    )


def _fresh_approve(conn, task_id: str, *, expires_at: int = 200):
    evidence = _signed_authority(
        conn,
        task_id,
        action="issue_fresh_terminal_approval",
        evidence_type="terminal_approval",
        principal=_TEST_APPROVER,
        principal_role="approver",
        expires_at=expires_at,
    )
    return authority_harness.fresh_approve(
        conn, task_id, authority_evidence=evidence, authority=_TEST_AUTHORITY
    )


def _resume(conn, task_id: str, *, evidence: str | None = None):
    stop = glh._event_payload(conn, task_id, "theseus_architect_stop")
    assert stop is not None
    evidence = evidence or _signed_authority(
        conn,
        task_id,
        action="resume_after_architect_decision",
        evidence_type="architect_decision",
        principal=_TEST_ARCHITECT,
        principal_role="architect",
        run_id=int(stop["stopped_run_id"]),
        stop_token=stop["stop_token"],
    )
    return authority_harness.resume(
        conn, task_id, authority_evidence=evidence, authority=_TEST_AUTHORITY
    )


def _create_role_task(conn, **kwargs):
    role = kwargs["role"]
    builder_task_id = kwargs["builder_task_id"]
    evidence = _signed_authority(
        conn,
        builder_task_id,
        action=f"create_{role}_task",
        evidence_type="architect_decision",
        principal=_TEST_ARCHITECT,
        principal_role="architect",
    )
    kwargs["authority_evidence"] = evidence
    kwargs["authority"] = _TEST_AUTHORITY
    kwargs.pop("authorization_ref", None)
    return authority_harness.create_role_task(conn, **kwargs)


@pytest.fixture
def lifecycle_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_KANBAN_HOME", str(home))
    monkeypatch.setenv("HERMES_PROFILE", glh.DESIGNATED_DISPATCHER_PROFILE)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(glh.time, "time", lambda: 110)
    monkeypatch.setattr(
        glh,
        "_read_git_identity",
        lambda path: {
            "root": str(Path(path).resolve()),
            "branch": {
                "builder-wt": "pilot/builder",
                "reviewer-wt": "pilot/reviewer",
                "investigator-wt": "pilot/investigator",
            }.get(Path(path).name, "pilot/builder"),
            "head": "b" * 40,
            "parent": "a" * 40,
        },
        raising=False,
    )
    monkeypatch.setattr(kbd, "_profile_exists_fn", lambda: lambda _profile: True)
    monkeypatch.setattr(
        kbd._kbw,
        "_resolve_worktree_workspace",
        lambda task, board=None: (Path(task.workspace_path), task.branch_name),
    )
    kb._INITIALIZED_PATHS.discard(str(kb.kanban_db_path(board="default").resolve()))
    kb.init_db(board="default")
    with kbc.connect_closing(board="default") as conn:
        yield conn, tmp_path


def _builder(conn, tmp_path: Path, *, expires_at: int = 200):
    worktree = tmp_path / "builder-wt"
    worktree.mkdir()
    return glh.create_builder_task(
        conn,
        package_id="pkg-pilot",
        title="Synthetic Builder",
        baseline_sha="a" * 40,
        candidate_sha="b" * 40,
        branch="pilot/builder",
        worktree=str(worktree),
        approval_expires_at=expires_at,
    )


def test_production_authority_is_blocked_without_trusted_configuration(lifecycle_db):
    conn, tmp_path = lifecycle_db
    task_id = _builder(conn, tmp_path)

    with pytest.raises(
        ValueError,
        match="^BLOCKED — TRUSTED AUTHORITY NOT CONFIGURED$",
    ):
        glh.record_terminal_approval(
            conn,
            task_id,
            approval_ref="caller-controlled",
            approved_at=110,
        )

    task = kb.get_task(conn, task_id)
    assert task is not None
    assert task.status == "blocked"
    assert task.current_step_key == glh.AWAITING_TERMINAL_APPROVAL
    assert not any(
        event.kind == "theseus_terminal_approved"
        for event in kb.list_events(conn, task_id)
    )


def test_cli_and_gateway_shared_slash_path_reject_caller_metadata(lifecycle_db):
    conn, tmp_path = lifecycle_db
    task_id = _builder(conn, tmp_path)

    output = kc.run_slash(
        f"lifecycle approve {task_id} --authority-evidence forged --json"
    )

    assert "BLOCKED — TRUSTED AUTHORITY NOT CONFIGURED" in output
    assert kb.get_task(conn, task_id).status == "blocked"


def test_public_lifecycle_rejects_synthetic_test_configuration(lifecycle_db):
    conn, tmp_path = lifecycle_db
    task_id = _builder(conn, tmp_path)
    evidence = _signed_authority(
        conn,
        task_id,
        action="record_terminal_approval",
        evidence_type="terminal_approval",
        principal=_TEST_APPROVER,
        principal_role="approver",
    )

    with pytest.raises(
        ValueError,
        match="^BLOCKED — TRUSTED AUTHORITY NOT CONFIGURED$",
    ):
        glh.record_terminal_approval(
            conn,
            task_id,
            authority_evidence=evidence,
            _test_authority=_TEST_AUTHORITY,
        )

    assert kb.get_task(conn, task_id).status == "blocked"
    assert not any(
        event.kind == "theseus_authority_consumed"
        for event in kb.list_events(conn, task_id)
    )


def test_shipped_lifecycle_exposes_no_synthetic_authority_mutation_surface():
    assert not hasattr(glh, "SyntheticAuthorityTestConfiguration")
    assert not hasattr(glh, "_record_terminal_approval_for_test")
    assert not hasattr(glh, "_issue_fresh_terminal_approval_for_test")
    assert not hasattr(glh, "_create_role_task_for_test")
    assert not hasattr(glh, "_resume_after_architect_decision_for_test")


@pytest.mark.parametrize("role", ["reviewer", "investigator"])
def test_public_role_creation_is_blocked_before_any_database_write(lifecycle_db, role):
    conn, tmp_path = lifecycle_db
    builder_id = _builder(conn, tmp_path)
    with kb.write_txn(conn):
        conn.execute("UPDATE tasks SET status='done' WHERE id=?", (builder_id,))
    role_path = tmp_path / f"blocked-{role}-wt"
    role_path.mkdir()
    before = "\n".join(conn.iterdump())

    with pytest.raises(ValueError, match="^BLOCKED — TRUSTED AUTHORITY NOT CONFIGURED$"):
        glh.create_role_task(
            conn,
            builder_task_id=builder_id,
            role=role,
            title=f"Blocked {role}",
            candidate_sha="b" * 40,
            branch=f"pilot/blocked-{role}",
            worktree=str(role_path),
            authority_evidence="caller-controlled",
        )

    assert "\n".join(conn.iterdump()) == before


@pytest.mark.parametrize("role", ["reviewer", "investigator"])
def test_authorized_role_creation_rolls_back_authority_and_all_role_writes(
    lifecycle_db, monkeypatch, role
):
    conn, tmp_path = lifecycle_db
    builder_id = _builder(conn, tmp_path)
    with kb.write_txn(conn):
        conn.execute("UPDATE tasks SET status='done' WHERE id=?", (builder_id,))
    role_path = tmp_path / f"rollback-{role}-wt"
    role_path.mkdir()
    monkeypatch.setattr(
        glh,
        "_read_git_identity",
        lambda path: {
            "root": str(Path(path).resolve()),
            "branch": f"pilot/rollback-{role}",
            "head": "b" * 40,
            "parent": "a" * 40,
        },
    )
    before = "\n".join(conn.iterdump())
    original_append = kb._append_event

    def fail_final_audit(conn_arg, task_id, kind, payload, **kwargs):
        if kind == "theseus_role_task_linked":
            raise RuntimeError("forced role audit failure")
        return original_append(conn_arg, task_id, kind, payload, **kwargs)

    monkeypatch.setattr(kb, "_append_event", fail_final_audit)

    with pytest.raises(RuntimeError, match="forced role audit failure"):
        _create_role_task(
            conn,
            builder_task_id=builder_id,
            role=role,
            title=f"Rollback {role}",
            candidate_sha="b" * 40,
            branch=f"pilot/rollback-{role}",
            worktree=str(role_path),
        )

    assert "\n".join(conn.iterdump()) == before


def test_direct_phase_transition_cannot_bypass_authority_boundary(lifecycle_db):
    conn, tmp_path = lifecycle_db
    task_id = _builder(conn, tmp_path)

    with pytest.raises(ValueError, match="authority mutation boundary"):
        glh._transition(
            conn,
            task_id,
            glh.READY_FOR_BUILDER,
            actor="architect",
        )

    task = kb.get_task(conn, task_id)
    assert task is not None
    assert task.status == "blocked"
    assert task.current_step_key == glh.AWAITING_TERMINAL_APPROVAL


def test_signed_wrong_scope_and_caller_metadata_cannot_authorize(lifecycle_db):
    conn, tmp_path = lifecycle_db
    task_id = _builder(conn, tmp_path)
    wrong_scope = _signed_authority(
        conn,
        task_id,
        action="record_terminal_approval",
        evidence_type="terminal_approval",
        principal=_TEST_APPROVER,
        principal_role="approver",
        overrides={"scope": "forged.scope"},
    )

    with pytest.raises(ValueError, match="binding"):
        authority_harness.approve(
            conn,
            task_id,
            authority_evidence=wrong_scope,
            authority=_TEST_AUTHORITY,
            approval_ref="caller-cannot-repair-scope",
            actor="architect",
        )

    assert kb.get_task(conn, task_id).status == "blocked"
    assert not any(
        event.kind == "theseus_authority_consumed"
        for event in kb.list_events(conn, task_id)
    )


def test_receipt_consumption_and_transition_are_atomic_against_replay(lifecycle_db):
    conn, tmp_path = lifecycle_db
    task_id = _builder(conn, tmp_path)
    evidence = _signed_authority(
        conn,
        task_id,
        action="record_terminal_approval",
        evidence_type="terminal_approval",
        principal=_TEST_APPROVER,
        principal_role="approver",
    )

    assert _approve(conn, task_id, evidence=evidence)
    with kb.write_txn(conn):
        conn.execute(
            "UPDATE tasks SET status='blocked', current_step_key=?, block_kind='approval' WHERE id=?",
            (glh.AWAITING_TERMINAL_APPROVAL, task_id),
        )
    with pytest.raises(ValueError, match="replay"):
        _approve(conn, task_id, evidence=evidence)

    task = kb.get_task(conn, task_id)
    assert task is not None and task.status == "blocked"
    events = kb.list_events(conn, task_id)
    assert sum(event.kind == "theseus_authority_consumed" for event in events) == 1
    assert sum(event.kind == "theseus_terminal_approved" for event in events) == 1


def test_concurrent_signed_approval_has_one_state_transition(lifecycle_db):
    conn, tmp_path = lifecycle_db
    task_id = _builder(conn, tmp_path)
    evidence = _signed_authority(
        conn,
        task_id,
        action="record_terminal_approval",
        evidence_type="terminal_approval",
        principal=_TEST_APPROVER,
        principal_role="approver",
    )

    def attempt(_index):
        with kbc.connect_closing(board="default") as contender:
            try:
                _approve(contender, task_id, evidence=evidence)
                return "accepted"
            except ValueError:
                return "rejected"

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(attempt, range(16)))

    assert outcomes.count("accepted") == 1
    assert outcomes.count("rejected") == 15
    events = kb.list_events(conn, task_id)
    assert sum(event.kind == "theseus_authority_consumed" for event in events) == 1
    assert sum(event.kind == "theseus_terminal_approved" for event in events) == 1


def test_glh_01_and_03_stable_task_new_run_and_approval_gate(lifecycle_db):
    conn, tmp_path = lifecycle_db
    task_id = _builder(conn, tmp_path)

    task = kb.get_task(conn, task_id)
    assert task is not None
    assert task.status == "blocked"
    assert task.block_kind == "approval"
    assert task.current_step_key == glh.AWAITING_TERMINAL_APPROVAL
    assert kb.list_runs(conn, task_id) == []
    assert task.worker_pid is None

    assert _approve(conn, task_id)
    first = kbd.dispatch_once(conn, spawn_fn=lambda *_args, **_kwargs: 41001)
    assert [item[0] for item in first.spawned] == [task_id]
    first_task = kb.get_task(conn, task_id)
    first_run = first_task.current_run_id
    assert first_run is not None
    assert first_task.worker_pid == 41001
    assert first_task.current_step_key == glh.BUILDER_RUNNING
    run = kb.list_runs(conn, task_id)[0]
    assert run.metadata["artifacts"]["report"].endswith(f"/{task_id}/{first_run}/report.md")
    assert run.metadata["artifacts"]["result"].endswith(f"/{task_id}/{first_run}/result.md")
    assert kbd.heartbeat_worker(conn, task_id, expected_run_id=first_run)
    first_task = kb.get_task(conn, task_id)
    assert first_task.last_heartbeat_at is not None

    assert glh.stop_for_architect(
        conn,
        task_id,
        expected_run_id=first_run,
        stop_type="architecture",
        reason="Architect decision required",
        decision_questions=["Proceed with synthetic correction?"],
        forbidden_actions=["Do not dispatch"],
        baseline_sha="a" * 40,
        candidate_sha="b" * 40,
    )
    stopped = kb.get_task(conn, task_id)
    assert stopped.id == task_id
    assert stopped.worker_pid is None
    assert stopped.status == "blocked"
    assert stopped.current_step_key == glh.STOPPED_AWAITING_ARCHITECT

    assert _resume(conn, task_id)
    second = kbd.dispatch_once(conn, spawn_fn=lambda *_args, **_kwargs: 41002)
    assert [item[0] for item in second.spawned] == [task_id]
    resumed = kb.get_task(conn, task_id)
    assert resumed.current_run_id != first_run
    assert resumed.worker_pid == 41002
    assert len(kb.list_runs(conn, task_id)) == 2


def test_investigator_creation_rejects_caller_supplied_architect_reference(lifecycle_db):
    conn, tmp_path = lifecycle_db
    builder_id = _builder(conn, tmp_path)
    with kb.write_txn(conn):
        conn.execute("UPDATE tasks SET status='done' WHERE id=?", (builder_id,))
    investigator_path = tmp_path / "investigator-wt"
    investigator_path.mkdir()

    with pytest.raises(
        ValueError,
        match="^BLOCKED — TRUSTED AUTHORITY NOT CONFIGURED$",
    ):
        glh.create_role_task(
            conn,
            builder_task_id=builder_id,
            role="investigator",
            title="Synthetic Investigator",
            candidate_sha="b" * 40,
            branch="pilot/investigator",
            worktree=str(investigator_path),
            authorization_ref="architect:caller-controlled",
        )

    assert conn.execute(
        "SELECT COUNT(*) FROM tasks WHERE id != ?", (builder_id,)
    ).fetchone()[0] == 0


def test_native_completion_finalizes_exact_run_and_phase(lifecycle_db):
    conn, tmp_path = lifecycle_db
    task_id = _builder(conn, tmp_path)
    _approve(conn, task_id)
    assert kbd.dispatch_once(conn, spawn_fn=lambda *_args, **_kwargs: 41101).spawned
    task = kb.get_task(conn, task_id)
    assert task is not None and task.current_run_id is not None
    run_id = task.current_run_id
    run = kb.list_runs(conn, task_id)[0]
    Path(run.metadata["artifacts"]["report"]).write_text("report\n", encoding="utf-8")
    Path(run.metadata["artifacts"]["result"]).write_text("result\n", encoding="utf-8")

    assert kb.complete_task(conn, task_id, expected_run_id=run_id)

    completed = kb.get_task(conn, task_id)
    assert completed is not None
    assert completed.current_step_key == glh.BUILDER_COMPLETE_AWAITING_REVIEW
    terminal_run = kb.list_runs(conn, task_id)[0]
    assert terminal_run.ended_at is not None
    assert terminal_run.metadata["theseus_artifacts"]["artifacts"]["report"]["sha256"]
    assert terminal_run.metadata["theseus_artifacts"]["artifacts"]["result"]["sha256"]


def test_native_request_review_finalizes_exact_run_and_phase(lifecycle_db):
    conn, tmp_path = lifecycle_db
    task_id = _builder(conn, tmp_path)
    _approve(conn, task_id)
    assert kbd.dispatch_once(conn, spawn_fn=lambda *_args, **_kwargs: 41102).spawned
    task = kb.get_task(conn, task_id)
    assert task is not None and task.current_run_id is not None
    run_id = task.current_run_id
    run = kb.list_runs(conn, task_id)[0]
    assert isinstance(run.metadata, dict)
    Path(run.metadata["artifacts"]["report"]).write_text("review report\n", encoding="utf-8")
    Path(run.metadata["artifacts"]["result"]).write_text("review result\n", encoding="utf-8")

    assert kb.request_review(conn, task_id, expected_run_id=run_id)

    reviewed = kb.get_task(conn, task_id)
    assert reviewed is not None
    assert reviewed.current_step_key == glh.BUILDER_COMPLETE_AWAITING_REVIEW
    terminal_run = kb.list_runs(conn, task_id)[0]
    assert terminal_run.outcome == "review_requested"
    assert isinstance(terminal_run.metadata, dict)
    assert terminal_run.metadata["theseus_artifacts"]["run_id"] == run_id
    assert terminal_run.metadata["theseus_artifacts"]["artifacts"]["report"]["sha256"]


def test_native_request_changes_finalizes_exact_reviewer_run(lifecycle_db):
    conn, tmp_path = lifecycle_db
    builder_id = _builder(conn, tmp_path)
    with kb.write_txn(conn):
        conn.execute("UPDATE tasks SET status='done' WHERE id=?", (builder_id,))
    reviewer_path = tmp_path / "reviewer-wt"
    reviewer_path.mkdir()
    reviewer_id = _create_role_task(
        conn,
        builder_task_id=builder_id,
        role="reviewer",
        title="Native review changes",
        candidate_sha="b" * 40,
        branch="pilot/reviewer",
        worktree=str(reviewer_path),
    )
    with kb.write_txn(conn):
        conn.execute("UPDATE tasks SET status='review' WHERE id=?", (reviewer_id,))
        kb._append_event(
            conn,
            reviewer_id,
            "review_requested",
            {"implementer": "theseus-builder", "reviewer": "theseus-reviewer"},
        )
    assert kbd.dispatch_once(conn, spawn_fn=lambda *_args, **_kwargs: 41103).spawned
    task = kb.get_task(conn, reviewer_id)
    assert task is not None and task.current_run_id is not None
    run_id = task.current_run_id
    run = kb.list_runs(conn, reviewer_id)[0]
    assert isinstance(run.metadata, dict)
    Path(run.metadata["artifacts"]["report"]).write_text("change report\n", encoding="utf-8")
    Path(run.metadata["artifacts"]["result"]).write_text("change result\n", encoding="utf-8")

    changed, _implementer = kb.request_changes(
        conn, reviewer_id, reason="correct this", expected_run_id=run_id
    )

    assert changed
    reviewed = kb.get_task(conn, reviewer_id)
    assert reviewed is not None and reviewed.current_step_key == glh.CHANGES_REQUESTED
    terminal_run = kb.list_runs(conn, reviewer_id)[0]
    assert terminal_run.outcome == "changes_requested"
    assert isinstance(terminal_run.metadata, dict)
    assert terminal_run.metadata["theseus_artifacts"]["run_id"] == run_id
    assert terminal_run.metadata["theseus_artifacts"]["artifacts"]["result"]["sha256"]


@pytest.mark.parametrize(
    ("role", "worktree_name", "branch", "pid", "expected_phase"),
    [
        ("reviewer", "reviewer-wt", "pilot/reviewer", 41104, glh.GATE2_RECOMMENDATION_READY),
        ("investigator", "investigator-wt", "pilot/investigator", 41105, glh.CORRECTION_READY),
    ],
)
def test_native_role_completion_finalizes_run_hashes(
    lifecycle_db, role, worktree_name, branch, pid, expected_phase
):
    conn, tmp_path = lifecycle_db
    builder_id = _builder(conn, tmp_path)
    with kb.write_txn(conn):
        conn.execute("UPDATE tasks SET status='done' WHERE id=?", (builder_id,))
    role_path = tmp_path / worktree_name
    role_path.mkdir()
    role_id = _create_role_task(
        conn,
        builder_task_id=builder_id,
        role=role,
        title=f"Native {role} completion",
        candidate_sha="b" * 40,
        branch=branch,
        worktree=str(role_path),
        authorization_ref="architect:investigate" if role == "investigator" else None,
    )
    assert kbd.dispatch_once(conn, spawn_fn=lambda *_args, **_kwargs: pid).spawned
    task = kb.get_task(conn, role_id)
    assert task is not None and task.current_run_id is not None
    run_id = task.current_run_id
    run = kb.list_runs(conn, role_id)[0]
    assert isinstance(run.metadata, dict)
    Path(run.metadata["artifacts"]["report"]).write_text(f"{role} report\n", encoding="utf-8")
    Path(run.metadata["artifacts"]["result"]).write_text(f"{role} result\n", encoding="utf-8")

    assert kb.complete_task(conn, role_id, expected_run_id=run_id)

    completed = kb.get_task(conn, role_id)
    assert completed is not None and completed.current_step_key == expected_phase
    terminal_run = kb.list_runs(conn, role_id)[0]
    assert terminal_run.ended_at is not None
    assert isinstance(terminal_run.metadata, dict)
    assert terminal_run.metadata["theseus_artifacts"]["run_id"] == run_id
    assert terminal_run.metadata["theseus_artifacts"]["artifacts"]["report"]["sha256"]
    assert terminal_run.metadata["theseus_artifacts"]["artifacts"]["result"]["sha256"]


def test_builder_creation_has_no_caller_controlled_clock():
    assert "now" not in inspect.signature(glh.create_builder_task).parameters


def test_concurrent_builder_creation_has_one_durable_identity(lifecycle_db):
    conn, tmp_path = lifecycle_db
    worktree = tmp_path / "concurrent-builder"
    worktree.mkdir()

    def create(_index):
        with kbc.connect_closing(board="default") as worker_conn:
            return glh.create_builder_task(
                worker_conn,
                package_id="pkg-concurrent",
                title="Concurrent Builder",
                baseline_sha="a" * 40,
                candidate_sha="b" * 40,
                branch="pilot/concurrent",
                worktree=str(worktree),
                approval_expires_at=200,
            )

    with ThreadPoolExecutor(max_workers=8) as pool:
        ids = list(pool.map(create, range(16)))

    assert len(set(ids)) == 1
    rows = conn.execute(
        "SELECT id FROM tasks WHERE idempotency_key=? AND status != 'archived'",
        ("theseus-work-package:pkg-concurrent:builder",),
    ).fetchall()
    assert [row["id"] for row in rows] == [ids[0]]


def test_glh_03_expired_approval_never_creates_run_or_pid(lifecycle_db, monkeypatch):
    conn, tmp_path = lifecycle_db
    monkeypatch.setattr(glh.time, "time", lambda: 100)
    task_id = _builder(conn, tmp_path, expires_at=105)
    monkeypatch.setattr(glh.time, "time", lambda: 110)

    expired = _signed_authority(
        conn,
        task_id,
        action="record_terminal_approval",
        evidence_type="terminal_approval",
        principal=_TEST_APPROVER,
        principal_role="approver",
        issued_at=100,
        expires_at=105,
    )
    with pytest.raises(ValueError, match="expired"):
        _approve(conn, task_id, evidence=expired)
    result = kbd.dispatch_once(conn, spawn_fn=lambda *_args, **_kwargs: 99999)

    assert result.spawned == []
    task = kb.get_task(conn, task_id)
    assert task.status == "blocked"
    assert task.current_step_key == glh.AWAITING_TERMINAL_APPROVAL
    assert task.worker_pid is None
    assert kb.list_runs(conn, task_id) == []
    assert not any(
        event.kind in {"theseus_authority_consumed", "theseus_terminal_approved"}
        for event in kb.list_events(conn, task_id)
    )

    assert _fresh_approve(conn, task_id)
    fresh = kbd.dispatch_once(conn, spawn_fn=lambda *_args, **_kwargs: 99998)
    assert [item[0] for item in fresh.spawned] == [task_id]


@pytest.mark.parametrize(
    ("now", "allowed"),
    [(149, True), (150, False), (151, False)],
)
def test_stored_approval_expiry_is_exclusive_at_claim_boundary(
    lifecycle_db, monkeypatch, now, allowed
):
    conn, tmp_path = lifecycle_db
    task_id = _builder(conn, tmp_path)
    assert _approve(conn, task_id, expires_at=150)

    monkeypatch.setattr(glh.time, "time", lambda: now)

    assert (glh._approval_for_claim(conn, task_id) is not None) is allowed
    assert glh.dispatch_preflight(conn, task_id) == (
        allowed,
        None if allowed else "approval_expired",
    )


def test_exact_expiry_dispatch_creates_no_run_claim_or_state_transition(
    lifecycle_db, monkeypatch
):
    conn, tmp_path = lifecycle_db
    task_id = _builder(conn, tmp_path)
    assert _approve(conn, task_id, expires_at=150)
    before_task = kb.get_task(conn, task_id)
    before_events = [(event.kind, event.payload) for event in kb.list_events(conn, task_id)]
    monkeypatch.setattr(glh.time, "time", lambda: 150)

    dispatched = kbd.dispatch_once(conn, spawn_fn=lambda *_args, **_kwargs: 99997)

    after_task = kb.get_task(conn, task_id)
    assert before_task is not None
    assert after_task is not None
    assert dispatched.spawned == []
    assert kb.list_runs(conn, task_id) == []
    assert (after_task.status, after_task.current_step_key) == (
        before_task.status,
        before_task.current_step_key,
    )
    assert [(event.kind, event.payload) for event in kb.list_events(conn, task_id)] == before_events


def test_exact_expiry_native_claim_creates_no_run_or_state_transition(
    lifecycle_db, monkeypatch
):
    conn, tmp_path = lifecycle_db
    task_id = _builder(conn, tmp_path)
    assert _approve(conn, task_id, expires_at=150)
    before_task = kb.get_task(conn, task_id)
    assert before_task is not None
    monkeypatch.setattr(glh.time, "time", lambda: 150)

    assert kb.claim_task(conn, task_id) is None

    after_task = kb.get_task(conn, task_id)
    assert after_task is not None
    assert kb.list_runs(conn, task_id) == []
    assert (after_task.status, after_task.current_step_key) == (
        before_task.status,
        before_task.current_step_key,
    )
    assert not any(
        event.kind in {"claimed", "spawned", "theseus_approval_consumed"}
        for event in kb.list_events(conn, task_id)
    )


def test_native_claim_unblock_and_promote_cannot_bypass_terminal_approval(lifecycle_db):
    conn, tmp_path = lifecycle_db
    task_id = _builder(conn, tmp_path)

    assert not kb.unblock_task(conn, task_id)
    promoted, reason = kb.promote_task(conn, task_id, actor="operator", force=True)
    assert not promoted
    assert reason == "THESEUS lifecycle gate requires terminal approval"
    with kb.write_txn(conn):
        conn.execute("UPDATE tasks SET status='ready' WHERE id=?", (task_id,))
    assert kb.claim_task(conn, task_id) is None
    assert kb.list_runs(conn, task_id) == []


def test_generic_unblock_cannot_bypass_lifecycle_approval(lifecycle_db):
    conn, tmp_path = lifecycle_db
    task_id = _builder(conn, tmp_path)

    assert not kb.unblock_task(conn, task_id)
    result = kbd.dispatch_once(conn, spawn_fn=lambda *_args, **_kwargs: 99999)

    assert result.spawned == []
    assert kb.list_runs(conn, task_id) == []
    task = kb.get_task(conn, task_id)
    assert task.status == "blocked"
    assert task.current_step_key == glh.AWAITING_TERMINAL_APPROVAL
    assert not any(event.kind == "spawned" for event in kb.list_events(conn, task_id))


def test_glh_02_resume_requires_specific_architect_decision(lifecycle_db):
    conn, tmp_path = lifecycle_db
    task_id = _builder(conn, tmp_path)
    _approve(conn, task_id)
    kbd.dispatch_once(conn, spawn_fn=lambda *_args, **_kwargs: 42001)
    run_id = kb.get_task(conn, task_id).current_run_id
    glh.stop_for_architect(
        conn,
        task_id,
        expected_run_id=run_id,
        stop_type="approval",
        reason="Need scope decision",
        decision_questions=["Authorize correction?"],
        forbidden_actions=["No worker launch"],
        baseline_sha="a" * 40,
        candidate_sha="b" * 40,
    )

    with pytest.raises(ValueError, match="^BLOCKED — TRUSTED AUTHORITY NOT CONFIGURED$"):
        glh.resume_after_architect_decision(conn, task_id, decision_ref="", actor="architect")

    assert kbd.dispatch_once(conn, spawn_fn=lambda *_args, **_kwargs: 42002).spawned == []
    assert len(kb.list_runs(conn, task_id)) == 1


def test_resume_rejects_forged_actor_and_actual_git_mismatch(lifecycle_db, monkeypatch):
    conn, tmp_path = lifecycle_db
    task_id = _builder(conn, tmp_path)
    _approve(conn, task_id)
    kbd.dispatch_once(conn, spawn_fn=lambda *_args, **_kwargs: 42011)
    run_id = kb.get_task(conn, task_id).current_run_id
    assert run_id is not None
    assert glh.stop_for_architect(
        conn,
        task_id,
        expected_run_id=run_id,
        stop_type="scope",
        reason="decision",
        decision_questions=["continue?"],
        forbidden_actions=["do not dispatch"],
        baseline_sha="a" * 40,
        candidate_sha="b" * 40,
    )
    with pytest.raises(ValueError, match="^BLOCKED — TRUSTED AUTHORITY NOT CONFIGURED$"):
        glh.resume_after_architect_decision(
            conn, task_id, decision_ref="forged", actor="builder"
        )
    monkeypatch.setattr(
        glh,
        "_read_git_identity",
        lambda _path: {
            "root": str(tmp_path / "builder-wt"),
            "branch": "wrong/branch",
            "head": "c" * 40,
            "parent": "a" * 40,
        },
    )
    stop = glh._event_payload(conn, task_id, "theseus_architect_stop")
    assert stop is not None
    with pytest.raises(ValueError, match="Git identity"):
        authority_harness.resume(
            conn,
            task_id,
            authority_evidence=_signed_authority(
                conn,
                task_id,
                action="resume_after_architect_decision",
                evidence_type="architect_decision",
                principal=_TEST_ARCHITECT,
                principal_role="architect",
                run_id=int(run_id),
                stop_token=stop["stop_token"],
            ),
            authority=_TEST_AUTHORITY,
        )


def test_legacy_task_dispatch_is_unchanged(lifecycle_db):
    conn, _ = lifecycle_db
    task_id = kb.create_task(conn, title="legacy", assignee="worker")
    result = kbd.dispatch_once(conn, spawn_fn=lambda *_args, **_kwargs: 43001)
    assert [item[0] for item in result.spawned] == [task_id]
    assert kb.get_task(conn, task_id).workflow_template_id is None


def test_glh_04_and_05_crash_recovery_requires_fresh_approval(lifecycle_db, monkeypatch):
    conn, tmp_path = lifecycle_db
    task_id = _builder(conn, tmp_path)
    _approve(conn, task_id)
    assert len(kbd.dispatch_once(conn, spawn_fn=lambda *_args, **_kwargs: 45001).spawned) == 1
    first_run = kb.get_task(conn, task_id).current_run_id

    monkeypatch.setenv("HERMES_KANBAN_CRASH_GRACE_SECONDS", "0")
    monkeypatch.setattr(kbd, "_pid_alive", lambda _pid: False)
    recovered = kbd.dispatch_once(conn, spawn_fn=lambda *_args, **_kwargs: 45002)

    assert recovered.crashed == [task_id]
    assert recovered.spawned == []
    task = kb.get_task(conn, task_id)
    assert task is not None
    assert task.status == "blocked"
    assert task.current_step_key == glh.AWAITING_TERMINAL_APPROVAL
    assert task.current_run_id is None
    assert task.worker_pid is None
    runs = kb.list_runs(conn, task_id)
    assert len(runs) == 1
    assert runs[0].id == first_run
    assert runs[0].outcome == "crashed"


def test_glh_06_two_dispatch_ticks_create_one_run(lifecycle_db):
    conn, tmp_path = lifecycle_db
    task_id = _builder(conn, tmp_path)
    _approve(conn, task_id)
    calls = []

    first = kbd.dispatch_once(conn, spawn_fn=lambda *_args, **_kwargs: calls.append(task_id) or 46001)
    second = kbd.dispatch_once(conn, spawn_fn=lambda *_args, **_kwargs: calls.append(task_id) or 46002)

    assert len(first.spawned) == 1
    assert second.spawned == []
    assert calls == [task_id]
    assert len(kb.list_runs(conn, task_id)) == 1


def test_isolated_pilot_uses_synthetic_subprocess_and_run_readback(lifecycle_db):
    conn, tmp_path = lifecycle_db
    task_id = _builder(conn, tmp_path)
    assert _approve(conn, task_id)
    workers: list[subprocess.Popen] = []

    def spawn_synthetic(*_args, **_kwargs):
        worker = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            cwd=tmp_path,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        workers.append(worker)
        return worker.pid

    try:
        dispatched = kbd.dispatch_once(conn, spawn_fn=spawn_synthetic)
        assert [item[0] for item in dispatched.spawned] == [task_id]
        state = glh.readback(conn, task_id)
        run_id = state["current_run_id"]
        assert state["worker_pid"] == workers[0].pid
        assert state["active_run"] == run_id
        package = glh.package_metadata(conn, task_id)
        assert package is not None
        assert package["worktree"] == str(tmp_path / "builder-wt")
        assert kbd.heartbeat_worker(conn, task_id, expected_run_id=run_id)
        assert glh.stop_for_architect(
            conn,
            task_id,
            expected_run_id=run_id,
            stop_type="pilot-decision",
            reason="Synthetic pilot STOP",
            decision_questions=["Resume the isolated pilot?"],
            forbidden_actions=["Do not dispatch before decision"],
            baseline_sha="a" * 40,
            candidate_sha="b" * 40,
        )
        stopped = glh.readback(conn, task_id)
        assert stopped["status"] == "blocked"
        assert stopped["worker_pid"] is None
        assert stopped["active_run"] is None
    finally:
        for worker in workers:
            if worker.poll() is None:
                worker.terminate()
                worker.wait(timeout=5)


def test_glh_07_reviewer_and_investigator_use_separate_linked_worktrees(lifecycle_db):
    conn, tmp_path = lifecycle_db
    builder_id = _builder(conn, tmp_path)
    with kb.write_txn(conn):
        conn.execute("UPDATE tasks SET status='done' WHERE id=?", (builder_id,))
    builder_path = kb.get_task(conn, builder_id).workspace_path

    reviewer_path = tmp_path / "reviewer-wt"
    investigator_path = tmp_path / "investigator-wt"
    reviewer_path.mkdir()
    investigator_path.mkdir()
    reviewer_id = _create_role_task(
        conn,
        builder_task_id=builder_id,
        role="reviewer",
        title="Synthetic review",
        candidate_sha="b" * 40,
        branch="pilot/reviewer",
        worktree=str(reviewer_path),
    )
    investigator_id = _create_role_task(
        conn,
        builder_task_id=builder_id,
        role="investigator",
        title="Synthetic investigation",
        candidate_sha="b" * 40,
        branch="pilot/investigator",
        worktree=str(investigator_path),
        authorization_ref="architect:synthetic-investigation",
    )

    assert len({builder_id, reviewer_id, investigator_id}) == 3
    role_tasks = [kb.get_task(conn, reviewer_id), kb.get_task(conn, investigator_id)]
    assert {task.assignee for task in role_tasks} == {"theseus-reviewer", "theseus-investigator"}
    assert all(task.workspace_path != builder_path for task in role_tasks)
    assert kb.parent_ids(conn, reviewer_id) == [builder_id]
    assert kb.parent_ids(conn, investigator_id) == [builder_id]
    assert all(glh.package_metadata(conn, task.id)["candidate_sha"] == "b" * 40 for task in role_tasks)


def test_role_candidate_collision_and_nonconcurrency_are_enforced(lifecycle_db, monkeypatch):
    conn, tmp_path = lifecycle_db
    builder_id = _builder(conn, tmp_path)
    with kb.write_txn(conn):
        conn.execute("UPDATE tasks SET status='done' WHERE id=?", (builder_id,))
    reviewer_path = tmp_path / "reviewer-guard-wt"
    investigator_path = tmp_path / "investigator-guard-wt"
    reviewer_path.mkdir()
    investigator_path.mkdir()

    with pytest.raises(ValueError, match="candidate"):
        _create_role_task(
            conn,
            builder_task_id=builder_id,
            role="reviewer",
            title="mismatch",
            candidate_sha="c" * 40,
            branch="pilot/reviewer-guard",
            worktree=str(reviewer_path),
        )

    def identity(path):
        path = str(Path(path).resolve())
        branch = "pilot/reviewer-guard" if path == str(reviewer_path) else "pilot/investigator-guard"
        return {"root": path, "branch": branch, "head": "b" * 40, "parent": "a" * 40}

    monkeypatch.setattr(glh, "_read_git_identity", identity)
    reviewer_id = _create_role_task(
        conn,
        builder_task_id=builder_id,
        role="reviewer",
        title="review",
        candidate_sha="b" * 40,
        branch="pilot/reviewer-guard",
        worktree=str(reviewer_path),
    )
    with pytest.raises(ValueError, match="worktree|branch"):
        _create_role_task(
            conn,
            builder_task_id=builder_id,
            role="investigator",
            title="collision",
            candidate_sha="b" * 40,
            branch="pilot/reviewer-guard",
            worktree=str(reviewer_path),
            authorization_ref="architect:investigate",
        )
    investigator_id = _create_role_task(
        conn,
        builder_task_id=builder_id,
        role="investigator",
        title="investigation",
        candidate_sha="b" * 40,
        branch="pilot/investigator-guard",
        worktree=str(investigator_path),
        authorization_ref="architect:investigate",
    )
    first = kbd.dispatch_once(conn, spawn_fn=lambda *_args, **_kwargs: 49101, max_spawn=1)
    assert [item[0] for item in first.spawned] == [reviewer_id]
    second = kbd.dispatch_once(conn, spawn_fn=lambda *_args, **_kwargs: 49102)
    assert not [item for item in second.spawned if item[0] == investigator_id]


def test_role_native_claim_rejects_wrong_capability_and_active_peer(lifecycle_db, monkeypatch):
    conn, tmp_path = lifecycle_db
    builder_id = _builder(conn, tmp_path)
    with kb.write_txn(conn):
        conn.execute("UPDATE tasks SET status='done' WHERE id=?", (builder_id,))
    reviewer_path = tmp_path / "reviewer-native-wt"
    investigator_path = tmp_path / "investigator-native-wt"
    reviewer_path.mkdir()
    investigator_path.mkdir()
    monkeypatch.setattr(
        glh,
        "_read_git_identity",
        lambda path: {
            "root": str(Path(path).resolve()),
            "branch": (
                "pilot/reviewer-native"
                if Path(path).resolve() == reviewer_path.resolve()
                else "pilot/investigator-native"
            ),
            "head": "b" * 40,
            "parent": "a" * 40,
        },
    )
    reviewer_id = _create_role_task(
        conn,
        builder_task_id=builder_id,
        role="reviewer",
        title="native review",
        candidate_sha="b" * 40,
        branch="pilot/reviewer-native",
        worktree=str(reviewer_path),
    )
    investigator_id = _create_role_task(
        conn,
        builder_task_id=builder_id,
        role="investigator",
        title="native investigation",
        candidate_sha="b" * 40,
        branch="pilot/investigator-native",
        worktree=str(investigator_path),
        authorization_ref="architect:investigate",
    )

    with kb.write_txn(conn):
        conn.execute("UPDATE tasks SET assignee='theseus-builder' WHERE id=?", (reviewer_id,))
    assert kb.claim_task(conn, reviewer_id) is None
    with kb.write_txn(conn):
        conn.execute("UPDATE tasks SET assignee=? WHERE id=?", (glh.ROLE_PROFILES["reviewer"], reviewer_id))

    assert kb.claim_task(conn, reviewer_id) is None
    assert kb.list_runs(conn, reviewer_id) == []

    assert not hasattr(glh, "_role_dispatch_claim_grant")

    reviewer_dispatch = kbd.dispatch_once(
        conn, spawn_fn=lambda *_args, **_kwargs: 49801, max_spawn=1
    )
    assert [item[0] for item in reviewer_dispatch.spawned] == [reviewer_id]
    assert kb.claim_task(conn, investigator_id) is None
    assert kb.list_runs(conn, investigator_id) == []


@pytest.mark.parametrize("role", ["reviewer", "investigator"])
def test_role_worker_capabilities_are_enforced_at_schema_and_native_dispatch(monkeypatch, role):
    monkeypatch.setenv("HERMES_KANBAN_TASK", "t-role")
    monkeypatch.setenv("HERMES_THESEUS_RESTRICTED_ROLE", role)
    selected = model_tools._select_tool_names(["hermes-cli"], None, True)

    assert {"read_file", "search_files", "kanban_show", "kanban_complete"} <= selected
    assert not {
        "terminal",
        "process_manage",
        "write_file",
        "patch",
        "execute_code",
        "delegate_task",
        "tool_call",
        "skill_manage",
        "memory",
        "cronjob_manage",
    } & selected
    denied = json.loads(model_tools.handle_function_call("terminal", {"command": "git push"}))
    assert "read-only" in denied["error"]


def test_glh_08_run_artifacts_are_distinct_hashed_and_collision_guarded(lifecycle_db):
    _conn, tmp_path = lifecycle_db
    paths = glh.run_artifact_paths(tmp_path / "runs", "pilot", "task-1", 7)
    Path(paths["report"]).write_text("long report\n" * 20, encoding="utf-8")
    Path(paths["result"]).write_text("short result\n", encoding="utf-8")

    manifest = glh.finalize_artifacts(paths, manifest_facts={"candidate_sha": "b" * 40})

    assert paths["report"] != paths["result"]
    assert manifest["artifacts"]["report"]["sha256"] != manifest["artifacts"]["result"]["sha256"]
    assert os.stat(paths["directory"]).st_mode & 0o777 == 0o700
    assert os.stat(paths["manifest"]).st_mode & 0o777 == 0o600
    Path(paths["result"]).unlink()
    os.link(paths["report"], paths["result"])
    with pytest.raises(ValueError, match="collide"):
        glh.finalize_artifacts(paths)


def test_artifacts_reject_traversal_symlink_and_replacement(lifecycle_db):
    _conn, tmp_path = lifecycle_db
    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(real_parent, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        glh.run_artifact_paths(linked_parent / "runs", "board", "task-1", 1)

    root = tmp_path / "secure-runs"
    with pytest.raises(ValueError, match="component"):
        glh.run_artifact_paths(root, "../escape", "task-1", 1)

    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "linked").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        glh.run_artifact_paths(root, "linked", "task-1", 1)

    paths = glh.run_artifact_paths(root, "board", "task-1", 2)
    report = Path(paths["report"])
    report.write_text("original", encoding="utf-8")
    report.unlink()
    secret = tmp_path / "secret"
    secret.write_text("do not hash", encoding="utf-8")
    report.symlink_to(secret)
    with pytest.raises(ValueError, match="replaced|symlink"):
        glh.finalize_artifacts(paths)


def test_artifacts_reject_prepare_finalize_ancestor_replacement_with_hardlinks(lifecycle_db):
    _conn, tmp_path = lifecycle_db
    root = tmp_path / "secure-runs"
    paths = glh.run_artifact_paths(root, "board", "task-1", 3)
    Path(paths["report"]).write_text("report", encoding="utf-8")
    Path(paths["result"]).write_text("result", encoding="utf-8")

    held = tmp_path / "held-runs"
    root.rename(held)
    replacement = root / "board" / "task-1" / "3"
    replacement.mkdir(parents=True)
    os.link(held / "board" / "task-1" / "3" / "report.md", replacement / "report.md")
    os.link(held / "board" / "task-1" / "3" / "result.md", replacement / "result.md")

    with pytest.raises(ValueError, match="directory.*replaced|identity"):
        glh.finalize_artifacts(paths)
    assert not (replacement / "manifest.json").exists()
    assert not (held / "board" / "task-1" / "3" / "manifest.json").exists()


def test_artifact_publication_fails_closed_on_unsupported_platform(lifecycle_db, monkeypatch):
    _conn, tmp_path = lifecycle_db
    root = tmp_path / "unsupported-runs"
    monkeypatch.setattr(glh, "_artifact_platform_supported", lambda: False)

    with pytest.raises(ValueError, match="unsupported"):
        glh.run_artifact_paths(root, "board", "task-1", 39)

    assert not root.exists()


def test_artifact_manifest_recovers_around_stale_temp_and_never_replaces_final(lifecycle_db):
    _conn, tmp_path = lifecycle_db
    paths = glh.run_artifact_paths(tmp_path / "secure-runs", "board", "task-1", 41)
    Path(paths["report"]).write_text("report", encoding="utf-8")
    Path(paths["result"]).write_text("result", encoding="utf-8")
    stale = Path(paths["directory"]) / ".manifest.crashed.tmp"
    stale.write_text("partial", encoding="utf-8")

    glh.finalize_artifacts(paths)
    published = Path(paths["manifest"]).read_bytes()
    with pytest.raises(ValueError, match="manifest"):
        glh.finalize_artifacts(paths)

    assert Path(paths["manifest"]).read_bytes() == published
    assert stale.read_text(encoding="utf-8") == "partial"


def test_artifact_manifest_is_not_visible_before_complete_write(lifecycle_db, monkeypatch):
    _conn, tmp_path = lifecycle_db
    paths = glh.run_artifact_paths(tmp_path / "secure-runs", "board", "task-1", 40)
    Path(paths["report"]).write_text("report", encoding="utf-8")
    Path(paths["result"]).write_text("result", encoding="utf-8")
    original_write = glh.os.write
    observed = []

    def observing_write(fd, data):
        observed.append(Path(paths["manifest"]).exists())
        return original_write(fd, data)

    monkeypatch.setattr(glh.os, "write", observing_write)
    glh.finalize_artifacts(paths)

    assert observed and not any(observed)
    assert json.loads(Path(paths["manifest"]).read_text(encoding="utf-8"))["artifacts"]


def test_artifact_manifest_write_failure_removes_partial_file(lifecycle_db, monkeypatch):
    _conn, tmp_path = lifecycle_db
    paths = glh.run_artifact_paths(tmp_path / "secure-runs", "board", "task-1", 4)
    Path(paths["report"]).write_text("report", encoding="utf-8")
    Path(paths["result"]).write_text("result", encoding="utf-8")
    monkeypatch.setattr(glh.os, "fsync", lambda _fd: (_ for _ in ()).throw(OSError("forced fsync")))

    with pytest.raises(ValueError, match="manifest"):
        glh.finalize_artifacts(paths)
    assert not Path(paths["manifest"]).exists()


def test_missing_pid_and_pid_bind_failure_are_not_reported_as_spawned(lifecycle_db, monkeypatch):
    conn, tmp_path = lifecycle_db
    task_id = _builder(conn, tmp_path)
    _approve(conn, task_id)

    missing = kbd.dispatch_once(conn, spawn_fn=lambda *_args, **_kwargs: 0)
    assert missing.spawned == []
    missing_task = kb.get_task(conn, task_id)
    assert missing_task is not None
    assert missing_task.worker_pid is None
    assert not [run for run in kb.list_runs(conn, task_id) if run.ended_at is None]

    # A distinct fresh receipt is required for the retry.
    with kb.write_txn(conn):
        conn.execute(
            "UPDATE tasks SET status='blocked', current_step_key=?, block_kind='approval' WHERE id=?",
            (glh.AWAITING_TERMINAL_APPROVAL, task_id),
        )
    _fresh_approve(conn, task_id)
    terminated = []
    monkeypatch.setattr(kbd, "_set_worker_pid", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        kbd,
        "_capture_spawned_child",
        lambda _raw: kbd.SpawnedChildIdentity(pid=49001, pidfd=77, process=None),
    )
    monkeypatch.setattr(
        kbd,
        "_terminate_spawned_child",
        lambda identity: terminated.append(identity.pid) or {"terminated": True},
    )
    failed = kbd.dispatch_once(conn, spawn_fn=lambda *_args, **_kwargs: 49001)
    assert failed.spawned == []
    assert terminated == [49001]


def test_pid_bind_failure_does_not_kill_unverified_process(lifecycle_db, monkeypatch):
    conn, tmp_path = lifecycle_db
    task_id = _builder(conn, tmp_path)
    _approve(conn, task_id)
    terminated = []
    monkeypatch.setattr(kbd, "_set_worker_pid", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        kbd,
        "_capture_spawned_child",
        lambda _raw: kbd.SpawnedChildIdentity(pid=49002, pidfd=None, process=None),
    )
    monkeypatch.setattr(
        kbd,
        "_terminate_spawned_child",
        lambda identity: {
            "prev_pid": identity.pid,
            "birth_identity_verified": False,
            "termination_attempted": False,
            "terminated": False,
        },
    )

    failed = kbd.dispatch_once(conn, spawn_fn=lambda *_args, **_kwargs: 49002)

    assert failed.spawned == []
    assert terminated == []
    fenced = kb.get_task(conn, task_id)
    assert fenced is not None
    assert fenced.status == "blocked"
    assert fenced.block_kind == "manual"
    assert fenced.current_run_id is not None
    assert [run.id for run in kb.list_runs(conn, task_id) if run.ended_at is None] == [
        fenced.current_run_id
    ]
    retry = kbd.dispatch_once(conn, spawn_fn=lambda *_args, **_kwargs: 49022)
    assert retry.spawned == []


def test_spawn_cleanup_uses_birth_handle_instead_of_reusable_pid(monkeypatch):
    sent = []
    identity = kbd.SpawnedChildIdentity(pid=49033, pidfd=77, process=None)
    monkeypatch.setattr(
        kbd.signal,
        "pidfd_send_signal",
        lambda pidfd, sig, _siginfo=None, _flags=0: sent.append((pidfd, sig)),
        raising=False,
    )
    monkeypatch.setattr(kbd, "_poll_pidfd_exit", lambda _pidfd: True)
    monkeypatch.setattr(
        kbd.os,
        "kill",
        lambda *_args: (_ for _ in ()).throw(AssertionError("numeric PID signal used")),
    )

    result = kbd._terminate_spawned_child(identity)

    assert result["terminated"]
    assert sent == [(77, kbd.signal.SIGTERM)]


def test_pid_bind_exception_terminates_verified_child_and_preserves_retry_integrity(
    lifecycle_db, monkeypatch
):
    conn, tmp_path = lifecycle_db
    task_id = _builder(conn, tmp_path)
    _approve(conn, task_id)
    original_set_worker_pid = kbd._set_worker_pid
    terminated = []

    def forced_exception(*_args, **_kwargs):
        raise RuntimeError("forced PID bind exception")

    monkeypatch.setattr(kbd, "_set_worker_pid", forced_exception)
    monkeypatch.setattr(
        kbd,
        "_capture_spawned_child",
        lambda _raw: kbd.SpawnedChildIdentity(pid=49003, pidfd=78, process=None),
    )
    monkeypatch.setattr(
        kbd,
        "_terminate_spawned_child",
        lambda identity: terminated.append(identity.pid) or {"terminated": True},
    )

    failed = kbd.dispatch_once(conn, spawn_fn=lambda *_args, **_kwargs: 49003)

    assert failed.spawned == []
    assert terminated == [49003]
    failed_task = kb.get_task(conn, task_id)
    assert failed_task is not None and failed_task.worker_pid is None
    assert not [run for run in kb.list_runs(conn, task_id) if run.ended_at is None]

    monkeypatch.setattr(kbd, "_set_worker_pid", original_set_worker_pid)
    monkeypatch.setattr(
        kbd,
        "_capture_spawned_child",
        lambda raw: kbd.SpawnedChildIdentity(pid=int(raw), pidfd=None, process=None),
    )
    with kb.write_txn(conn):
        conn.execute(
            "UPDATE tasks SET status='blocked', current_step_key=?, block_kind='approval' WHERE id=?",
            (glh.AWAITING_TERMINAL_APPROVAL, task_id),
        )
    assert _fresh_approve(conn, task_id)
    retry = kbd.dispatch_once(conn, spawn_fn=lambda *_args, **_kwargs: 49004)
    assert [item[0] for item in retry.spawned] == [task_id]
    assert kb.get_task(conn, task_id).worker_pid == 49004
    assert len(kb.list_runs(conn, task_id)) == 2


def test_lifecycle_dry_run_is_byte_for_byte_non_mutating(lifecycle_db):
    conn, tmp_path = lifecycle_db
    lifecycle_id = _builder(conn, tmp_path)
    with kb.write_txn(conn):
        conn.execute("UPDATE tasks SET status='ready' WHERE id=?", (lifecycle_id,))

    stale_id = kb.create_task(conn, title="dry-run stale", assignee="builder")
    promotable_id = kb.create_task(conn, title="dry-run promotable", assignee="builder")
    with kb.write_txn(conn):
        conn.execute("UPDATE tasks SET status='ready' WHERE id=?", (stale_id,))
        conn.execute("UPDATE tasks SET status='todo' WHERE id=?", (promotable_id,))
    stale = kb.claim_task(conn, stale_id, ttl_seconds=1)
    assert stale is not None
    with kb.write_txn(conn):
        conn.execute(
            "UPDATE tasks SET claim_expires=0, worker_pid=NULL WHERE id=?",
            (stale_id,),
        )

    artifact_root = tmp_path / "home" / "artifacts"
    artifact_root.mkdir()
    marker = artifact_root / "existing.txt"
    marker.write_text("unchanged\n", encoding="utf-8")

    def snapshot():
        db = "\n".join(conn.iterdump())
        files = {
            str(path.relative_to(artifact_root)): (path.stat().st_mode, path.read_bytes())
            for path in artifact_root.rglob("*")
            if path.is_file()
        }
        return db, files

    before = snapshot()
    first = kbd.dispatch_once(
        conn, spawn_fn=lambda *_args, **_kwargs: 99999, dry_run=True
    )
    after_first = snapshot()
    second = kbd.dispatch_once(
        conn, spawn_fn=lambda *_args, **_kwargs: 99999, dry_run=True
    )
    after_second = snapshot()

    assert before == after_first == after_second
    assert first == second
    assert kb.get_task(conn, stale_id).status == "running"
    assert kb.get_task(conn, promotable_id).status == "todo"


def test_glh_09_dispatcher_policy_validation_is_opt_in_and_non_mutating():
    legacy = {"dispatch_in_gateway": False}
    before = json.dumps(legacy, sort_keys=True)
    glh.validate_dispatcher_host("any-profile", legacy)
    assert json.dumps(legacy, sort_keys=True) == before

    enabled = {
        "dispatch_in_gateway": True,
        "theseus_lifecycle": {"enabled": True, "dispatcher_profile": "theseus-builder"},
    }
    glh.validate_dispatcher_host("theseus-builder", enabled)
    with pytest.raises(ValueError, match="theseus-builder"):
        glh.validate_dispatcher_host("theseus-reviewer", enabled)


def test_gateway_boot_enforces_designated_lifecycle_host(monkeypatch, tmp_path):
    from gateway.kanban_watchers import GatewayKanbanWatchersMixin
    from hermes_cli import config as hermes_config

    monkeypatch.setenv("HERMES_PROFILE", "theseus-reviewer")
    monkeypatch.setenv("HERMES_KANBAN_HOME", str(tmp_path))
    monkeypatch.setattr(
        hermes_config,
        "load_config",
        lambda: {
            "kanban": {
                "dispatch_in_gateway": True,
                "theseus_lifecycle": {
                    "enabled": True,
                    "dispatcher_profile": "theseus-builder",
                },
            }
        },
    )
    runner = GatewayKanbanWatchersMixin()
    assert runner._kanban_dispatcher_boot() is None
    assert getattr(runner, "_kanban_dispatcher_lock_handle", None) is None


@pytest.mark.parametrize("profile", ["theseus-reviewer", ""])
def test_all_dispatch_and_native_claim_routes_reject_non_designated_host(
    lifecycle_db, monkeypatch, profile
):
    conn, tmp_path = lifecycle_db
    task_id = _builder(conn, tmp_path)
    assert _approve(conn, task_id)
    if profile:
        monkeypatch.setenv("HERMES_PROFILE", profile)
    else:
        monkeypatch.delenv("HERMES_PROFILE", raising=False)
        monkeypatch.delenv("HERMES_PROFILE_NAME", raising=False)

    dispatched = kbd.dispatch_once(conn, spawn_fn=lambda *_args, **_kwargs: 49901)
    assert dispatched.spawned == []
    assert kb.list_runs(conn, task_id) == []
    assert kb.get_task(conn, task_id).status == "blocked"

    with kb.write_txn(conn):
        conn.execute(
            "UPDATE tasks SET status='ready', current_step_key=?, block_kind=NULL WHERE id=?",
            (glh.READY_FOR_BUILDER, task_id),
        )
    assert kb.claim_task(conn, task_id) is None
    assert kb.list_runs(conn, task_id) == []

    legacy_id = kb.create_task(conn, title="legacy wrong-host pass-through", assignee="worker")
    legacy = kbd.dispatch_once(conn, spawn_fn=lambda *_args, **_kwargs: 49902)
    assert [item[0] for item in legacy.spawned] == [legacy_id]


def test_glh_10_stop_wins_over_late_heartbeat_and_recovery(lifecycle_db):
    conn, tmp_path = lifecycle_db
    task_id = _builder(conn, tmp_path)
    _approve(conn, task_id)
    kbd.dispatch_once(conn, spawn_fn=lambda *_args, **_kwargs: 47001)
    run_id = kb.get_task(conn, task_id).current_run_id
    assert glh.stop_for_architect(
        conn,
        task_id,
        expected_run_id=run_id,
        stop_type="approval",
        reason="Need decision",
        decision_questions=["Continue?"],
        forbidden_actions=["No retry"],
        baseline_sha="a" * 40,
        candidate_sha="b" * 40,
    )

    assert not kbd.heartbeat_worker(conn, task_id, expected_run_id=run_id)
    assert kbd.detect_stale_running(conn, stale_timeout_seconds=1) == []
    assert kbd.dispatch_once(conn, spawn_fn=lambda *_args, **_kwargs: 47002).spawned == []
    assert kb.get_task(conn, task_id).current_step_key == glh.STOPPED_AWAITING_ARCHITECT
    assert len(kb.list_runs(conn, task_id)) == 1


def test_stop_is_one_fenced_transaction_without_unblock_gap(lifecycle_db, monkeypatch):
    conn, tmp_path = lifecycle_db
    task_id = _builder(conn, tmp_path)
    _approve(conn, task_id)
    kbd.dispatch_once(conn, spawn_fn=lambda *_args, **_kwargs: 47011)
    task = kb.get_task(conn, task_id)
    assert task is not None and task.current_run_id is not None
    run_id = task.current_run_id
    original = kb.block_task
    raced = []

    def interleaving_block(*args, **kwargs):
        result = original(*args, **kwargs)
        raced.append(kb.unblock_task(conn, task_id))
        return result

    monkeypatch.setattr(kb, "block_task", interleaving_block)
    assert glh.stop_for_architect(
        conn,
        task_id,
        expected_run_id=run_id,
        stop_type="race",
        reason="fence",
        decision_questions=["continue?"],
        forbidden_actions=["no retry"],
        baseline_sha="a" * 40,
        candidate_sha="b" * 40,
    )
    stopped = kb.get_task(conn, task_id)
    assert raced == []
    assert stopped is not None and stopped.status == "blocked"
    assert stopped.current_step_key == glh.STOPPED_AWAITING_ARCHITECT
    assert stopped.current_run_id is None


def test_glh_11_stop_payload_is_redacted(lifecycle_db):
    conn, tmp_path = lifecycle_db
    task_id = _builder(conn, tmp_path)
    _approve(conn, task_id)
    kbd.dispatch_once(conn, spawn_fn=lambda *_args, **_kwargs: 48001)
    run_id = kb.get_task(conn, task_id).current_run_id
    secret = "ghp_" + ("x" * 40)
    glh.stop_for_architect(
        conn,
        task_id,
        expected_run_id=run_id,
        stop_type="approval",
        reason=f"token={secret}",
        decision_questions=[f"Use token={secret}?"],
        forbidden_actions=[f"Do not print token={secret}"],
        baseline_sha="a" * 40,
        candidate_sha="b" * 40,
    )
    payload = glh.readback(conn, task_id)["latest_stop"]
    assert secret not in json.dumps(payload)


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"dispatcher_enabled": False}, "dispatcher_disabled"),
        ({"lock_contended": True}, "lock_contended"),
        ({"profile_available": False}, "profile_unavailable"),
        ({"capacity_available": False}, "capacity_limit"),
    ],
)
def test_glh_12_dispatch_diagnostics_distinguish_no_spawn_reasons(lifecycle_db, kwargs, reason):
    conn, tmp_path = lifecycle_db
    task_id = _builder(conn, tmp_path)
    defaults = {
        "dispatcher_enabled": True,
        "lock_contended": False,
        "profile_available": True,
        "capacity_available": True,
    }
    defaults.update(kwargs)
    assert glh.dispatch_diagnostic(conn, task_id, **defaults)["reason"] == reason

    if not kwargs:
        assert glh.dispatch_diagnostic(conn, task_id, **defaults)["reason"] == "approval_blocked"


def test_lifecycle_cli_show_and_approve_fail_closed_on_active_board(lifecycle_db):
    conn, tmp_path = lifecycle_db
    task_id = _builder(conn, tmp_path)

    shown = json.loads(kc.run_slash(f"lifecycle show {task_id} --json"))
    assert shown["task_id"] == task_id
    assert shown["phase"] == glh.AWAITING_TERMINAL_APPROVAL
    assert shown["dispatch_diagnostic"]["reason"] == "approval_blocked"

    blocked = kc.run_slash(
        f"lifecycle approve {task_id} --authority-evidence forged --json"
    )
    assert "BLOCKED — TRUSTED AUTHORITY NOT CONFIGURED" in blocked
    assert kb.get_task(conn, task_id).status == "blocked"

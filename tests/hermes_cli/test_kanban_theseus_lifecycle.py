from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from hermes_cli import kanban_db as kb
from hermes_cli import kanban_db_connect as kbc
from hermes_cli import kanban_db_dispatch as kbd
from hermes_cli import kanban as kc
from hermes_cli import kanban_theseus_lifecycle as glh


@pytest.fixture
def lifecycle_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_KANBAN_HOME", str(home))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
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
        now=100,
    )


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

    assert glh.record_terminal_approval(
        conn, task_id, approval_ref="terminal:receipt-1", approved_at=110, now=110
    )
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

    assert glh.resume_after_architect_decision(
        conn, task_id, decision_ref="architect:decision-1", actor="architect"
    )
    second = kbd.dispatch_once(conn, spawn_fn=lambda *_args, **_kwargs: 41002)
    assert [item[0] for item in second.spawned] == [task_id]
    resumed = kb.get_task(conn, task_id)
    assert resumed.current_run_id != first_run
    assert resumed.worker_pid == 41002
    assert len(kb.list_runs(conn, task_id)) == 2


def test_glh_03_expired_approval_never_creates_run_or_pid(lifecycle_db):
    conn, tmp_path = lifecycle_db
    task_id = _builder(conn, tmp_path, expires_at=105)

    assert not glh.record_terminal_approval(
        conn, task_id, approval_ref="terminal:late", approved_at=106, now=106
    )
    result = kbd.dispatch_once(conn, spawn_fn=lambda *_args, **_kwargs: 99999)

    assert result.spawned == []
    task = kb.get_task(conn, task_id)
    assert task.status == "blocked"
    assert task.current_step_key == glh.AWAITING_TERMINAL_APPROVAL
    assert task.worker_pid is None
    assert kb.list_runs(conn, task_id) == []
    assert any(event.kind == "theseus_approval_expired" for event in kb.list_events(conn, task_id))


def test_generic_unblock_cannot_bypass_lifecycle_approval(lifecycle_db):
    conn, tmp_path = lifecycle_db
    task_id = _builder(conn, tmp_path)
    assert kb.unblock_task(conn, task_id)

    result = kbd.dispatch_once(conn, spawn_fn=lambda *_args, **_kwargs: 99999)

    assert result.spawned == []
    assert kb.list_runs(conn, task_id) == []
    task = kb.get_task(conn, task_id)
    assert task.status == "blocked"
    assert task.current_step_key == glh.AWAITING_TERMINAL_APPROVAL
    assert any(event.kind == "theseus_dispatch_blocked" for event in kb.list_events(conn, task_id))


def test_glh_02_resume_requires_specific_architect_decision(lifecycle_db):
    conn, tmp_path = lifecycle_db
    task_id = _builder(conn, tmp_path)
    glh.record_terminal_approval(conn, task_id, approval_ref="terminal:ok", approved_at=101, now=101)
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

    with pytest.raises(ValueError, match="decision_ref"):
        glh.resume_after_architect_decision(conn, task_id, decision_ref="", actor="architect")

    assert kbd.dispatch_once(conn, spawn_fn=lambda *_args, **_kwargs: 42002).spawned == []
    assert len(kb.list_runs(conn, task_id)) == 1


def test_legacy_task_dispatch_is_unchanged(lifecycle_db):
    conn, _ = lifecycle_db
    task_id = kb.create_task(conn, title="legacy", assignee="worker")
    result = kbd.dispatch_once(conn, spawn_fn=lambda *_args, **_kwargs: 43001)
    assert [item[0] for item in result.spawned] == [task_id]
    assert kb.get_task(conn, task_id).workflow_template_id is None


def test_glh_04_and_05_crash_recovery_never_duplicates_live_attempt(lifecycle_db, monkeypatch):
    conn, tmp_path = lifecycle_db
    task_id = _builder(conn, tmp_path)
    glh.record_terminal_approval(conn, task_id, approval_ref="terminal:ok", approved_at=101, now=101)
    assert len(kbd.dispatch_once(conn, spawn_fn=lambda *_args, **_kwargs: 45001).spawned) == 1
    first_run = kb.get_task(conn, task_id).current_run_id

    monkeypatch.setenv("HERMES_KANBAN_CRASH_GRACE_SECONDS", "0")
    monkeypatch.setattr(kbd, "_pid_alive", lambda _pid: False)
    recovered = kbd.dispatch_once(conn, spawn_fn=lambda *_args, **_kwargs: 45002)

    assert recovered.crashed == [task_id]
    assert [item[0] for item in recovered.spawned] == [task_id]
    task = kb.get_task(conn, task_id)
    assert task.current_run_id != first_run
    assert task.worker_pid == 45002
    runs = kb.list_runs(conn, task_id)
    assert len([run for run in runs if run.ended_at is None]) == 1
    assert any(run.outcome == "crashed" for run in runs)


def test_glh_06_two_dispatch_ticks_create_one_run(lifecycle_db):
    conn, tmp_path = lifecycle_db
    task_id = _builder(conn, tmp_path)
    glh.record_terminal_approval(conn, task_id, approval_ref="terminal:ok", approved_at=101, now=101)
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
    assert glh.record_terminal_approval(
        conn, task_id, approval_ref="terminal:pilot", approved_at=101, now=101
    )
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
    reviewer_id = glh.create_role_task(
        conn,
        builder_task_id=builder_id,
        role="reviewer",
        title="Synthetic review",
        candidate_sha="b" * 40,
        branch="pilot/reviewer",
        worktree=str(reviewer_path),
    )
    investigator_id = glh.create_role_task(
        conn,
        builder_task_id=builder_id,
        role="investigator",
        title="Synthetic investigation",
        candidate_sha="b" * 40,
        branch="pilot/investigator",
        worktree=str(investigator_path),
    )

    assert len({builder_id, reviewer_id, investigator_id}) == 3
    role_tasks = [kb.get_task(conn, reviewer_id), kb.get_task(conn, investigator_id)]
    assert {task.assignee for task in role_tasks} == {"theseus-reviewer", "theseus-investigator"}
    assert all(task.workspace_path != builder_path for task in role_tasks)
    assert kb.parent_ids(conn, reviewer_id) == [builder_id]
    assert kb.parent_ids(conn, investigator_id) == [builder_id]
    assert all(glh.package_metadata(conn, task.id)["candidate_sha"] == "b" * 40 for task in role_tasks)


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


def test_glh_10_stop_wins_over_late_heartbeat_and_recovery(lifecycle_db):
    conn, tmp_path = lifecycle_db
    task_id = _builder(conn, tmp_path)
    glh.record_terminal_approval(conn, task_id, approval_ref="terminal:ok", approved_at=101, now=101)
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


def test_glh_11_stop_payload_is_redacted(lifecycle_db):
    conn, tmp_path = lifecycle_db
    task_id = _builder(conn, tmp_path)
    glh.record_terminal_approval(conn, task_id, approval_ref="terminal:ok", approved_at=101, now=101)
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


def test_lifecycle_cli_show_and_approve_use_active_board(lifecycle_db):
    conn, tmp_path = lifecycle_db
    task_id = _builder(conn, tmp_path)

    shown = json.loads(kc.run_slash(f"lifecycle show {task_id} --json"))
    assert shown["task_id"] == task_id
    assert shown["phase"] == glh.AWAITING_TERMINAL_APPROVAL

    approved = json.loads(
        kc.run_slash(
            f"lifecycle approve {task_id} --approval-ref terminal:cli-1 "
            "--approved-at 101 --now 101 --json"
        )
    )
    assert approved == {"approved": True, "task_id": task_id}
    assert kb.get_task(conn, task_id).status == "ready"

"""Opt-in THESEUS work-package lifecycle on the existing Kanban schema.

The adapter stores phase and package identity in the existing workflow columns
and audit events.  It deliberately creates no schema and has no effect on cards
without :data:`WORKFLOW_TEMPLATE_ID`.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import time
from pathlib import Path
from typing import Any, Iterable, Optional

from hermes_cli import kanban_db as kb

WORKFLOW_TEMPLATE_ID = "theseus-gateway-lifecycle-v1"
DESIGNATED_DISPATCHER_PROFILE = "theseus-builder"

PLANNED = "PLANNED"
AWAITING_TERMINAL_APPROVAL = "AWAITING_TERMINAL_APPROVAL"
READY_FOR_BUILDER = "READY_FOR_BUILDER"
BUILDER_RUNNING = "BUILDER_RUNNING"
STOPPED_AWAITING_ARCHITECT = "STOPPED_AWAITING_ARCHITECT"
BUILDER_COMPLETE_AWAITING_REVIEW = "BUILDER_COMPLETE_AWAITING_REVIEW"
REVIEW_RUNNING = "REVIEW_RUNNING"
CHANGES_REQUESTED = "CHANGES_REQUESTED"
GATE2_RECOMMENDATION_READY = "GATE2_RECOMMENDATION_READY"
INVESTIGATION_RUNNING = "INVESTIGATION_RUNNING"
CORRECTION_READY = "CORRECTION_READY"
ARCHITECT_GATE_DECISION_REQUIRED = "ARCHITECT_GATE_DECISION_REQUIRED"

ROLE_PROFILES = {
    "builder": "theseus-builder",
    "reviewer": "theseus-reviewer",
    "investigator": "theseus-investigator",
}
ROLE_READY_PHASE = {
    "builder": READY_FOR_BUILDER,
    "reviewer": REVIEW_RUNNING,
    "investigator": INVESTIGATION_RUNNING,
}
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")

_ALLOWED_TRANSITIONS = {
    PLANNED: {AWAITING_TERMINAL_APPROVAL},
    AWAITING_TERMINAL_APPROVAL: {READY_FOR_BUILDER},
    READY_FOR_BUILDER: {BUILDER_RUNNING, STOPPED_AWAITING_ARCHITECT},
    BUILDER_RUNNING: {STOPPED_AWAITING_ARCHITECT, BUILDER_COMPLETE_AWAITING_REVIEW},
    STOPPED_AWAITING_ARCHITECT: {READY_FOR_BUILDER},
    BUILDER_COMPLETE_AWAITING_REVIEW: {REVIEW_RUNNING, INVESTIGATION_RUNNING, ARCHITECT_GATE_DECISION_REQUIRED},
    REVIEW_RUNNING: {CHANGES_REQUESTED, GATE2_RECOMMENDATION_READY},
    CHANGES_REQUESTED: {READY_FOR_BUILDER, INVESTIGATION_RUNNING},
    INVESTIGATION_RUNNING: {CORRECTION_READY},
    CORRECTION_READY: {READY_FOR_BUILDER},
    GATE2_RECOMMENDATION_READY: {ARCHITECT_GATE_DECISION_REQUIRED},
}


def _require_text(name: str, value: Any) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        raise ValueError(f"{name} is required")
    return cleaned


def _require_sha(name: str, value: str) -> str:
    cleaned = _require_text(name, value).lower()
    if not _SHA_RE.fullmatch(cleaned):
        raise ValueError(f"{name} must be an exact 40-character hexadecimal SHA")
    return cleaned


def _require_worktree(path: str) -> str:
    resolved = Path(_require_text("worktree", path)).expanduser().resolve()
    if not resolved.is_absolute() or not resolved.is_dir():
        raise ValueError("worktree must be an existing absolute directory")
    return str(resolved)


def _event_payload(conn, task_id: str, kind: str) -> Optional[dict]:
    row = conn.execute(
        "SELECT payload FROM task_events WHERE task_id=? AND kind=? ORDER BY id DESC LIMIT 1",
        (task_id, kind),
    ).fetchone()
    if row is None:
        return None
    try:
        value = json.loads(row["payload"] or "{}")
    except (TypeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def package_metadata(conn, task_id: str) -> Optional[dict]:
    return _event_payload(conn, task_id, "theseus_lifecycle_initialized")


def _transition(
    conn,
    task_id: str,
    phase: str,
    *,
    actor: str,
    event_kind: str = "theseus_phase_transition",
    extra: Optional[dict] = None,
    allowed_from: Optional[Iterable[str]] = None,
) -> None:
    task = kb.get_task(conn, task_id)
    if task is None or task.workflow_template_id != WORKFLOW_TEMPLATE_ID:
        raise ValueError("task is not opted into the THESEUS lifecycle")
    previous = task.current_step_key or PLANNED
    allowed = set(allowed_from) if allowed_from is not None else _ALLOWED_TRANSITIONS.get(previous, set())
    if phase not in allowed:
        raise ValueError(f"invalid THESEUS phase transition: {previous} -> {phase}")
    payload = {"actor": _require_text("actor", actor), "previous_phase": previous, "phase": phase}
    if extra:
        payload.update(extra)
    with kb.write_txn(conn):
        changed = conn.execute(
            "UPDATE tasks SET current_step_key=? WHERE id=? AND workflow_template_id=? AND current_step_key IS ?",
            (phase, task_id, WORKFLOW_TEMPLATE_ID, task.current_step_key),
        )
        if changed.rowcount != 1:
            raise ValueError("task phase changed concurrently")
        kb._append_event(conn, task_id, event_kind, payload, run_id=task.current_run_id)


def create_builder_task(
    conn,
    *,
    package_id: str,
    title: str,
    baseline_sha: str,
    candidate_sha: str,
    branch: str,
    worktree: str,
    approval_expires_at: int,
    now: Optional[int] = None,
) -> str:
    """Create one stable Builder card, initially blocked before any attempt."""
    package_id = _require_text("package_id", package_id)
    baseline_sha = _require_sha("baseline_sha", baseline_sha)
    candidate_sha = _require_sha("candidate_sha", candidate_sha)
    branch = _require_text("branch", branch)
    worktree = _require_worktree(worktree)
    now = int(time.time() if now is None else now)
    expires_at = int(approval_expires_at)
    if expires_at <= now:
        raise ValueError("approval_expires_at must be in the future")
    task_id = kb.create_task(
        conn,
        title=title,
        assignee=ROLE_PROFILES["builder"],
        workspace_kind="worktree",
        workspace_path=worktree,
        branch_name=branch,
        initial_status="blocked",
        idempotency_key=f"theseus-work-package:{package_id}:builder",
        created_by="theseus-lifecycle",
    )
    task = kb.get_task(conn, task_id)
    if task is not None and task.workflow_template_id == WORKFLOW_TEMPLATE_ID:
        return task_id
    metadata = {
        "package_id": package_id,
        "role": "builder",
        "baseline_sha": baseline_sha,
        "candidate_sha": candidate_sha,
        "branch": branch,
        "worktree": worktree,
        "approval_expires_at": expires_at,
        "dispatcher_profile": DESIGNATED_DISPATCHER_PROFILE,
    }
    with kb.write_txn(conn):
        conn.execute(
            "UPDATE tasks SET workflow_template_id=?, current_step_key=?, block_kind='approval' WHERE id=?",
            (WORKFLOW_TEMPLATE_ID, AWAITING_TERMINAL_APPROVAL, task_id),
        )
        kb._append_event(conn, task_id, "theseus_lifecycle_initialized", metadata)
        kb._append_event(
            conn,
            task_id,
            "theseus_terminal_approval_required",
            {"phase": AWAITING_TERMINAL_APPROVAL, "approval_expires_at": expires_at},
        )
    return task_id


def record_terminal_approval(
    conn,
    task_id: str,
    *,
    approval_ref: str,
    approved_at: int,
    now: Optional[int] = None,
) -> bool:
    approval_ref = kb.redact_review_value(_require_text("approval_ref", approval_ref))
    task = kb.get_task(conn, task_id)
    metadata = package_metadata(conn, task_id)
    if task is None or metadata is None or task.current_step_key != AWAITING_TERMINAL_APPROVAL:
        raise ValueError("task is not awaiting terminal approval")
    approved_at = int(approved_at)
    now = int(time.time() if now is None else now)
    expires_at = int(metadata["approval_expires_at"])
    if approved_at > expires_at or now > expires_at:
        with kb.write_txn(conn):
            conn.execute("UPDATE tasks SET status='blocked', worker_pid=NULL WHERE id=?", (task_id,))
            kb._append_event(
                conn,
                task_id,
                "theseus_approval_expired",
                {"approval_ref": approval_ref, "approved_at": approved_at, "approval_expires_at": expires_at},
            )
        return False
    if task.current_run_id is not None or task.worker_pid is not None or kb.list_runs(conn, task_id):
        raise ValueError("approval pre-dispatch task already has run/PID history")
    with kb.write_txn(conn):
        changed = conn.execute(
            "UPDATE tasks SET status='ready', current_step_key=?, block_kind=NULL "
            "WHERE id=? AND status='blocked' AND current_step_key=? AND current_run_id IS NULL AND worker_pid IS NULL",
            (READY_FOR_BUILDER, task_id, AWAITING_TERMINAL_APPROVAL),
        )
        if changed.rowcount != 1:
            raise ValueError("approval state changed concurrently")
        kb._append_event(
            conn,
            task_id,
            "theseus_terminal_approved",
            {"approval_ref": approval_ref, "approved_at": approved_at, "phase": READY_FOR_BUILDER},
        )
    return True


def stop_for_architect(
    conn,
    task_id: str,
    *,
    expected_run_id: int,
    stop_type: str,
    reason: str,
    decision_questions: Iterable[str],
    forbidden_actions: Iterable[str],
    baseline_sha: str,
    candidate_sha: str,
) -> bool:
    questions = [
        kb.redact_review_value(_require_text("decision question", item))
        for item in decision_questions
    ]
    forbidden = [
        kb.redact_review_value(_require_text("forbidden action", item))
        for item in forbidden_actions
    ]
    if not questions or not forbidden:
        raise ValueError("decision_questions and forbidden_actions are required")
    payload = {
        "stop_type": kb.redact_review_value(_require_text("stop_type", stop_type)),
        "reason": kb.redact_review_value(_require_text("reason", reason)),
        "stopped_run_id": int(expected_run_id),
        "baseline_sha": _require_sha("baseline_sha", baseline_sha),
        "candidate_sha": _require_sha("candidate_sha", candidate_sha),
        "decision_questions": questions,
        "forbidden_actions": forbidden,
    }
    if not kb.block_task(
        conn, task_id, reason=payload["reason"], kind="needs_input", expected_run_id=int(expected_run_id)
    ):
        return False
    task = kb.get_task(conn, task_id)
    with kb.write_txn(conn):
        conn.execute(
            "UPDATE tasks SET current_step_key=? WHERE id=? AND status='blocked' AND worker_pid IS NULL",
            (STOPPED_AWAITING_ARCHITECT, task_id),
        )
        kb._append_event(
            conn, task_id, "theseus_architect_stop", payload, run_id=task.current_run_id if task else None
        )
    return True


def create_role_task(
    conn,
    *,
    builder_task_id: str,
    role: str,
    title: str,
    candidate_sha: str,
    branch: str,
    worktree: str,
) -> str:
    """Create an isolated Reviewer or Investigator task linked to Builder."""
    if role not in {"reviewer", "investigator"}:
        raise ValueError("role must be reviewer or investigator")
    builder = kb.get_task(conn, builder_task_id)
    builder_meta = package_metadata(conn, builder_task_id)
    if builder is None or builder_meta is None:
        raise ValueError("builder task is not a THESEUS work package")
    if builder.status not in {"done", "archived"}:
        raise ValueError("builder task must be terminal before a linked role task is created")
    worktree = _require_worktree(worktree)
    if Path(worktree).resolve() == Path(builder.workspace_path or "").resolve():
        raise ValueError(f"{role} task cannot reuse the Builder worktree")
    branch = _require_text("branch", branch)
    if branch == builder.branch_name:
        raise ValueError(f"{role} task cannot reuse the Builder branch")
    candidate_sha = _require_sha("candidate_sha", candidate_sha)
    package_id = _require_text("package_id", builder_meta.get("package_id"))
    task_id = kb.create_task(
        conn,
        title=title,
        body=(
            f"Pinned candidate: {candidate_sha}. Read-only {role} authority: "
            "do not modify application source, publish, merge, or reuse the Builder worktree."
        ),
        assignee=ROLE_PROFILES[role],
        workspace_kind="worktree",
        workspace_path=worktree,
        branch_name=branch,
        parents=(builder_task_id,),
        idempotency_key=f"theseus-work-package:{package_id}:{role}:{candidate_sha}",
        created_by="theseus-lifecycle",
    )
    task = kb.get_task(conn, task_id)
    if task is not None and task.workflow_template_id == WORKFLOW_TEMPLATE_ID:
        return task_id
    metadata = {
        "package_id": package_id,
        "role": role,
        "builder_task_id": builder_task_id,
        "baseline_sha": builder_meta.get("baseline_sha"),
        "candidate_sha": candidate_sha,
        "branch": branch,
        "worktree": worktree,
        "authority": "read-only",
        "publish_allowed": False,
        "merge_allowed": False,
        "dispatcher_profile": DESIGNATED_DISPATCHER_PROFILE,
    }
    with kb.write_txn(conn):
        conn.execute(
            "UPDATE tasks SET workflow_template_id=?, current_step_key=? WHERE id=?",
            (WORKFLOW_TEMPLATE_ID, ROLE_READY_PHASE[role], task_id),
        )
        kb._append_event(conn, task_id, "theseus_lifecycle_initialized", metadata)
        kb._append_event(
            conn,
            task_id,
            "theseus_role_task_linked",
            {"builder_task_id": builder_task_id, "role": role, "candidate_sha": candidate_sha},
        )
    return task_id


def resume_after_architect_decision(conn, task_id: str, *, decision_ref: str, actor: str) -> bool:
    decision_ref = kb.redact_review_value(_require_text("decision_ref", decision_ref))
    actor = kb.redact_review_value(_require_text("actor", actor))
    task = kb.get_task(conn, task_id)
    stop = _event_payload(conn, task_id, "theseus_architect_stop")
    if task is None or stop is None or task.current_step_key != STOPPED_AWAITING_ARCHITECT:
        raise ValueError("task has no unresolved Architect STOP")
    if task.status != "blocked" or task.worker_pid is not None:
        raise ValueError("stopped task must be blocked with no live worker PID")
    active_run = conn.execute(
        "SELECT 1 FROM task_runs WHERE task_id=? AND ended_at IS NULL LIMIT 1", (task_id,)
    ).fetchone()
    if active_run is not None:
        raise ValueError("prior run is still active")
    metadata = package_metadata(conn, task_id) or {}
    if metadata.get("role") != "builder" or task.assignee != ROLE_PROFILES["builder"]:
        raise ValueError("Builder role/profile preflight failed")
    if _require_worktree(str(metadata.get("worktree") or "")) != _require_worktree(task.workspace_path or ""):
        raise ValueError("Builder worktree preflight failed")
    if _require_text("branch", metadata.get("branch")) != _require_text("branch", task.branch_name):
        raise ValueError("Builder branch preflight failed")
    _require_sha("baseline_sha", str(metadata.get("baseline_sha") or ""))
    _require_sha("candidate_sha", str(metadata.get("candidate_sha") or ""))
    with kb.write_txn(conn):
        changed = conn.execute(
            "UPDATE tasks SET status='ready', current_step_key=?, block_kind=NULL "
            "WHERE id=? AND status='blocked' AND current_step_key=? AND worker_pid IS NULL",
            (READY_FOR_BUILDER, task_id, STOPPED_AWAITING_ARCHITECT),
        )
        if changed.rowcount != 1:
            raise ValueError("STOP state changed concurrently")
        kb._append_event(
            conn,
            task_id,
            "theseus_architect_decision",
            {
                "actor": actor,
                "decision_ref": decision_ref,
                "resolves_stop_run_id": stop["stopped_run_id"],
                "phase": READY_FOR_BUILDER,
            },
        )
    return True


def dispatch_preflight(conn, task_id: str) -> tuple[bool, Optional[str]]:
    """Fail closed only for opted-in cards; legacy cards always pass."""
    task = kb.get_task(conn, task_id)
    if task is None:
        return False, "task_not_found"
    if task.workflow_template_id != WORKFLOW_TEMPLATE_ID:
        return True, None
    metadata = package_metadata(conn, task_id)
    if metadata is None:
        return False, "lifecycle_metadata_missing"
    role = metadata.get("role")
    if task.assignee != ROLE_PROFILES.get(str(role)):
        return False, "role_profile_mismatch"
    dispatchable_phases = set(ROLE_READY_PHASE.values())
    if role == "builder":
        # Crash recovery ends the prior task_run and returns the same stable
        # card to ready; retaining BUILDER_RUNNING preserves truthful phase
        # history while allowing the dispatcher to create a fenced new run.
        dispatchable_phases.add(BUILDER_RUNNING)
    if task.current_step_key not in dispatchable_phases:
        return False, "phase_not_dispatchable"
    if task.worker_pid is not None:
        return False, "worker_pid_present"
    if role == "builder" and not (
        _event_payload(conn, task_id, "theseus_terminal_approved")
        or _event_payload(conn, task_id, "theseus_architect_decision")
    ):
        return False, "approval_missing"
    return True, None


def enforce_dispatch_preflight(conn, task_id: str) -> tuple[bool, Optional[str]]:
    """Park an opted-in card when generic mutation tried to bypass its gate."""
    ok, reason = dispatch_preflight(conn, task_id)
    task = kb.get_task(conn, task_id)
    if ok or task is None or task.workflow_template_id != WORKFLOW_TEMPLATE_ID:
        return ok, reason
    if task.status == "ready":
        with kb.write_txn(conn):
            changed = conn.execute(
                "UPDATE tasks SET status='blocked', claim_lock=NULL, claim_expires=NULL, "
                "worker_pid=NULL, block_kind=? "
                "WHERE id=? AND status='ready' AND current_run_id IS NULL",
                ("approval" if task.current_step_key == AWAITING_TERMINAL_APPROVAL else "needs_input", task_id),
            )
            if changed.rowcount == 1:
                kb._append_event(
                    conn,
                    task_id,
                    "theseus_dispatch_blocked",
                    {"reason": reason, "phase": task.current_step_key},
                )
    return False, reason


def mark_run_started(conn, task_id: str, *, board: Optional[str]) -> dict[str, str]:
    """Bind an opted-in claim to its phase and immutable run directory."""
    task = kb.get_task(conn, task_id)
    if task is None or task.workflow_template_id != WORKFLOW_TEMPLATE_ID:
        return {}
    if task.current_run_id is None or task.status != "running":
        raise ValueError("THESEUS run start requires an active claimed run")
    metadata = package_metadata(conn, task_id) or {}
    if metadata.get("role") == "builder" and task.current_step_key == READY_FOR_BUILDER:
        _transition(
            conn,
            task_id,
            BUILDER_RUNNING,
            actor="dispatcher",
            extra={"run_id": task.current_run_id},
        )
    slug = kb._normalize_board_slug(board) or kb.get_current_board()
    return persist_run_artifact_paths(
        conn,
        task_id,
        task.current_run_id,
        board=slug,
        root=kb.kanban_home() / "theseus-runs",
    )


def validate_dispatcher_host(profile: str, kanban_config: dict) -> None:
    """Validate policy without changing config or service state."""
    lifecycle = kanban_config.get("theseus_lifecycle", {}) if isinstance(kanban_config, dict) else {}
    if not isinstance(lifecycle, dict) or not lifecycle.get("enabled", False):
        return
    designated = lifecycle.get("dispatcher_profile", DESIGNATED_DISPATCHER_PROFILE)
    if designated != DESIGNATED_DISPATCHER_PROFILE or profile != DESIGNATED_DISPATCHER_PROFILE:
        raise ValueError("THESEUS lifecycle dispatcher must be hosted by profile 'theseus-builder'")
    if not kanban_config.get("dispatch_in_gateway", True):
        raise ValueError("THESEUS lifecycle requires kanban.dispatch_in_gateway=true on the designated host")


def readback(conn, task_id: str) -> dict:
    task = kb.get_task(conn, task_id)
    if task is None:
        raise ValueError("task not found")
    runs = kb.list_runs(conn, task_id)
    active = next((run for run in runs if run.ended_at is None), None)
    return {
        "task_id": task.id,
        "package": package_metadata(conn, task_id),
        "phase": task.current_step_key,
        "status": task.status,
        "worker_pid": task.worker_pid,
        "last_heartbeat_at": task.last_heartbeat_at,
        "current_run_id": task.current_run_id,
        "active_run": active.id if active else None,
        "run_count": len(runs),
        "latest_stop": _event_payload(conn, task_id, "theseus_architect_stop"),
        "latest_decision": _event_payload(conn, task_id, "theseus_architect_decision"),
    }


def dispatch_diagnostic(
    conn,
    task_id: str,
    *,
    dispatcher_enabled: bool,
    lock_contended: bool,
    profile_available: bool,
    capacity_available: bool,
) -> dict:
    task = kb.get_task(conn, task_id)
    if not dispatcher_enabled:
        reason = "dispatcher_disabled"
    elif lock_contended:
        reason = "lock_contended"
    elif task is None:
        reason = "task_not_found"
    elif not profile_available:
        reason = "profile_unavailable"
    elif not capacity_available:
        reason = "capacity_limit"
    elif task.status == "blocked" and task.current_step_key in {
        AWAITING_TERMINAL_APPROVAL,
        STOPPED_AWAITING_ARCHITECT,
    }:
        reason = "approval_blocked"
    elif task.status == "running" or task.current_run_id is not None:
        reason = "already_claimed"
    elif task.status != "ready":
        reason = "no_ready_task"
    else:
        reason = "ready"
    return {"task_id": task_id, "reason": reason, "status": task.status if task else None}


def run_artifact_paths(root: Path, board: str, task_id: str, run_id: int) -> dict[str, str]:
    directory = Path(root).expanduser().resolve() / board / task_id / str(int(run_id))
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(directory, 0o700)
    report = directory / "report.md"
    result = directory / "result.md"
    if report.resolve() == result.resolve() or (report.exists() and result.exists() and os.path.samefile(report, result)):
        raise ValueError("report and result artifact paths collide")
    return {
        "directory": str(directory),
        "report": str(report),
        "result": str(result),
        "manifest": str(directory / "manifest.json"),
    }


def persist_run_artifact_paths(conn, task_id: str, run_id: int, *, board: str, root: Path) -> dict[str, str]:
    paths = run_artifact_paths(root, board, task_id, run_id)
    row = conn.execute(
        "SELECT metadata FROM task_runs WHERE id=? AND task_id=? AND ended_at IS NULL", (int(run_id), task_id)
    ).fetchone()
    if row is None:
        raise ValueError("active run not found")
    try:
        metadata = json.loads(row["metadata"] or "{}")
    except (TypeError, json.JSONDecodeError):
        metadata = {}
    if not isinstance(metadata, dict):
        metadata = {}
    metadata["artifacts"] = paths
    with kb.write_txn(conn):
        conn.execute(
            "UPDATE task_runs SET metadata=? WHERE id=? AND task_id=? AND ended_at IS NULL",
            (json.dumps(metadata, sort_keys=True), int(run_id), task_id),
        )
        kb._append_event(conn, task_id, "theseus_artifacts_prepared", paths, run_id=int(run_id))
    return paths


def finalize_artifacts(paths: dict[str, str], *, manifest_facts: Optional[dict] = None) -> dict:
    report = Path(paths["report"]).resolve()
    result = Path(paths["result"]).resolve()
    if report == result or (report.exists() and result.exists() and os.path.samefile(report, result)):
        raise ValueError("report and result artifact paths collide")
    files: dict[str, dict] = {}
    for name, path in (("report", report), ("result", result)):
        if not path.is_file():
            files[name] = {"path": str(path), "status": "NOT PRODUCED"}
            continue
        data = path.read_bytes()
        files[name] = {
            "path": str(path),
            "status": "PRESENT",
            "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
    manifest = {"artifacts": files, **(manifest_facts or {})}
    manifest_path = Path(paths["manifest"])
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(manifest_path, stat.S_IRUSR | stat.S_IWUSR)
    return manifest

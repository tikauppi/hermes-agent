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
import secrets
import stat
import subprocess
import time
from pathlib import Path
from typing import Any, Iterable, Optional

from hermes_cli import kanban_db as kb


WORKFLOW_TEMPLATE_ID = "theseus-gateway-lifecycle-v1"
DESIGNATED_DISPATCHER_PROFILE = "theseus-builder"
AUTHORITY_SCOPE = "theseus.gateway-kanban-lifecycle"
PRODUCTION_AUTHORITY_BLOCKED = "BLOCKED — TRUSTED AUTHORITY NOT CONFIGURED"


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


def _current_dispatcher_profile() -> str:
    for name in ("HERMES_PROFILE_NAME", "HERMES_PROFILE"):
        value = os.environ.get(name, "").strip()
        if value:
            return value
    try:
        from hermes_cli.profiles import get_active_profile_name

        return str(get_active_profile_name() or "default")
    except Exception:
        return "default"


def _dispatcher_host_allowed(metadata: dict) -> bool:
    return (
        metadata.get("dispatcher_profile") == DESIGNATED_DISPATCHER_PROFILE
        and _current_dispatcher_profile() == DESIGNATED_DISPATCHER_PROFILE
    )


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
    if phase == READY_FOR_BUILDER and previous in {
        AWAITING_TERMINAL_APPROVAL,
        STOPPED_AWAITING_ARCHITECT,
        CHANGES_REQUESTED,
        CORRECTION_READY,
    }:
        raise ValueError("authority mutation boundary is required for this phase transition")
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
) -> str:
    """Create one stable Builder card, initially blocked before any attempt."""
    package_id = _require_text("package_id", package_id)
    baseline_sha = _require_sha("baseline_sha", baseline_sha)
    candidate_sha = _require_sha("candidate_sha", candidate_sha)
    branch = _require_text("branch", branch)
    worktree = _require_worktree(worktree)
    now = int(time.time())
    expires_at = int(approval_expires_at)
    if expires_at <= now:
        raise ValueError("approval_expires_at must be in the future")
    idempotency_key = f"theseus-work-package:{package_id}:builder"
    with kb.write_txn(conn):
        existing = conn.execute(
            "SELECT id FROM tasks WHERE idempotency_key=? AND status != 'archived' "
            "ORDER BY created_at, id LIMIT 1",
            (idempotency_key,),
        ).fetchone()
        if existing is not None:
            return existing["id"]
        task_id = kb.create_task(
            conn,
            title=title,
            assignee=ROLE_PROFILES["builder"],
            workspace_kind="worktree",
            workspace_path=worktree,
            branch_name=branch,
            initial_status="blocked",
            idempotency_key=idempotency_key,
            created_by="theseus-lifecycle",
        )
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
    authority_evidence: str | bytes | None = None,
    **_caller_metadata: object,
) -> bool:
    """Production entrypoint; unavailable until a trusted authority is configured."""
    raise ValueError(PRODUCTION_AUTHORITY_BLOCKED)


def issue_fresh_terminal_approval(
    conn,
    task_id: str,
    *,
    authority_evidence: str | bytes | None = None,
    **_caller_metadata: object,
) -> bool:
    """Production entrypoint; unavailable until a trusted authority is configured."""
    raise ValueError(PRODUCTION_AUTHORITY_BLOCKED)


def _approval_for_claim(conn, task_id: str) -> Optional[dict]:
    approval = _event_payload(conn, task_id, "theseus_terminal_approved")
    if not approval or approval.get("task_id") != task_id:
        return None
    receipt_id = approval.get("receipt_id")
    if not isinstance(receipt_id, str) or int(approval.get("approval_expires_at", 0)) <= int(time.time()):
        return None
    consumed = conn.execute(
        "SELECT 1 FROM task_events WHERE task_id=? AND kind='theseus_approval_consumed' "
        "AND json_extract(payload, '$.receipt_id')=? LIMIT 1",
        (task_id, receipt_id),
    ).fetchone()
    return None if consumed else approval


def _stored_approval_is_expired(conn, task_id: str) -> bool:
    approval = _event_payload(conn, task_id, "theseus_terminal_approved")
    if not approval or approval.get("task_id") != task_id:
        return False
    expires_at = approval.get("approval_expires_at")
    return isinstance(expires_at, int) and not isinstance(expires_at, bool) and int(time.time()) >= expires_at


def _decision_for_claim(conn, task_id: str) -> Optional[dict]:
    decision = _event_payload(conn, task_id, "theseus_architect_decision")
    stop = _event_payload(conn, task_id, "theseus_architect_stop")
    if not decision or not stop or decision.get("stop_token") != stop.get("stop_token"):
        return None
    decision_id = decision.get("decision_id")
    if not isinstance(decision_id, str):
        return None
    consumed = conn.execute(
        "SELECT 1 FROM task_events WHERE task_id=? AND kind='theseus_decision_consumed' "
        "AND json_extract(payload, '$.decision_id')=? LIMIT 1",
        (task_id, decision_id),
    ).fetchone()
    return None if consumed else decision


def _claim_allowed_locked(conn, task_id: str, *, role_dispatch: bool) -> bool:
    row = conn.execute(
        "SELECT workflow_template_id, current_step_key, assignee FROM tasks WHERE id=?", (task_id,)
    ).fetchone()
    if row is None or row["workflow_template_id"] != WORKFLOW_TEMPLATE_ID:
        return True
    metadata = package_metadata(conn, task_id)
    if metadata is None:
        return False
    if not _dispatcher_host_allowed(metadata):
        return False
    role = str(metadata.get("role") or "")
    if row["assignee"] != ROLE_PROFILES.get(role):
        return False
    if role in {"reviewer", "investigator"}:
        if not role_dispatch:
            return False
        if (
            metadata.get("authority") != "read-only"
            or metadata.get("publish_allowed") is not False
            or metadata.get("merge_allowed") is not False
        ):
            return False
        active_peer = conn.execute(
            "SELECT 1 FROM tasks t JOIN task_events e ON e.task_id=t.id "
            "WHERE e.kind='theseus_lifecycle_initialized' AND t.id!=? AND t.status='running' "
            "AND json_extract(e.payload, '$.package_id')=? "
            "AND json_extract(e.payload, '$.role') IN ('reviewer','investigator') LIMIT 1",
            (task_id, metadata.get("package_id")),
        ).fetchone()
        if active_peer is not None:
            return False
    phase = row["current_step_key"]
    if phase == READY_FOR_BUILDER:
        return _approval_for_claim(conn, task_id) is not None or _decision_for_claim(conn, task_id) is not None
    if phase == BUILDER_RUNNING:
        return _decision_for_claim(conn, task_id) is not None
    return phase in {REVIEW_RUNNING, INVESTIGATION_RUNNING}


def native_claim_allowed_locked(conn, task_id: str) -> bool:
    """Public/native claims never acquire restricted role tasks."""
    return _claim_allowed_locked(conn, task_id, role_dispatch=False)


def dispatch_claim_allowed_locked(conn, task_id: str) -> bool:
    """Validate the common dispatcher claim path while its write txn is held."""
    return _claim_allowed_locked(conn, task_id, role_dispatch=True)


def restricted_role_for_worker(task: Any) -> Optional[str]:
    """Return the enforced read-only role for a validated lifecycle worker."""
    if getattr(task, "workflow_template_id", None) != WORKFLOW_TEMPLATE_ID:
        return None
    phase = str(getattr(task, "current_step_key", None) or "")
    role = {
        REVIEW_RUNNING: "reviewer",
        INVESTIGATION_RUNNING: "investigator",
    }.get(phase)
    if role is None:
        return None
    if getattr(task, "assignee", None) != ROLE_PROFILES[role]:
        raise ValueError("lifecycle role/profile capability mismatch")
    return role


def bind_claim_authority_locked(conn, task_id: str, run_id: int) -> None:
    task = kb.get_task(conn, task_id)
    if task is None or task.workflow_template_id != WORKFLOW_TEMPLATE_ID:
        return
    approval = _approval_for_claim(conn, task_id)
    if approval is not None:
        kb._append_event(
            conn,
            task_id,
            "theseus_approval_consumed",
            {"receipt_id": approval["receipt_id"], "run_id": int(run_id)},
            run_id=int(run_id),
        )
        return
    decision = _decision_for_claim(conn, task_id)
    if decision is not None:
        kb._append_event(
            conn,
            task_id,
            "theseus_decision_consumed",
            {"decision_id": decision["decision_id"], "run_id": int(run_id)},
            run_id=int(run_id),
        )


def native_promotion_allowed_locked(conn, task_id: str) -> bool:
    row = conn.execute(
        "SELECT workflow_template_id, current_step_key FROM tasks WHERE id=?", (task_id,)
    ).fetchone()
    return bool(
        row is None
        or row["workflow_template_id"] != WORKFLOW_TEMPLATE_ID
        or row["current_step_key"] not in {AWAITING_TERMINAL_APPROVAL, STOPPED_AWAITING_ARCHITECT}
    )


def prepare_native_terminal_locked(
    conn,
    task_id: str,
    expected_run_id: Optional[int],
    operation: str,
    metadata: Optional[dict] = None,
) -> Optional[dict]:
    """Finalize the exact lifecycle run and CAS its phase inside caller txn."""
    task = kb.get_task(conn, task_id)
    if task is None or task.workflow_template_id != WORKFLOW_TEMPLATE_ID:
        return metadata
    if expected_run_id is None or task.current_run_id != int(expected_run_id):
        raise ValueError("THESEUS terminal operation requires the exact active run")
    role = (package_metadata(conn, task_id) or {}).get("role")
    phase_by_operation = {
        ("builder", "complete"): BUILDER_COMPLETE_AWAITING_REVIEW,
        ("builder", "review"): BUILDER_COMPLETE_AWAITING_REVIEW,
        ("reviewer", "changes"): CHANGES_REQUESTED,
        ("reviewer", "complete"): GATE2_RECOMMENDATION_READY,
        ("investigator", "complete"): CORRECTION_READY,
    }
    target = phase_by_operation.get((str(role), operation))
    if target is None:
        raise ValueError("terminal operation is not authorized for lifecycle role")
    row = conn.execute(
        "SELECT metadata FROM task_runs WHERE id=? AND task_id=? AND ended_at IS NULL",
        (int(expected_run_id), task_id),
    ).fetchone()
    if row is None:
        raise ValueError("exact active lifecycle run not found")
    try:
        run_metadata = json.loads(row["metadata"] or "{}")
    except (TypeError, json.JSONDecodeError):
        run_metadata = {}
    if not isinstance(run_metadata, dict):
        run_metadata = {}
    paths = run_metadata.get("artifacts")
    if not isinstance(paths, dict):
        raise ValueError("lifecycle artifact paths are missing")
    manifest = finalize_artifacts(
        paths,
        manifest_facts={"task_id": task_id, "run_id": int(expected_run_id)},
    )
    changed = conn.execute(
        "UPDATE tasks SET current_step_key=? WHERE id=? AND current_step_key=? AND current_run_id=?",
        (target, task_id, task.current_step_key, int(expected_run_id)),
    )
    if changed.rowcount != 1:
        raise ValueError("lifecycle terminal phase changed concurrently")
    merged = {**run_metadata, **(metadata or {}), "theseus_artifacts": manifest}
    kb._append_event(
        conn,
        task_id,
        "theseus_phase_transition",
        {"previous_phase": task.current_step_key, "phase": target, "operation": operation},
        run_id=int(expected_run_id),
    )
    return merged


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
    metadata = package_metadata(conn, task_id) or {}
    if payload["baseline_sha"] != metadata.get("baseline_sha") or payload["candidate_sha"] != metadata.get("candidate_sha"):
        raise ValueError("STOP Git identity does not match the work package")
    stop_token = hashlib.sha256(
        f"{task_id}\0{int(expected_run_id)}\0{payload['stop_type']}\0{payload['reason']}".encode()
    ).hexdigest()
    payload["stop_token"] = stop_token
    with kb.write_txn(conn):
        row = conn.execute(
            "SELECT status, current_step_key, current_run_id, worker_pid, claim_lock "
            "FROM tasks WHERE id=?",
            (task_id,),
        ).fetchone()
        if row is None or row["status"] != "running" or row["current_run_id"] != int(expected_run_id):
            return False
        if row["current_step_key"] not in {READY_FOR_BUILDER, BUILDER_RUNNING}:
            return False
        run_changed = conn.execute(
            "UPDATE task_runs SET status='blocked', outcome='blocked', summary=?, ended_at=?, "
            "claim_lock=NULL, claim_expires=NULL, worker_pid=NULL "
            "WHERE id=? AND task_id=? AND ended_at IS NULL AND claim_lock IS ? AND worker_pid IS ?",
            (
                payload["reason"],
                int(time.time()),
                int(expected_run_id),
                task_id,
                row["claim_lock"],
                row["worker_pid"],
            ),
        )
        if run_changed.rowcount != 1:
            return False
        changed = conn.execute(
            "UPDATE tasks SET status='blocked', current_step_key=?, current_run_id=NULL, "
            "claim_lock=NULL, claim_expires=NULL, worker_pid=NULL, block_kind='needs_input' "
            "WHERE id=? AND status='running' AND current_run_id=? AND claim_lock IS ? AND worker_pid IS ?",
            (
                STOPPED_AWAITING_ARCHITECT,
                task_id,
                int(expected_run_id),
                row["claim_lock"],
                row["worker_pid"],
            ),
        )
        if changed.rowcount != 1:
            raise ValueError("STOP task fence changed concurrently")
        kb._append_event(
            conn, task_id, "theseus_architect_stop", payload, run_id=int(expected_run_id)
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
    authority_evidence: str | bytes | None = None,
    **_caller_metadata: object,
) -> str:
    """Production entrypoint; role authorization is unavailable until authority is configured."""
    raise ValueError(PRODUCTION_AUTHORITY_BLOCKED)


def _read_git_identity(worktree: str) -> dict[str, str]:
    def git(*args: str) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=worktree,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        return result.stdout.strip()

    branch = git("branch", "--show-current")
    if not branch:
        raise ValueError("actual Git worktree is detached")
    return {
        "root": str(Path(git("rev-parse", "--show-toplevel")).resolve()),
        "branch": branch,
        "head": git("rev-parse", "HEAD").lower(),
        "parent": git("rev-parse", "HEAD^").lower(),
    }


def resume_after_architect_decision(
    conn,
    task_id: str,
    *,
    authority_evidence: str | bytes | None = None,
    **_caller_metadata: object,
) -> bool:
    """Production entrypoint; unavailable until a trusted authority is configured."""
    raise ValueError(PRODUCTION_AUTHORITY_BLOCKED)


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
    if not _dispatcher_host_allowed(metadata):
        return False, "dispatcher_host_mismatch"
    role = metadata.get("role")
    if task.assignee != ROLE_PROFILES.get(str(role)):
        return False, "role_profile_mismatch"
    if role in {"reviewer", "investigator"}:
        if metadata.get("authority") != "read-only" or metadata.get("publish_allowed") is not False or metadata.get("merge_allowed") is not False:
            return False, "role_authority_policy_mismatch"
        active_peer = conn.execute(
            "SELECT 1 FROM tasks t JOIN task_events e ON e.task_id=t.id "
            "WHERE e.kind='theseus_lifecycle_initialized' AND t.id!=? AND t.status='running' "
            "AND json_extract(e.payload, '$.package_id')=? "
            "AND json_extract(e.payload, '$.role') IN ('reviewer','investigator') LIMIT 1",
            (task_id, metadata.get("package_id")),
        ).fetchone()
        if active_peer is not None:
            return False, "role_concurrency_blocked"
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
        _approval_for_claim(conn, task_id) or _decision_for_claim(conn, task_id)
    ):
        return False, "approval_expired" if _stored_approval_is_expired(conn, task_id) else "approval_missing"
    return True, None


def enforce_dispatch_preflight(conn, task_id: str) -> tuple[bool, Optional[str]]:
    """Park an opted-in card when generic mutation tried to bypass its gate."""
    ok, reason = dispatch_preflight(conn, task_id)
    task = kb.get_task(conn, task_id)
    if ok or task is None or task.workflow_template_id != WORKFLOW_TEMPLATE_ID:
        return ok, reason
    if reason == "approval_expired":
        return False, reason
    if task.status == "ready":
        with kb.write_txn(conn):
            next_phase = (
                AWAITING_TERMINAL_APPROVAL
                if reason == "approval_missing" and (package_metadata(conn, task_id) or {}).get("role") == "builder"
                else task.current_step_key
            )
            changed = conn.execute(
                "UPDATE tasks SET status='blocked', current_step_key=?, claim_lock=NULL, claim_expires=NULL, "
                "worker_pid=NULL, block_kind=? "
                "WHERE id=? AND status='ready' AND current_run_id IS NULL",
                (
                    next_phase,
                    "approval" if reason == "approval_missing" or task.current_step_key == AWAITING_TERMINAL_APPROVAL else "needs_input",
                    task_id,
                ),
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
        "dispatch_diagnostic": dispatch_diagnostic(
            conn,
            task_id,
            dispatcher_enabled=True,
            lock_contended=False,
            profile_available=True,
            capacity_available=True,
        ),
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


_ARTIFACT_COMPONENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _artifact_component(name: str, value: Any) -> str:
    value = str(value)
    if value in {".", ".."} or not _ARTIFACT_COMPONENT_RE.fullmatch(value):
        raise ValueError(f"invalid artifact path component: {name}")
    return value


def _directory_identity(fd: int) -> list[int]:
    st = os.fstat(fd)
    if not stat.S_ISDIR(st.st_mode):
        raise ValueError("artifact directory component is not a directory")
    return [int(st.st_dev), int(st.st_ino)]


def _artifact_platform_supported() -> bool:
    """The artifact fence requires POSIX dir-fd and no-follow primitives."""
    required_dir_fd = (os.open, os.mkdir, os.link, os.unlink)
    return bool(
        os.name == "posix"
        and hasattr(os, "O_DIRECTORY")
        and hasattr(os, "O_NOFOLLOW")
        and all(operation in os.supports_dir_fd for operation in required_dir_fd)
    )


def _require_artifact_platform() -> None:
    if not _artifact_platform_supported():
        raise ValueError("secure artifact publication is unsupported on this platform")


def _open_secure_directory(path: Path) -> tuple[int, list[list[int]]]:
    """Open/create an absolute directory chain and capture every identity."""
    _require_artifact_platform()
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open(path.anchor, flags)
    chain = [_directory_identity(fd)]
    try:
        for component in path.parts[1:]:
            created = False
            try:
                os.mkdir(component, 0o700, dir_fd=fd)
                created = True
            except FileExistsError:
                pass
            next_fd = os.open(component, flags, dir_fd=fd)
            if created:
                os.fchmod(next_fd, 0o700)
            os.close(fd)
            fd = next_fd
            chain.append(_directory_identity(fd))
        os.fchmod(fd, 0o700)
        return fd, chain
    except BaseException:
        os.close(fd)
        raise


def run_artifact_paths(root: Path, board: str, task_id: str, run_id: int) -> dict[str, Any]:
    components = (
        _artifact_component("board", board),
        _artifact_component("task_id", task_id),
        _artifact_component("run_id", str(int(run_id))),
    )
    root_path = Path(os.path.abspath(os.fspath(Path(root).expanduser())))
    try:
        fd, directory_chain = _open_secure_directory(root_path)
    except OSError as exc:
        raise ValueError("artifact root contains a symlink or unsafe component") from exc
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        current = root_path
        for component in components:
            try:
                os.mkdir(component, 0o700, dir_fd=fd)
            except FileExistsError:
                pass
            next_fd = os.open(component, flags, dir_fd=fd)
            os.fchmod(next_fd, 0o700)
            os.close(fd)
            fd = next_fd
            current /= component
            directory_chain.append(_directory_identity(fd))
        identities: dict[str, list[int]] = {}
        create_flags = os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        for name in ("report", "result"):
            filename = f"{name}.md"
            try:
                artifact_fd = os.open(filename, create_flags, 0o600, dir_fd=fd)
            except FileExistsError as exc:
                raise ValueError(f"artifact {name} already exists") from exc
            try:
                st = os.fstat(artifact_fd)
                identities[name] = [int(st.st_dev), int(st.st_ino)]
            finally:
                os.close(artifact_fd)
    except OSError as exc:
        raise ValueError("artifact path contains a symlink or unsafe component") from exc
    finally:
        os.close(fd)
    return {
        "directory": str(current),
        "report": str(current / "report.md"),
        "result": str(current / "result.md"),
        "manifest": str(current / "manifest.json"),
        "_identity": identities,
        "_directory_identity": directory_chain,
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


def finalize_artifacts(paths: dict[str, Any], *, manifest_facts: Optional[dict] = None) -> dict:
    _require_artifact_platform()
    directory = Path(paths["directory"])
    identities = paths.get("_identity")
    if not isinstance(identities, dict):
        raise ValueError("prepared artifact identity is missing")
    expected_chain = paths.get("_directory_identity")
    if not isinstance(expected_chain, list) or len(expected_chain) != len(directory.parts):
        raise ValueError("prepared artifact directory identity is missing")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    directory_fd = os.open(directory.anchor, flags)
    try:
        for index, expected in enumerate(expected_chain):
            if index:
                next_fd = os.open(directory.parts[index], flags, dir_fd=directory_fd)
                os.close(directory_fd)
                directory_fd = next_fd
            if not isinstance(expected, list) or _directory_identity(directory_fd) != expected:
                raise ValueError("artifact directory chain was replaced after prepare")
    except BaseException:
        os.close(directory_fd)
        raise
    files: dict[str, dict] = {}
    try:
        seen: set[tuple[int, int]] = set()
        for name in ("report", "result"):
            expected = identities.get(name)
            if not isinstance(expected, list) or len(expected) != 2:
                raise ValueError(f"prepared {name} identity is missing")
            try:
                fd = os.open(
                    f"{name}.md",
                    os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=directory_fd,
                )
            except OSError as exc:
                raise ValueError(f"artifact {name} was replaced or is a symlink") from exc
            try:
                st = os.fstat(fd)
                identity = (int(st.st_dev), int(st.st_ino))
                if identity != tuple(expected) or identity in seen or not stat.S_ISREG(st.st_mode):
                    raise ValueError(f"artifact {name} was replaced or paths collide")
                seen.add(identity)
                chunks = []
                while True:
                    chunk = os.read(fd, 1024 * 1024)
                    if not chunk:
                        break
                    chunks.append(chunk)
                data = b"".join(chunks)
            finally:
                os.close(fd)
            files[name] = {
                "path": str(directory / f"{name}.md"),
                "status": "PRESENT",
                "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        manifest = {"artifacts": files, **(manifest_facts or {})}
        temp_name = f".manifest.{secrets.token_hex(16)}.tmp"
        temp_created = False
        try:
            manifest_fd = os.open(
                temp_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=directory_fd,
            )
            temp_created = True
            try:
                payload = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
                offset = 0
                while offset < len(payload):
                    offset += os.write(manifest_fd, payload[offset:])
                os.fsync(manifest_fd)
            finally:
                os.close(manifest_fd)
            os.link(
                temp_name,
                "manifest.json",
                src_dir_fd=directory_fd,
                dst_dir_fd=directory_fd,
                follow_symlinks=False,
            )
            os.unlink(temp_name, dir_fd=directory_fd)
            temp_created = False
            os.fsync(directory_fd)
        except BaseException:
            if temp_created:
                try:
                    os.unlink(temp_name, dir_fd=directory_fd)
                except FileNotFoundError:
                    pass
                try:
                    os.fsync(directory_fd)
                except OSError:
                    pass
            raise
    except OSError as exc:
        raise ValueError("artifact manifest path is unsafe or already finalized") from exc
    finally:
        os.close(directory_fd)
    return manifest

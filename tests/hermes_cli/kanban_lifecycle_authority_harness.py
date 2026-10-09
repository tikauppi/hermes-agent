"""Synthetic authority harness confined to the test tree.

This module exercises transaction behavior with disposable keys. It is not
shipped as a lifecycle API and is not a security boundary against arbitrary
code already running with the test process's SQLite rights.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hermes_cli import kanban_db as kb
from hermes_cli import kanban_theseus_lifecycle as glh
from hermes_cli.kanban_authority_verifier import AuthorityVerifier


@dataclass(frozen=True)
class SyntheticAuthority:
    verifier: AuthorityVerifier


def _gate_locked(
    conn,
    task_id: str,
    *,
    authority_evidence: str | bytes,
    expected_bindings: dict[str, object],
    authority: SyntheticAuthority,
):
    def consume_once(issuer: str, nonce: str, digest: str) -> bool:
        replay = conn.execute(
            "SELECT 1 FROM task_events WHERE kind='theseus_authority_consumed' "
            "AND json_extract(payload, '$.issuer')=? "
            "AND json_extract(payload, '$.nonce')=? LIMIT 1",
            (issuer, nonce),
        ).fetchone()
        if replay is not None:
            return False
        kb._append_event(
            conn,
            task_id,
            "theseus_authority_consumed",
            {
                "issuer": issuer,
                "nonce": nonce,
                "evidence_digest": digest,
                "action": expected_bindings["action"],
                "scope": expected_bindings["scope"],
            },
        )
        return True

    return authority.verifier.verify_and_consume(
        authority_evidence,
        expected=expected_bindings,
        now=int(glh.time.time()),
        consume_once=consume_once,
    )


def approve(
    conn,
    task_id: str,
    *,
    authority_evidence: str | bytes,
    authority: SyntheticAuthority,
    action: str = "record_terminal_approval",
    renew_window: bool = False,
    **_caller_metadata: object,
) -> bool:
    with kb.write_txn(conn):
        task = kb.get_task(conn, task_id)
        metadata = glh.package_metadata(conn, task_id)
        if (
            task is None
            or metadata is None
            or task.current_step_key != glh.AWAITING_TERMINAL_APPROVAL
        ):
            raise ValueError("task is not awaiting terminal approval")
        if task.current_run_id is not None or task.worker_pid is not None:
            raise ValueError("approval pre-dispatch task already has an active run/PID")
        verified = _gate_locked(
            conn,
            task_id,
            authority_evidence=authority_evidence,
            authority=authority,
            expected_bindings={
                "version": 1,
                "algorithm": "Ed25519",
                "principal_role": "approver",
                "evidence_type": "terminal_approval",
                "action": action,
                "scope": glh.AUTHORITY_SCOPE,
                "package_id": metadata["package_id"],
                "task_id": task_id,
                "run_id": 0,
                "stop_token": "none",
                "code_sha": metadata["candidate_sha"],
            },
        )
        payload = verified.payload
        window = (
            glh._event_payload(conn, task_id, "theseus_approval_window_renewed")
            or metadata
        )
        window_expires_at = int(window["approval_expires_at"])
        if not renew_window and int(payload["expires_at"]) > window_expires_at:
            raise ValueError("authority evidence exceeds the configured approval window")
        if renew_window:
            window_expires_at = int(payload["expires_at"])
            kb._append_event(
                conn,
                task_id,
                "theseus_approval_window_renewed",
                {
                    "approval_expires_at": window_expires_at,
                    "issued_at": payload["issued_at"],
                },
            )
        changed = conn.execute(
            "UPDATE tasks SET status='ready', current_step_key=?, block_kind=NULL "
            "WHERE id=? AND status='blocked' AND current_step_key=? "
            "AND current_run_id IS NULL AND worker_pid IS NULL",
            (glh.READY_FOR_BUILDER, task_id, glh.AWAITING_TERMINAL_APPROVAL),
        )
        if changed.rowcount != 1:
            raise ValueError("approval state changed concurrently")
        kb._append_event(
            conn,
            task_id,
            "theseus_terminal_approved",
            {
                "issuer": payload["issuer"],
                "principal": payload["principal"],
                "approved_at": payload["issued_at"],
                "approval_expires_at": payload["expires_at"],
                "receipt_id": verified.evidence_digest,
                "task_id": task_id,
                "phase": glh.READY_FOR_BUILDER,
            },
        )
    return True


def fresh_approve(
    conn,
    task_id: str,
    *,
    authority_evidence: str | bytes,
    authority: SyntheticAuthority,
) -> bool:
    return approve(
        conn,
        task_id,
        authority_evidence=authority_evidence,
        authority=authority,
        action="issue_fresh_terminal_approval",
        renew_window=True,
    )


def create_role_task(
    conn,
    *,
    builder_task_id: str,
    role: str,
    title: str,
    candidate_sha: str,
    branch: str,
    worktree: str,
    authority_evidence: str | bytes,
    authority: SyntheticAuthority,
) -> str:
    if role not in {"reviewer", "investigator"}:
        raise ValueError("role must be reviewer or investigator")
    builder = kb.get_task(conn, builder_task_id)
    builder_meta = glh.package_metadata(conn, builder_task_id)
    if builder is None or builder_meta is None:
        raise ValueError("builder task is not a THESEUS work package")
    if builder.status not in {"done", "archived"}:
        raise ValueError("builder task must be terminal before a linked role task is created")
    worktree = glh._require_worktree(worktree)
    if Path(worktree).resolve() == Path(builder.workspace_path or "").resolve():
        raise ValueError(f"{role} task cannot reuse the Builder worktree")
    branch = glh._require_text("branch", branch)
    if branch == builder.branch_name:
        raise ValueError(f"{role} task cannot reuse the Builder branch")
    candidate_sha = glh._require_sha("candidate_sha", candidate_sha)
    builder_candidate = glh._require_sha(
        "builder candidate_sha", str(builder_meta.get("candidate_sha") or "")
    )
    if candidate_sha != builder_candidate:
        raise ValueError("linked role candidate must equal the Builder candidate")
    actual = glh._read_git_identity(worktree)
    if (
        actual["root"] != worktree
        or actual["branch"] != branch
        or actual["head"] != candidate_sha
    ):
        raise ValueError(f"actual Git identity does not match the {role} task")
    package_id = glh._require_text("package_id", builder_meta.get("package_id"))

    with kb.write_txn(conn):
        _gate_locked(
            conn,
            builder_task_id,
            authority_evidence=authority_evidence,
            authority=authority,
            expected_bindings={
                "version": 1,
                "algorithm": "Ed25519",
                "principal_role": "architect",
                "evidence_type": "architect_decision",
                "action": f"create_{role}_task",
                "scope": glh.AUTHORITY_SCOPE,
                "package_id": package_id,
                "task_id": builder_task_id,
                "run_id": 0,
                "stop_token": "none",
                "code_sha": candidate_sha,
            },
        )
        collision = conn.execute(
            "SELECT t.id FROM tasks t JOIN task_events e ON e.task_id=t.id "
            "WHERE e.kind='theseus_lifecycle_initialized' "
            "AND json_extract(e.payload, '$.package_id')=? AND t.id!=? "
            "AND t.status!='archived' AND (t.workspace_path=? OR t.branch_name=?) LIMIT 1",
            (package_id, builder_task_id, worktree, branch),
        ).fetchone()
        if collision is not None:
            raise ValueError(
                "role worktree or branch collides with another active package task"
            )
        task_id = kb.create_task(
            conn,
            title=title,
            body=(
                f"Pinned candidate: {candidate_sha}. Read-only {role} authority: "
                "do not modify application source, publish, merge, or reuse the Builder worktree."
            ),
            assignee=glh.ROLE_PROFILES[role],
            workspace_kind="worktree",
            workspace_path=worktree,
            branch_name=branch,
            parents=(builder_task_id,),
            idempotency_key=(
                f"theseus-work-package:{package_id}:{role}:{candidate_sha}"
            ),
            created_by="theseus-lifecycle-test-harness",
        )
        task = kb.get_task(conn, task_id)
        if task is not None and task.workflow_template_id == glh.WORKFLOW_TEMPLATE_ID:
            return task_id
        metadata: dict[str, Any] = {
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
            "dispatcher_profile": glh.DESIGNATED_DISPATCHER_PROFILE,
        }
        conn.execute(
            "UPDATE tasks SET workflow_template_id=?, current_step_key=? WHERE id=?",
            (glh.WORKFLOW_TEMPLATE_ID, glh.ROLE_READY_PHASE[role], task_id),
        )
        kb._append_event(conn, task_id, "theseus_lifecycle_initialized", metadata)
        kb._append_event(
            conn,
            task_id,
            "theseus_role_task_linked",
            {
                "builder_task_id": builder_task_id,
                "role": role,
                "candidate_sha": candidate_sha,
            },
        )
    return task_id


def resume(
    conn,
    task_id: str,
    *,
    authority_evidence: str | bytes,
    authority: SyntheticAuthority,
) -> bool:
    task = kb.get_task(conn, task_id)
    stop = glh._event_payload(conn, task_id, "theseus_architect_stop")
    if task is None or stop is None or task.current_step_key != glh.STOPPED_AWAITING_ARCHITECT:
        raise ValueError("task has no unresolved Architect STOP")
    if task.status != "blocked" or task.worker_pid is not None:
        raise ValueError("stopped task must be blocked with no live worker PID")
    active_run = conn.execute(
        "SELECT 1 FROM task_runs WHERE task_id=? AND ended_at IS NULL LIMIT 1",
        (task_id,),
    ).fetchone()
    if active_run is not None:
        raise ValueError("prior run is still active")
    metadata = glh.package_metadata(conn, task_id) or {}
    if metadata.get("role") != "builder" or task.assignee != glh.ROLE_PROFILES["builder"]:
        raise ValueError("Builder role/profile preflight failed")
    expected_worktree = glh._require_worktree(str(metadata.get("worktree") or ""))
    if expected_worktree != glh._require_worktree(task.workspace_path or ""):
        raise ValueError("Builder worktree preflight failed")
    expected_branch = glh._require_text("branch", metadata.get("branch"))
    if expected_branch != glh._require_text("branch", task.branch_name):
        raise ValueError("Builder branch preflight failed")
    expected_baseline = glh._require_sha(
        "baseline_sha", str(metadata.get("baseline_sha") or "")
    )
    expected_candidate = glh._require_sha(
        "candidate_sha", str(metadata.get("candidate_sha") or "")
    )
    actual = glh._read_git_identity(expected_worktree)
    if actual != {
        "root": expected_worktree,
        "branch": expected_branch,
        "head": expected_candidate,
        "parent": expected_baseline,
    }:
        raise ValueError("actual Git identity does not match the fenced work package")
    with kb.write_txn(conn):
        verified = _gate_locked(
            conn,
            task_id,
            authority_evidence=authority_evidence,
            authority=authority,
            expected_bindings={
                "version": 1,
                "algorithm": "Ed25519",
                "principal_role": "architect",
                "evidence_type": "architect_decision",
                "action": "resume_after_architect_decision",
                "scope": glh.AUTHORITY_SCOPE,
                "package_id": metadata["package_id"],
                "task_id": task_id,
                "run_id": int(stop["stopped_run_id"]),
                "stop_token": stop["stop_token"],
                "code_sha": expected_candidate,
            },
        )
        changed = conn.execute(
            "UPDATE tasks SET status='ready', current_step_key=?, block_kind=NULL "
            "WHERE id=? AND status='blocked' AND current_step_key=? AND worker_pid IS NULL",
            (glh.READY_FOR_BUILDER, task_id, glh.STOPPED_AWAITING_ARCHITECT),
        )
        if changed.rowcount != 1:
            raise ValueError("STOP state changed concurrently")
        payload = verified.payload
        kb._append_event(
            conn,
            task_id,
            "theseus_architect_decision",
            {
                "actor": payload["principal"],
                "issuer": payload["issuer"],
                "decision_id": verified.evidence_digest,
                "stop_token": stop["stop_token"],
                "resolves_stop_run_id": stop["stopped_run_id"],
                "phase": glh.READY_FOR_BUILDER,
            },
        )
    return True

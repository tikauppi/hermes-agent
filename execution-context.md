# Gateway/Kanban lifecycle hardening — execution context

Authority: Architect-authorized R1 correction and fast track to an independent Gate 2 re-review, supplied to Hermes session `20261009_014800_8cd02d`.

Approved correction worktree: `/opt/data/hermes-glh-r1-correction`
Approved correction branch: `fix/theseus-gateway-kanban-lifecycle-r1`
Reviewed faulty candidate / expected initial HEAD: `80cc81e85a6ded0fc1835ce22d8db811b929eb93`
Immutable parent baseline: `fef0e16fe19b79ded929209f87c7434270b03825`
Locked review: `/opt/data/logs/glh-gate2-reviewer-20261009.report.md`, SHA-256 `dbb5e93d346aeb8367074b1a8f502e5e23c537a699920f250482ba5aca642aa8`.
Approved proposal remains `/opt/data/THESEUS-worktrees/gateway-kanban-lifecycle-planning/planning/gateway-kanban-lifecycle-implementation-proposal.md` at `3e742998a7643ab68e5b4853b93466fb22c67a1c`.

## Mandatory command guard

Run these exact top-level and branch guards before every Git mutation and every test command:

```sh
[ "$(git rev-parse --show-toplevel)" = "/opt/data/hermes-glh-r1-correction" ] || { echo TYOALUE-VAARIN >&2; exit 2; }
[ "$(git branch --show-current)" = "fix/theseus-gateway-kanban-lifecycle-r1" ] || { echo BRANCH-VAARIN >&2; exit 2; }
```

Initial-write guard additionally established:

```sh
[ "$(git rev-parse HEAD)" = "80cc81e85a6ded0fc1835ce22d8db811b929eb93" ] || { echo HEAD-VAARIN >&2; exit 2; }
[ "$(git rev-parse HEAD^)" = "fef0e16fe19b79ded929209f87c7434270b03825" ] || { echo PARENT-VAARIN >&2; exit 2; }
[ "$(sha256sum /opt/data/logs/glh-gate2-reviewer-20261009.report.md | cut -d' ' -f1)" = "dbb5e93d346aeb8367074b1a8f502e5e23c537a699920f250482ba5aca642aa8" ] || { echo REVIEW-HASH-VAARIN >&2; exit 2; }
test -z "$(git status --porcelain=v1 -uall)" || { echo TYOPUU-EI-PUHDAS >&2; exit 2; }
```

After the implementation commit, the immutable baseline remains an ancestor and the exact code SHA replaces the initial-HEAD equality check. Unknown or out-of-scope changes stop the work; they are never stashed, reset, rebased, or absorbed.

## Scope guard

Only the Architect-authorized R1 corrections F-01 through F-09 for the opt-in `theseus-gateway-lifecycle-v1` Kanban lifecycle, their isolated synthetic pilot, tests, and tightly scoped validation evidence are authorized. Ordinary/non-opt-in Kanban behavior must remain unchanged. Use only existing tasks, task_runs, task_events, metadata, and links; no global schema migration or `work_packages` table. Do not launch a real Gateway or role profile, mutate a production board, alter desired state/profile configuration, change S123/S124, perform Gate 2 review/approval, merge, or force-push. Two normal pushes to this correction branch are authorized: first the immutable code/tests commit, then the separate evidence/docs commit after remote divergence checks and readback.

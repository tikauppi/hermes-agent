# Gateway/Kanban lifecycle hardening — execution context

Authority: Architect Gate 1 as supplied to Hermes session `20261008_172616_035fab`.

Approved source worktree: `/opt/data/hermes-gateway-kanban-lifecycle-hardening`
Approved branch: `theseus/gateway-kanban-lifecycle-hardening`
Immutable baseline / expected initial HEAD: `fef0e16fe19b79ded929209f87c7434270b03825`
Approved proposal: `/opt/data/THESEUS-worktrees/gateway-kanban-lifecycle-planning/planning/gateway-kanban-lifecycle-implementation-proposal.md` at `3e742998a7643ab68e5b4853b93466fb22c67a1c`.

## Mandatory command guard

Run these exact top-level and branch guards before every Git mutation and every test command:

```sh
[ "$(git rev-parse --show-toplevel)" = "/opt/data/hermes-gateway-kanban-lifecycle-hardening" ] || { echo TYOALUE-VAARIN >&2; exit 2; }
[ "$(git branch --show-current)" = "theseus/gateway-kanban-lifecycle-hardening" ] || { echo BRANCH-VAARIN >&2; exit 2; }
```

Initial-write guard additionally established:

```sh
[ "$(git rev-parse HEAD)" = "fef0e16fe19b79ded929209f87c7434270b03825" ] || { echo HEAD-VAARIN >&2; exit 2; }
test -z "$(git status --porcelain=v1 -uall)" || { echo TYOPUU-EI-PUHDAS >&2; exit 2; }
```

After the implementation commit, the immutable baseline remains an ancestor and the exact code SHA replaces the initial-HEAD equality check. Unknown or out-of-scope changes stop the work; they are never stashed, reset, rebased, or absorbed.

## Scope guard

Only opt-in Hermes Kanban lifecycle adapter/API/CLI behavior, its isolated synthetic pilot, and tests are authorized. No live Gateway/service/profile/board/worktree mutation is authorized. No schema migration or `work_packages` table is authorized. No push is authorized. The implementation ends after one immutable code commit and the two external log handoff artifacts.

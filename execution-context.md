# S126-C F6 GitHub acceptance adapter — execution context

Authority: Architect implementation authorization recorded on Kanban task `t_7a8c4217`, run 28, session `default/20261011_103854_dfca2c`.

Approved source worktree: `/opt/data/hermes-f6-github-acceptance-adapter`
Approved branch: `fix/theseus-s126-f6-github-acceptance-adapter`
Immutable baseline / expected initial HEAD: `80cc81e85a6ded0fc1835ce22d8db811b929eb93`
External read-only preflight target: `tikauppi/THESEUS` PR #25, expected head `c0a7d0d5bf1a69bf8e0968caf5343350d43d1d83`, expected base `integration/126-canonical-s121-s123-full-vue-recovery`.

## Mandatory command guard

Run these exact top-level and branch guards before every write, Git mutation, publication, and test command:

```sh
[ "$(git rev-parse --show-toplevel)" = "/opt/data/hermes-f6-github-acceptance-adapter" ] || { echo TYOALUE-VAARIN >&2; exit 2; }
[ "$(git branch --show-current)" = "fix/theseus-s126-f6-github-acceptance-adapter" ] || { echo BRANCH-VAARIN >&2; exit 2; }
```

Initial-write guard additionally established:

```sh
[ "$(git rev-parse HEAD)" = "80cc81e85a6ded0fc1835ce22d8db811b929eb93" ] || { echo HEAD-VAARIN >&2; exit 2; }
test -z "$(git status --porcelain=v1 -uall)" || { echo TYOPUU-EI-PUHDAS >&2; exit 2; }
```

After an authorized implementation commit, the immutable baseline must remain an ancestor and the exact implementation SHA replaces the initial-HEAD equality check. Unknown or out-of-scope changes stop work; they are never stashed, reset, rebased, or absorbed.

## Scope guard

Only the Hermes PR-acceptance collector API adapter, its targeted tests, and truthful read-only preflight evidence are authorized. The adapter must use supported authenticated GitHub APIs, validate exact PR provenance/head/base, fail closed, classify 401/403/404 truthfully, and reject zero or missing required-check policy. GitHub plan limitations remain blockers rather than being bypassed.

Prohibited: modifying `/opt/hermes`, `/opt/data/THESEUS`, PR #24/#25, main, or the historical R3 worktree; changing acceptance contracts; completing Kanban; self-review; Gate 2; merge; force push; feature activation; or any mutating GitHub API request. If a contract change is required, stop with a change proposal.

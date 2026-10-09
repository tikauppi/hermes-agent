# Gateway/Kanban Lifecycle Hardening — R3 implementation results

Tila: `PARTIALLY_BLOCKED_AWAITING_INDEPENDENT_REVIEWER_R3`

Session: `@session:theseus-builder/20261009_034127_37677e`

Tämä on Builderin toteutus- ja validointievidenssi. Se ei ole oma katselmus, Gate 2 -hyväksyntä, merge-lupa eikä Gateway-aktivointi.

## Commit- ja julkaisuidentiteetti

- R3 base / R1 evidence: `03ddc791f935f4f4d9534f90df1bb9481dc7369a`.
- R1 code: `0c8c82f94d4df4bfadad105b999133bddbbed11e`.
- R3 code SHA: `3cfc86168ba6560a42fa0696032e150fc231e8c8`.
- R3 code fork-readback: `3cfc86168ba6560a42fa0696032e150fc231e8c8` — MATCH.
- Evidence SHA: tämän tiedoston ja R3-validation-osion sisältävän evidence/docs-commitin Git-object ID; täsmällistä SHA:ta ei voida sisällyttää commitin omaan sisältöön ilman mahdotonta itseviittausta. Exact local/live SHA raportoidaan commitin jälkeisessä remote-readbackissa.
- Branch: `fix/theseus-gateway-kanban-lifecycle-r3`.
- Origin säilyi: `https://github.com/NousResearch/hermes-agent.git`.
- Fork säilyi: `git@github.com:tikauppi/hermes-agent.git`.
- R2 report SHA-256: `66f4ab74bf587a5970ddd1e120167df9c62637cb3fbb1a89085467d755ba1fdf` — MATCH.

## R3-01…R3-06

| R3 | Tila | Toteutus / rajaus |
|---|---|---|
| R3-01 | `BLOCKED — ARCHITECT DECISION REQUIRED` | Puuttuva trust-anchor-päätös: valitse tai toteuta erikseen luotettu server-side authenticated approval/decision principal sekä authoritative receipt issuer/store, joka todentaa terminal approval- ja Architect decision -päätökset caller-controlled `actor`, `approval_ref`, `approved_at` ja `decision_ref` -arvoista riippumatta. Sopivaa olemassa olevaa Hermes-lähdettä ei löytynyt; Builder ei keksinyt uutta auktoriteettia eikä laajentanut julkista sopimusta. |
| R3-02 | IMPLEMENTED / VALIDATED | Reviewer/Investigator-role claim sallitaan vain dispatcher-kontekstissa, oikealla profiililla, read-only-metadatalla ja ilman aktiivista peer-roolia. Native direct claim ohitetaan. Worker saa rajatun tool-allowlistin sekä schema- että native function-dispatch -rajalla. |
| R3-03 | IMPLEMENTED / VALIDATED | Koko prepare-vaiheen absoluuttinen directory chain sidotaan device/inode-identiteeteillä ja avataan finalize-vaiheessa descriptor-relatiivisesti `O_NOFOLLOW`:lla. Ancestor replacement + hardlink -hyökkäys estyy; manifest on exclusive/contained ja osittainen tiedosto poistetaan failure-polulla. |
| R3-04 | IMPLEMENTED / VALIDATED | Task preflight ja native claim vaativat metadata- ja nykyprofiiliksi designated `theseus-builder`; Gateway, standalone dispatch ja direct native bypass on katettu. Legacy/non-opt-in pass-through säilyy. |
| R3-05 | IMPLEMENTED / VALIDATED | PID-bind `False` ja exception terminoivat vain varmennetun uuden direct childin. Unverified/PID-reuse-kohdetta ei tapeta. Run/claim retry -eheys ja fresh approval on todennettu. |
| R3-06 | IMPLEMENTED / VALIDATED | `dry_run` ei suorita reclaim-, orphan-, crash-, timeout-, promotion-, recompute-ready- tai WAL checkpoint -kirjoituksia. Koko DB dump ja artefaktipuu säilyvät identtisinä kahdella peräkkäisellä ajolla reclaimable/promotable-fixtureillä. |

R3-01-blokin vuoksi Gate 2 -valmiutta ei väitetä.

## Koodicommitin muuttamat polut

1. `hermes_cli/kanban_db_dispatch.py`
2. `hermes_cli/kanban_theseus_lifecycle.py`
3. `model_tools.py`
4. `tests/gateway/test_kanban_reconcile_orphans.py`
5. `tests/hermes_cli/test_kanban_db_repair.py`
6. `tests/hermes_cli/test_kanban_theseus_lifecycle.py`

Ei skeema-/migraatio-/taulumuutosta, `work_packages`-taulua, S123/S124-muutosta eikä alkuperäisen R1/R2-historian muutosta.

## TDD RED → GREEN

Kaikissa turvallisesti erotettavissa käyttäytymisissä testi kirjoitettiin ja ajettiin ensin RED exit `1`, minkä jälkeen rajattu tuotantokorjaus tuotti GREEN exit `0`.

- R3-02:
  - `test_role_native_claim_rejects_wrong_capability_and_active_peer`
  - `test_role_worker_capabilities_are_enforced_at_schema_and_native_dispatch[reviewer]`
  - `test_role_worker_capabilities_are_enforced_at_schema_and_native_dispatch[investigator]`
- R3-03:
  - `test_artifacts_reject_prepare_finalize_ancestor_replacement_with_hardlinks`
  - `test_artifact_manifest_write_failure_removes_partial_file`
- R3-04:
  - `test_all_dispatch_and_native_claim_routes_reject_non_designated_host[theseus-reviewer]`
  - `test_all_dispatch_and_native_claim_routes_reject_non_designated_host[]`
- R3-05:
  - `test_pid_bind_exception_terminates_verified_child_and_preserves_retry_integrity`
  - olemassa olevat bind-False ja unverified no-kill -testit säilyivät GREEN.
- R3-06:
  - `test_lifecycle_dry_run_is_byte_for_byte_non_mutating`

## Exact code SHA -validointi

Testattu SHA: `3cfc86168ba6560a42fa0696032e150fc231e8c8`.

- Focused R3/GLH: exit `0`; `42 passed, 0 failed`.
- Affected Kanban/Gateway: exit `0`; `592 passed, 0 failed, 3 skipped` / 83 tiedostoa.
- Skips: kolme Windows-only-testiä; `SKIPPED`, ei PASS.
- Isolated synthetic pilot: exit `0`; `1 passed`.
- Ruff changed Python paths `--no-cache`: exit `0`; `All checks passed!`.
- `git diff --check 03ddc791f935f4f4d9534f90df1bb9481dc7369a..3cfc86168ba6560a42fa0696032e150fc231e8c8`: exit `0`.
- Third-party secret scanner: `NOT AVAILABLE` (`gitleaks`, `trufflehog`, `detect-secrets`, `semgrep` eivät olleet PATHissa); ei PASS-väitettä.

Kanoninen regression komento:

`HERMES_PYTHON=/opt/data/cache/glh-r1-20261009-venv/bin/python scripts/run_tests.sh tests/hermes_cli/test_kanban*.py tests/gateway/test_kanban*.py tests/plugins/test_kanban*.py tests/tools/test_kanban*.py tests/agent/test_kanban*.py tests/tui_gateway/test_kanban*.py -q --tb=short -p no:cacheprovider`

## Flake, pilot ja rollback

- Historiallinen `test_kanban_wake_acceptance.py` first-attempt 300 s timeout säilyy `FLAKY`-tilassa; sitä ei nimetä clean first-passiksi. Current exact-SHA full suite läpäisi.
- Synthetic pilot käytti disposable SQLite-kantaa, temporary worktree -polkuja ja synteettistä aliprosessia; PID/run/terminal state luettiin takaisin.
- Live Gateway: `NOT RUN` / ei aktivoitu.
- Production board: `NOT RUN` / ei käytetty.
- Rollback on branch/commit-eristys: lifecycle pysyy opt-ininä, eikä branchia aktivoida ennen erillistä hyväksyntää.

## Ulkoiset report/result-hashit

Pre-evidence snapshot, jonka sisältö nimeää code SHA:n ja tämän evidence-itseviittauksen rajan:

- `/opt/data/logs/glh-r3-builder-20261009.report.md`: `06e411b8cbd8d6b1f8992ba793f3e9d7fbf205ff1dd1fbd2fc8e074a902555b5`.
- `/opt/data/logs/glh-r3-builder-20261009.result.md`: `61ce290667e3d4bff71ced733475dbc210d106d8fd13235b449a6962934b335f`.

## No-live- ja scope-attestointi

- Ei live Gatewayn käynnistystä, pysäytystä, aktivointia tai konfiguraatiomuutosta.
- Ei tuotantoboardia tai production-board-testejä.
- Ei mergeä, rebasea eikä force-pushia.
- Ei origin-pushia tai origin-URL:n muutosta.
- Ei S123/S124-muutosta.
- Ei globaalia migraatiota/taulua tai `work_packages`-taulua.
- Ei Builderin omaa Reviewer R3 -katselmusta eikä Reviewer-dispatchia.
- Ei Gate 2 -hyväksyntää eikä Gate 2 -valmiusväitettä.

R3 CORRECTIONS COMPLETE OR PARTIALLY BLOCKED — AWAITING INDEPENDENT REVIEWER R3

# Gateway/Kanban Lifecycle Hardening R1 — validointitulokset

Tila: `IMPLEMENTED_VALIDATED_AWAITING_INDEPENDENT_GATE2_R2`

Gate 2 on edelleen avoin. Tämä Builder-evidenssi ei hyväksy Gate 2:ta, sulje työtä eikä valtuuta mergeä.

Session: `@session:theseus-builder/20261009_014800_8cd02d`

## Identiteetti ja julkaisureadback

- Alkuperäinen virheellinen candidate: `80cc81e85a6ded0fc1835ce22d8db811b929eb93`
- Parent baseline: `fef0e16fe19b79ded929209f87c7434270b03825`
- R1-koodi-SHA: `0c8c82f94d4df4bfadad105b999133bddbbed11e`
- Paikallinen branch: `fix/theseus-gateway-kanban-lifecycle-r1`
- Julkaisukohde: `git@github.com:tikauppi/hermes-agent.git`
- Forkin code-SHA-readback: `0c8c82f94d4df4bfadad105b999133bddbbed11e`
- Paikallinen/fork-koodi-SHA-yhtäsuuruus: PASS
- Upstream `origin` säilyi muuttumattomana: `https://github.com/NousResearch/hermes-agent.git`
- Alkuperäisen katselmuksen SHA-256: `dbb5e93d346aeb8367074b1a8f502e5e23c537a699920f250482ba5aca642aa8`

Koodicommit julkaistiin ilman forcea vasta sen jälkeen, kun fork-haaran todettiin puuttuvan. Forkin `main`-readback oli valtuutuksen mukainen `3b0dc776b6602b0dd05429d7842bb143d73434b7`.

## Muutosraja

Koodicommitin muuttamat polut:

1. `execution-context.md`
2. `gateway/kanban_watchers.py`
3. `hermes_cli/kanban.py`
4. `hermes_cli/kanban_db.py`
5. `hermes_cli/kanban_db_dispatch.py`
6. `hermes_cli/kanban_parser.py`
7. `hermes_cli/kanban_theseus_lifecycle.py`
8. `tests/hermes_cli/test_kanban_theseus_lifecycle.py`

Evidenssicommitin sallittu ja ainoa sisältöpolku on tämä tiedosto:
`planning/gateway-kanban-lifecycle-hardening/validation-results.md`.

Ei globaalia skeemamigraatiota, uutta taulua, tuotantoboardia, Gateway-aktivointia, profiili-/desired-state-muutosta tai S123/S124-muutosta.

## F-01–F-09 disposition

| Havainto | Builder-disposition | Evidenssi |
|---|---|---|
| F-01 | CORRECTED / VALIDATED | Native claim/unblock/promote ei ohita hyväksyntää; luotettu aika; receipt/decision sidotaan ja kulutetaan täsmärunille; expiry/replay torjutaan; fresh approval onnistuu. |
| F-02 | CORRECTED / VALIDATED | Builder-taskin vakaa idempotenssiavain ja atominen write transaction; concurrent create tuottaa yhden durable identityn; ei migraatiota. |
| F-03 | CORRECTED / VALIDATED | Native completion/request-review/request-changes ja Reviewer/Investigator-terminalointi päivittävät lifecycle/run/artifact-hashit täsmärunille. |
| F-04 | CORRECTED / VALIDATED | STOP on yksi fence-transaktio; RESUME vaatii Architect-roolin, täsmä-STOP-päätöksen ja todellisen Git worktree/branch/HEAD/baseline-identiteetin; replay torjutaan. |
| F-05 | CORRECTED / VALIDATED | Candidate-, rooli-, authorization-, worktree/branch-uniikkius- ja non-concurrency-politiikat enforceataan create- ja dispatch-preflight-polulla. |
| F-06 | CORRECTED / VALIDATED | Traversal, symlinkit ja replacement/TOCTOU torjutaan descriptor-relative/O_NOFOLLOW/exclusive-tekniikoilla; hashit sidotaan terminaaliruniin. |
| F-07 | CORRECTED / VALIDATED | Designated dispatcher-host tarkistetaan todellisessa soveltuvassa Gateway watcher -polussa; legacy/non-opt-in säilyy. |
| F-08 | CORRECTED / VALIDATED | Positiivinen PID CAS-sidotaan täsmä task/run/claimiin; bind failure ei ole success; vain varmennettu uusi child voidaan terminoida. |
| F-09 | CORRECTED / VALIDATED | Dry-run on havainnoiva ja jättää task/run/event-kannan byte-for-byte muuttumattomaksi. |

## TDD RED → GREEN

Kohdennettu komentomuoto:

`HERMES_PYTHON=/opt/data/cache/glh-r1-20261009-venv/bin/python scripts/run_tests.sh tests/hermes_cli/test_kanban_theseus_lifecycle.py -k '<selector>' -x -vv --tb=short -p no:cacheprovider`

Seuraaville käyttäytymisille kirjattiin RED exit 1 ennen tuotantokorjausta ja GREEN exit 0 korjauksen jälkeen:

- native approval bypass claim/unblock/promote
- expiry, old-time replay, distinct fresh approval ja caller-clock removal
- concurrent stable Builder identity
- native completion/request-review/request-changes ja terminaalihashit
- STOP-transaction/fencing sekä forged/mismatched RESUME/Git identity
- role/candidate/worktree/branch collision ja non-concurrency
- traversal/symlink/ancestor-symlink/replacement/TOCTOU
- missing/zero PID, bind failure, verified-child cleanup ja unverified-PID no-kill
- byte-for-byte non-mutating dry-run
- actual Gateway host-policy enforcement
- typed CLI lifecycle diagnostics
- legacy-dispatchin opt-in PID-binding-regressio

## Phase A — hyväksytty dependency-remediation

### Asennus

Komento:

`uv pip install --python /opt/data/cache/glh-r1-20261009-venv/bin/python 'aiohttp==3.14.3'`

Exit: `0`

Tulokset:

- Python: `3.13.5`
- Ympäristö: `/opt/data/cache/glh-r1-20261009-venv`
- Resolver: 9 pakettia
- Asennetut: `aiohttp==3.14.3`, `aiohappyeyeballs==2.7.1`, `aiosignal==1.4.0`, `frozenlist==1.8.0`, `multidict==6.9.1`, `propcache==0.5.4`, `yarl==1.25.1`
- Normaali komento hyväksyttiin scannerissa; päätöstä ei ohitettu, vaimennettu tai kierretty.

Provenienssireadback:

`uv pip show --python /opt/data/cache/glh-r1-20261009-venv/bin/python aiohttp`

Exit: `0`; versio `3.14.3`; sijainti `/opt/data/cache/glh-r1-20261009-venv/lib/python3.13/site-packages`.

## Testit koodi-SHA:lla 0c8c82f94d4df4bfadad105b999133bddbbed11e

### Aiemmin BLOCKED-kohteet

Komento:

`HERMES_PYTHON=/opt/data/cache/glh-r1-20261009-venv/bin/python scripts/run_tests.sh tests/gateway/test_kanban_wake_scope.py tests/gateway/test_kanban_wake_acceptance.py -q --tb=short -p no:cacheprovider`

Exit: `0`

Tulos: `12 passed, 0 failed` kahdessa tiedostossa, 2.0 s. Aiempi aiohttp-environment blocker on poistunut.

### Affected Kanban/Gateway regression suite

Komento:

`HERMES_PYTHON=/opt/data/cache/glh-r1-20261009-venv/bin/python scripts/run_tests.sh tests/hermes_cli/test_kanban*.py tests/gateway/test_kanban*.py tests/plugins/test_kanban*.py tests/tools/test_kanban*.py tests/agent/test_kanban*.py tests/tui_gateway/test_kanban*.py -q --tb=short -p no:cacheprovider`

Exit: `0`

Tulos: `584 passed, 0 failed, 3 skipped`, 83 tiedostoa, 304.5 s. Kolme skip-tapausta ovat Windows-only ja merkitään SKIP, ei PASS.

Retained flake: `tests/gateway/test_kanban_wake_acceptance.py` ylitti 300 sekunnin tiedostokohtaisen aikarajan ensimmäisellä yrityksellä kahden testipisteen jälkeen. Kanonisen runnerin yksi puhdas retry läpäisi kaikki kolme testiä 0.98 sekunnissa. Runnerin lopullinen exit oli 0, mutta ensimmäinen timeout säilytetään näkyvästi FLAKY-evidenssinä.

### F-01–F-09 / GLH focused suite

Komento:

`HERMES_PYTHON=/opt/data/cache/glh-r1-20261009-venv/bin/python scripts/run_tests.sh tests/hermes_cli/test_kanban_theseus_lifecycle.py -q --tb=short -p no:cacheprovider`

Exit: `0`

Tulos: `34 passed, 0 failed`, 3.7 s.

### Muut koodivalidoinnit

- Ruff changed Python paths: exit `0`, `All checks passed!`
- `git diff --check 80cc81e85a6ded0fc1835ce22d8db811b929eb93..0c8c82f94d4df4bfadad105b999133bddbbed11e`: exit `0`
- Kolmannen osapuolen scoped secret scanner: `NOT AVAILABLE`; sitä ei merkitä PASSiksi.
- Rajattu regex-tarkistus muuttuneille Python-poluille: 0 credential-assignment-, `shell=True`-, `eval/exec`- tai pickle-load-osumaa.
- Salaisuuksia, tunnuksia tai avainsisältöä ei tallennettu evidenssiin.

## GLH-01–GLH-12

| GLH | Tila | Todennus |
|---|---|---|
| GLH-01 | PASS | Vakaa work-package task identity ja uusi exact run identity. |
| GLH-02 | PASS | Täsmällinen Architect STOP/decision RESUME authority sekä actual Git identity. |
| GLH-03 | PASS | Approval gate, expiry, non-replay ja fresh approval. |
| GLH-04 | PASS | Crashed run terminalisoidaan eikä sitä duplikoida hiljaisesti. |
| GLH-05 | PASS | Retry tarvitsee uuden authorityn ja tuottaa uuden runin. |
| GLH-06 | PASS | Concurrent dispatch ticks tuottaa yhden runin. |
| GLH-07 | PASS | Reviewer/Investigator linked-role isolation ja erilliset worktreet. |
| GLH-08 | PASS | Erilliset artefaktit, final hashit, exclusive manifest ja collision/TOCTOU-suojat. |
| GLH-09 | PASS | Dispatcher policy on opt-in; dry-run/policy validation on non-mutating; legacy pass-through säilyy. |
| GLH-10 | PASS | STOP voittaa late heartbeat/recovery -kilpailun. |
| GLH-11 | PASS | STOP payload redaction. |
| GLH-12 | PASS | Typed no-spawn diagnostics erottelevat syyt ja näkyvät lifecycle CLI readbackissa. |

## Synthetic pilot ja rollback-evidenssi

- Synthetic pilot: PASS. `test_isolated_pilot_uses_synthetic_subprocess_and_run_readback` käytti disposable SQLite-kantaa, väliaikaisia worktree-polkuja ja synteettistä aliprosessia; PID/run-binding ja terminaalirun luettiin takaisin.
- Rollback/opt-out: GLH-09 sekä byte-for-byte dry-run todentavat non-mutating opt-in/legacy-polun. STOP/recovery-testit todentavat fenced DB-state readbackin.
- Live Gateway rollback: `NOT RUN`, koska Gatewayn käynnistys sekä desired-state/profiilimuutos olivat rajauksen ulkopuolella.
- Tuotantoboardi: `NOT RUN` / ei käytetty.

## Ulkoiset Builder-artefaktit ennen evidence-commitia

Nämä SHA-256-arvot ovat ulkoisten raporttien Phase A -tilanne juuri ennen tämän evidence-tiedoston luontia. Ulkoiset raportit päivitetään evidence-pushin jälkeen, jolloin niiden lopulliset hashit muuttuvat ja raportoidaan handoffissa.

- `/opt/data/logs/glh-r1-builder-20261009.report.md`: `d6d8187978041f00b10a9951544cbc7f208b081420de62d1aacf3c085950e9f3`
- `/opt/data/logs/glh-r1-builder-20261009.result.md`: `f7070724176abc51415331850d77def1dc7d5a93165ea64518dc0e53c904f767`

## No-live/scope-attestointi

- Ei oikeaa Gateway- tai rooliprofiiliprosessia.
- Ei production boardia.
- Ei desired-state- tai profiilikonfiguraation muutosta.
- Ei S123/S124-muutosta.
- Ei globaalia taulua tai skeemamigraatiota.
- Ei upstream-originin muutosta.
- Ei mergeä, rebasea tai force-pushia.
- Ei Reviewerin käynnistystä tai uudelleenkäyttöä.
- Gate 2: `PENDING INDEPENDENT REVIEWER R2`.

Builderin tekninen validointi ei ole Arkkitehdin hyväksyntä.

---

# R3 corrective validation — 2026-10-09

Tila: `PARTIALLY_BLOCKED_AWAITING_INDEPENDENT_REVIEWER_R3`

Session: `@session:theseus-builder/20261009_034127_37677e`

R3 code SHA: `3cfc86168ba6560a42fa0696032e150fc231e8c8`

Fork code readback: `3cfc86168ba6560a42fa0696032e150fc231e8c8` — MATCH

Evidence SHA: tämän R3-osion ja `implementation-results.md`:n sisältävän evidence/docs-commitin SHA; exact arvo todennetaan vasta commitin muodostamisen jälkeen remote-readbackissa, koska commit ei voi sisältää omaa tulevaa SHA:taan.

R2 report SHA-256: `66f4ab74bf587a5970ddd1e120167df9c62637cb3fbb1a89085467d755ba1fdf` — MATCH

## R3 disposition

| R3 | Tila | Validointi |
|---|---|---|
| R3-01 | `BLOCKED — ARCHITECT DECISION REQUIRED` | Puuttuva trust-anchor-päätös on luotettu server-side authenticated approval/decision principal + authoritative receipt issuer/store. Caller-controlled `actor`, `approval_ref`, `approved_at` tai `decision_ref` ei kelpaa. Sopivaa olemassa olevaa Hermes-lähdettä ei löytynyt, joten uutta auktoriteettia tai julkista sopimusta ei keksitty. |
| R3-02 | IMPLEMENTED / VALIDATED | Dispatcher-only native claim grant, role/profile/read-only capability -tarkistus, atomisen claimin active-peer-hylkäys sekä schema/native tool allowlist. Wrong capability, direct native bypass ja concurrent peer testattu. |
| R3-03 | IMPLEMENTED / VALIDATED | Koko directory chain device/inode -sidonta prepare→finalize, descriptor-relative `O_NOFOLLOW`, hardlink+ancestor replacement -hylkäys, manifest containment ja failure cleanup. |
| R3-04 | IMPLEMENTED / VALIDATED | Designated `theseus-builder` -profiili tarkistetaan lifecycle preflightissa ja native claimissa. Wrong/missing profile, standalone dispatch ja direct bypass testattu; legacy pass-through säilyy. |
| R3-05 | IMPLEMENTED / VALIDATED | Bind-False ja bind-exception käsittelevät vain identity-verified uuden childin; unverified/PID-reuse no-kill sekä retry/run-integrity testattu. |
| R3-06 | IMPLEMENTED / VALIDATED | Dry-run ohittaa reclaim/orphan/crash/timeout/promotion/recompute-ready/WAL checkpoint -kirjoitukset; täydellinen DB dump + artifact tree pysyy identtisenä ja repeatable reclaimable/promotable-fixtureillä. |

R3-01:n vuoksi Builder ei väitä Gate 2 -valmiutta.

## TDD RED → GREEN

- R3-02 testit `test_role_native_claim_rejects_wrong_capability_and_active_peer` ja `test_role_worker_capabilities_are_enforced_at_schema_and_native_dispatch`: RED exit `1`, GREEN exit `0`.
- R3-03 testit `test_artifacts_reject_prepare_finalize_ancestor_replacement_with_hardlinks` ja `test_artifact_manifest_write_failure_removes_partial_file`: RED exit `1`, GREEN exit `0`.
- R3-04 `test_all_dispatch_and_native_claim_routes_reject_non_designated_host`: RED exit `1`, GREEN exit `0`.
- R3-05 `test_pid_bind_exception_terminates_verified_child_and_preserves_retry_integrity`: RED exit `1`, GREEN exit `0`.
- R3-06 `test_lifecycle_dry_run_is_byte_for_byte_non_mutating`: RED exit `1`, GREEN exit `0`.

## Exact code SHA -ajot

1. Focused R3/GLH:
   - Komento: `HERMES_PYTHON=/opt/data/cache/glh-r1-20261009-venv/bin/python scripts/run_tests.sh tests/hermes_cli/test_kanban_theseus_lifecycle.py -q --tb=short -p no:cacheprovider`
   - Exit `0`; `42 passed, 0 failed`.
2. Affected Kanban/Gateway:
   - Komento: `HERMES_PYTHON=/opt/data/cache/glh-r1-20261009-venv/bin/python scripts/run_tests.sh tests/hermes_cli/test_kanban*.py tests/gateway/test_kanban*.py tests/plugins/test_kanban*.py tests/tools/test_kanban*.py tests/agent/test_kanban*.py tests/tui_gateway/test_kanban*.py -q --tb=short -p no:cacheprovider`
   - Exit `0`; `592 passed, 0 failed, 3 skipped`, 83 tiedostoa.
   - Kolme skip-tapausta ovat Windows-only; `SKIPPED`, ei PASS.
3. Isolated synthetic pilot:
   - Selector `isolated_pilot_uses_synthetic_subprocess_and_run_readback`.
   - Exit `0`; `1 passed`.
4. Ruff changed Python paths `--no-cache`: exit `0`; `All checks passed!`.
5. `git diff --check 03ddc791f935f4f4d9534f90df1bb9481dc7369a..3cfc86168ba6560a42fa0696032e150fc231e8c8`: exit `0`.
6. Third-party secret scanner: `NOT AVAILABLE` (`gitleaks`, `trufflehog`, `detect-secrets`, `semgrep` puuttuivat); ei PASS-väitettä.

## Flake/skips/no-live

- Aiempi ensimmäisen yrityksen 300 s `test_kanban_wake_acceptance.py` timeout säilyy `FLAKY`-tilassa; current exact-SHA full suite läpäisi.
- Kolme Windows-only-testiä: `SKIPPED`, ei PASS.
- Live Gateway ja live rollback: `NOT RUN` rajauksen vuoksi.
- Production board: `NOT RUN` / ei käytetty.
- Synthetic pilot käytti vain disposable SQLitea, temporary worktree -polkuja ja synteettistä aliprosessia.

## Report/result ja scope

- Builder report SHA-256: `06e411b8cbd8d6b1f8992ba793f3e9d7fbf205ff1dd1fbd2fc8e074a902555b5`.
- Builder result SHA-256: `61ce290667e3d4bff71ced733475dbc210d106d8fd13235b449a6962934b335f`.
- Origin säilyi `https://github.com/NousResearch/hermes-agent.git` eikä originia pushattu.
- Ei S123/S124-, migraatio-, taulu-, `work_packages`-, desired-state-, profiili- tai production-board-muutosta.
- Ei mergeä, rebasea, force-pushia, live-aktivointia, Reviewer-dispatchia tai Gate 2 -päätöstä.

R3 CORRECTIONS COMPLETE OR PARTIALLY BLOCKED — AWAITING INDEPENDENT REVIEWER R3

---

# R4 corrective validation — 2026-10-09

Tila: `R4_CORRECTIONS_COMPLETE_OR_PARTIALLY_BLOCKED_AWAITING_INDEPENDENT_REVIEWER_R4`

Session: `@session:theseus-builder/20261009_043005_0f4e02`

- Base/evidence: `93d90f11c900c7a70597056dac61965c4b4d7108`.
- R3 code: `3cfc86168ba6560a42fa0696032e150fc231e8c8`.
- R4 code SHA: `6bcaa640a5b0df3fedc309429ec494e628d10f65`.
- Fork code readback: MATCH.
- Evidence/docs SHA: tämän R4-osion ja päivitetyn `implementation-results.md`:n sisältävän seuraavan commitin SHA; exact arvo varmennetaan pushin jälkeisessä remote-readbackissa.

## R4-matriisi

| Kohta | Tila | Validointi |
|---|---|---|
| R4-01 | `PARTIALLY BLOCKED — ARCHITECT DECISION REQUIRED` | Eristetty verifier validoi canonical signed evidence -skeeman ja sitoo issuer/key-id/principal/role/type/action/scope/package/task/run/STOP/code SHA/issued/expiry/nonce-arvot expected-kontekstiin. Negatiiviset forged/missing/expired/wrong principal/action/task/run/SHA/replay/revoked/malformed sekä concurrent one-time consumption PASS. Oikea issuer, production trust store ja lifecycle-kirjoituksen atominen integration boundary puuttuvat tarkoituksella ja vaativat Arkkitehdin päätöksen. |
| R4-02 | PASS | ContextVar self-grant poistettu. Direct native claim, dispatcher route, wrong/missing profile, role policy ja peer concurrency harjoitettiin. Gateway boot ja standalone/Gateway-yhteinen `dispatch_once`-polku säilyivät. R3-04 ei regressioitunut. |
| R4-03 | PASS Linux/POSIX; Windows `SKIPPED/NOT RUN` | Ancestor replacement, symlink, hardlink collision, final visibility, partial fsync failure, stale-temp recovery, final no-replace ja unsupported-platform fail-closed PASS. Manifest näkyy final-nimellä vasta täydellisen write+file-fsyncin jälkeen ja directory fsync suoritetaan publication jälkeen. |
| R4-05 | PASS Linux/POSIX | pidfd birth-handle käyttää exact process identityä. Numeric PID signaalipolku hylättiin testissä. Bind False/exception, unverifiable cleanup, manual fence, active run/claim preservation ja retry prevention PASS. |
| R3-06 | PASS | Kaksi dry-run-tickiä säilyttää DB dumpin ja artifact tree -snapshotin byte-for-byte. |

## Authority contract

- `planning/gateway-kanban-lifecycle-hardening/authority-contract.md`.
- SHA-256 `e4dac75c311235901336d14a37cecb0cb527a23c433fdbdb339a29bd0abfa815`.
- Ei oikeaa issueria, production signing keytä, salaisuutta, live-palvelua eikä auto-self-issuancea.

## Exact code SHA -komennot ja exitit

1. Focused R4:
   - `HERMES_PYTHON=/opt/data/cache/glh-r1-20261009-venv/bin/python scripts/run_tests.sh tests/hermes_cli/test_kanban_authority_verifier.py tests/hermes_cli/test_kanban_theseus_lifecycle.py -q --tb=short -p no:cacheprovider`
   - exit `0`; `60 passed, 0 failed`.
2. Affected Kanban/Gateway:
   - `HERMES_PYTHON=/opt/data/cache/glh-r1-20261009-venv/bin/python scripts/run_tests.sh tests/hermes_cli/test_kanban*.py tests/gateway/test_kanban*.py tests/plugins/test_kanban*.py tests/tools/test_kanban*.py tests/agent/test_kanban*.py tests/tui_gateway/test_kanban*.py -q --tb=short -p no:cacheprovider`
   - exit `0`; 84 tiedostoa; `610 passed, 0 failed, 3 skipped`.
   - Kolme Windows-only-testiä: `SKIPPED`, eivät PASS.
3. Synthetic pilot:
   - sama canonical runner, selector `isolated_pilot_uses_synthetic_subprocess_and_run_readback`.
   - exit `0`; `1 passed`.
4. Ruff:
   - changed Python paths, `--no-cache`.
   - exit `0`; `All checks passed!`.
5. Diff:
   - `git diff --check 93d90f11c900c7a70597056dac61965c4b4d7108..6bcaa640a5b0df3fedc309429ec494e628d10f65`.
   - exit `0`.
6. Secret scanner availability:
   - `gitleaks`, `trufflehog`, `detect-secrets`, `semgrep`: `NOT AVAILABLE`.
   - Ei scanner-PASS-väitettä.

## Synthetic evidence

- Synteettinen Ed25519 private key generoidaan vain testissä eikä sitä tallenneta tuotantoasetukseen, repoon tai worker-ympäristöön.
- Verifierin positiivinen fixture käyttää synteettisiä issuer-, key-id-, principal-, package-, task-, run-, STOP- ja nonce-arvoja.
- Concurrent consume-once -testissä täsmälleen 1/16 yrityksestä hyväksyttiin ja 15/16 hylättiin replayna.
- Synthetic lifecycle pilot käytti disposable SQLite-kantaa, temporary worktree -polkuja ja synteettistä aliprosessia; live Gatewayta tai production boardia ei käytetty.

## Flake, skips, blockerit ja report/result

- Historiallinen `tests/gateway/test_kanban_wake_acceptance.py` 300 s first-attempt timeout säilyy `FLAKY`; current R4 exact-SHA run: 3 PASS.
- Windows-only: 3 `SKIPPED`; Windows artifact runtime `NOT RUN` tällä Linux-hostilla. Unsupported-platform-politiikka testattiin fail-closed pure boundaryna ilman host-OS:n feikkausta.
- R4-01 production issuer/integration: `PARTIALLY BLOCKED — ARCHITECT DECISION REQUIRED`.
- Muut R4-02/03/05: IMPLEMENTED / VALIDATED.
- Builder report SHA-256: `85b1cd5fb6e114806d026cb8842126c75587f2ba8a3d0ae50376d04ee85676a5`.
- Builder result SHA-256: `9f0110c2e746a17a47b608cdfe0f01dd99f09d05d37d7885b7b01b065b7044ab`.
- R3 reviewer report SHA-256: `d0af61340aeeb3795f60df823612d9a0516681ad0ff4dc8b031aab4eb2bb6e7b` — MATCH.
- R3 reviewer result SHA-256: `696a80d842166db2a4d43bf59445fa669222fa27e39df6924f1155131eaebffb` — MATCH.

## No-live, rollback ja origin

- Live Gateway: `NOT RUN`; ei käynnistetty, pysäytetty tai aktivoitu.
- Production board: `NOT RUN`; ei käytetty.
- Live rollback: `NOT RUN`; rollback on branch/commit-eristys ja opt-in lifecycle.
- Origin säilyi `https://github.com/NousResearch/hermes-agent.git` eikä originia pushattu.
- Fork säilyi `git@github.com:tikauppi/hermes-agent.git`.
- Ei S123/S124-, migraatio-, taulu-, `work_packages`-, merge-, rebase-, force-push-, Gate 2- tai Reviewer-dispatch-muutosta.

Builder pysähtyy riippumattomaan Reviewer R4 -katselmukseen.

R4 CORRECTIONS COMPLETE OR PARTIALLY BLOCKED — AWAITING INDEPENDENT REVIEWER R4

---

# R5 corrective validation — 2026-10-09

Tila: `R5 TECHNICALLY VALIDATED — PRODUCTION AUTHORITY BLOCKED`

Session: `@session:theseus-builder/20261009_051058_6d682d`

- Base/evidence: `44a7c25d5709798bbae567e9743a004089dbda1f`.
- R4 code: `6bcaa640a5b0df3fedc309429ec494e628d10f65`.
- R5 code SHA: `dcb83f318959191f2b3bc7492d7802f2dbcf7f93`.
- Fork code readback: MATCH.
- Evidence/docs SHA: tämän R5-osion ja päivitetyn `implementation-results.md`:n sisältävä evidence commit. Exact SHA varmennetaan pushin jälkeisessä remote-readbackissa, koska commit ei voi sisältää omaa tulevaa SHA:taan.

## R5-validointimatriisi

| Kohta | Tila | Exact clean code SHA -evidenssi |
|---|---|---|
| R5-DEC-01 / R5-01 | IMPLEMENTED + SYNTHETICALLY TESTED; production BLOCKED | Public production API, CLI ja Gateway slash -polku fail-closed; private test-only injection harjoittaa common same-transaction mutation boundarya. Signed binding, audit, atomic receipt+transition, replay ja concurrency PASS. |
| R5-02 | PASS | Genuine JSON int/not-bool, safe range/order, exact expiry boundary, malformed/missing, unknown issuer, unauthorized principal, wrong scope/action/type/target, forged signature, revoked issuer/key/nonce ja replay/concurrency PASS. |
| R4-02 | PASS / preserved | Native/dispatcher claim, role/profile/read-only, active peer, designated host ja legacy regressiot PASS. |
| R4-03 | PASS Linux/POSIX / preserved | Artifact identity, symlink/hardlink/replacement, fsync, no-replace, failure cleanup ja unsupported-boundary regressiot PASS. Windows runtime `NOT RUN`. |
| R4-05 | PASS Linux / preserved | pidfd birth identity, bind failure/exception, manual fence ja retry prevention PASS. |
| R3-06 | PASS / preserved | Byte-for-byte dry-run DB/artifact non-mutation PASS. |

## Exact clean code SHA -komennot ja exitit

Kaikki kanoniset tulokset ajettiin puhtaasta `dcb83f318959191f2b3bc7492d7802f2dbcf7f93`-checkoutista.

1. Focused R5 security/lifecycle:
   - Komento: `HERMES_PYTHON=/opt/data/cache/glh-r1-20261009-venv/bin/python scripts/run_tests.sh tests/hermes_cli/test_kanban_authority_verifier.py tests/hermes_cli/test_kanban_theseus_lifecycle.py -q --tb=short -p no:cacheprovider`
   - Exit `0`; 2 tiedostoa; `80 passed, 0 failed`; verifier 26, lifecycle 54; 5.4 s.
2. Affected GLH/Kanban/Gateway regressiot:
   - Komento: `HERMES_PYTHON=/opt/data/cache/glh-r1-20261009-venv/bin/python scripts/run_tests.sh tests/hermes_cli/test_kanban*.py tests/gateway/test_kanban*.py tests/plugins/test_kanban*.py tests/tools/test_kanban*.py tests/agent/test_kanban*.py tests/tui_gateway/test_kanban*.py -q --tb=short -p no:cacheprovider`
   - Exit `0`; 84 tiedostoa; `630 passed, 0 failed, 3 skipped`; 38.9 s.
   - Kolme skip-tapausta ovat Windows-only: `SKIPPED`, eivät PASS.
3. Synthetic pilot:
   - Sama canonical runner; selector `isolated_pilot_uses_synthetic_subprocess_and_run_readback`.
   - Exit `0`; `1 passed`; 1.3 s.
4. Ruff muuttuneille Python-poluille:
   - `/opt/data/cache/glh-r1-20261009-venv/bin/python -m ruff check --no-cache hermes_cli/kanban.py hermes_cli/kanban_authority_verifier.py hermes_cli/kanban_parser.py hermes_cli/kanban_theseus_lifecycle.py tests/hermes_cli/test_kanban_authority_verifier.py tests/hermes_cli/test_kanban_theseus_lifecycle.py`
   - Exit `0`; `All checks passed!`.
5. Diff:
   - `git diff --check 44a7c25d5709798bbae567e9743a004089dbda1f..dcb83f318959191f2b3bc7492d7802f2dbcf7f93`
   - Exit `0`.

## TDD RED → GREEN

R5-korjaukset toteutettiin käyttäytymiskohtaisesti testit ensin. Tallennetut RED-exitit sisälsivät unknown principal -authorizationin, caller-controlled Investigator-refin, direct protected phase transition -ohituksen ja julkisen production entrypointin validin synthetic configuration -ohituksen. Public synthetic -tapauksen RED: exit `1`, `DID NOT RAISE ValueError`; GREEN sisältyy clean-SHA focused-ajon 80 PASSiin. Testejä tai kriteereitä ei lievennetty.

## Synthetic issuer -raja

Synthetic private key luodaan vain testiprosessissa disposable fixtureksi. Private test-only wrapperit välittävät verifierin mutation boundarylle. Public production lifecycle -entrypointit eivät hyväksy testikonfiguraatiota; CLI ja Gateway eivät voi välittää sitä. Synthetic pilot ei ole production authority success.

Production status:

`BLOCKED — TRUSTED AUTHORITY NOT CONFIGURED`

## Authority contract ja hashit

- `authority-contract.md` SHA-256: `00e4af41d4493155c82c5278bb48482e190905a21108e6bacd1531aacbb92b92`.
- R5 Builder report `/opt/data/logs/glh-r5-builder-20261009.report.md` SHA-256: `7c933bc445f430d5097c6b79cd743dacf8b7341e35a74a100d0b8427450c2bd8`.
- R5 Builder result `/opt/data/logs/glh-r5-builder-20261009.result.md` SHA-256: `32430d8154cd06f7df23ea90c75804ec9e193a1868e9f4c6bb160cf952386be3`.
- Reviewer R4 report SHA-256: `0be26f1125deac07af5b563ffdcd010b33bec012f96685217e1b5b42bffacedc` — MATCH.
- Reviewer R4 result SHA-256: `e5ed1470a7906a3e4afaac826f772d7ecc9fae9b547d5a6a2e5a7016640a3b7d` — MATCH.

## Scannerit

- `gitleaks`: `NOT AVAILABLE`.
- `trufflehog`: `NOT AVAILABLE`.
- `detect-secrets`: `NOT AVAILABLE`.
- `semgrep`: `NOT AVAILABLE`.
- Rajattu credential/private-key/dangerous-Python-regexhaku muuttuneesta diffistä: 0 osumaa.

Scannerien puuttumista ei merkitä PASSiksi.

## FLAKY, skips ja no-live

- Historiallinen `tests/gateway/test_kanban_wake_acceptance.py` 300 s first-attempt timeout säilyy `FLAKY`. R5:n pre-commit-ajossa first attempt timeouttasi ja canonical retry tuotti `3 passed`; exact clean-SHA -ajossa sama tiedosto läpäisi ensimmäisellä yrityksellä (`3 passed`, 3.8 s). Historiaa ei pyyhitty.
- Windows-only: 3 `SKIPPED`; Windows artifact runtime `NOT RUN` Linux-hostilla.
- Live Gateway: `NOT RUN`; ei käynnistetty tai aktivoitu.
- Production board ja live rollback: `NOT RUN`.
- Production issuer/signing key/trust store/revocation service: `NOT CREATED / NOT USED`.

## Publication ja muuttumattomuus

- Code commit pushattiin forkille normaalisti ilman forcea.
- Fork code SHA readback: `dcb83f318959191f2b3bc7492d7802f2dbcf7f93` — MATCH.
- Origin säilyi `https://github.com/NousResearch/hermes-agent.git` eikä originia pushattu.
- Fork säilyi `git@github.com:tikauppi/hermes-agent.git`.
- Evidence commit muuttaa vain `implementation-results.md`- ja `validation-results.md`-tiedostoja; tämä varmennetaan staged scope-, remote scope- ja blob-hash-readbackissa.
- Ei S123/S124-, schema/table/migration-, merge-, rebase-, force-push-, Gate 2- tai Reviewer R5 -dispatch-muutosta.

Builderin tekninen validointi ei ole oma katselmus eikä Arkkitehdin hyväksyntä.

R5 TECHNICALLY VALIDATED — PRODUCTION AUTHORITY BLOCKED — AWAITING INDEPENDENT REVIEWER R5

---

# R6 corrective validation — 2026-10-09

Tila: `R6 TECHNICALLY VALIDATED — PRODUCTION AUTHORITY/DEPLOYMENT BLOCKED — AWAITING INDEPENDENT REVIEWER R6`

Session: `@session:theseus-builder/20261009_061621_1e0e6e`

- Authorization lock / parent: `8e6aacc2c591da7d36a6700472129fc35b392eed`.
- Tested R6 code SHA: `55fe9171cee560a632ca1948c9f7593200a15c60`.
- Fork code readback: `55fe9171cee560a632ca1948c9f7593200a15c60` — MATCH.
- Evidence/docs SHA: tämän kolmen tiedoston evidence-commitin SHA; exact local/live arvo varmennetaan pushin jälkeen.

## R6-validointimatriisi

| Kohta | Tila | Exact code SHA -evidenssi |
|---|---|---|
| R6-01 | PASS scoped containment | Shipping-moduulissa ei ole `SyntheticAuthorityTestConfiguration`-luokkaa, `_for_test`-mutaatiowrappereita tai caller-injektoitavaa test authority -parametria. Testiharness sijaitsee testipuussa. Production lifecycle, direct Python, CLI ja Gateway bypass -tapaukset fail-closed. Tämä ei ole väite saman prosessin arbitrary Python -eristyksestä. |
| R6-02 | PASS | Reviewer/Investigator direct/native, CLI ja Gateway-reitit harjoitettiin. Julkinen creation hylättiin ennen DB-writea; no-write snapshot säilyi. Sisäisen hyväksytyn polun forced event/audit failure rollbackasi taskin, linkin, metadatan ja eventin. Concurrent/replay/idempotency-rajat säilyivät. |
| R6-03 | PASS | Stored approval testattiin ennen expiry-rajaa, exact boundarylla ja sen jälkeen. `now >= approval_expires_at` hylättiin ennen runia, claim-eventtiä tai persistent transitionia sekä dispatch/preflight- että native claim -kulutuksessa. |
| R4-02 / R3-04 | PASS / preserved | Restricted-role dispatcher/native claim, designated profile/host, read-only capability ja active-peer -rajat säilyivät. |
| R4-03 | PASS Linux/POSIX / preserved | Artifact identity, symlink/hardlink/replacement, fsync/no-replace, cleanup ja unsupported-platform fail-closed -regressiot säilyivät. Windows runtime `NOT RUN`. |
| R4-05 | PASS Linux / preserved | pidfd birth identity, manual retry fence, bind failure/exception ja retry prevention säilyivät. |
| R3-06 | PASS / preserved | Dry-run DB/artifact non-mutation säilyi. |

## Exact clean code SHA -komennot, exitit ja tulokset

Kaikki alla olevat testitulokset ajettiin puhtaasta `55fe9171cee560a632ca1948c9f7593200a15c60`-checkoutista canonical `scripts/run_tests.sh` -runnerilla ja `HERMES_TEST_FILE_RETRIES=0`:lla.

1. Focused authority/lifecycle:
   - Komento: `HERMES_TEST_FILE_RETRIES=0 HERMES_PYTHON=/opt/data/cache/glh-r1-20261009-venv/bin/python scripts/run_tests.sh tests/hermes_cli/test_kanban_authority_verifier.py tests/hermes_cli/test_kanban_theseus_lifecycle.py -q --tb=short -p no:cacheprovider`
   - Exit `0`; `90 passed, 0 failed`.
2. Affected Kanban/Gateway:
   - Komento: `HERMES_TEST_FILE_RETRIES=0 HERMES_PYTHON=/opt/data/cache/glh-r1-20261009-venv/bin/python scripts/run_tests.sh tests/hermes_cli/test_kanban*.py tests/gateway/test_kanban*.py tests/plugins/test_kanban*.py tests/tools/test_kanban*.py tests/agent/test_kanban*.py tests/tui_gateway/test_kanban*.py -q --tb=short -p no:cacheprovider`
   - Exit `0`; 84 tiedostoa; `640 passed, 0 failed, 3 skipped`.
   - Kolme skip-tapausta ovat Windows-only: `SKIPPED`, eivät PASS.
3. Retained R4/R3 invariants:
   - Komento: `HERMES_TEST_FILE_RETRIES=0 HERMES_PYTHON=/opt/data/cache/glh-r1-20261009-venv/bin/python scripts/run_tests.sh tests/hermes_cli/test_kanban_theseus_lifecycle.py -k 'role_native_claim or role_worker_capabilities or all_dispatch_and_native_claim or artifact or pid_bind or spawn_cleanup or lifecycle_dry_run' -q --tb=short -p no:cacheprovider`
   - Exit `0`; `17 passed, 0 failed`.
4. Isolated synthetic pilot:
   - Komento: `HERMES_TEST_FILE_RETRIES=0 HERMES_PYTHON=/opt/data/cache/glh-r1-20261009-venv/bin/python scripts/run_tests.sh tests/hermes_cli/test_kanban_theseus_lifecycle.py -k isolated_pilot_uses_synthetic_subprocess_and_run_readback -q --tb=short -p no:cacheprovider`
   - Exit `0`; `1 passed`.
5. Ruff:
   - Komento: `/opt/data/cache/glh-r1-20261009-venv/bin/python -m ruff check --no-cache hermes_cli/kanban_theseus_lifecycle.py tests/hermes_cli/kanban_lifecycle_authority_harness.py tests/hermes_cli/test_kanban_theseus_lifecycle.py`
   - Exit `0`; `All checks passed!`.
6. Diff:
   - Komento: `git diff --check 8e6aacc2c591da7d36a6700472129fc35b392eed..55fe9171cee560a632ca1948c9f7593200a15c60`
   - Exit `0`.
7. Secret scanner availability:
   - Komento: `command -v gitleaks; command -v trufflehog; command -v detect-secrets; command -v semgrep`.
   - Exit `1`; kaikki neljä `NOT AVAILABLE`; poissaoloa ei merkitä PASSiksi.
   - Rajattu fallback-riskikuviohaku muuttuneista Python-tiedostoista: 0 osumaa.

## Synthetic pilot ja trust boundary

Pilot käytti disposable SQLite-kantaa, temporary worktree -polkuja, testipuussa generoitua disposable Ed25519-avainta ja synteettistä aliprosessia. PID/run/terminal-state luettiin takaisin. Live Gatewayta, production boardia, production issueria, signing keytä tai trust storea ei käytetty.

Testihakemisto ja import containment eivät eristä mielivaltaista Pythonia, jolla on samat prosessi- tai DB-oikeudet. Todellinen raja on trusted process + database rights. R6:n PASS koskee normaalin toimitettavan lifecycle/API/CLI/Gateway-pinnan synteettisen authority capabilityn poistamista ja testatun mutaatiopolun fail-closed-käyttäytymistä.

## FLAKY, platformit ja NOT RUN

- Historiallinen `tests/gateway/test_kanban_wake_acceptance.py` first-attempt 300 s timeout säilyy `FLAKY`; current R6 exact-SHA affected suite läpäisi.
- Windows runtime: `NOT RUN` Linux-hostilla.
- Windows-only: 3 `SKIPPED`, eivät PASS.
- Live Gateway, production board, live deployment ja live rollback: `NOT RUN`.

## Scannerit ja avoimet riskit

- `gitleaks`: `NOT AVAILABLE`.
- `trufflehog`: `NOT AVAILABLE`.
- `detect-secrets`: `NOT AVAILABLE`.
- `semgrep`: `NOT AVAILABLE`.
- Scannerien puuttumista ei merkitä PASSiksi.
- Arbitrary same-process Python ja suora SQLite-write-oikeus ovat edelleen trust boundaryn sisällä; prosessi-/DB-sandboxia ei lisätty.

## Production authority- ja deployment-blockerit

Production authenticated identity, Architect-approved issuer, principal/role authorization, signing-key management, trusted public-key distribution/trust store, authoritative revocation/receipt store, cross-board replay policy, monitoring, retention, incident response, canary ja rollout-päätös puuttuvat. Production approval/decision/resume säilyy fail-closed-tilassa `BLOCKED — TRUSTED AUTHORITY NOT CONFIGURED`. Nämä ovat erillisiä operational/deployment-riippuvuuksia, eivät R6-scopeen piilotettuja toteutuspuutteita.

## Publication- ja scope-attestointi

- R6 code commit muuttaa vain kolmea koodi/testipolkua ja on julkaistu forkille normaalisti ilman forcea.
- Tämä erillinen evidence/docs-commit muuttaa vain `authority-contract.md`, `implementation-results.md` ja `validation-results.md`.
- Ei source/test-lisäcommittia, S123/S124-, schema/table/migration-, domain/API/UI/public-contract-, desired-state-, profile-, production-board- tai production-authority-muutosta.
- Ei mergeä, rebasea, force-pushia, origin-pushia, live-aktivointia, Reviewer R6 -dispatchia, R7-aloitusta tai Gate 2 -päätöstä.

Builderin tekninen validointi ei ole oma katselmus, Gate 2 -hyväksyntä, sprintin sulkeminen tai production activation readiness -väite.

R6 TECHNICALLY VALIDATED — PRODUCTION AUTHORITY/DEPLOYMENT BLOCKED — AWAITING INDEPENDENT REVIEWER R6

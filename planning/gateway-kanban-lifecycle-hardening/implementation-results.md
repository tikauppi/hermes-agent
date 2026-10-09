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

---

# Gateway/Kanban Lifecycle Hardening — R4 implementation results

Tila: `R4_CORRECTIONS_COMPLETE_OR_PARTIALLY_BLOCKED_AWAITING_INDEPENDENT_REVIEWER_R4`

Session: `@session:theseus-builder/20261009_043005_0f4e02`

Tämä osio on Builder-evidenssiä. Se ei ole oma katselmus, Gate 2 -hyväksyntä, merge-lupa eikä live Gateway -aktivointi.

## Commit- ja julkaisuidentiteetti

- R4 base/evidence: `93d90f11c900c7a70597056dac61965c4b4d7108`.
- R3 code: `3cfc86168ba6560a42fa0696032e150fc231e8c8`.
- R4 code SHA: `6bcaa640a5b0df3fedc309429ec494e628d10f65`.
- Branch: `fix/theseus-gateway-kanban-lifecycle-r4`.
- Fork code readback: `6bcaa640a5b0df3fedc309429ec494e628d10f65` — MATCH.
- Evidence/docs SHA on tämän osion sisältävän seuraavan commitin SHA; exact arvo todennetaan commitin jälkeen remote-readbackilla.
- Origin: `https://github.com/NousResearch/hermes-agent.git` — unchanged.
- Fork: `git@github.com:tikauppi/hermes-agent.git` — unchanged.

## R4-01/02/03/05

| Kohta | Tila | Toteutus / rajaus |
|---|---|---|
| R4-01 | `PARTIALLY BLOCKED — ARCHITECT DECISION REQUIRED` | Eristetty Ed25519-verifier ja synteettiset signed fixturet toteutettiin. Signed payload sidotaan expected issuer/key-id/principal/role/type/action/scope/package/task/run/STOP/code-SHA/issued/expiry/nonce-kontekstiin; forged, missing, expired, wrong principal/action/task/run/SHA, replay, revoked, malformed ja concurrent replay hylätään. Oikeaa issueria, production-avainta, trust storea, live-palvelua tai self-issuancea ei toteutettu. Production lifecycle -integraatio jää blokkiin, kunnes Arkkitehti nimeää issuerin, principal-mäppäyksen, trust storen ja atomisen integraatioboundaryn. |
| R4-02 | IMPLEMENTED / VALIDATED | Julkinen ContextVar-grant poistettiin. Kaikki opt-in lifecycle dispatchit claimaavat yhteisen atomisen dispatcher-transaktion kautta; direct native claim ei saa restricted rolea. Role/profile/read-only/active-peer-säännöt tarkistetaan claim-transaktiossa. Gateway ja standalone käyttävät samaa `dispatch_once`-polkua. |
| R4-03 | IMPLEMENTED / VALIDATED | Complete ancestor identity fencing säilyy. Manifest syntyy non-final temp-nimeen, data fsyncataan, final julkaistaan atomisella safe no-replace-hardlinkillä verified run-dir FD:n sisällä, temp poistetaan ja hakemisto fsyncataan. Unsupported platform hylätään ennen polun mutaatiota. |
| R4-05 | IMPLEMENTED / VALIDATED | Linux-spawn capture ottaa pidfd-birth-handlen heti direct-child-varmennuksen jälkeen. Cleanup käyttää pidfd-signaalia eikä PID-numeroa. Unverifiable/surviving child säilyttää `blocked/manual`-tilan sekä aktiivisen run/claim-fencen ja estää dispatch/retryn. |

## Authority contract

- Polku: `planning/gateway-kanban-lifecycle-hardening/authority-contract.md`.
- SHA-256: `e4dac75c311235901336d14a37cecb0cb527a23c433fdbdb339a29bd0abfa815`.
- Sopimus määrittää external issuer authorization-, signing/verification-, workerien ulkopuolisen key storage-, canonical schema-, action/type/scope/target/expiry-, nonce/replay/atomic consumption-, revocation/audit-, fail-closed-, rollout/key rotation -ehdot ja erottaa oikean issuerin R4:n synteettisestä test issuerista.

## TDD RED → GREEN

- Verifierin puuttuva moduuli: RED collection exit `1` → valid signed/replay GREEN.
- Binding/expiry/revocation: RED exit `1` → GREEN; forged/malformed/concurrent replay lisättiin.
- ContextVar self-grant: RED osoitti `_role_dispatch_claim_grant`-symbolin → symboli ja grant poistettiin, dispatch boundary GREEN.
- Manifest visibility: RED havaitsi finalin olemassaolon ennen ensimmäistä writea → temp+fsync+atomic no-replace+dir-fsync GREEN.
- Unverifiable bind: RED palautti taskin `ready`-tilaan → manual fence/retry prevention GREEN.
- Birth identity: RED puuttuva birth-handle → pidfd-signaalipolku GREEN ilman numeric `os.kill(pid)` -käyttöä.

## Clean exact code SHA -validointi

Testattu SHA: `6bcaa640a5b0df3fedc309429ec494e628d10f65`.

- R4 focused/security/concurrency/interruption: exit `0`; `60 passed, 0 failed` kahdessa tiedostossa.
- Affected Kanban/Gateway: exit `0`; 84 tiedostoa; `610 passed, 0 failed, 3 skipped`.
- Kolme Windows-only-testiä: `SKIPPED`, eivät PASS.
- Synthetic pilot: exit `0`; `1 passed`.
- Ruff changed Python paths: exit `0`; `All checks passed!`.
- `git diff --check 93d90f11c900c7a70597056dac61965c4b4d7108..6bcaa640a5b0df3fedc309429ec494e628d10f65`: exit `0`.
- Third-party scannerit `gitleaks`, `trufflehog`, `detect-secrets`, `semgrep`: `NOT AVAILABLE`, ei PASS.
- Historiallinen `test_kanban_wake_acceptance.py` 300 s first-attempt timeout säilyy `FLAKY`; R4 exact-SHA runissa 3 testiä PASS.

## Ulkoiset report/result-hashit

- `/opt/data/logs/glh-r4-builder-20261009.report.md`: `85b1cd5fb6e114806d026cb8842126c75587f2ba8a3d0ae50376d04ee85676a5`.
- `/opt/data/logs/glh-r4-builder-20261009.result.md`: `9f0110c2e746a17a47b608cdfe0f01dd99f09d05d37d7885b7b01b065b7044ab`.
- R3 reviewer report: `d0af61340aeeb3795f60df823612d9a0516681ad0ff4dc8b031aab4eb2bb6e7b` — MATCH.
- R3 reviewer result: `696a80d842166db2a4d43bf59445fa669222fa27e39df6924f1155131eaebffb` — MATCH.

## No-live, rollback ja scope

- Live Gateway, production board ja live rollback: `NOT RUN`; mitään ei aktivoitu.
- Ei tuotantoavainta, production issueria, salaisuutta tai automaattista self-issuancea.
- Ei S123/S124-, skeema-, migraatio-, taulu- tai `work_packages`-muutosta.
- Ei mergeä, rebasea, force-pushia, origin-pushia tai remote-URL-muutosta.
- Rollback on branch/commit-eristys; lifecycle pysyy opt-ininä.
- Builder ei dispatchaa Reviewer R4:ää eikä myönnä Gate 2:ta.

R4 CORRECTIONS COMPLETE OR PARTIALLY BLOCKED — AWAITING INDEPENDENT REVIEWER R4

---

# R5 limited corrective implementation — 2026-10-09

Tila: `R5 TECHNICALLY VALIDATED — PRODUCTION AUTHORITY BLOCKED`

Session: `@session:theseus-builder/20261009_051058_6d682d`

- Base/evidence: `44a7c25d5709798bbae567e9743a004089dbda1f`.
- R4 code: `6bcaa640a5b0df3fedc309429ec494e628d10f65`.
- R5 code SHA: `dcb83f318959191f2b3bc7492d7802f2dbcf7f93`.
- Fork code readback: `dcb83f318959191f2b3bc7492d7802f2dbcf7f93` — MATCH.
- Evidence/docs SHA: tämän R5-osion ja päivitetyn `validation-results.md`:n sisältävä seuraava commit. Exact arvo varmennetaan non-force pushin jälkeisessä remote-readbackissa; commit ei voi sisältää omaa tulevaa SHA:taan.

## R5-toteutusmatriisi

| Kohta | Tila | Toteutus |
|---|---|---|
| R5-DEC-01 / R5-01 | IMPLEMENTED WITH SYNTHETIC TEST AUTHORITY; production BLOCKED | Common `_authority_gate_locked` varmentaa ja kuluttaa evidenssin varsinaisen SQLite-mutaatiotransaktion sisällä. Terminal approval, fresh approval, Architect resume ja Investigator authorization käyttävät samaa rajaa. Public production entrypointit, CLI ja Gatewayn yhteinen slash-polku hylkäävät myös validin synteettisen evidenssin tilalla `BLOCKED — TRUSTED AUTHORITY NOT CONFIGURED`. |
| R5-02 | IMPLEMENTED / VALIDATED | Genuine JSON int, bool-hylkäys, safe range/order, `now < expires_at`, issuer/principal authorization, Ed25519-signature, type/action/scope/target-sidonnat, issuer/key/nonce-revokaatio, replay ja concurrency. |
| R4-02 | PRESERVED | Restricted-role native/dispatcher claim -raja ja designated host -politiikka säilyvät. |
| R4-03 | PRESERVED Linux/POSIX | Artifact identity, atomic publication, fsync/no-replace ja fail-closed unsupported-platform -raja säilyvät. |
| R4-05 | PRESERVED Linux | pidfd birth-identity, manual fence ja retry prevention säilyvät. |
| R3-06 | PRESERVED | Dry-run säilyy DB/artifact non-mutating -polkuna. |

## Common authority mutation boundary

`_authority_gate_locked` saa expected binding -kontekstin lifecycle-koodilta, ei caller-metadatasta. Verifier tarkistaa issuer/key-id trust-mapin, issuerin authorized principal/role -mäppäyksen, allekirjoituksen, päätöstyypin, actionin, scopen, package/task/run/STOP/code SHA -kohteen, ajan ja revokaation. Caller `actor`, ref, timestamp, metadata, env tai ContextVar ei anna auktoriteettia.

Receipt `(issuer, nonce)` etsitään ja `theseus_authority_consumed` kirjoitetaan samassa `BEGIN IMMEDIATE` -transaktiossa lifecycle-tilasiirtymän ja päätösauditin kanssa. Replay, CAS-failure tai audit/transition-poikkeus rollbackaa receiptin ja tilan yhdessä. Uutta skeemaa tai taulua ei lisätty.

Public `record_terminal_approval`, `issue_fresh_terminal_approval` ja `resume_after_architect_decision` ovat production-configuraation puuttuessa aina fail-closed. Public Investigator creation kulkee samaan blokkiin. Private test-only wrapperit sallivat disposable synteettisen verifierin harjoittaa todellista mutation boundarya; public API hylkää samankin synteettisen konfiguraation. Reviewer-taskin normaali read-only-luonti ei ole Architect approval -kirjoitus ja säilyy ennallaan.

CLI korvaa caller-controlled `--approval-ref`/`--approved-at`-pinnan `--authority-evidence`-syötteellä, mutta production verifier/trust storea ei ole kytketty, joten CLI ja Gatewayn `/kanban`-delegointi pysyvät blokissa. Suora yleinen `_transition` ei voi siirtää approval-/resume-suojattua vaihetta `READY_FOR_BUILDER`-tilaan.

## Strict verifier

- Exact envelope- ja payload-kentät; JSON-duplikaattiavaimet hylätään.
- `version`, `run_id`, `issued_at`, `expires_at`: `int` mutta ei `bool`, alue `0 <= x < 2^63`.
- `version == 1`, `algorithm == Ed25519`, SHA-1-muotoinen 40-merkkinen lowercase code SHA nykyisen sopimuksen mukaisesti.
- Aika: `issued_at <= now < expires_at` ja `issued_at < expires_at`.
- Unknown issuer/key, unauthorized principal/role, revoked issuer/key/nonce, forged/malformed, wrong type/action/scope/package/task/run/STOP/SHA ja replay hylätään.

## Authority contract

- Polku: `planning/gateway-kanban-lifecycle-hardening/authority-contract.md`.
- SHA-256: `00e4af41d4493155c82c5278bb48482e190905a21108e6bacd1531aacbb92b92`.
- Sopimus erottaa eksplisiittisesti `IMPLEMENTED`, `TESTED WITH SYNTHETIC ISSUER` ja `BLOCKED — PRODUCTION AUTHORITY NOT AVAILABLE`.

## Production blocker ja rajattu Architect-muutosesitys

Tuotannon authenticated decision identity, hyväksytty issuer, principal/role authorization, signing-key management, trusted public-key distribution/trust store, authoritative revocation/receipt store, cross-board replay policy, rollout-monitorointi sekä incident/rollback-päätökset puuttuvat. Niitä ei keksitty tai aktivoitu R5:ssä.

Täsmällinen production tila on:

`BLOCKED — TRUSTED AUTHORITY NOT CONFIGURED`

Jos cross-board atomic consumption vaatii uuden globaalin mallin, skeeman tai taulun, toteutus edellyttää erillistä Architect-lupaa. Authority contract sisältää rajatun muutosesityksen.

## Scope

Koodicommit muuttaa täsmälleen seitsemän polkua: neljä lifecycle/verifier/CLI Python-polkuja, authority contractin sekä kaksi testiä. Ei S123/S124-, schema/table/migration-, production issuer/key/trust-store-, desired-state-, profile-, live Gateway- tai production board -muutosta. Ei mergeä, rebasea, force-pushia, origin-pushia, Gate 2 -päätöstä tai Reviewer R5 -dispatchia.

R5 TECHNICALLY VALIDATED — PRODUCTION AUTHORITY BLOCKED — AWAITING INDEPENDENT REVIEWER R5

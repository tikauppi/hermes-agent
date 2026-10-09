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

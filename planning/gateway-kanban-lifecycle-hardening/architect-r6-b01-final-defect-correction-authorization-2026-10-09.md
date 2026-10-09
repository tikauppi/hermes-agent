# THESEUS / Hermes GLH — R6 B-01 final defect correction authorization

Päivä: 2026-10-09  
Tila: `LIMITED DEFECT CORRECTION AUTHORIZED`  
Työskentelytunniste: `@session theseus-glh-r6-b01-2026-10-09`

Tämä on Arkkitehdin yksi rajattu jälkikorjauslupa Reviewer R6:n B-01-virheeseen ja D-01-dokumentaatiotarkennukseen. Tämä ei ole R7 eikä uusi kehityssprintti. Asiakirja ei myönnä Gate 2:ta, merge-lupaa, sprintin sulkemista tai live Gateway -aktivointia.

## Immutable lähtötilanne

- Fork: `tikauppi/hermes-agent`
- R6 code SHA: `55fe9171cee560a632ca1948c9f7593200a15c60`
- R6 evidence SHA: `8cd1f198aebf2348cbe8a2672eaa9c93a96d78d9`
- Reviewer R6 verdict: `CHANGES_REQUESTED`
- Reviewer B-01: expired native `claim_task` kirjoittaa pysyvän `claim_rejected`-eventin, vaikka se ei luo runia tai task-siirtymää.

## Hyväksytty toteutusraja

### B-01 — expired approval claim rejection

Korjaa vain vanhentuneen approvalin native claim -käsittely. Kun `now >= approval_expires_at`, järjestelmä ei saa synnyttää task_runia, claim-eventtiä, task-tilasiirtymää eikä muuta pysyvää Kanban-tilamuutosta.

Säilytä muiden hylkäyssyiden nykyinen käyttäytyminen, ellei täsmälleen B-01:n korjaus sitä vaadi. Älä toteuta uutta auditointimallia, tietokantaskeemaa, migraatiota tai taulua.

### D-01 — terminology

Päivitä `authority-contract.md`: poista tai korvaa viittaus poistettuun shipping `_authority_gate_locked`-toteutukseen. Kuvaa nykyinen toteutus ja production authorityn puuttuminen täsmällisesti.

## Pakollinen näyttö

- Test-first RED ja GREEN B-01:stä.
- Approval ennen expiryä, täsmälleen expiry-hetkellä ja sen jälkeen.
- Vanhentunut native claim ja dispatch/preflight eivät tee mitään pysyvää Kanban-muutosta; varmista vähintään tapahtumat ja DB-snapshot.
- Muiden claim-hylkäysten regressio: niiden olemassa oleva käyttäytyminen säilyy.
- Aiemmin läpäisseiden R3/R4/R6 turvarajojen regressiot, soveltuva Kanban/Gateway-sarja, eristetty synteettinen pilotti, Ruff, `git diff --check` ja secret-scan tai `NOT AVAILABLE`.

## Rajat ja julkaisu

Ei live Gatewayta, production authority -infrastruktuuria, S123/S124-muutoksia, upstream-mergeä, rebasea, force-pushia tai R7-aloitusta. Production authority säilyy `BLOCKED — PRODUCTION AUTHORITY NOT AVAILABLE` -operatiivisena riippuvuutena.

Tee yksi rajattu code/test commit ja erillinen evidence/docs commit; julkaise normaalilla non-force-pushilla, varmista remote SHA:t ja immediate-parent-suhde. Käynnistä tämän jälkeen yksi uusi eristetty riippumaton post-correction Reviewer. Reviewer ei aloita R7:ää; tulos palautetaan Arkkitehdille Gate 2 -päätöstä varten.

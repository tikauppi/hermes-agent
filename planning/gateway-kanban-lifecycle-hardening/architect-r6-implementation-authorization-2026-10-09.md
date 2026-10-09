# THESEUS / Hermes GLH R6 — Architect implementation authorization

Päivä: 2026-10-09  
Tila: `IMPLEMENTATION AUTHORIZED — SCOPE FROZEN`  
Työskentelytunniste: `@session theseus-glh-r6-2026-10-09`

Tämä dokumentti tallentaa Arkkitehdin kirjallisen R6-toteutusluvan. Se ei ole Gate 2 -hyväksyntä, merge-lupa eikä live Gatewayn aktivointilupa.

## Immutable lähtötilanne

- Repository/fork: `tikauppi/hermes-agent`
- R5 code SHA: `dcb83f318959191f2b3bc7492d7802f2dbcf7f93`
- R5 evidence SHA: `002feaf6f1e6cdaa1972d2853e1477053e4837cd`
- Reviewer R5 verdict: `CHANGES_REQUESTED`

R6 luodaan R5 evidence -commitista. Aiempi historia säilytetään: ei rebasea, force-pushia eikä aiempien commitien muutosta.

## Hyväksytty rajattu toteutus

R6 sisältää täsmälleen nämä korjauskokonaisuudet:

1. **R6-01 — Synthetic authority containment.** Estä caller-controlled synteettisen issuerin, trust rootin, avaimen tai principalin käyttö normaalissa tuotannon lifecycle-mutaatiossa. Inventoi `_for_test`-helperit, `SyntheticAuthorityTestConfiguration`, importit ja kutsuketjut. Turvarajaa ei saa väittää pelkäksi import- tai nimeämisrajaksi: dokumentoi prosessi- ja tietokantaoikeuksiin perustuva todellinen luottamusraja. Testaa, ettei normaali tuotantokutsuja voi itse myöntämällään testivaltuutuksella kirjoittaa authority-eventtiä tai lifecycle-mutaatiota.
2. **R6-02 — Role creation authorization.** Inventoi kaikki Reviewer- ja Investigator-rooleja luovat reitit. Pakota auktorisointi ennen roolin, taskin, linkin, metadatan tai tapahtuman kirjoitusta. Estä `create_role_task(role="reviewer")` sekä suorat ja vaihtoehtoiset ohitukset. Testaa epäonnistuneiden kutsujen täydellinen transaction rollback.
3. **R6-03 — Stored approval expiry.** Yhtenäistä tallennetun hyväksynnän ja päätöstodisteen voimassaolo: `now >= approval_expires_at` on vanhentunut. Testaa ennen rajaa, rajalla ja rajan jälkeen sekä ettei vanhentunut approval luo runia, claim-eventtiä tai pysyvää tilasiirtymää.

## Säilytettävät rajat

Säilytä R4-02 native claim capability, R4-03 Linux/POSIX atomic artifact publication, R4-05 verified child identity/manual retry fence, R3-06 dry-run zero persistent mutations, R3-04 designated dispatcher-host-policy sekä auditointi-, idempotenssi- ja fail-closed-ominaisuudet.

Ei domain-, API-, UI-, tietomalli- tai skeemalaajennusta, uutta migraatiota tai julkista sopimusmuutosta ilman uutta Architect-päätöstä.

## Production authority on erillinen operatiivinen riippuvuus

R6 ei toteuta production issuer-palvelua, signing-avaimia, trust storea, identiteettipalvelua tai uusia production approval -oikeuksia. Production approval-/decision-/resume-polut säilyvät fail-closed-tilassa. `authority-contract.md` erottaa IMPLEMENTED-, TESTED WITH SYNTHETIC ISSUER- ja `BLOCKED — PRODUCTION AUTHORITY NOT AVAILABLE` -tilat.

## Pakollinen validointi ja julkaisu

- R6-01–R6-03 positiiviset/negatiiviset testit sekä Python/native-, CLI- ja Gateway-ohitusyritykset.
- Concurrent/replay-, atomic rollback- ja säilytettävien turvarajojen regressiot.
- Kanban/Gateway-regressio, eristetty synteettinen pilotti, Ruff, `git diff --check` sekä secret-scan tai täsmällinen `NOT AVAILABLE`.
- Windows-only skipit ja Windows runtime `NOT RUN` erikseen; historiallinen wake-acceptance timeout säilyy `FLAKY`-merkintänä.
- Yksi R6-code commit non-force-pushilla, remote code SHA -readback, sitten erillinen evidence/docs commit ja remote evidence SHA / parent-suhde -readback.
- Yksi uusi eristetty riippumaton Reviewer R6. Se luokittelee löydökset vain: SECURITY BLOCKER, FUNCTIONAL DEFECT, OPERATIONAL DEPENDENCY tai IMPROVEMENT.

## STOP-raja

Ei live Gatewayta, upstream-mergeä, rebasea, force-pushia, S123/S124-muutosta, Gate 2 -hyväksyntäväitettä tai automaattista R7-kierrosta. STOP AFTER REVIEWER R6; koko Gate 2 -paketti palautetaan Arkkitehdille lopullista päätöstä varten.

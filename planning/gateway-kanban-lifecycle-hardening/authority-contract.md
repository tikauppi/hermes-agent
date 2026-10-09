# Gateway/Kanban Lifecycle Hardening — auktoriteettisopimus R6

Tila: `BLOCKED — PRODUCTION AUTHORITY NOT AVAILABLE`

Tämä sopimus erottaa toteutetun turvarajan, testipuuhun rajatulla synteettisellä issuerilla testatun käyttäytymisen ja puuttuvan tuotantoauktoriteetin. Synteettinen onnistuminen ei ole tuotantoauktoriteetin onnistuminen. Asiakirja ei myönnä Gate 2:ta, merge-lupaa eikä live Gateway -aktivointia.

## 1. IMPLEMENTED

### Nykyinen toimitettava mutaatioraja

Toimitettavat production-entrypointit terminal approvalille, fresh approvalille, Architect resumelle sekä Reviewer/Investigator-roolitaskin luonnille pysähtyvät ennen ensimmäistä tietokantakirjoitusta tilaan `BLOCKED — TRUSTED AUTHORITY NOT CONFIGURED`. CLI ja Gatewayn `/kanban` käyttävät samaa `run_slash`- ja lifecycle-polkuja, eikä Pythonin suora lifecycle-kutsu saa erillistä poikkeusta. Yleinen `_transition` ei saa siirtää approval- tai Architect-päätöstä vaativaa vaihetta `READY_FOR_BUILDER`-tilaan.

Allekirjoitetun evidenssin varmennus, atominen kulutus, tilasiirtymä ja auditointi harjoitetaan nykyisin vain testipuun `tests/hermes_cli/kanban_lifecycle_authority_harness.py`-rajassa. Poistettua shipping-symbolia `_authority_gate_locked` ei ole. Testiharness kutsuu lifecycle-moduulin sisäisiä transaktiomutaatioita samalla SQLite-write-transaktiolla, mutta sitä ei paketoida production API:ksi eikä normaali API-, CLI- tai Gateway-kutsuja voi toimittaa sille synteettistä issuer-, avain-, trust- tai principal-materiaalia.

Caller-supplied `actor`, `approval_ref`, `approved_at`, `decision_ref`, muu metadata, ympäristömuuttuja, profiili tai `ContextVar` ei muodosta auktoriteettia. Niillä ei voi korjata allekirjoituksen, issuer-valtuutuksen tai sidonnan virhettä.

### Evidenssi ja päätösidentiteetti

Hyväksyttävä evidenssi on ulkoisen issuerin Ed25519-allekirjoittama canonical JSON. Payload sisältää täsmälleen version, algoritmin, issuerin, key-id:n, varmennetun principalin ja roolin, evidenssityypin, actionin, scopen, package-id:n, task-id:n, run-id:n, STOP-tokenin, code SHA:n, issued-at-ajan, expires-at-ajan ja noncen.

Verifier tarkistaa:

- issuer/key-id-parin ennalta luotetusta julkisesta avainkartasta;
- principalin ja roolin issuer-kohtaisesta authorization-kartasta;
- Ed25519-allekirjoituksen;
- decision type-, action-, scope-, package-, task-, run-, STOP- ja code-SHA-sidonnat erikseen muodostettuun odotettuun kontekstiin;
- exact kenttäjoukon, duplikaattiavainten kiellon ja canonical allekirjoitussisällön;
- `version`, `run_id`, `issued_at` ja `expires_at` genuine JSON integer -tyyppeinä: `bool` ei kelpaa ja sallittu alue on `0 <= value < 2^63`;
- aikajärjestyksen `issued_at <= now < expires_at` ja `issued_at < expires_at`;
- issuer-, key- ja nonce-revokaation;
- replay-suojan.

Tuntematon issuer/key-id, valtuuttamaton principal/rooli, väärä scope/action/type/target/run/STOP/SHA, forged tai malformed allekirjoitus, puuttuva tai ylimääräinen kenttä, bool integer-kentässä, turvarajan ulkopuolinen integer, tuleva issued-at, `now >= expires_at`, revokaatio ja replay hylätään fail-closed.

### Atominen kulutus, tilasiirtymä ja audit

Hyväksytyn evidenssin `(issuer, nonce)` tarkistus ja `theseus_authority_consumed`-audit-event, varsinainen task-tilasiirtymä sekä approval/decision-audit-event tehdään samassa `BEGIN IMMEDIATE` -write-transaktiossa. Jos sidonta, kulutus, CAS-tilasiirtymä tai auditointi epäonnistuu, transaktio perutaan eikä hyväksyntä, resume, Investigator-task tai worker-run synny.

Audit sisältää vähintään issuerin, noncen, evidenssidigestin, actionin, scopen, principalin päätöstapahtumassa sekä target/run/STOP-sidonnan päätöstapahtumassa. Yksityistä avainta tai muuta allekirjoitussalaisuutta ei tallenneta.

Toteutus käyttää nykyisiä `task_events`- ja task-rakenteita. Se ei lisää skeemaa, taulua tai migraatiota.

### R6-korjausmatriisi

| Kohta | Tila | Toteutettu raja |
|---|---|---|
| R6-01 Synthetic authority containment | IMPLEMENTED / VALIDATED | `SyntheticAuthorityTestConfiguration` sekä `_record_terminal_approval_for_test`, `_issue_fresh_terminal_approval_for_test`, `_create_role_task_for_test` ja `_resume_after_architect_decision_for_test` poistettiin toimitettavasta `hermes_cli`-moduulista. Disposable key-, issuer-, trust-root- ja principal-rakennus on vain `tests/hermes_cli/kanban_lifecycle_authority_harness.py`:ssä. Normaali production lifecycle -kutsuja ei voi toimittaa synteettistä verifieria tai caller-controlled trust materiaalia mutaatiopolulle. |
| R6-02 Role creation authorization | IMPLEMENTED / VALIDATED | Julkinen `create_role_task` hylkää sekä `reviewer`- että `investigator`-luonnin ennen ensimmäistä tietokantakirjoitusta. Sisäinen auktorisoitu testipolku suorittaa taskin, linkin, metadatan ja eventin yhdessä transaktiossa; pakotettu event/audit-virhe rollbackaa kaiken. CLI ja Gateway käyttävät samoja lifecycle-polkuja eivätkä saa vaihtoehtoista roolinluontiohitusta. |
| R6-03 Stored approval expiry / B-01 | CORRECTED / BUILDER VALIDATED — AWAITING INDEPENDENT POST-CORRECTION REVIEW | Tallennettu approval validoidaan uudelleen claim/preflight-kulutusrajalla. `now >= approval_expires_at` on vanhentunut. Ennen rajaa approval voidaan kuluttaa; täsmälleen rajalla ja rajan jälkeen dispatch/preflight sekä native claim eivät synnytä runia, claim-eventtiä, task-siirtymää tai muuta pysyvää Kanban-muutosta. Builderin validointi ei korvaa riippumatonta katselmusta. |

### Todellinen trust boundary

Tuotannon turvallisuusraja ei ole Python-symbolin nimi, alaviiva, undocumented import tai testihakemiston importtipolku. Prosessi, jolla on oikeus ajaa mielivaltaista Pythonia samassa Hermes-prosessissa tai kirjoittaa Kanbanin SQLite-tietokantaan, kuuluu luotettuun computing/database-rights -rajaan: tällainen koodi voi muuttaa muistia, monkeypatchata funktioita tai kirjoittaa tietokantaan suoraan, eikä import-raja turvallisuuseristä sitä.

R6-01:n containment-takuu on rajatumpi ja todennettava: toimitettava normaali lifecycle-API, CLI ja Gateway eivät tarjoa caller-controlled synthetic issuer/trust root/key/principal -kyvykkyyttä eivätkä synteettistä mutaatio-entrypointia. Testiharness ei ole production API eikä security sandbox. Prosessi- ja tietokantaoikeuksien eristäminen, production identity sekä authority service ovat erillisiä operational/deployment-riippuvuuksia.

## 2. TESTED WITH TEST-TREE SYNTHETIC ISSUER

Testit generoivat disposable Ed25519-avaimen testipuun `kanban_lifecycle_authority_harness.py`-moduulissa. Harness kutsuu sisäistä same-transaction-mutaatiota vain testissä. Toimitettava `hermes_cli.kanban_theseus_lifecycle` ei sisällä `SyntheticAuthorityTestConfiguration`-luokkaa, `_for_test`-mutaatiowrappereita eikä `_test_authority`-parametria. CLI- ja Gateway-polut eivät voi välittää testiharnessia ja pysyvät tuotantopolkuna fail-closed.

Synteettisellä issuerilla on testattu:

- validi approval, fresh approval, Architect resume sekä Reviewer/Investigator-roolilinkitys testiharnessissa;
- issuer authorization sekä approver/architect-roolisidonta;
- allekirjoitus, action, type, scope, package, task, run, STOP-token ja code SHA;
- malformed-, missing-, bool-integer- ja safe-range-tapaukset;
- stored approval ennen expiry-rajaa, täsmälleen rajalla `now == approval_expires_at` ja rajan jälkeen;
- unknown issuer, valtuuttamaton principal, revoked issuer/key/nonce ja forged signature;
- replay sekä samanaikaiset yritykset, joista vain yksi saa atomisen kulutuksen ja tilasiirtymän;
- caller-metadatan kyvyttömyys korjata väärää allekirjoitettua scopea;
- CLI-, Gatewayn yhteisen slash-polun, Python native -kutsun ja suoran lifecycle-mutaation fail-closed-käyttäytyminen.

Synteettinen private key ja trust-map ovat vain testikoodissa. Niitä ei toimiteta konfiguraationa, trust storena, issuer-palveluna, ympäristömuuttujana tai live Gatewayn käyttöön. Synteettiset principalit eivät ole tuotantoidentiteettejä. Testipuuhun siirtäminen vähentää toimitettavaa capability-pintaa, mutta ei väitä eristävän mielivaltaista koodia, jolla jo on samat prosessi- tai tietokantaoikeudet.

## 3. BLOCKED — PRODUCTION AUTHORITY NOT AVAILABLE

Tuotantoon ei ole konfiguroitu eikä tässä R6:ssa luotu:

1. server-side authenticated päätösidentiteettiä;
2. Arkkitehdin hyväksymää production issueria;
3. issuerin authorization- ja principal/role-mäppäystä;
4. production signing key -hallintaa;
5. luotettua julkisten avainten jakelua tai trust storea;
6. authoritative issuer/key/nonce-revokaatiolähdettä ja sen availability-politiikkaa;
7. boardit ylittävää authoritative receipt storea;
8. rollout-, valvonta-, retention- ja incident response -päätöksiä.

Siksi jokainen tuotannon approval-, fresh approval-, Architect resume- ja Investigator authorization -kirjoitus päättyy täsmälliseen tilaan:

`BLOCKED — TRUSTED AUTHORITY NOT CONFIGURED`

Tämä koskee CLI:tä, Gatewayn `/kanban`-polkua, Python native -kutsuja ja suoria lifecycle-funktioita. Profiili, env, `ContextVar`, caller-ref, caller-aika tai actor-merkkijono ei poista blokkia.

### Rajattu Architect-muutosesitys

Tuotantoblokin poistaminen vaatii erillisen Architect-päätöksen ja uuden rajatun toteutusluvan seuraaville asioille:

- nimetä authenticated identity provider ja production issuer;
- määrittää issuerin principal/role-authorization;
- valita signing key -säilytys, key rotation ja julkisen avaimen luotettu jakelu;
- valita authoritative revocation- ja receipt store sekä availability/fail-closed-politiikka;
- ratkaista eri Kanban-boardien välinen kertakäyttöisyys. Jos se vaatii uuden globaalin mallin, taulun tai skeeman, sitä ei lisätä ilman nimenomaista lupaa;
- toteuttaa production-only configuration loader, joka ei hyväksy testikonfiguraatiota;
- tehdä canary-rollout erillisellä luvalla ja riippumattomalla katselmuksella.

Nykyinen R6 ei toteuta tai aktivoi näitä riippuvuuksia.

## 4. Allekirjoitusavainten hallintaraja

Production private key kuuluu issuer-palvelun hallintaan Hermes-workerien, Kanban-tietokantojen, työpuiden, lokien, testifixtureiden ja ympäristömuuttujien ulkopuolelle. Hermes saa vain varmennukseen tarvittavan luotetun julkisen avainmateriaalin. Key-id on yksikäsitteinen issuerin sisällä. Kompromettoitu issuer tai key-id revokoidaan authoritative lähteessä ennen uuden evidenssin hyväksyntää.

## 5. Revokaatio ja fail-closed

Issuer-, key- ja nonce-revokaatio tarkistetaan ennen receipt-kulutusta. Tuotannon revokaatiolähteen puuttuminen tai saavuttamattomuus estää operaation. Offline-poikkeusta ei ole hyväksytty. Kryptokirjaston, trust storen, revokaation, kellon, SQLite-transaktion, CAS-päivityksen tai auditoinnin virhe estää tilasiirtymän.

## 6. Rollout ja rollback

Rollout-riippuvuudet ovat Architect-päätös, production issuer/trust-store/revocation/receipt-store, turvallinen avainjakelu, monitorointi, canary ja riippumaton Reviewer. Ennen niiden täyttymistä ominaisuus jää blokkiin eikä live Gatewayta aktivoida.

Rollback on fail-closed: production authority -konfiguraatio poistetaan käytöstä, uudet auktoriteettikirjoitukset palaavat täsmälliseen blocked-tilaan ja jo kirjoitetut audit-eventit säilytetään. Rollback ei poista tai uudelleenkäytä nonceja, ei alenna scope-/signature-tarkistuksia eikä muuta historiallista evidenssiä.

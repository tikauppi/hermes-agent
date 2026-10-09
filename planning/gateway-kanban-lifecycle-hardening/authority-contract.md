# Gateway/Kanban Lifecycle Hardening — auktoriteettisopimus R5

Tila: `BLOCKED — PRODUCTION AUTHORITY NOT AVAILABLE`

Tämä sopimus erottaa toteutetun turvarajan, synteettisellä issuerilla testatun käyttäytymisen ja puuttuvan tuotantoauktoriteetin. Synteettinen onnistuminen ei ole tuotantoauktoriteetin onnistuminen. Asiakirja ei myönnä Gate 2:ta, merge-lupaa eikä live Gateway -aktivointia.

## 1. IMPLEMENTED

### Yhteinen pakollinen mutaatioraja

Terminal approval, fresh approval, Architect resume ja Investigator-luontiin liittyvä Architect-päätös kulkevat saman `_authority_gate_locked`-rajan kautta varsinaisessa SQLite-write-transaktiossa. CLI ja Gatewayn `/kanban` käyttävät samaa `run_slash`- ja lifecycle-polkuja. Pythonin suora lifecycle-kutsu ei saa erillistä poikkeusta. Yleinen `_transition` ei saa siirtää approval- tai Architect-päätöstä vaativaa vaihetta `READY_FOR_BUILDER`-tilaan.

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

## 2. TESTED WITH SYNTHETIC ISSUER

Testit generoivat prosessin sisäisen disposable Ed25519-avaimen ja injektoivat `SyntheticAuthorityTestConfiguration`-olion vain eksplisiittisellä `_test_authority`-parametrilla. CLI- ja Gateway-polut eivät välitä tätä parametria ja hylkäävät synteettisen evidenssin tuotantopolkuna.

Synteettisellä issuerilla on testattu:

- validi approval, fresh approval, Architect resume ja Investigator-päätös;
- issuer authorization sekä approver/architect-roolisidonta;
- allekirjoitus, action, type, scope, package, task, run, STOP-token ja code SHA;
- malformed-, missing-, bool-integer- ja safe-range-tapaukset;
- expiry-raja `now == expires_at`;
- unknown issuer, valtuuttamaton principal, revoked issuer/key/nonce ja forged signature;
- replay sekä samanaikaiset yritykset, joista vain yksi saa atomisen kulutuksen ja tilasiirtymän;
- caller-metadatan kyvyttömyys korjata väärää allekirjoitettua scopea;
- CLI-, Gatewayn yhteisen slash-polun, Python native -kutsun ja suoran lifecycle-mutaation fail-closed-käyttäytyminen.

Synteettinen private key on vain testikoodissa. Sitä ei toimiteta konfiguraationa, trust storena, issuer-palveluna, ympäristömuuttujana tai live Gatewayn käyttöön. Synteettiset principalit eivät ole tuotantoidentiteettejä.

## 3. BLOCKED — PRODUCTION AUTHORITY NOT AVAILABLE

Tuotantoon ei ole konfiguroitu eikä tässä R5:ssä luotu:

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

Nykyinen R5 ei toteuta tai aktivoi näitä riippuvuuksia.

## 4. Allekirjoitusavainten hallintaraja

Production private key kuuluu issuer-palvelun hallintaan Hermes-workerien, Kanban-tietokantojen, työpuiden, lokien, testifixtureiden ja ympäristömuuttujien ulkopuolelle. Hermes saa vain varmennukseen tarvittavan luotetun julkisen avainmateriaalin. Key-id on yksikäsitteinen issuerin sisällä. Kompromettoitu issuer tai key-id revokoidaan authoritative lähteessä ennen uuden evidenssin hyväksyntää.

## 5. Revokaatio ja fail-closed

Issuer-, key- ja nonce-revokaatio tarkistetaan ennen receipt-kulutusta. Tuotannon revokaatiolähteen puuttuminen tai saavuttamattomuus estää operaation. Offline-poikkeusta ei ole hyväksytty. Kryptokirjaston, trust storen, revokaation, kellon, SQLite-transaktion, CAS-päivityksen tai auditoinnin virhe estää tilasiirtymän.

## 6. Rollout ja rollback

Rollout-riippuvuudet ovat Architect-päätös, production issuer/trust-store/revocation/receipt-store, turvallinen avainjakelu, monitorointi, canary ja riippumaton Reviewer. Ennen niiden täyttymistä ominaisuus jää blokkiin eikä live Gatewayta aktivoida.

Rollback on fail-closed: production authority -konfiguraatio poistetaan käytöstä, uudet auktoriteettikirjoitukset palaavat täsmälliseen blocked-tilaan ja jo kirjoitetut audit-eventit säilytetään. Rollback ei poista tai uudelleenkäytä nonceja, ei alenna scope-/signature-tarkistuksia eikä muuta historiallista evidenssiä.

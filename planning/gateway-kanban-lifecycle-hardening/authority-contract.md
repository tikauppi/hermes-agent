# Gateway/Kanban Lifecycle Hardening — auktoriteettisopimus

Tila: R4:n eristetyn verifierin sopimus. Tämä asiakirja ei nimeä eikä toteuta tuotannon issuedia, avainhallintaa tai live-palvelua eikä myönnä Gate 2:ta.

## 1. Luottamusraja ja ulkoinen issuer

Terminal approval- ja Architect decision -valtuutus syntyy Hermes-workerin ulkopuolisessa, Arkkitehdin erikseen hyväksymässä issuer-palvelussa. Issuer tunnistaa käyttäjän server-side-menetelmällä, ratkaisee varmennetun principalin hyväksyttyyn rooliin ja tarkistaa ennen allekirjoitusta, että principal saa suorittaa pyydetyn toiminnon täsmälleen nimetylle kohteelle.

Hermes-worker, CLI-argumentti, Gateway-viesti, ympäristömuuttuja, profiilinimi, `ContextVar`, caller-supplied actor/ref/aika tai Kanban-eventti ei saa yksin luoda valtuutusta. Hermes vain varmentaa ulkoisen issuerin allekirjoittaman evidenssin ja kuluttaa sen atomisesti kohdeoperaation yhteydessä.

## 2. Allekirjoitus ja varmennus

Issuer allekirjoittaa kanonisoidun evidenssipayloadin hyväksytyllä epäsymmetrisellä algoritmilla. Verifier käyttää vain ennalta luotettua issuer-tunnisteen ja julkisen varmennusavaimen sidontaa. Tuntematon issuer, tuntematon avain-id, väärä algoritmi, väärä allekirjoitus, epäkanoninen tai virheellinen payload ja ylimääräinen tai puuttuva kenttä hylätään fail-closed-periaatteella.

Tuotannon yksityinen allekirjoitusavain säilytetään Hermes-workereiden, Kanban-tietokannan, työpuiden, lokien ja ympäristömuuttujien ulkopuolella. Workerille jaetaan vain varmennukseen tarvittava julkinen avain tai luotettu avainrekisteri. Avaimen materiaalia ei kirjoiteta task-eventteihin.

## 3. Kanoninen allekirjoitettu evidenssi

Kanoninen payload on UTF-8-koodattu JSON, jossa objektien avaimet järjestetään deterministisesti, turha välilyönti poistetaan, duplikaattiavaimet kielletään ja arvotyypit validoidaan. Allekirjoituksen kattama skeema sisältää täsmälleen:

- version ja allekirjoitusalgoritmin;
- issuerin ja key-id:n;
- varmennetun principalin sekä principalin roolin;
- actionin ja evidenssin tyypin;
- scopen;
- targetin: package-id ja task-id;
- run-id:n sekä terminal approvalissa hyväksyttävän run-scope-arvon tai Architect decisionissa täsmällisen pysäytetyn run-id:n;
- STOP-tokenin, kun action on Architect resume;
- code/candidate SHA:n;
- issued-at- ja expiry-ajan;
- kryptografisesti satunnaisen nonce-arvon.

Action, type, scope, target, run/STOP-token ja code SHA verrataan verifierille erikseen annettuun odotettuun päätöskontekstiin. Payload ei saa määrätä omaa odotettua kontekstiaan.

## 4. Nonce, replay-suoja ja atominen kulutus

Nonce on issuerin luoma kertakäyttöinen tunniste. Verifier tarkistaa allekirjoituksen, kaikki sidonnat, voimassaoloajan ja revokaation ennen hyväksyntää. Hyväksytty nonce kulutetaan samassa tietokantatransaktiossa kuin terminal approval- tai resume-tilasiirtymä. Kulutus kirjataan olemassa olevaan audit/event-rakenteeseen; uutta globaalia skeemaa tai taulua ei oleteta tässä R4:ssa. Sama nonce, sama allekirjoitus tai sama päätösevidenssi hylätään kaikissa myöhemmissä yrityksissä, myös rinnakkaisissa kutsuissa.

Jos turvallista atomista kulutusta ei voida toteuttaa olemassa olevilla rakenteilla, tuotantointegraatio pysyy tilassa `BLOCKED — ARCHITECT DECISION REQUIRED` eikä verifierin positiivista tulosta saa käyttää tilasiirtymään.

## 5. Revokaatio ja auditointi

Issuer tai erillinen Arkkitehdin hyväksymä revokaatiolähde voi peruuttaa avaimen, issuerin tai yksittäisen noncen. Verifier hylkää revokoidun kohteen ennen kulutusta. Audit-tietueeseen tallennetaan vähintään payloadin tiiviste, issuer, key-id, principal, action, target, run/STOP-sidonta, code SHA, issued-at, expiry, nonce, varmennustulos, hylkäyssyy ja kulutuksen tulos. Salaisuuksia tai yksityistä avainmateriaalia ei tallenneta.

Revokaatiolähteen saavuttamattomuuden politiikka on fail-closed, ellei Arkkitehti hyväksy erillistä, rajattua offline-politiikkaa. R4 ei ota käyttöön offline-poikkeusta.

## 6. Fail-closed-semanttiikka

Puuttuva, vanhentunut, tulevaisuuteen päivätty, malformed, forged, väärälle principalille/actionille/tyypille/scopelle/taskille/package-id:lle/runille/STOP-tokenille/SHA:lle allekirjoitettu, replayattu tai revokoitu evidenssi hylätään. Kellon, avainrekisterin, revokaatiolähteen, kryptokirjaston, tietokannan tai atomisen kulutuksen virhe hylkää operaation. Hylkäys ei avaa taskia, luo runia, vapauta STOP-tilaa eikä käynnistä workeria.

## 7. Rollout ja avainkierto

Tuotantorollout vaatii erillisen Architect-päätöksen issuerista, authentication- ja role-mäppäyksestä, avainrekisterin omistajasta, revokaatiosta, retentionista, valvonnasta, failure-politiikasta ja integraatioboundarysta. Rollout tehdään ensin pois päältä olevalla verifierillä, sitten synteettisillä testivektoreilla, rajatulla canarylla ja vasta erillisen hyväksynnän jälkeen live-käyttöön.

Avainkierrossa issuer julkaisee uuden key-id:n ja julkisen avaimen ennen käyttöönottoa. Vanha ja uusi varmennusavain voivat olla rajatun overlap-ajan luotettuja, mutta allekirjoitus valitsee yksikäsitteisen key-id:n. Kompromettoitu avain revokoidaan välittömästi; sen aiemmin käyttämättömät evidenssit hylätään. Yksityisiä avaimia ei kopioida Hermes-workereihin kierrossakaan.

## 8. R4:n synteettinen test issuer

R4 toteuttaa vain eristetyn verifier-komponentin ja testien sisäisen synteettisen issuerin/fixturet. Synteettinen yksityinen avain luodaan testissä, sitä ei toimiteta tuotantoasetuksena, palveluna, salaisuutena tai automaattisena self-issuance-polkuina. Synteettinen issuer ei ole oikea issuer, sen principalit eivät ole tuotantoidentiteettejä eikä sen allekirjoitus valtuuta live Gatewayta, tuotantoboardia tai todellista päätöstä.

Oikea issuer jää Arkkitehdin erikseen nimettäväksi ja toteutettavaksi. R4-verifierin API ei saa kätkeä tätä eroa eikä hyväksyä caller-controlled avainta luottamusankkuriksi.
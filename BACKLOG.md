# VenTrax - Volledige Backlog
Laatste update: 2026-06-17
Gebruik dit bestand als briefing voor een nieuwe Claude sessie.

---

## v12 Codex update - 2026-06-05

## v13 Codex update - 2026-06-05

## v13.2 Codex update - 2026-06-05

### Prio 0 - opgepakt
- [x] Dashboard 500-error hersteld (`Badge.earned_at`).
- [x] Bekende directe showstoppers uit v12/v13 zijn opgepakt: rolselectie, difficulty, target/catch/naam raden, upload, puntenformatting en dashboard.

### Prio 1 - opgepakt
- [x] **Speelveld instellen** is verplaatst naar Prio 1 en als eerste werkende versie toegevoegd.
- [x] Spelmaker kan in Nieuw Spel punten op een kaart klikken om het speelveld te tekenen.
- [x] Vanaf 3 punten sluit VenTrax het speelveld automatisch.
- [x] Spelmaker kan buitengebied-kleur kiezen: Radiation groen, Storm blauw, Nuclear geel, Heat rood.
- [x] Speelveld wordt per game opgeslagen zonder database-migratie.
- [x] In het spel wordt het speelveld op de kaart getoond.
- [x] Buiten het speelveld wordt als gekleurde wolk/overlay getoond.
- [x] Kaart wordt begrensd tot speelveld + buffer, zodat spelers niet onbeperkt over de wereld scrollen.

### Prio 2 - ingepland / zichtbaar
- [ ] **Alle extra's** zijn verplaatst naar Prio 2: dropboxes, landmijn, laser detectie, tripwire, glitch, hacker en toekomstige power-ups.
- [ ] Dropbox instellingen moeten in een volgende ronde actief worden: algemeen standaard 1/max 3, per team standaard 2/max 5, met punten-multiplier penalty.
- [ ] Dropbox spawn-logica moet nog volgen binnen het speelveld.
- [ ] Landmijn, laser, tripwire, glitch en hacker moeten nog spelregels, UI, cooldowns en kaartinteractie krijgen.

### Opgelost / aangepast
- [x] Desktop rolselectie zichtbaar gemaakt: geselecteerde Hunter/Runner krijgt nu een rode rand.
- [x] Difficulty presets passen nu ook de onderliggende instellingen en multiplier-preview aan.
- [x] Custom start vanuit Gemiddeld in plaats van direct naar 0.90 te zakken.
- [x] Spelnaam krijgt standaard datum en tijd.
- [x] QR-code gebruikt `static/img/logo_round.png` als logo in het midden.
- [x] Foto-upload gebruikt de juiste file inputs en toont echte foutmeldingen.
- [x] Chat toont gemiste berichten per Team/Globaal/Proxy plus totaal onderin.
- [x] Eindmail toegevoegd met standen, foto's en chat voor alle spelers met e-mailadres.
- [x] Snelheidsmelding is standaard verborgen en toont pas "Niet rennen" bij echte hoge snelheid.
- [x] Offline melding toont schuilnaam en hunters/runner zien aftellende timers.
- [x] Runner afstand tot dichtstbijzijnde hunter respecteert interval/live tracking instelling.
- [x] Dashboard toont badges; profielmenu is opgeschoond; Admin-items staan onder Admin.
- [x] Changelog seed bijgewerkt naar v1.6.2.
- [x] Spel wordt automatisch gestopt als een speler vertrekt en er daardoor geen hunter of runner meer over is.

### Prio 2 / aparte ronde
- [ ] Extra speelelementen uitwerken: detector laser, landmijn, tripwire, dropboxes en bijbehorende UI/regels.
- [ ] Speelveld-editor uitbreiden met gaten/verboden zones uitsnijden en kaart bewaren als template.
- [ ] Kaartlagen/veiligheid: wegen, weilanden, huizen/achtertuinen detecteren en rennen daar blokkeren of waarschuwen.

### PRIO 0 opgelost in deze ronde
- [x] Nieuw spel: rol kiezen werkt weer. De rolkaarten zetten nu expliciet de verborgen radio op Hunter/Runner.
- [x] Nieuw spel: moeilijkheid kiezen werkt weer. Presets blijven geselecteerd en springen niet direct terug naar Custom.
- [x] Target instellen werkt weer. `doTarget()` bewaart runner-id en naam voordat het modal sluit.
- [x] Markeer als gepakt werkt weer. `doCatch()` stuurt nu de juiste runner-id naar `/catch`.
- [x] Naam raden gebruikt de gekozen speler weer correct. `doGuessName()` bewaart target-id/naam en gebruikt de dropdown-keuze.
- [x] Dashboard-JS crasht niet meer op ontbrekende helpers. `fmtMM`, `fmtDist` en `fmtPts` zijn teruggezet.
- [x] Punten worden in de UI afgerond op 2 decimalen met komma, bijvoorbeeld `1,38`.
- [x] Leaflet +/- zoomknoppen zijn verwijderd.
- [x] Kaart recenter/auto-fit stopt zodra de gebruiker zelf beweegt of zoomt, zodat zoom niet telkens terugspringt.
- [x] Valse snelheidswaarschuwingen zijn minder agressief: waarschuwing pas na stabiele GPS-samples en redelijke nauwkeurigheid.
- [x] Dubbele pauzeknop in Menu is verwijderd.
- [x] Panels hebben extra ruimte voor het sluitkruisje, zodat Info/Feed/Chat/Menu duidelijker sluitbaar zijn.

### Nog open / volgende ronde
- [ ] Locatie-permissie volledig afdwingen in lobby en nooit pas bij start opnieuw vragen.
- [ ] Adres tonen/toevoegen.
- [ ] Chat per Team/Globaal/Proxy als aparte gefilterde views verder uitwerken.
- [ ] Bij verlaten/stoppen eindmail met overzicht naar maker en deelnemers sturen.
- [ ] Als iemand een ander spel probeert te joinen: link naar huidig spel plus verlaten/verwijderen duidelijker maken.
- [ ] Echte GPS-startpositie verbeteren met warming-up/accuracy gate in lobby.

### Nieuwe backlog ronde - 2026-06-17

#### Bugs / UI
- [x] Countdown blijft op `00:01` staan en verdwijnt niet zonder refresh.
- [x] Gemaakte foto's moeten naar `Wachtend` / pending status gaan.
- [ ] VenFaye-tekst op Home vervangen door VenTrax.
- [ ] Voorbeeld van naam van speelveld aanpassen zodat de maker niet herkenbaar is.
- [x] Tekst rond actieve spellen verduidelijken als de lobby-link en "Terug naar spel" hetzelfde zijn.
- [ ] QR-scan moet direct camera-toegang vragen en scannen, niet eerst het code-scherm tonen.
- [ ] Als camera niet is goedgekeurd, eerst popup aan maker tonen voor start.
- [ ] Zinnen "Jij bent Hunter" / "Jij bent Runner" omzetten naar correct Nederlands.
- [x] Target countdown live laten aftellen en het `02:00`-label verwijderen.
- [x] Target-scherm netjes sluiten zodra de tijd voorbij is.
- [x] Offline countdown corrigeren zodat die echt live aftelt.
- [ ] Samenvatting opschonen zodat rare tekens verdwijnen.
- [ ] Classes opschonen zodat speler-only info niet zichtbaar blijft.

#### Features / backlog
- [ ] Betere puntenverdeling uitwerken met overzicht van wat het spel moeilijker of makkelijker maakt.
- [ ] Speelveldkeuze baseren op de locatie van de spelers.
- [ ] Speelveld opslaan als herbruikbare optie.
- [ ] Beheerders speelvelden laten zien, aanpassen en verwijderen.
- [ ] Bij extra's min. afstand verbergen als er een speelveld is, en max. afstand verbergen zodra een speelveld bestaat.
- [ ] Dropboxes / lootboxes minimaal 500 meter en maximaal 750 meter laten droppen.
- [ ] Korte uitleg bij Extra's toevoegen.
- [ ] Scherm buiten de zone langzaam laten "ademen" terwijl de kaart zichtbaar blijft.
- [ ] Badges moeilijker maken en uitbreiden met puntenbadges en nummer-1-badge met datum.
- [x] Power-uitleg tonen bij start of via info.
- [x] Power-knop verplaatsen naar de kaart linksonder met countdown in de knop.
- [x] Offline-knop countdown in kaart tonen.
- [x] Bij meerdere offline-knoppen het aantal resterende uses in de knop tonen.
- [ ] Offline countdown groter en bovenin tonen, net als target.
- [ ] Standaard styles uitbreiden met TV / Serie-thema's en leuke namen.
- [ ] Teksten voor speelveld, extra's en classes verder opschonen.

---

## 🔴 PRIO 0 — Showstoppers (spel onbruikbaar)

- [ ] **Spel dashboard 500 error** — `{#runnerPanel` Jinja2 comment bug OPGELOST in v5
- [x] **Target zetten doet niets** — Runner krijgt geen scherm "Je bent een Target!". Hunters/runners zien geen bevestiging. Alle hunters moeten melding krijgen dat `<Naam>` een target heeft gezet op `<Schuilnaam>`. Backend stuurt WS-event maar frontend verwerkt het niet zichtbaar genoeg.
- [ ] **Chat werkt niet zichtbaar** — Berichten verschijnen niet. Panel toont alleen input, geen berichtenlijst. Niemand ziet verzonden berichten terug.
- [ ] **Lobby refresh vereist voor nieuwe spelers** — WebSocket `player_joined` event wordt verstuurd maar maker ziet nieuwe speler niet zonder refresh.
- [ ] **QR code scan stuurt niet door naar spel** — Na scannen moet code auto-ingevuld worden én direct doorsturen naar join_team pagina.
- [x] **Countdown start pas NADAT 5 seconden gewacht is** — Gebruiker ziet niets en denkt dat er niets gebeurt. Countdown moet DIRECT starten als je op Start klikt.

---

## 🟠 PRIO 1 — Onwerkbaar

- [ ] **Schuilnaam zichtbaar in lobby** — Verborgen houden! Leukste is dat je niet weet hoe de andere kant heet. Pas tonen TIJDENS het spel.
- [ ] **Rol veranderen niet mogelijk in lobby** — Speler moet Hunter↔Runner kunnen wisselen vóór spel start. Controle pas bij start (te weinig hunters/runners).
- [ ] **Dropdown "Spel" werkt niet op desktop** — Hover op Spel in navbar geeft geen dropdown. Via Dashboard werkt het wel.
- [ ] **Bottombar knoppen vereisen exacte klik** — Balk verdwijnt als je net naast knop klikt. Grotere klikgebieden + kruisje om panel te sluiten + nogmaals klikken = sluiten.
- [ ] **Camera knop niet zichtbaar bij runners** — Moet zichtbaar zijn als foto feed is ingeschakeld in spel.
- [x] **Offline knop melding mist bij hunters** — Hunters moeten zien: `<SCHUILNAAM> heeft offline knop gebruikt! Onzichtbaar voor X minuten`. Timer hoelang offline nog duurt op kaart.
- [ ] **Zoom kaart hunter** — Kaart moet automatisch inzoomen zodat alle runners + jijzelf in beeld zijn (tenzij runner offline is).
- [ ] **Zoom kaart runner** — Runner ziet zichzelf goed ingezoomd op zijn eigen locatie.
- [ ] **Afstand badge verkeerde plek bij runner** — Afstand moet linksboven, camera rechtsboven (nu beide rechtsboven).
- [ ] **Offline timer na afloop** — Nadat offline tijd voorbij is → nieuwe locatie runner direct naar hunters sturen.
- [ ] **Hunters hebben geen Pauze knop** — Hunters moeten ook kunnen pauzeren (zelfde systeem als runners).
- [ ] **Feed badge telt niet** — Aantal nieuwe ongelezen foto's moet als cijfer op Feed knop staan.
- [ ] **Noodknop van map verwijderen** — Staat nu dubbel (kaart + Menu). Alleen in Menu houden.

---

## 🟡 PRIO 2 — Nodig om andere dingen op te lossen

- [ ] **Admin Checklist + TODO met Claude AI prompt** — Admins kunnen items afvinken, "werkt niet" markeren + commentaar. Automatisch Claude-prompt genereren voor bug rapportage zodat admin het direct kan kopiëren.
- [ ] **Admin Logging** — Wie doet wat op de website (login, spel aanmaken, punten aanpassen, etc.).
- [ ] **IP-check bij login** — Waarschuwingsmail als inlog uit onverwacht land/regio komt. Overzicht van actieve sessies per apparaat + IP. Sessie verwijderen indien onbekend.
- [ ] **Waarschuwingssysteem gebruikers** — Waarschuwing 1: punten aftrek + mail. Waarschuwing 2: 1 week ban. Waarschuwing 3: perm ban. Gebruiker kan aanvechten met bewijs. Datum/tijd bij elke waarschuwing. Admin plaatst commentaar.
- [ ] **Temp ban in admin gebruikersbeheer** — Ban knop, commentaar veld, tijdstip logging.
- [ ] **Nieuwsbrief inschrijven/uitschrijven** — Mail bij nieuwe goedgekeurde nieuwspost. Uitschrijflink in mail.
- [ ] **Disclaimer nieuws feed altijd onderin** — Mag niet verdwijnen als je scrollt.
- [ ] **Moeilijkheidsgraad aanpassen = multiplier aanpassen** — Als je na keuze "Makkelijk" nog iets aanpast, wordt het "Custom" en past de multiplier aan (bijv. ×0.95 als je het nog makkelijker maakt).
- [ ] **Platform architectuur: VenTrax = platform en spelcatalogus** — Homepage wordt spel-keuze scherm met tegels. VenTrax tegel gebruikt het VenTrax logo. Leaderboard bovenaan. Structuur voor toekomstige spellen via `game_type` in DB.

---

## 🟢 PRIO 3 — Verbetert ervaring

- [ ] **QR code fullscreen bij klik** — Klik op QR → fullscreen overlay met kruisje.
- [x] **Target visueel duidelijk voor iedereen**
  - Runner: rood scherm/overlay "JE BENT EEN TARGET!" met countdown timer hoelang nog
  - Hunter die target zette: bevestiging + timer
  - Andere hunters: melding `<Naam> heeft target gezet op <Schuilnaam>`
  - Offline blokkeren als runner target is
- [ ] **Naam raden keuze scherm** — Hunter klikt op runner → keuze scherm met alle echte spelersnamen → goed = +5pt, fout = -10pt. Mag negatief worden.
- [ ] **Runner wordt Hunter na pakken** — Extra spelmodus: gepakte runner wordt hunter. Runners krijgen melding. Runners krijgen ×0.5 extra punten als dit ingeschakeld is.
- [ ] **Chat verbeterd**
  - Berichten zichtbaar in panel (geschiedenis tonen)
  - Keuze: heel team OF heel spel
  - Aantal nieuwe berichten als badge
  - Chat "popt" uit als nieuw bericht binnenkomt
- [ ] **Pauze: offline knop + target pauzeren** — Timers stoppen tijdens pauze (paused_at verrekenen in expires_at).
- [ ] **Offline blokkeren tijdens 5-sec countdown** — State API weigert offline tijdens countdown status.

---

## ⚪ PRIO 4 — Nice-to-have

- [ ] QR scanner via camera bij join pagina
- [ ] E-mail verificatie verplicht voor spel joinen
- [ ] HTML e-mail na afloop spel (punten, foto's, winnaar)
- [ ] Logo in e-mails
- [ ] Leaderboard per dag/week/maand/alltime tabs
- [ ] Naam raden (schuilnaam vrijspelen)
- [ ] Offline knop kopen na 50-80% spel (15 punten)
- [ ] Hacker / Glitch activeer-knoppen in UI
- [ ] 2FA authenticatie (TOTP)
- [ ] Foto locatie-opdracht GPS match +5 punten
- [ ] Snitch, Hunter deelt afstand, naam ontmaskeren
- [ ] Thema's (Wizard, Superhelden + schuilnamen)
- [ ] Geluidsbeheer + in-game geluidseffecten
- [ ] Lokale fonts (Syne + DM Sans woff2)
- [ ] Anti-valsspelen auto-detectie verbeterd
- [ ] Record snelste vangst bijhouden

---

## 🔴 NIET MOGELIJK

- 4K AI afbeelding genereren
- Bellen / portofoon (WebRTC STUN/TURN server nodig)
- iOS push notificaties (Apple developer account nodig)
- SMS verificatie (Twilio betaald account nodig)

---

## 📋 CLAUDE SESSIE INSTRUCTIES

Start een nieuwe sessie met:
```
Ik werk aan VenTrax. De code staat op /opt/VenTrax/
Lees eerst /opt/VenTrax/BACKLOG.md voor de volledige context.
Begin met Prio 0 items, dan Prio 1.
Test altijd met: cd /opt/VenTrax && python -c "from app import init_db; init_db()"
Scan templates na elke wijziging op {#CSS bugs: grep -n '{#[a-zA-Z]' templates/*.html
```

## 🏗️ TECHNISCHE STACK

- Flask + gevent-websocket (NIET flask-sock)
- SQLite via SQLAlchemy
- Jinja2 templates
- Leaflet.js + Esri satelliet tiles
- Docker op poort 5001:5000
- .env voor configuratie (APP_URL of BASE_URL)

## ⚠️ BEKENDE VALKUILEN

1. `{#` in CSS (bijv. `{#id{...}}`) = Jinja2 comment bug → altijd spatie toevoegen: `{ #id{} }`
2. Jinja2 macros VOOR gebruik definiëren (niet erna)
3. flask-sock NIET gebruiken — geeft greenlet threading crash
4. Macro's in lobby.html moeten vóór `{% block content %}` staan

---

## 🆕 Nieuwe features — backlog update 2026-06-04

### Gameplay mechanics
- [ ] **Detector Laser** — Speler plaatst laser op kaart (1 min stilstaan). Als tegenstander binnen x meter komt → melding bij plaatser. Knipperend icoontje voor x minuten. Alleen via dropbox te vinden.
- [ ] **Landmijn** — Speler vindt landmijn in dropbox. Plaatst op kaart. Andere speler komt erbinnen x meter → 1 minuut stilstaan verplicht (bomontmanteling, max 30m bewegen). Bewegen = straf: Hunters -3pt + volgende runner-update geskipt; Runners -3pt + locatie live x minuten.
- [ ] **Tripwire** — Gevonden in dropbox. Plaatsbaar op dropbox van tegenstander. Als die opent → vernietigd + locatie melding naar alle spelers.
- [ ] **Dropboxes** — Verschijnen op random plekken op kaart. Drie types: iedereen / runners only / hunters only. Inhoud: punten, laser, landmijn, tripwire en meer. Openen vanaf 50m afstand. Optie: direct of wachttijd. Niet in water/achtertuinen (via kaartlaag). 
- [ ] **Speelveld** — Maker tekent speelgebied door punten te zetten op kaart. Buiten = melding → terug. Daarna pauze voor iedereen.
- [ ] **Runner → Hunter conversie** — Gepakte runner kan Hunter worden (instelbaar). Min. 3 runners nodig. Runners krijgen extra ×0.5 punten.
- [ ] **Hunter → Runner conversie** — Optioneel. Min. 2 hunters nodig.
- [ ] **Cooldown 5 min na spel** — Voorkomt misbruik naam-raden via snel nieuw spel.
- [ ] **Punten bij vroegtijdig stoppen** — Maker stopt voor einde: punten = (voorbij%) − 10%. Dus bij 50% voorbij: 40% van behaalde punten.
- [ ] **Aantallen eerlijk houden** — 1 runner vs 2 hunters = runner krijgt extra hulp (punten/offline). Schaalbaar systeem.
- [ ] **Proxy chat** — Stuur chat naar iedereen binnen x meter (bijv. 500m). Kost punten.
- [ ] **Chat onderscheppen** — Voor x minuten zie je de chat van het andere team. Kost punten + cooldown.
- [ ] **Foto locatie ophalen** — Kost punten. Geeft oude info terug (kan verouderd zijn).

### Nieuwe "extra's" (speciaal acties)
- [ ] **Glitch** — Runner: locatie springt elke 5s naar random plek binnen 100m. Hunters weten niet exact waar je bent. Dropbox: "Speedcoil".
- [ ] **Hacker** — Runner teleporteert naar andere plek binnen 500m. Dropbox: "Laptop".
- [ ] **Kortsluiting** — Hunters zien x seconden niets. Melding: "Storing — een runner struikelde over een kabel". Dropbox: "Kabel".
- [ ] **Snitch** — Runner deelt locatie van andere runner (kost 10pt).
- [ ] **Hunter deelt afstand** — Stuurt eigen afstand naar alle runners (5pt, cooldown).
- [ ] **Naam raden** (Hunters EN Runners) — Min. 2 van dezelfde rol. Klik schuilnaam → kies echte naam. Goed = +3pt, fout = -10pt. Cooldown 5min na spel.

### Platform
- [ ] **VenTrax = platform met meerdere speltypes** — Homepage: leaderboard bovenaan + spel-tegels. game_type in DB voor meerdere spellen.

### UI fixes (uit commentaar)
- [ ] **Schuilnaam verborgen in lobby** — Pas tonen IN het spel.
- [ ] **Logo in QR code** — Logo in midden van QR.
- [ ] **Auto-zoom kaart hunter** — Alle runners + jijzelf in beeld.
- [ ] **Auto-zoom kaart runner** — Eigen locatie ingezoomd, geen flikkering.
- [ ] **Zoom knoppen verwijderd** — Pinch-to-zoom voldoende op mobiel.
- [ ] **Feed badge met getal** — Aantal ongelezen foto's als cijfer.
- [ ] **Changelog automatisch updaten** — Niet alleen handmatig via admin.

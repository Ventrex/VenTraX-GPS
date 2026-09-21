# VenTrax - Next Session Backlog
*Opgeslagen op het einde van sessie, uitvoeren in volgorde van prioriteit*

---

## 🔴 PRIO 0 — Showstoppers (spel werkt niet)

### BUG: Game dashboard 500 error
- **Oorzaak**: `{#runnerPanel` in CSS → Jinja2 ziet dit als comment tag
- **Fix**: Al gedaan in v5 (`{ #runnerPanel` met spatie)
- **Actie**: Controleer of v5.zip is uitgerold

### BUG: Lobby realtime join werkt niet
- Maker ziet nieuwe speler NIET zonder page refresh
- WebSocket `player_joined` event wordt verstuurd maar DOM update faalt
- **Fix**: Controleer `addPlayerToDOM()` in lobby.html — mogelijk race condition met connectWS()

### BUG: Target zetten doet niets zichtbaars (opgelost, live testen)
- Hunter zet target → runner krijgt GEEN scherm "Je bent een Target!"
- Andere hunters zien ook niets
- **Fix**: WS `target_set` event is aanwezig in backend, frontend handler ontbreekt/werkt niet
- Runner moet rood scherm krijgen met countdown timer
- Hunters (allemaal) moeten melding zien: `<Naam> heeft target gezet op <Schuilnaam>`

### BUG: QR code scan stuurt niet door naar spel
- Scannen QR → moet direct naar /join?code=XXXX gaan en auto-invullen
- Huidige flow: scan → handmatig code invullen → joinen
- **Fix**: QR URL = `{BASE_URL}/join?code={code}` — join.html moet `?code=` prefill verwerken

### BUG: Countdown toont niets 5 seconden lang (opgelost, live testen)
- Start knop → 5 sec wachten zonder feedback → dan pas countdown
- **Fix**: Stuur `countdown_start` WS event DIRECT bij klikken, niet na gevent.sleep()
- Frontend moet overlay METEEN tonen, server start spel op de achtergrond

### BUG: Knoppen onderin verdwijnen als je panel opent
- Panel opent maar klikken op balk is niet precies genoeg
- **Fix**: Bottombar hoogte vergroten (min 64px), touch targets groter maken (48px min)
- Panel sluiten via: nogmaals klikken op zelfde knop OF kruisje in panel header

### BUG: Chat werkt niet zichtbaar
- Bericht sturen → niemand ziet het, ook afzender niet
- **Fix**: `addChatMsg()` werkt alleen als panel open is — ook berichten opslaan in array
- Chat panel moet berichten tonen bij openen (history laden)
- Teller met ongelezen berichten op knop

---

## 🔴 PRIO 1 — Onwerkbaar

### Rol wisselen in lobby
- Runner/Hunter keuze moet aanpasbaar zijn VOOR start
- Validatie pas bij "Start spel" knop
- **Fix**: Voeg "Rol wijzigen" knop toe in lobby die join_team opnieuw aanroept

### Schuilnaam verborgen in lobby
- Spelers zien nu hun eigen codename in de lobby — dit mag NIET
- **Fix**: Verberg codenames in lobby, toon pas in game_dashboard

### Camera verplicht als foto-opdrachten aan staan
- Als `feat_photo_missions=True` → camera toestemming VERPLICHT voor start
- **Fix**: `api_start_game` check: if game.feat_photo_missions and not p.camera_enabled → error

### Offline knop visible bij alle hunters als runner offline gaat (deels opgelost, live testen)
- Hunters moeten melding krijgen: `<SCHUILNAAM> is offline! Onzichtbaar voor X minuten`
- Timer tonen bij marker op kaart (countdown hoelang offline nog duurt)
- Na aflopen offline → nieuwe locatie direct naar hunters sturen

### Dropdown "Spel" menu werkt niet op desktop
- Nav dropdown werkt niet bij direct klik
- **Fix**: CSS `:hover` fix in base.html — mogelijk conflict met nieuwe styles

---

## 🟠 PRIO 2 — Moet opgelost voor andere features

### VenTrax = Platform Met Meerdere Speltypes
- Homepage wordt spel-keuzescherm
- Leaderboard BOVEN de fold (prominent, niet onderaan)
- Spel-tegels: VenTrax en toekomstige speltypes met eigen logo
- `game_type` kolom toevoegen aan Game model
- Structuur klaar voor toekomstige spellen

### Admin Checklist & TODO systeem
- Admins kunnen items afvinken als getest/werkend
- Of markeren als "werkt niet" + commentaar
- Auto-genereer Claude AI prompt bij "werkt niet" items
- Template: `admin_checklist.html`

### Uitgebreider waarschuwingssysteem gebruikers
- 3-strikes systeem: Waarschuwing 1 → punten aftrek, Waarschuwing 2 → week ban, Waarschuwing 3 → perm ban
- User model: `warnings` (int), `banned_until` (datetime), `ban_reason` (text), `warning_history` (JSON)
- Elke waarschuwing stuurt een mail naar de gebruiker
- Gebruiker kan waarschuwing aanvechten (appeal formulier)
- In admin gebruikersoverzicht: knop "Waarschuwing geven" + commentaar veld

### Login/sessie overzicht
- Gebruiker ziet welke devices/IPs ingelogd zijn
- Kan sessies verwijderen die ze niet kennen
- Model: `UserSession` (id, user_id, ip, user_agent, created_at, last_seen, revoked)

### IP-gebaseerde checks
- Waarschuwing bij login vanuit onbekend land/IP
- Mail sturen bij verdachte aanmeldpoging
- IP-regio check (gebruik gratis ip-api.com of vergelijkbaar)
- Admin kan IP-ranges blokkeren

### Activiteitenlog uitbreiden
- Log: wie logt in, wie maakt spel aan, wie stuurt chat, wie gebruikt offline knop
- Bestaande ActivityLog model uitbreiden met meer event types

---

## 🟡 PRIO 3 — Verbetert ervaring aanzienlijk

### QR code fullscreen bij klikken
- QR code in lobby → klikken → fullscreen overlay met sluitknop
- Makkelijker te scannen voor andere telefoons

### Zoom kaart automatisch
- Runner: zoom zodat runner goed zichtbaar is (level 16-17)
- Hunter: zoom zodat ALLE runners + zichzelf in beeld zijn (auto-fit bounds)
- Tenzij runner offline is → niet meenemen in bounds

### Runner → Hunter conversie (extra speltype)
- Als runner gepakt wordt: keuze scherm "Jij bent nu een Hunter!"
- Rol wisselt naar hunter in DB
- Runners krijgen melding: `<SCHUILNAAM> is gepakt en nu een Hunter!`
- Runners krijgen ×0.5 punten bonus als een mede-runner hunter wordt

### Naam raden systeem
- Hunter klikt op runner → keuze: Target / Pakken / Naam raden
- Naam raden: lijst van echte namen (van runners) → hunter kiest
- Goed: +5 punten, Fout: -10 punten
- Real name wordt onthuld als correct geraden

### Afstand badge verplaatsen (runner)
- Afstand tot dichtste hunter: van rechtsboven naar linksboven
- Camera knop blijft rechtsboven

### Hunters krijgen ook pauze knop
- Pauze niet alleen voor runners maar ook hunters
- Zelfde 10-sec bevestiging + reden systeem

### Feed teller ongelezen foto's
- Nummer badge op Feed knop in bottombar
- Reset als je feed opent

### Nieuws Feed disclaimer onderaan houden
- Disclaimer moet ALTIJD onderaan de feed blijven, ook als er veel artikelen zijn
- **Fix**: `position: sticky; bottom: 0` of disclaimer altijd als laatste item renderen

### Nieuwsbrief abonnement
- Checkbox "Schrijf me in voor nieuwsbrief" in account instellingen
- Bij nieuw goedgekeurd artikel → mail naar ingeschreven gebruikers
- Uitschrijflink in elke mail (unsubscribe token)
- User model: `newsletter_subscribed` (boolean, al aanwezig maar niet gebruikt)

### Temp ban + commentaar in admin gebruikersbeheer
- Naast bestaande acties: "Tijdelijk bannen" met einddatum
- Commentaar veld per gebruiker (admin notes, zichtbaar voor alle admins)
- Waarschuwingsgeschiedenis tonen per gebruiker

---

## 🟢 PRIO 4 — Leuke toevoegingen

### Moeilijkheidsgraad aanpasbaar maar met multiplier impact
- Als je "Makkelijk" kiest maar daarna iets nog makkelijker maakt → multiplier zakt
- Live preview van multiplier aanpassing in new_game.html (al deels aanwezig)
- **Fix**: Multiplier altijd herberekenen bij wijziging, ook na preset keuze

### Snitch, Hacker, Glitch activeer-knoppen
- Backend aanwezig, UI knoppen ontbreken
- In info panel of apart abilities panel

### Offline knop kopen na 50-80% spel (15 punten)

### Naam ontmaskeren kopen (10 punten)

### Hunter deelt afstand met runners (5 pt, cooldown)

### Record snelste vangst bijhouden

---

## 🔵 PRIO 5 — Nice-to-have

### Animerende achtergrond homepage

### Zoek-de-locatie foto spelmodus

### Volledig CMS homepage

### Lokale fonts (Syne + DM Sans woff2)

### Font Awesome lokaal hosten

---

## 📋 TECHNISCHE NOTITIES voor volgende sessie

### Hoe te starten
```bash
cd /opt/VenTrax
python -c "from app import init_db; init_db(); print('OK')"
# Check templates
python3 -c "
from jinja2 import Environment, FileSystemLoader
env = Environment(loader=FileSystemLoader('templates'))
import os
for f in os.listdir('templates'):
    if f.endswith('.html'):
        try: env.get_template(f)
        except Exception as e: print(f'ERROR {f}:', e)
print('Template check done')
"
```

### Belangrijke bestanden
- `app.py` — volledige Flask backend (~1700 regels)
- `templates/base.html` — nav, tooltip, toast systeem
- `templates/base_game.html` — game-only base (geen nav)
- `templates/game_dashboard.html` — fullscreen game UI
- `templates/lobby.html` — lobby met GPS/camera/QR
- `static/img/logo_round.png` - VenTrax logo (door gebruiker geplaatst)
- `static/img/bg_default.png` — achtergrond (door gebruiker geplaatst)

### WebSocket hub
- Native gevent-websocket (GEEN flask-sock!)
- WS route: `/ws/<code>` voor spel, `/ws/news` voor nieuws
- WSHub class in app.py regelt broadcasts per room

### Bekende Jinja2 gotcha
- CSS `{#id` wordt gezien als Jinja2 comment start
- Altijd spatie: `{ #id` of schrijf als `[id="x"]`

### Database modellen aanwezig
- User, Game, GamePlayer, Target, Post, PostLike
- NewsArticle, NewsLike, ChatMessage
- Report, ActivityLog, Changelog
- Nog te maken: UserSession, UserWarning

### .env variabelen
- `BASE_URL` of `APP_URL` (beide werken)
- `SECRET_KEY`, `DATABASE_URL`, `PORT`
- `MAIL_SERVER`, `MAIL_PORT`, `MAIL_USE_TLS`, `MAIL_USERNAME`, `MAIL_PASSWORD`

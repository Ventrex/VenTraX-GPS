# VenTrax-GPS - werkafspraken voor Claude

## Git
- **Zet wijzigingen altijd direct in `main`**: werk op een branch, push, maak een PR en merge die zelf (squash) zodra de tests slagen. De eigenaar (Ventrex) wil op de server alleen `git pull` hoeven te doen.
- Vraag eerst bij iets onomkeerbaars of groots (database wissen, data verwijderen, geheimen aanpassen).
- Commit-berichten in het Engels of Nederlands, kort en duidelijk.

## Taal
- De eigenaar spreekt Nederlands. Antwoorden en UI-teksten in het Nederlands, in simpele taal.
- Leg server-stappen uit als copy/paste-commando's. Op de server heet het `docker compose` (met spatie).
  Geef geen `git checkout`-stappen die een token vragen; `git checkout` en `git merge --ff-only origin/main` doen dat niet.

## Project
- Flask + SQLite + gevent-websocket, `app.py` is de hele backend, templates in `templates/`, JS in `static/js/`.
- Database-kolommen toevoegen: via `ensure_column(...)` in `init_db()` (geen Alembic).
- Uploads staan in volumes (`static/uploads`, `static/backgrounds`, `static/audio`, `static/qr`); zie `docker-compose.yml`.
- Thema's (`SoundTheme`) bepalen kleuren, lettertypes, logo, achtergrond en geluiden. **Klassiek** (OLED-zwart + donkerrood) is de basis: nieuwe thema's beginnen als kopie.
- Alle admin-schermen horen in het Admin Panel (`templates/_admin_nav.html`); maak geen losse admin-menu's.
- Teksten die de admin moet kunnen aanpassen: voeg ze toe aan `SITE_TEXTS` en gebruik `t('sleutel')` in templates.

## Testen
- `pip install -r requirements.txt pytest` (Python 3.12; gevent 24.2.1 bouwt niet op 3.13) en daarna `python -m pytest -q`.
- Bij UI-wijzigingen: start de app lokaal en kijk met Playwright/Chromium (`/opt/pw-browsers`) naar de schermen.

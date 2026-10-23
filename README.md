# VenTrax

Real-time GPS buitenspel: Hunters zoeken Runners op een live kaart.

## Snel starten met Docker

```bash
docker-compose up --build
```

Open `http://localhost:5001` in je browser. De eerste persoon die zich registreert wordt automatisch admin.

## Hoe speel je?

1. Admin maakt bij eerste opstart een account aan.
2. Spelers registreren en worden goedgekeurd.
3. Maak een spel aan en deel de 6-letterige code.
4. Iedereen joint, kiest Hunter of Runner en zet GPS aan.
5. De maker start het spel.

## Belangrijke instellingen

- Speelduur en voorsprong voor runners.
- Hunter locatie-update interval.
- Target systeem met duur en cooldown.
- Runner afstand-update interval.
- Offline knop met maximale duur.
- Pauze, speelveld, extra's, classes en lootboxes.

## Thema's, geluiden en teksten (admin)

- **Admin > Geluiden**: maak thema's (bijv. Halloween) en zet per gebeurtenis een of meer geluidjes (start, echte start, einde, lootbox, Hunter in de buurt, buiten de zone, offline, target, ...). Zonder upload speelt een ingebouwd geluid. Het standaardthema bepaalt ook het uiterlijk van de site; de spelmaker kan bij Nieuw Spel een ander thema kiezen.
- **Admin > Pagina's** en **Teksten**: eigen pagina's (`/p/naam`) en teksten op home, menu en handleiding aanpassen zonder code.
- Geüploade geluiden staan in `static/audio/themes` (volume-mount in `docker-compose.yml`).
- Telefoons: eenmalige setup (locatie + geluid) en "installeer als app" (PWA) zodat toestemmingen onthouden worden.

## Bots

Creator kan in de lobby bots toevoegen (Runner of Hunter, max 8 per spel) om alleen te testen of een groep aan te vullen.
- Kaartdata komt van OpenStreetMap via de Overpass API (`OVERPASS_URL`, standaard de publieke server; resultaten worden 7 dagen gecachet in `instance/terrain`). Op een eigen Overpass-server kan ook.
- Water, gebouwen, spoor en snelwegen zijn geblokkeerd; bosjes/struiken half zo snel; paden, wegen en bruggen altijd begaanbaar (dus ook tunnels en bruggen over water/spoor).
- Snelheid volgt de moeilijkheid: makkelijk 1,0 m/s, gemiddeld 1,4 m/s, moeilijk 2,0 m/s (wandelen, niet rennen).
- Beperkingen: tuinen en hekken staan niet op de kaart; OSM kan fout of verouderd zijn; bots weten waar iedereen is, gebruiken geen offline/pauze, en tikken binnen 6 m (de kaart heeft 6 m-cellen). Zonder kaartdata lopen ze over open terrein en krijgen spelers een melding.

## Lokaal draaien

```bash
pip install -r requirements.txt
python run.py
```

App draait standaard op `http://localhost:5000`.

## Structuur

```text
VenTrax/
  app.py
  run.py
  templates/
  static/
  instance/
  Dockerfile
  docker-compose.yml
```

Let op: de bestaande SQLite database heet nog `venfaye.db` voor compatibiliteit met eerdere releases. Hernoem die pas bewust met een migratie/backup.

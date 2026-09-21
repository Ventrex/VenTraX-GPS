# Cloudflare-instellingen voor VenTrax

Dit document beschrijft welke instellingen je **handmatig** in het Cloudflare
dashboard moet maken om registratie-bots, scanners en nepaccounts te beperken.
De applicatie zelf doet ook een deel van het werk (Turnstile-validatie,
rate limiting, e-mailverificatie, honeypot) - zie de code in `app.py`
(`verify_turnstile`, `check_register_rate_limit`, `get_client_ip`) en
`templates/register.html`. Dit document gaat over de Cloudflare-kant die dat
aanvult.

Uitgangspunt overal hieronder: **Managed Challenge voor verdacht verkeer,
nooit een harde blokkade van heel Nederland of van gewone bezoekers.**

## 1. Turnstile widget aanmaken

1. Log in op [dash.cloudflare.com](https://dash.cloudflare.com) → **Turnstile**
   (linkermenu, onder "Security" of via de zoekbalk).
2. **Add widget**.
   - **Widget name**: bijv. `VenTrax registratie`.
   - **Domain**: `ventrax.ventrex.cc` (en eventueel je testdomein).
   - **Widget mode**: "Managed" - dit toont meestal geen puzzel, alleen bij
     verdachte bezoekers een korte interactieve check. Dat is de instelling
     die het minste hinder geeft voor normale gebruikers.
3. Na het aanmaken krijg je een **Site Key** en een **Secret Key**.
4. Zet deze in je `.env` op de server (nooit committen naar git):
   ```
   TURNSTILE_SITE_KEY=<site key>
   TURNSTILE_SECRET_KEY=<secret key>
   ```
5. Herstart de app. Zolang `TURNSTILE_SECRET_KEY` leeg is, slaat de app de
   Turnstile-check over (met een waarschuwing in de logs) - handig voor lokale
   ontwikkeling, maar zet 'm altijd aan in productie.

### Lokaal testen zonder een echte widget

Cloudflare publiceert vaste testsleutels die altijd hetzelfde resultaat geven,
handig voor lokale development (zie de officiële Turnstile-documentatie voor
de actuele lijst - zoek naar "Turnstile testing"). Zet in je lokale `.env`
een sitekey/secretkey-paar dat altijd slaagt, zodat je de hele flow lokaal
kan doorlopen zonder een productiewidget aan te maken.

## 2. Environment variables (samenvatting)

| Variabele | Waar vandaan | Verplicht |
|---|---|---|
| `TURNSTILE_SITE_KEY` | Turnstile widget (stap 1) | Aanbevolen, anders staat de bot-check uit |
| `TURNSTILE_SECRET_KEY` | Turnstile widget (stap 1) | Idem |
| `TRUSTED_PROXY_CIDRS` | Alleen invullen als er een eigen reverse proxy tussen Cloudflare en de app staat (zie §7) | Nee |

## 3. Aanbevolen WAF Custom Rules

Ga naar je zone → **Security → WAF → Custom rules**. Voeg onderstaande regels
toe (van specifiek naar generiek; volgorde maakt uit in Cloudflare).

### 3a. Blokkeer bekende probe-paden die VenTrax niet gebruikt

Deze paden horen bij WordPress, phpMyAdmin, .env-scanners e.d. - VenTrax
gebruikt ze nooit, dus een treffer hier is altijd een scanner.

- **Rule name**: `Block known probe paths`
- **Expression** (URI Path bevat één van):
  ```
  (http.request.uri.path contains "/.env") or
  (http.request.uri.path contains "/.git/") or
  (http.request.uri.path contains "/wp-login.php") or
  (http.request.uri.path contains "/wp-admin") or
  (http.request.uri.path contains "/xmlrpc.php") or
  (http.request.uri.path contains "/phpmyadmin") or
  (http.request.uri.path contains "/.aws/") or
  (http.request.uri.path contains "/config.php") or
  (http.request.uri.path contains "/vendor/phpunit")
  ```
- **Action**: **Block**.

### 3b. Managed Challenge voor verdacht registratieverkeer

In plaats van blokkeren: een Managed Challenge geeft echte bezoekers een
seconde vertraging, maar houdt de meeste bots tegen.

- **Rule name**: `Challenge suspicious registration traffic`
- **Expression**:
  ```
  (http.request.uri.path eq "/register") and (cf.threat_score gt 14)
  ```
- **Action**: **Managed Challenge**.

Pas de threat-score-drempel aan op basis van wat je in de Security-analytics
ziet; begin conservatief (hoger getal = strenger/minder false positives).

### 3c. Nooit: land-brede blokkade

Voeg **geen** regel toe als `ip.geoip.country eq "NL"` met action Block. Als
je geo-gebaseerd iets wil doen, gebruik dan een Managed Challenge voor landen
waar je normaal geen spelers verwacht, nooit een Block - en nooit voor NL/BE
waar je eigen spelers zitten.

## 4. Aanbevolen Rate Limiting Rules

Ga naar **Security → WAF → Rate limiting rules**. Dit is de edge-laag die de
in-app rate limiting (max. 3 registraties per IP per 10 min, zie `app.py`)
aanvult - Cloudflare's laag werkt ook als de app herstart (in-app teller is
per proces) en stopt misbruik al vóór het je server bereikt.

### 4a. `/register` beschermen

- **Rule name**: `Rate limit /register`
- **Expression**: `(http.request.uri.path eq "/register") and (http.request.method eq "POST")`
- **Characteristics**: IP address.
- **Period**: 10 minutes.
- **Requests**: 5 (iets ruimer dan de in-app limiet van 3, zodat de nette
  Nederlandstalige foutmelding van de app meestal als eerste getoond wordt).
- **Action**: Managed Challenge (niet meteen Block - een gedeeld IP,
  bijv. een school of kantoor, mag niet meteen dichtslaan).

### 4b. `/login` beschermen (brute-force)

- **Rule name**: `Rate limit /login`
- **Expression**: `(http.request.uri.path eq "/login") and (http.request.method eq "POST")`
- **Characteristics**: IP address.
- **Period**: 5 minutes.
- **Requests**: 10.
- **Action**: Managed Challenge.

Let op: dit raakt **geen** bestaande sessies of accounts - het vertraagt
alleen een IP dat heel veel inlogpogingen in korte tijd doet.

## 5. Bot Fight Mode / Super Bot Fight Mode

Onder **Security → Bots**:

- **Bot Fight Mode** is gratis op elk plan en zet automatisch bekende bots
  (scrapers, oude libraries, misbruikte user-agents) op een Managed
  Challenge. Zet dit aan als het nog niet aan staat - lage kans op
  false positives voor echte spelers.
- **Super Bot Fight Mode** / **Bot Management** (Pro/Business/Enterprise,
  afhankelijk van plan) geeft fijnmaziger opties (JS-detectie,
  verified-bot-uitzonderingen). Alleen relevant als je plan dit aanbiedt -
  check je huidige plan onder **Overview** in het dashboard voordat je dit
  instelt, anders zie je de optie niet.

## 6. Login/register endpoints extra beschermen (samenvatting)

- Turnstile: alleen op `/register` (stap 1) - een puzzel bij elke login is
  onnodige hinder voor bestaande gebruikers en is niet gevraagd.
- Rate limiting: §4a (`/register`) en §4b (`/login`).
- WAF custom rule §3b voor verdacht verkeer richting `/register`.
- Overweeg later hetzelfde patroon voor `/forgot` (wachtwoord-reset-aanvraag)
  als je daar ook misbruik ziet - nu nog niet toegevoegd om niet vooruit te
  lopen op een probleem dat er nog niet is.

## 7. Reverse proxy / hoe de app het echte IP bepaalt

De app gebruikt `get_client_ip()` (in `app.py`) om het echte bezoekers-IP te
bepalen:

1. Het kijkt naar de TCP-peer van het binnenkomende request
   (`request.remote_addr`) - dit kan een client zelf **niet** vervalsen.
2. Alleen als die peer een bekend Cloudflare-IP is (of staat in
   `TRUSTED_PROXY_CIDRS`), vertrouwt de app de `CF-Connecting-IP`-header voor
   het echte IP.
3. `X-Forwarded-For` wordt **nooit** vertrouwd voor beveiligingsbeslissingen
   (rate limiting, logging) - die header kan een aanvaller zelf meesturen.

**Wat betekent dit voor jouw deployment?**

- **Als Cloudflare rechtstreeks naar de container/host verbindt** (bijv. via
  Cloudflare Tunnel, of DNS-proxy direct naar de exposed poort): dit werkt
  out-of-the-box, niets aan te passen.
- **Als er een eigen reverse proxy (nginx, Caddy, Traefik) tussen Cloudflare
  en deze app in staat**: die proxy is dan de laatste hop die de app ziet, niet
  Cloudflare zelf. Zet in dat geval het interne IP/subnet van die proxy
  (bijv. `127.0.0.1/32` of het Docker-netwerk-subnet) in `TRUSTED_PROXY_CIDRS`,
  én zorg dat die proxy zelf de originele `CF-Connecting-IP`-header
  ongewijzigd doorstuurt (de meeste reverse proxies doen dit standaard, maar
  controleer je proxy-config).
- **Controleer of de origin server (poort 5001/5000) ook rechtstreeks
  bereikbaar is zonder Cloudflare** (bijv. via het kale server-IP of een
  interne DNS-naam). Zo ja, kan een aanvaller Cloudflare omzeilen en zelf een
  `CF-Connecting-IP`-header verzinnen. Dat is dan geen probleem voor de app
  zelf (die trust die header dan sowieso niet, want de TCP-peer is geen
  Cloudflare-IP) - maar het omzeilt wél al je WAF/Turnstile/rate-limiting op
  Cloudflare-niveau. Blokkeer in dat geval rechtstreeks verkeer op firewall-
  niveau (bijv. alleen Cloudflare's IP-ranges toestaan op de poort van de
  origin server), of gebruik een Cloudflare Tunnel zodat de origin sowieso
  nooit een publiek IP heeft.

## 8. Checklist

- [ ] Turnstile widget aangemaakt, site key + secret key in `.env`
- [ ] `TURNSTILE_SECRET_KEY` bevestigd ingesteld in productie (niet leeg)
- [ ] WAF-regel: bekende probe-paden blokkeren (§3a)
- [ ] WAF-regel: Managed Challenge voor verdacht `/register`-verkeer (§3b)
- [ ] Rate limiting: `/register` (§4a)
- [ ] Rate limiting: `/login` (§4b)
- [ ] Bot Fight Mode aan
- [ ] Gecontroleerd of de origin server direct bereikbaar is buiten Cloudflare om (§7), en zo nodig afgeschermd
- [ ] `TRUSTED_PROXY_CIDRS` ingesteld, alleen als er een eigen reverse proxy tussen Cloudflare en de app staat

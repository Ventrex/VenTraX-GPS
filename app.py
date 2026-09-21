"""
VenTrax - Real-time GPS hunting game
WebSockets: native gevent-websocket (fixes the threading/greenlet conflict)
"""
import os, json, random, string, math, time, threading, io, base64, html, mimetypes, ipaddress
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import (Flask, render_template, request, redirect, url_for,
                   flash, jsonify, send_from_directory, session)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text as sql_text
from flask_login import (LoginManager, UserMixin, login_user, logout_user,
                         login_required, current_user)
from flask_mail import Mail, Message
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from itsdangerous import URLSafeTimedSerializer
from PIL import Image, ImageDraw
import qrcode
from qrcode.image.styledpil import StyledPilImage
import requests as http_requests

# gevent-websocket (NOT flask-sock â€” that causes greenlet threading conflicts)
from geventwebsocket import WebSocketError
from geventwebsocket.handler import WebSocketHandler

# â”€â”€ App â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'venfaye-dev-secret-change-in-prod')
_db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'instance', 'venfaye.db')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', f'sqlite:///{_db_path}')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER']  = os.path.join(os.path.dirname(__file__), 'static', 'uploads')
app.config['BG_FOLDER']      = os.path.join(os.path.dirname(__file__), 'static', 'backgrounds')
app.config['MAX_CONTENT_LENGTH'] = 8 * 1024 * 1024

# Mail config â€” set via environment variables or .env
app.config['MAIL_SERVER']   = os.environ.get('MAIL_SERVER',   'smtp.gmail.com')
app.config['MAIL_PORT']     = int(os.environ.get('MAIL_PORT', '587'))
app.config['MAIL_USE_TLS']  = os.environ.get('MAIL_USE_TLS', 'true').lower() == 'true'
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME', '')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD', '')
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get('MAIL_DEFAULT_SENDER', 'noreply@venfaye.nl')
app.config['BASE_URL'] = os.environ.get('BASE_URL', os.environ.get('APP_URL', 'http://localhost:5001'))

# Cloudflare Turnstile (bot protection on registration) - see docs/CLOUDFLARE_SECURITY.md.
# Leave TURNSTILE_SECRET_KEY empty for local dev: the check is then skipped (logged loudly)
# instead of locking registration entirely.
app.config['TURNSTILE_SITE_KEY']   = os.environ.get('TURNSTILE_SITE_KEY', '')
app.config['TURNSTILE_SECRET_KEY'] = os.environ.get('TURNSTILE_SECRET_KEY', '')

# Extra CIDRs (comma-separated) to trust for CF-Connecting-IP, on top of Cloudflare's own
# ranges - e.g. a local reverse proxy sitting between Cloudflare and this app. Never trust
# X-Forwarded-For; only Cloudflare's own header, and only from a verified hop.
app.config['TRUSTED_PROXY_CIDRS'] = [c.strip() for c in os.environ.get('TRUSTED_PROXY_CIDRS', '').split(',') if c.strip()]

ALLOWED_IMG   = {'png', 'jpg', 'jpeg', 'webp'}
ALLOWED_AUDIO = {'webm', 'ogg', 'mp3', 'm4a', 'wav'}
AUDIO_FOLDER  = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'audio')
# Code chars â€” no confusable chars (0/O, 1/I/L, 2/Z, 5/S, 6/G, 8/B)
CODE_CHARS = 'ACDEFHJKMNPQRTUVWXY3479'

for _d in [app.config['UPLOAD_FOLDER'], app.config['BG_FOLDER'],
           os.path.join(os.path.dirname(__file__), 'instance'),
           os.path.join(os.path.dirname(__file__), 'logs'),
           os.path.join(os.path.dirname(__file__), 'static', 'qr'),
           os.path.join(os.path.dirname(__file__), 'static', 'fonts')]:
    os.makedirs(_d, exist_ok=True)

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Log in om verder te gaan.'
mail = Mail(app)
serializer = URLSafeTimedSerializer(app.config['SECRET_KEY'])

# â”€â”€ Client IP (Cloudflare-aware) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Cloudflare's published IPv4/IPv6 ranges (https://www.cloudflare.com/ips/).
# Update this list if Cloudflare changes it - see docs/CLOUDFLARE_SECURITY.md.
CLOUDFLARE_IP_RANGES = [
    '173.245.48.0/20', '103.21.244.0/22', '103.22.200.0/22', '103.31.4.0/22',
    '141.101.64.0/18', '108.162.192.0/18', '190.93.240.0/20', '188.114.96.0/20',
    '197.234.240.0/22', '198.41.128.0/17', '162.158.0.0/15', '104.16.0.0/13',
    '104.24.0.0/14', '172.64.0.0/13', '131.0.72.0/22',
    '2400:cb00::/32', '2606:4700::/32', '2803:f800::/32', '2405:b500::/32',
    '2405:8100::/32', '2a06:98c0::/29', '2c0f:f248::/32',
]

def _parse_cidrs(cidrs):
    nets = []
    for c in cidrs:
        try:
            nets.append(ipaddress.ip_network(c, strict=False))
        except ValueError:
            app.logger.warning(f"Ignoring invalid CIDR in trusted-proxy config: {c!r}")
    return nets

_CLOUDFLARE_NETWORKS = _parse_cidrs(CLOUDFLARE_IP_RANGES)

def _trusted_forwarder_networks():
    return _CLOUDFLARE_NETWORKS + _parse_cidrs(app.config['TRUSTED_PROXY_CIDRS'])

def get_client_ip():
    """Real client IP, Cloudflare-aware.

    Only trusts the CF-Connecting-IP header when the request's actual TCP peer
    (request.remote_addr - not spoofable by the client) is itself a known
    Cloudflare edge IP, or an operator-configured trusted proxy (TRUSTED_PROXY_CIDRS).
    Otherwise - e.g. the app is reachable directly, bypassing Cloudflare - falls back to
    the real peer address and never trusts X-Forwarded-For for security decisions.
    """
    peer = request.remote_addr
    if peer:
        try:
            peer_ip = ipaddress.ip_address(peer)
            if any(peer_ip in net for net in _trusted_forwarder_networks()):
                cf_ip = request.headers.get('CF-Connecting-IP', '').strip()
                if cf_ip:
                    try:
                        ipaddress.ip_address(cf_ip)  # validate it's a real IP, not garbage
                        return cf_ip
                    except ValueError:
                        pass
        except ValueError:
            pass
    return peer or 'unknown'

# Stoere schuilnamen pool
CODENAMES_HUNTERS = [
    'Batman','Wolverine','Inspector Gadget','James Bond','Terminator',
    'RoboCop','Snake Eyes','Ghost Rider','Punisher','Nick Fury',
    'John Wick','El Diablo','Dredd','Hawkeye','Falcon',
]
CODENAMES_RUNNERS = [
    'Deadpool','Blade Runner','Flash','Quicksilver','Nightcrawler',
    'Phantom','Shadow','Ghost','Specter','Venom',
    'Black Panther','Spiderman','Neo','Trinity','Morpheus',
]

# â”€â”€ WebSocket Hub â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

BADGE_DEFS = {
    # FontAwesome icon names. Keep these ASCII to avoid broken emoji encoding.
    'first_catch':    {'icon': 'fa-crosshairs', 'name': 'Eerste Vangst', 'desc': 'Je eerste runner gepakt'},
    'hunter_x5':      {'icon': 'fa-trophy', 'name': 'Jager Elite', 'desc': '5 runners gepakt in totaal'},
    'hunter_x20':     {'icon': 'fa-crown', 'name': 'Meesterjager', 'desc': '20 runners gepakt in totaal'},
    'speed_hunter':   {'icon': 'fa-bolt', 'name': 'Bliksemjager', 'desc': 'Runner gepakt binnen 15 min'},
    'targetmaster':   {'icon': 'fa-bullseye', 'name': 'Targetmaster', 'desc': '5 targets succesvol ingezet'},
    'survivor':       {'icon': 'fa-person-running', 'name': 'Overlever', 'desc': 'Eerste spel gewonnen als runner'},
    'ghost':          {'icon': 'fa-eye-slash', 'name': 'Spook', 'desc': 'Offline knop 3x gebruikt in 1 spel'},
    'speedster_warn': {'icon': 'fa-triangle-exclamation', 'name': 'Te Snel!', 'desc': 'Meer dan 20 km/u geregistreerd'},
    'first_game':     {'icon': 'fa-gamepad', 'name': 'Eerste Spel', 'desc': 'Je eerste VenTrax spel gespeeld'},
    'sharpshooter':   {'icon': 'fa-user-check', 'name': 'Scherpschutter', 'desc': 'Echte naam correct geraden'},
    'veteran':        {'icon': 'fa-star', 'name': 'Veteraan', 'desc': '10 spellen gespeeld'},
    'legend':         {'icon': 'fa-star-of-life', 'name': 'Legende', 'desc': '50 spellen gespeeld'},
    'point_machine':  {'icon': 'fa-coins', 'name': 'Puntenmachine', 'desc': '1000 punten totaal behaald'},
    'marathon':       {'icon': 'fa-route', 'name': 'Marathon', 'desc': '50km gelopen in alle spellen samen'},
    'photographer':   {'icon': 'fa-camera', 'name': 'Fotograaf', 'desc': '10 fotos geplaatst'},
    'emergency':      {'icon': 'fa-triangle-exclamation', 'name': 'Noodknop', 'desc': 'Noodknop gebruikt'},
    'chatty':         {'icon': 'fa-comments', 'name': 'Babbelaar', 'desc': '50 chatberichten gestuurd'},
    'loot_first':     {'icon': 'fa-box-open', 'name': 'Eerste Dropbox', 'desc': 'Je eerste dropbox geopend'},
    'loot_x10':       {'icon': 'fa-boxes-stacked', 'name': 'Verzamelaar', 'desc': '10 dropboxes geopend'},
    'loot_rare':      {'icon': 'fa-gem', 'name': 'Zeldzame Vondst', 'desc': 'Een zeldzame dropbox-beloning gevonden'},
}

def award_badge(user_id, badge_type, game_id=None):
    """Award a badge if not already earned. Returns True if newly awarded."""
    with db.session.no_autoflush:
        existing = Badge.query.filter_by(user_id=user_id, badge_type=badge_type).first()
        if existing:
            return False
        badge = Badge(user_id=user_id, badge_type=badge_type, game_id=game_id)
        db.session.add(badge)
        return True

def check_badges_after_game(user_id, game_id):
    """Check and award all applicable badges after a game."""
    user = User.query.get(user_id)
    if not user: return []
    new_badges = []
    # Games played
    if user.total_games >= 1  and award_badge(user_id, 'first_game',   game_id): new_badges.append('first_game')
    if user.total_games >= 10 and award_badge(user_id, 'veteran',      game_id): new_badges.append('veteran')
    if user.total_games >= 50 and award_badge(user_id, 'legend',       game_id): new_badges.append('legend')
    # Points
    if user.total_points >= 1000 and award_badge(user_id, 'point_machine', game_id): new_badges.append('point_machine')
    # Distance (km)
    if user.total_distance >= 50000 and award_badge(user_id, 'marathon', game_id): new_badges.append('marathon')
    # Catches
    if user.runners_caught >= 1  and award_badge(user_id, 'first_catch', game_id): new_badges.append('first_catch')
    if user.runners_caught >= 5  and award_badge(user_id, 'hunter_x5',   game_id): new_badges.append('hunter_x5')
    if user.runners_caught >= 20 and award_badge(user_id, 'hunter_x20',  game_id): new_badges.append('hunter_x20')
    # Runner wins
    if user.runner_wins >= 1 and award_badge(user_id, 'survivor', game_id): new_badges.append('survivor')
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
    return new_badges

class WSHub:
    """Greenlet-safe WebSocket hub using gevent RLock."""
    def __init__(self):
        self._rooms: dict[str, set] = {}
        # Use gevent RLock â€” works correctly in greenlet context
        from gevent.lock import RLock
        self._lock = RLock()

    def join(self, code, ws):
        with self._lock:
            self._rooms.setdefault(code, set()).add(ws)

    def leave(self, code, ws):
        with self._lock:
            self._rooms.get(code, set()).discard(ws)

    def broadcast(self, code, event, data):
        msg = json.dumps({'event': event, 'data': data})
        dead = set()
        with self._lock:
            clients = set(self._rooms.get(code, set()))
        for ws in clients:
            try:
                ws.send(msg)
            except Exception:
                dead.add(ws)
        if dead:
            with self._lock:
                self._rooms.get(code, set()).difference_update(dead)

    def count(self, code):
        with self._lock:
            return len(self._rooms.get(code, set()))

hub = WSHub()

# â”€â”€ WebSocket routes (native gevent-websocket, NO flask-sock) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def log_activity(event, detail=None, user_id=None, game_id=None, flag=False):
    """Write to ActivityLog. Safe to call from anywhere."""
    try:
        ip = get_client_ip() if request else None
    except Exception:
        ip = None
    entry = ActivityLog(
        user_id=user_id or (current_user.id if current_user.is_authenticated else None),
        game_id=game_id,
        event=event, detail=detail, ip_address=ip, flag=flag
    )
    db.session.add(entry)
    # Don't commit here â€” let caller commit

@app.route('/ws/<code>')
def ws_game(code):
    ws = request.environ.get('wsgi.websocket')
    if ws is None:
        return 'WebSocket required', 400
    hub.join(code, ws)
    try:
        while True:
            try:
                raw = ws.receive()
            except WebSocketError:
                break
            if raw is None:
                break
            try:
                msg = json.loads(raw)
                if msg.get('event') == 'ping':
                    try:
                        game = Game.query.filter_by(code=code).first()
                        if game and current_user.is_authenticated:
                            me = GamePlayer.query.filter_by(game_id=game.id, user_id=current_user.id).first()
                            if me:
                                me.last_seen = datetime.utcnow()
                                db.session.commit()
                    except Exception:
                        db.session.rollback()
                    ws.send(json.dumps({'event': 'pong'}))
            except Exception:
                pass
    finally:
        hub.leave(code, ws)
    return ''

@app.route('/ws/news')
def ws_news():
    ws = request.environ.get('wsgi.websocket')
    if ws is None:
        return 'WebSocket required', 400
    hub.join('__news__', ws)
    try:
        while True:
            try:
                raw = ws.receive()
            except WebSocketError:
                break
            if raw is None:
                break
            try:
                msg = json.loads(raw)
                if msg.get('event') == 'ping':
                    ws.send(json.dumps({'event': 'pong'}))
            except Exception:
                pass
    finally:
        hub.leave('__news__', ws)
    return ''

# â”€â”€ Models â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
class SiteSetting(db.Model):
    key   = db.Column(db.String(80), primary_key=True)
    value = db.Column(db.Text, nullable=True)

    @staticmethod
    def get(key, default=None):
        r = SiteSetting.query.get(key)
        return r.value if r else default

    @staticmethod
    def set(key, value):
        r = SiteSetting.query.get(key)
        if r:
            r.value = value
        else:
            db.session.add(SiteSetting(key=key, value=value))
        db.session.commit()


class User(UserMixin, db.Model):
    id              = db.Column(db.Integer, primary_key=True)
    username        = db.Column(db.String(80), unique=True, nullable=False)
    email           = db.Column(db.String(120), unique=True, nullable=True)
    password_hash   = db.Column(db.String(256), nullable=False)
    is_admin        = db.Column(db.Boolean, default=False)
    is_owner        = db.Column(db.Boolean, default=False)
    email_verified  = db.Column(db.Boolean, default=False)
    # New-registration-only gate (see register()). Existing rows default to False
    # (no new column = no new obligation) so no existing account is ever restricted
    # by this. Distinct from email_verified/is_banned.
    requires_email_verification = db.Column(db.Boolean, default=False)
    # Set by admin_ban_user(). Checked at login() and in load_user() so a ban
    # both blocks future logins and immediately invalidates any active session.
    is_banned       = db.Column(db.Boolean, default=False)
    created_at      = db.Column(db.DateTime, default=datetime.utcnow)
    total_points    = db.Column(db.Float,   default=0.0)
    hunter_wins     = db.Column(db.Integer, default=0)
    runner_wins     = db.Column(db.Integer, default=0)
    total_games     = db.Column(db.Integer, default=0)
    total_distance  = db.Column(db.Float,   default=0.0)
    runners_caught  = db.Column(db.Integer, default=0)  # for leaderboard

    games    = db.relationship('GamePlayer', back_populates='user', foreign_keys='GamePlayer.user_id', lazy='dynamic')
    posts    = db.relationship('Post',       back_populates='author', lazy='dynamic')
    articles = db.relationship('NewsArticle', back_populates='author',
                               foreign_keys='NewsArticle.user_id',    lazy='dynamic')

    def set_password(self, pw):   self.password_hash = generate_password_hash(pw)
    def check_password(self, pw): return check_password_hash(self.password_hash, pw)

    @property
    def avatar_letter(self): return self.username[0].upper()

    def get_reset_token(self):
        return serializer.dumps(self.email, salt='pw-reset')

    @staticmethod
    def verify_reset_token(token, max_age=3600):
        try:
            email = serializer.loads(token, salt='pw-reset', max_age=max_age)
        except Exception:
            return None
        return User.query.filter_by(email=email).first()

    def get_verify_token(self):
        return serializer.dumps(self.email, salt='email-verify')


class Game(db.Model):
    id                  = db.Column(db.Integer, primary_key=True)
    name                = db.Column(db.String(120), nullable=False)
    code                = db.Column(db.String(6),   unique=True, nullable=False)
    creator_id          = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    status              = db.Column(db.String(20), default='lobby')  # lobby/active/finished
    difficulty          = db.Column(db.String(10), default='custom')
    points_multiplier   = db.Column(db.Float, default=1.0)

    # Basic
    duration_minutes    = db.Column(db.Integer, default=120)
    headstart_minutes   = db.Column(db.Integer, default=5)

    # Hunter
    hunter_interval_sec = db.Column(db.Integer, default=600)
    target_enabled      = db.Column(db.Boolean, default=True)
    target_duration_sec = db.Column(db.Integer, default=300)
    target_cooldown_sec = db.Column(db.Integer, default=600)
    target_uses_per_runner = db.Column(db.Integer, default=0)  # 0 = unlimited

    # Runner
    runner_interval_sec = db.Column(db.Integer, nullable=True)
    show_distance       = db.Column(db.Boolean, default=False)
    offline_uses        = db.Column(db.Integer, default=1)   # how many offline buttons per runner
    max_offline_sec     = db.Column(db.Integer, default=120)
    offline_button      = db.Column(db.Boolean, default=True)
    team_mode           = db.Column(db.Boolean, default=False)
    live_tracking       = db.Column(db.Boolean, default=False)
    pause_allowed       = db.Column(db.Boolean, default=True)
    max_pause_sec       = db.Column(db.Integer, default=120)

    # Special features
    feat_hacker         = db.Column(db.Boolean, default=False)
    feat_glitch         = db.Column(db.Boolean, default=False)
    feat_photo_missions = db.Column(db.Boolean, default=False)
    feat_emergency      = db.Column(db.Boolean, default=True)
    speed_limit_kmh     = db.Column(db.Float, default=15.0)  # above this, points reduced
    bike_allowed        = db.Column(db.Boolean, default=False)

    created_at       = db.Column(db.DateTime, default=datetime.utcnow)
    started_at       = db.Column(db.DateTime, nullable=True)
    ended_at         = db.Column(db.DateTime, nullable=True)
    countdown_until  = db.Column(db.DateTime, nullable=True)  # 5s countdown before start

    creator = db.relationship('User', foreign_keys=[creator_id])
    players = db.relationship('GamePlayer',   back_populates='game', lazy='dynamic', cascade='all, delete-orphan')
    posts   = db.relationship('Post',         back_populates='game', lazy='dynamic', cascade='all, delete-orphan')
    targets = db.relationship('Target',       back_populates='game', lazy='dynamic', cascade='all, delete-orphan')
    location_pings = db.relationship('LocationPing', back_populates='game', lazy='dynamic', cascade='all, delete-orphan')

    @property
    def effective_elapsed(self):
        if not self.started_at: return 0
        elapsed = (datetime.utcnow() - self.started_at).total_seconds()
        pause_state = get_game_pause_state(self)
        paused_sec = float(pause_state.get('total_paused_sec') or 0)
        if pause_state.get('active') and pause_state.get('paused_since'):
            try:
                paused_sec += max(0, (datetime.utcnow() - datetime.fromisoformat(pause_state['paused_since'])).total_seconds())
            except Exception:
                pass
        return max(0, elapsed - paused_sec)

    @property
    def is_headstart_over(self):
        return self.effective_elapsed > self.headstart_minutes * 60

    @property
    def is_finished(self):
        if not self.started_at: return False
        return self.effective_elapsed > self.duration_minutes * 60

    @property
    def progress_pct(self):
        if not self.started_at or self.duration_minutes == 0: return 0
        return min(100, self.effective_elapsed / (self.duration_minutes * 60) * 100)


class GamePlayer(db.Model):
    id               = db.Column(db.Integer, primary_key=True)
    game_id          = db.Column(db.Integer, db.ForeignKey('game.id'), nullable=False)
    user_id          = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    role             = db.Column(db.String(10), nullable=False)
    codename         = db.Column(db.String(40), nullable=True)  # random alias
    real_name_revealed = db.Column(db.Boolean, default=False)   # hunters can unmask
    is_ready         = db.Column(db.Boolean,  default=False)
    gps_enabled      = db.Column(db.Boolean,  default=False)
    camera_enabled   = db.Column(db.Boolean,  default=False)
    is_caught        = db.Column(db.Boolean,  default=False)
    caught_by        = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    caught_at        = db.Column(db.DateTime, nullable=True)
    points           = db.Column(db.Float,    default=0.0)
    distance         = db.Column(db.Float,    default=0.0)
    last_lat         = db.Column(db.Float,    nullable=True)
    last_lon         = db.Column(db.Float,    nullable=True)
    last_accuracy    = db.Column(db.Float,    nullable=True)
    last_speed_ms    = db.Column(db.Float,    nullable=True)  # m/s from GPS
    last_seen        = db.Column(db.DateTime, nullable=True)
    joined_at        = db.Column(db.DateTime, default=datetime.utcnow)

    # Offline system
    offline_uses_left  = db.Column(db.Integer, default=1)
    is_offline         = db.Column(db.Boolean, default=False)
    offline_since      = db.Column(db.DateTime, nullable=True)

    # Pause
    is_paused          = db.Column(db.Boolean, default=False)
    paused_since       = db.Column(db.DateTime, nullable=True)
    total_paused_sec   = db.Column(db.Integer,  default=0)
    pause_reason       = db.Column(db.String(200), nullable=True)

    # Target cooldown (per hunter)
    target_used_at     = db.Column(db.DateTime, nullable=True)
    target_uses_on     = db.Column(db.Text, default='{}')  # JSON {runner_id: count}

    # Special abilities used
    hacker_active      = db.Column(db.Boolean, default=False)
    hacker_until       = db.Column(db.DateTime, nullable=True)

    # Emergency
    emergency_at       = db.Column(db.DateTime, nullable=True)

    game        = db.relationship('Game', back_populates='players')
    user        = db.relationship('User', back_populates='games', foreign_keys=[user_id])
    caught_user = db.relationship('User', foreign_keys=[caught_by])


class Target(db.Model):
    id           = db.Column(db.Integer, primary_key=True)
    game_id      = db.Column(db.Integer, db.ForeignKey('game.id'), nullable=False)
    hunter_id    = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    runner_id    = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    activated_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at   = db.Column(db.DateTime, nullable=True)
    is_active    = db.Column(db.Boolean,  default=True)
    game   = db.relationship('Game', back_populates='targets')
    hunter = db.relationship('User', foreign_keys=[hunter_id])
    runner = db.relationship('User', foreign_keys=[runner_id])


class LocationPing(db.Model):
    """Throttled GPS breadcrumb trail per player, used to sketch each player's
    route in the end-of-game summary email. Not every raw update is stored -
    see _maybe_log_location_ping() - to keep the table from growing unbounded."""
    id          = db.Column(db.Integer, primary_key=True)
    game_id     = db.Column(db.Integer, db.ForeignKey('game.id'), nullable=False)
    user_id     = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    lat         = db.Column(db.Float, nullable=False)
    lon         = db.Column(db.Float, nullable=False)
    recorded_at = db.Column(db.DateTime, default=datetime.utcnow)
    game = db.relationship('Game', back_populates='location_pings')


class Post(db.Model):
    id             = db.Column(db.Integer, primary_key=True)
    game_id        = db.Column(db.Integer, db.ForeignKey('game.id'), nullable=False)
    user_id        = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    caption        = db.Column(db.String(500), nullable=True)
    image_filename = db.Column(db.String(256), nullable=True)
    audio_filename = db.Column(db.String(256), nullable=True)
    lat            = db.Column(db.Float, nullable=True)
    lon            = db.Column(db.Float, nullable=True)
    share_location = db.Column(db.Boolean, default=False)
    mission_id     = db.Column(db.Integer, nullable=True)  # linked photo mission
    approved       = db.Column(db.Boolean, nullable=True)  # None=pending, True/False
    points_awarded = db.Column(db.Float, default=0.0)
    created_at     = db.Column(db.DateTime, default=datetime.utcnow)
    likes          = db.Column(db.Integer,  default=0)
    game   = db.relationship('Game', back_populates='posts')
    author = db.relationship('User', back_populates='posts')
    liked_by = db.relationship('PostLike', back_populates='post',
                               lazy='dynamic', cascade='all, delete-orphan')


class PostLike(db.Model):
    id      = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    post    = db.relationship('Post', back_populates='liked_by')


class NewsArticle(db.Model):
    id             = db.Column(db.Integer, primary_key=True)
    user_id        = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title          = db.Column(db.String(200), nullable=False)
    content        = db.Column(db.Text, nullable=False)
    image_filename = db.Column(db.String(256), nullable=True)
    photo_consent  = db.Column(db.Boolean, default=False)
    status         = db.Column(db.String(20), default='pending')
    approved_by    = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    approved_at    = db.Column(db.DateTime, nullable=True)
    created_at     = db.Column(db.DateTime, default=datetime.utcnow)
    likes          = db.Column(db.Integer,  default=0)
    author   = db.relationship('User', foreign_keys=[user_id], back_populates='articles')
    approver = db.relationship('User', foreign_keys=[approved_by])
    liked_by = db.relationship('NewsLike', back_populates='article',
                               lazy='dynamic', cascade='all, delete-orphan')


class NewsLike(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    article_id = db.Column(db.Integer, db.ForeignKey('news_article.id'), nullable=False)
    user_id    = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    article    = db.relationship('NewsArticle', back_populates='liked_by')

class Report(db.Model):
    """Player bug reports, tips, ideas."""
    id          = db.Column(db.Integer, primary_key=True)
    user_id     = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    type        = db.Column(db.String(20), default='bug')  # bug/tip/idea/cheat
    title       = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    game_code   = db.Column(db.String(6), nullable=True)
    status      = db.Column(db.String(20), default='open')  # open/reviewing/resolved/closed
    admin_note  = db.Column(db.Text, nullable=True)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)
    resolved_at = db.Column(db.DateTime, nullable=True)
    author      = db.relationship('User', foreign_keys=[user_id])


class ActivityLog(db.Model):
    """Audit log for admin / anti-cheat monitoring."""
    id          = db.Column(db.Integer, primary_key=True)
    user_id     = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    game_id     = db.Column(db.Integer, db.ForeignKey('game.id'), nullable=True)
    event       = db.Column(db.String(60), nullable=False)
    detail      = db.Column(db.Text, nullable=True)
    ip_address  = db.Column(db.String(45), nullable=True)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)
    flag        = db.Column(db.Boolean, default=False)   # flagged as suspicious
    user        = db.relationship('User', foreign_keys=[user_id])


class Changelog(db.Model):
    """Public-facing changelog entries."""
    id          = db.Column(db.Integer, primary_key=True)
    version     = db.Column(db.String(20), nullable=False)   # e.g. "1.5.0"
    title       = db.Column(db.String(200), nullable=False)
    body        = db.Column(db.Text, nullable=False)          # markdown-ish
    type        = db.Column(db.String(20), default='update')  # update/fix/feature/security
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)
    published   = db.Column(db.Boolean, default=True)



class ChatMessage(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    game_id    = db.Column(db.Integer, db.ForeignKey('game.id'), nullable=False)
    user_id    = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    team       = db.Column(db.String(10), nullable=False)  # 'hunter'/'runner'/'all'
    message    = db.Column(db.String(500), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    author     = db.relationship('User', foreign_keys=[user_id])



class GameCatalog(db.Model):
    """Platform game registry â€” each entry is a playable game type."""
    id          = db.Column(db.Integer, primary_key=True)
    slug        = db.Column(db.String(40), unique=True, nullable=False)  # e.g. 'ventrax'
    name        = db.Column(db.String(80), nullable=False)               # e.g. 'VenTrax'
    tagline     = db.Column(db.String(200), nullable=True)
    description = db.Column(db.Text, nullable=True)
    icon        = db.Column(db.String(40), default='fa-crosshairs')      # FontAwesome icon
    color       = db.Column(db.String(20), default='#e11d48')
    logo_file   = db.Column(db.String(120), nullable=True)               # static/img/<file>
    is_active   = db.Column(db.Boolean, default=True)
    coming_soon = db.Column(db.Boolean, default=False)
    sort_order  = db.Column(db.Integer, default=0)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)

class Badge(db.Model):
    """Achievement badges earned by players."""
    id          = db.Column(db.Integer, primary_key=True)
    user_id     = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    badge_type  = db.Column(db.String(40), nullable=False)  # e.g. 'first_catch', 'speedster'
    earned_at   = db.Column(db.DateTime, default=datetime.utcnow)
    game_id     = db.Column(db.Integer, db.ForeignKey('game.id'), nullable=True)
    user        = db.relationship('User', foreign_keys=[user_id])


# â”€â”€ Helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@login_manager.user_loader
def load_user(uid):
    user = User.query.get(int(uid))
    # Returning None for a banned user invalidates their session on the very
    # next request, so a ban logs them out immediately, not just at next login.
    if user and user.is_banned:
        return None
    return user

def allowed_file(f): return '.' in f and f.rsplit('.', 1)[1].lower() in ALLOWED_IMG

def upload_too_large(file, max_bytes=6 * 1024 * 1024):
    try:
        pos = file.stream.tell()
        file.stream.seek(0, os.SEEK_END)
        size = file.stream.tell()
        file.stream.seek(pos)
        return size > max_bytes
    except Exception:
        return False

def gen_code():
    while True:
        c = ''.join(random.choices(CODE_CHARS, k=6))
        if not Game.query.filter_by(code=c).first():
            return c

def admin_required(f):
    @wraps(f)
    def d(*a, **kw):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash('Admin rechten vereist.', 'danger')
            return redirect(url_for('dashboard'))
        return f(*a, **kw)
    return d

CATCH_MAX_DISTANCE_M   = 2    # hunter must be within this many meters to tag a runner
CATCH_MIN_PROGRESS_PCT = 50   # tagging only allowed once the game is this far along

def haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

def speed_ms_to_kmh(ms): return ms * 3.6 if ms else 0

def calc_points(dist_m, speed_ms, multiplier):
    """
    Points with tiered speed penalty:
    0-10 km/h  : normal  (1pt per 100m)
    10 km/h    : 1pt per 150m
    11 km/h    : 1pt per 200m
    12 km/h    : 1pt per 250m
    13 km/h    : 1pt per 300m
    14 km/h    : 1pt per 350m
    15+ km/h   : 1pt per 400m
    """
    speed_kmh = speed_ms_to_kmh(speed_ms or 0)
    if speed_kmh < 10:
        meters_per_pt = 100
    elif speed_kmh < 11:
        meters_per_pt = 150
    elif speed_kmh < 12:
        meters_per_pt = 200
    elif speed_kmh < 13:
        meters_per_pt = 250
    elif speed_kmh < 14:
        meters_per_pt = 300
    elif speed_kmh < 15:
        meters_per_pt = 350
    else:
        meters_per_pt = 400
    pts = (dist_m / meters_per_pt) * multiplier
    return round(pts, 2)  # always 2 decimal places

def save_image(file, folder, max_size=(1400, 1400)):
    fn  = secure_filename(file.filename)
    ext = fn.rsplit('.', 1)[1].lower() if '.' in fn else 'jpg'
    if ext not in ALLOWED_IMG:
        raise ValueError('unsupported image type')
    if upload_too_large(file):
        raise ValueError('image too large')
    name = f"{int(time.time())}_{random.randint(1000,9999)}.{ext}"
    path = os.path.join(folder, name)
    img  = Image.open(file)
    img.thumbnail(max_size, Image.LANCZOS)
    if img.mode in ('RGBA', 'P'): img = img.convert('RGB')
    img.save(path, quality=88, optimize=True)
    return name

def save_audio(file, folder):
    fn  = secure_filename(file.filename)
    ext = fn.rsplit('.', 1)[1].lower() if '.' in fn else 'webm'
    if ext not in ALLOWED_AUDIO:
        raise ValueError('unsupported audio type')
    if upload_too_large(file, max_bytes=10 * 1024 * 1024):
        raise ValueError('audio too large')
    os.makedirs(folder, exist_ok=True)
    name = f"{int(time.time())}_{random.randint(1000,9999)}.{ext}"
    file.save(os.path.join(folder, name))
    return name

def render_route_sketch(points, size=(360, 360)):
    """Draw a simple normalized line sketch of a player's route from (lat,lon)
    points - no map tiles/network calls, just a schematic path for the e-mail."""
    if len(points) < 2:
        return None
    lats = [p[0] for p in points]; lons = [p[1] for p in points]
    lat_span = max(max(lats) - min(lats), 1e-6)
    lon_span = max(max(lons) - min(lons), 1e-6)
    pad = 24
    w, h = size
    img = Image.new('RGB', size, (241, 245, 249))
    draw = ImageDraw.Draw(img)
    def to_xy(lat, lon):
        x = pad + (lon - min(lons)) / lon_span * (w - 2 * pad)
        y = pad + (1 - (lat - min(lats)) / lat_span) * (h - 2 * pad)  # north = up
        return (x, y)
    xy = [to_xy(lat, lon) for lat, lon in points]
    draw.line(xy, fill=(37, 99, 235), width=3, joint='curve')
    sx, sy = xy[0]; ex, ey = xy[-1]
    draw.ellipse([sx - 6, sy - 6, sx + 6, sy + 6], fill=(16, 185, 129))
    draw.ellipse([ex - 6, ey - 6, ex + 6, ey + 6], fill=(239, 68, 68))
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return buf.getvalue()

def assign_codename(role, game_id):
    """Assign a unique codename per role per game."""
    pool = CODENAMES_HUNTERS if role == 'hunter' else CODENAMES_RUNNERS
    taken = {p.codename for p in GamePlayer.query.filter_by(game_id=game_id, role=role).all()
             if p.codename}
    available = [n for n in pool if n not in taken]
    if not available:
        # Fallback: add number suffix
        return random.choice(pool) + str(random.randint(2, 99))
    return random.choice(available)

def generate_qr(code, base_url):
    """Generate QR code PNG for game join URL, return filename."""
    url = f"{base_url}/join?code={code}"
    qr = qrcode.QRCode(version=2, box_size=10, border=3,
                       error_correction=qrcode.constants.ERROR_CORRECT_H)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#e11d48", back_color="white")
    pil_img = img.convert('RGB')
    center = (pil_img.width // 2, pil_img.height // 2)
    from PIL import ImageDraw
    draw = ImageDraw.Draw(pil_img)
    r = pil_img.width // 8
    draw.ellipse([center[0]-r, center[1]-r, center[0]+r, center[1]+r], fill='white')
    logo_path = os.path.join(os.path.dirname(__file__), 'static', 'img', 'logo_round.png')
    if os.path.exists(logo_path):
        try:
            logo = Image.open(logo_path).convert('RGBA')
            size = int(r * 1.75)
            logo.thumbnail((size, size), Image.LANCZOS)
            lx = center[0] - logo.width // 2
            ly = center[1] - logo.height // 2
            pil_img.paste(logo, (lx, ly), logo)
        except Exception as e:
            app.logger.warning(f"QR logo overlay failed: {e}")
            draw.ellipse([center[0]-r+4, center[1]-r+4, center[0]+r-4, center[1]+r-4], fill='#e11d48')
    else:
        draw.ellipse([center[0]-r+4, center[1]-r+4, center[0]+r-4, center[1]+r-4], fill='#e11d48')

    fname = f"qr_{code}.png"
    fpath = os.path.join(os.path.dirname(__file__), 'static', 'qr', fname)
    pil_img.save(fpath)
    return fname

def _playfield_key(game_id):
    return f'playfield:{game_id}'

def _profile_playfield_key(user_id):
    return f'profile_playfield:{user_id}'

def _profile_playfields_key(user_id):
    return f'profile_playfields:{user_id}'

def _global_playfields_key():
    return 'global_playfields'

def _game_templates_key(user_id):
    return f'game_templates:{user_id}'

def _extras_key(game_id):
    return f'game_extras:{game_id}'

def _lootboxes_key(game_id):
    return f'game_lootboxes:{game_id}'

def _classes_key(game_id):
    return f'game_classes:{game_id}'

def _effects_key(game_id):
    return f'game_effects:{game_id}'

def _runner_snapshot_key(game_id):
    return f'runner_location_snapshots:{game_id}'

def _lootbox_stats_key(user_id):
    return f'lootbox_stats:{user_id}'

def _game_end_result_key(game_id):
    return f'game_end_result:{game_id}'

def _zone_state_key(game_id):
    return f'zone_state:{game_id}'

def _pause_state_key(game_id):
    return f'pause_state:{game_id}'

def get_game_pause_state(game):
    try:
        data = json.loads(SiteSetting.get(_pause_state_key(game.id), '{}') or '{}')
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}

def save_game_pause_state(game, state):
    SiteSetting.set(_pause_state_key(game.id), json.dumps(state or {}))

def _pause_snapshot_ready(game, pause_state):
    """Return True when all active players are back within the pause snapshot radius."""
    snapshot = pause_state.get('snapshot') if isinstance(pause_state, dict) else {}
    if not pause_state or not pause_state.get('active') or not isinstance(snapshot, dict):
        return False
    for p in game.players:
        if p.is_caught:
            continue
        snap = snapshot.get(str(p.user_id))
        if not snap:
            return False
        if p.last_lat is None or p.last_lon is None:
            return False
        try:
            dist = haversine(float(p.last_lat), float(p.last_lon), float(snap['lat']), float(snap['lon']))
        except Exception:
            return False
        if dist > 10:
            return False
    return True

def maybe_resume_game_from_pause(game, broadcast=True):
    """Auto-resume a paused game once everyone is back within the stored radius."""
    pause_state = get_game_pause_state(game)
    if not pause_state.get('active'):
        return False
    if not _pause_snapshot_ready(game, pause_state):
        return False
    now = datetime.utcnow()
    started_at = pause_state.get('started_at')
    total_paused_sec = int(pause_state.get('total_paused_sec') or 0)
    if started_at:
        try:
            total_paused_sec += max(0, int((now - datetime.fromisoformat(started_at)).total_seconds()))
        except Exception:
            pass
    pause_state['active'] = False
    pause_state['paused_since'] = None
    pause_state['total_paused_sec'] = total_paused_sec
    pause_state['resumed_at'] = now.isoformat()
    save_game_pause_state(game, pause_state)
    for p in game.players:
        p.is_paused = False
        p.paused_since = None
        p.pause_reason = None
    db.session.commit()
    if broadcast:
        hub.broadcast(game.code, 'runner_unpaused', {
            'user_id': None,
            'forced': True,
            'game_paused': False,
        })
    return True

def sweep_stale_players(game, broadcast=True):
    """Mark players as out when they have not been reachable for 5 minutes."""
    if not game or game.status != 'active':
        return []
    now = datetime.utcnow()
    cutoff = now - timedelta(minutes=5)
    timed_out = []
    for p in game.players.all():
        if p.is_caught:
            continue
        if p.last_seen and p.last_seen < cutoff:
            p.is_caught = True
            p.is_offline = False
            p.is_paused = False
            p.offline_since = None
            p.paused_since = None
            p.pause_reason = None
            timed_out.append({
                'user_id': p.user_id,
                'username': p.user.username,
                'codename': p.codename or p.user.username,
                'role': p.role,
            })
    if timed_out:
        db.session.commit()
        for item in timed_out:
            if broadcast:
                hub.broadcast(game.code, 'player_left', {
                    'user_id': item['user_id'],
                    'username': item['username'],
                    'codename': item['codename'],
                    'reason': 'timeout',
                    'timeout': True,
                })
    return timed_out

CLASS_LOADOUTS = [
    {'id': 'signal_scout', 'name': 'Signal Scout', 'power': 'Echo', 'requires': 'echo',
     'desc': 'Laat zien hoe ver en in welke richting de dichtstbijzijnde tegenstander zit.'},
    {'id': 'codekraker', 'name': 'Codekraker', 'power': 'Hack', 'requires': 'hacker',
     'desc': 'Geeft een korte intel-hint over een tegenstander en recente chat.'},
    {'id': 'bomexpert', 'name': 'Bomexpert', 'power': 'Landmijn', 'requires': 'landmine',
     'desc': 'Ontmantelt een landmijn dichtbij je of plaatst anders een eigen landmijn.'},
    {'id': 'laserwachter', 'name': 'Laserwachter', 'power': 'Laser detectie', 'requires': 'laser',
     'desc': 'Plaatst een laser die waarschuwt als een tegenstander dichtbij komt.'},
    {'id': 'saboteur', 'name': 'Saboteur', 'power': 'Tripwire', 'requires': 'tripwire',
     'desc': 'Plaatst een tripwire bij je positie om tegenstanders te verrassen.'},
    {'id': 'glitcher', 'name': 'Glitcher', 'power': 'Glitch', 'requires': 'glitch',
     'desc': 'Verstoort tijdelijk de kaartinformatie van tegenstanders.'},
    {'id': 'spoorzoeker', 'name': 'Spoorzoeker', 'power': 'Richtinggevoel', 'requires': None,
     'desc': 'Geeft richting en afstand naar de dichtstbijzijnde tegenstander.'},
]

def save_game_extras(game, form):
    def form_int(name, default, lo, hi):
        try:
            value = int(form.get(name, default) or default)
        except Exception:
            value = default
        return max(lo, min(hi, value))

    dropbox_min_m = form_int('dropbox_min_m', 500, 50, 5000)
    dropbox_max_m = form_int('dropbox_max_m', 1500, 100, 10000)
    if dropbox_max_m < dropbox_min_m:
        dropbox_min_m, dropbox_max_m = dropbox_max_m, dropbox_min_m

    extras = {
        'game_style': form.get('game_style') or 'classic',
        'dropboxes': form.get('extra_dropboxes') == 'on',
        'landmine': form.get('extra_landmine') == 'on',
        'laser': form.get('extra_laser') == 'on',
        'tripwire': form.get('extra_tripwire') == 'on',
        'hacker': form.get('feat_hacker') == 'on',
        'glitch': form.get('feat_glitch') == 'on',
        'echo': form.get('extra_echo') == 'on',
        'classes_enabled': form.get('classes_enabled') == 'on',
        'class_theme': form.get('class_theme') or 'street',
        'class_cooldown_sec': form_int('class_cooldown_sec', 180, 60, 1800),
        'dropboxes_per_team': form_int('dropboxes_per_team', 2, 1, 5),
        'dropboxes_global': form_int('dropboxes_global', 1, 0, 3),
        'dropbox_min_m': dropbox_min_m,
        'dropbox_max_m': dropbox_max_m,
        'dropbox_wait_enabled': form.get('dropbox_wait_enabled') == 'on',
        'dropbox_wait_sec': form_int('dropbox_wait_sec', 20, 5, 120),
    }
    SiteSetting.set(_extras_key(game.id), json.dumps(extras))
    return extras

def get_game_extras(game):
    raw = SiteSetting.get(_extras_key(game.id), '')
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}

def get_available_classes(extras):
    # Classes are special powers. When random classes are enabled, pick from the
    # full class pool so players do not all receive Echo when only Echo is ticked.
    return CLASS_LOADOUTS[:]

def assign_game_classes(game):
    extras = get_game_extras(game)
    if not extras.get('classes_enabled'):
        SiteSetting.set(_classes_key(game.id), json.dumps({}))
        return {}
    try:
        assigned = json.loads(SiteSetting.get(_classes_key(game.id), '{}') or '{}')
    except Exception:
        assigned = {}
    choices = get_available_classes(extras)
    assigned_ids = {v.get('id') for v in assigned.values() if isinstance(v, dict)}
    if len(game.players.all()) > 1 and len(assigned_ids) <= 1 and len(choices) > 1:
        assigned = {}
    unused = [c for c in choices if c['id'] not in {v.get('id') for v in assigned.values() if isinstance(v, dict)}]
    if not unused:
        unused = choices[:]
    random.shuffle(unused)
    for p in game.players:
        key = str(p.user_id)
        if key not in assigned:
            if not unused:
                unused = choices[:]
                random.shuffle(unused)
            cls = unused.pop()
            assigned[key] = {
                'id': cls['id'],
                'name': cls['name'],
                'power': cls['power'],
                'desc': cls.get('desc', ''),
                'cooldown_sec': int(extras.get('class_cooldown_sec') or 180),
                'theme': extras.get('class_theme') or 'street',
            }
    SiteSetting.set(_classes_key(game.id), json.dumps(assigned))
    return assigned

def get_player_class(game, user_id):
    try:
        assigned = json.loads(SiteSetting.get(_classes_key(game.id), '{}') or '{}')
    except Exception:
        assigned = {}
    cls = assigned.get(str(user_id))
    if not cls:
        return None
    loadout = next((c for c in CLASS_LOADOUTS if c['id'] == cls.get('id')), None)
    if loadout and not cls.get('desc'):
        cls = dict(cls)
        cls['desc'] = loadout.get('desc', '')
    return cls

def get_game_effects(game):
    base = {'cooldowns': {}, 'hazards': [], 'glitches': {}}
    try:
        raw = json.loads(SiteSetting.get(_effects_key(game.id), '{}') or '{}')
        if isinstance(raw, dict):
            base.update(raw)
    except Exception:
        pass
    return base

def save_game_effects(game, effects):
    SiteSetting.set(_effects_key(game.id), json.dumps(effects))

def _now_ts():
    return time.time()

def utc_iso(dt):
    if not dt:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.isoformat(timespec='milliseconds') + 'Z'

def class_cooldown_remaining(game, user_id):
    effects = get_game_effects(game)
    until = float(effects.get('cooldowns', {}).get(str(user_id), 0) or 0)
    return max(0, int(math.ceil(until - _now_ts())))

def set_class_cooldown(game, user_id, seconds):
    effects = get_game_effects(game)
    effects.setdefault('cooldowns', {})[str(user_id)] = _now_ts() + int(seconds)
    save_game_effects(game, effects)

def _bearing_text(from_lat, from_lon, to_lat, to_lon):
    y = math.sin(math.radians(to_lon - from_lon)) * math.cos(math.radians(to_lat))
    x = (math.cos(math.radians(from_lat)) * math.sin(math.radians(to_lat)) -
         math.sin(math.radians(from_lat)) * math.cos(math.radians(to_lat)) * math.cos(math.radians(to_lon - from_lon)))
    deg = (math.degrees(math.atan2(y, x)) + 360) % 360
    names = ['noord', 'noordoost', 'oost', 'zuidoost', 'zuid', 'zuidwest', 'west', 'noordwest']
    return names[int((deg + 22.5) // 45) % 8]

def _opponents(game, player):
    return [p for p in game.players if p.role != player.role and not p.is_caught and p.last_lat is not None and p.last_lon is not None]

def _nearest_opponent(game, player):
    if player.last_lat is None or player.last_lon is None:
        return None, None
    candidates = _opponents(game, player)
    if not candidates:
        return None, None
    best = min(candidates, key=lambda p: haversine(player.last_lat, player.last_lon, p.last_lat, p.last_lon))
    return best, haversine(player.last_lat, player.last_lon, best.last_lat, best.last_lon)

def check_hazard_triggers(game, player, code):
    if player.last_lat is None or player.last_lon is None:
        return []
    effects = get_game_effects(game)
    changed = False
    messages = []
    for h in effects.get('hazards', []):
        if h.get('owner_role') == player.role:
            continue
        triggered = h.setdefault('triggered_by', [])
        if player.user_id in triggered:
            continue
        try:
            dist = haversine(player.last_lat, player.last_lon, float(h['lat']), float(h['lng']))
        except Exception:
            continue
        if dist > 35:
            continue
        triggered.append(player.user_id)
        changed = True
        kind = h.get('kind')
        if kind == 'landmine':
            player.points -= 8
            msg = f'{player.codename or player.user.username} liep in een landmijn: -8 punten'
        elif kind == 'laser':
            msg = f'Laser detectie: {player.codename or player.user.username} gedetecteerd'
        else:
            player.points -= 3
            msg = f'Tripwire geactiveerd door {player.codename or player.user.username}: -3 punten'
        messages.append(msg)
        hub.broadcast(code, 'hazard_triggered', {
            'kind': kind,
            'target_id': player.user_id,
            'target_codename': player.codename or player.user.username,
            'owner_id': h.get('owner_id'),
            'owner_codename': h.get('codename'),
            'message': msg,
            'lat': player.last_lat,
            'lon': player.last_lon,
        })
    if changed:
        save_game_effects(game, effects)
    return messages

def _point_in_poly(lat, lng, points):
    inside = False
    j = len(points) - 1
    for i in range(len(points)):
        yi, xi = points[i]['lat'], points[i]['lng']
        yj, xj = points[j]['lat'], points[j]['lng']
        if ((xi > lng) != (xj > lng)):
            y_cross = (yj - yi) * (lng - xi) / ((xj - xi) or 1e-12) + yi
            if lat < y_cross:
                inside = not inside
        j = i
    return inside

def _point_segment_distance_m(lat, lng, a, b):
    """Approximate distance from lat/lng point to a polygon segment in meters."""
    lat0 = math.radians(lat)
    mx = 111320.0 * math.cos(lat0)
    my = 110540.0
    px, py = lng * mx, lat * my
    ax, ay = float(a['lng']) * mx, float(a['lat']) * my
    bx, by = float(b['lng']) * mx, float(b['lat']) * my
    dx, dy = bx - ax, by - ay
    if abs(dx) < 1e-9 and abs(dy) < 1e-9:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    cx, cy = ax + t * dx, ay + t * dy
    return math.hypot(px - cx, py - cy)

def playfield_outside_distance_m(game, lat, lng):
    pf = get_playfield(game)
    pts = pf.get('points') if pf else None
    if not pts or len(pts) < 3:
        return 0
    lat = float(lat); lng = float(lng)
    if _point_in_poly(lat, lng, pts):
        return 0
    return min(_point_segment_distance_m(lat, lng, pts[i], pts[(i + 1) % len(pts)])
               for i in range(len(pts)))

def playfield_status(game, lat, lng):
    pf = get_playfield(game)
    if not pf or len(pf.get('points') or []) < 3:
        return 'none'
    return 'inside' if _point_in_poly(float(lat), float(lng), pf['points']) else 'outside'

def get_runner_snapshot(game, player):
    if player.last_lat is None or player.last_lon is None:
        return None
    if game.live_tracking:
        return {'lat': player.last_lat, 'lon': player.last_lon, 'live': True, 'slot': None}
    interval = int(game.hunter_interval_sec or 0)
    if interval <= 0:
        interval = 600
    elapsed = max(0, int(game.effective_elapsed or 0) - int(game.headstart_minutes or 0) * 60)
    slot = elapsed // interval
    try:
        snapshots = json.loads(SiteSetting.get(_runner_snapshot_key(game.id), '{}') or '{}')
        if not isinstance(snapshots, dict):
            snapshots = {}
    except Exception:
        snapshots = {}
    key = str(player.user_id)
    current = snapshots.get(key) or {}
    if current.get('slot') != slot or current.get('lat') is None or current.get('lon') is None:
        current = {
            'slot': slot,
            'lat': player.last_lat,
            'lon': player.last_lon,
            'captured_at': datetime.utcnow().isoformat(),
        }
        snapshots[key] = current
        SiteSetting.set(_runner_snapshot_key(game.id), json.dumps(snapshots))
    return {'lat': current['lat'], 'lon': current['lon'], 'live': False, 'slot': slot}

def award_lootbox_badges(user_id, rare=False, game_id=None):
    try:
        stats = json.loads(SiteSetting.get(_lootbox_stats_key(user_id), '{}') or '{}')
        if not isinstance(stats, dict):
            stats = {}
    except Exception:
        stats = {}
    stats['count'] = int(stats.get('count') or 0) + 1
    if rare:
        stats['rare'] = int(stats.get('rare') or 0) + 1
    SiteSetting.set(_lootbox_stats_key(user_id), json.dumps(stats))
    if stats['count'] >= 1:
        award_badge(user_id, 'loot_first', game_id)
    if stats['count'] >= 10:
        award_badge(user_id, 'loot_x10', game_id)
    if rare:
        award_badge(user_id, 'loot_rare', game_id)
    return stats

def get_game_end_result(game):
    try:
        data = json.loads(SiteSetting.get(_game_end_result_key(game.id), '{}') or '{}')
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}

def update_zone_pressure(game, player, outside_distance_m):
    """Track how long a player is safely outside the playfield margin."""
    limit_sec = 30
    margin_m = 5
    now_ts = _now_ts()
    try:
        state = json.loads(SiteSetting.get(_zone_state_key(game.id), '{}') or '{}')
        if not isinstance(state, dict):
            state = {}
    except Exception:
        state = {}
    key = str(player.user_id)
    item = state.get(key) or {'seconds': 0, 'last_ts': now_ts}
    seconds = float(item.get('seconds') or 0)
    last_ts = float(item.get('last_ts') or now_ts)
    delta = max(0, min(15, now_ts - last_ts))
    if outside_distance_m > margin_m:
        seconds = min(limit_sec, seconds + delta)
    else:
        seconds = 0
    item.update({
        'seconds': seconds,
        'last_ts': now_ts,
        'outside_m': round(float(outside_distance_m or 0), 1),
        'limit_sec': limit_sec,
        'margin_m': margin_m,
    })
    state[key] = item
    SiteSetting.set(_zone_state_key(game.id), json.dumps(state))
    return item

def get_zone_pressure(game, user_id):
    try:
        state = json.loads(SiteSetting.get(_zone_state_key(game.id), '{}') or '{}')
        item = state.get(str(user_id)) or {}
    except Exception:
        item = {}
    limit_sec = int(item.get('limit_sec') or 30)
    seconds = float(item.get('seconds') or 0)
    return {
        'seconds': round(seconds, 1),
        'limit_sec': limit_sec,
        'margin_m': int(item.get('margin_m') or 5),
        'outside_m': float(item.get('outside_m') or 0),
        'pct': round(min(100, (seconds / max(1, limit_sec)) * 100), 1),
    }

def _destination_point(lat, lng, meters, bearing_deg):
    r = 6371000.0
    br = math.radians(bearing_deg)
    lat1 = math.radians(lat); lon1 = math.radians(lng)
    lat2 = math.asin(math.sin(lat1) * math.cos(meters / r) +
                     math.cos(lat1) * math.sin(meters / r) * math.cos(br))
    lon2 = lon1 + math.atan2(math.sin(br) * math.sin(meters / r) * math.cos(lat1),
                             math.cos(meters / r) - math.sin(lat1) * math.sin(lat2))
    return round(math.degrees(lat2), 7), round(math.degrees(lon2), 7)

def _lootbox_center(game):
    coords = [(p.last_lat, p.last_lon) for p in game.players
              if p.last_lat is not None and p.last_lon is not None]
    if coords:
        return sum(c[0] for c in coords) / len(coords), sum(c[1] for c in coords) / len(coords)
    pf = get_playfield(game)
    if pf and pf.get('points'):
        pts = pf['points']
        return sum(p['lat'] for p in pts) / len(pts), sum(p['lng'] for p in pts) / len(pts)
    return 52.15, 5.38

def _random_lootbox_point(game):
    pf = get_playfield(game)
    if pf and len(pf.get('points') or []) >= 3:
        pts = pf['points']
        min_lat = min(p['lat'] for p in pts); max_lat = max(p['lat'] for p in pts)
        min_lng = min(p['lng'] for p in pts); max_lng = max(p['lng'] for p in pts)
        for _ in range(120):
            lat = random.uniform(min_lat, max_lat)
            lng = random.uniform(min_lng, max_lng)
            if _point_in_poly(lat, lng, pts):
                return round(lat, 7), round(lng, 7)
    lat, lng = _lootbox_center(game)
    extras = get_game_extras(game)
    try:
        min_m = int(extras.get('dropbox_min_m', 500) or 500)
        max_m = int(extras.get('dropbox_max_m', 1500) or 1500)
    except Exception:
        min_m, max_m = 500, 1500
    min_m = max(50, min(5000, min_m))
    max_m = max(100, min(10000, max_m))
    if max_m < min_m:
        min_m, max_m = max_m, min_m
    return _destination_point(lat, lng, random.uniform(min_m, max_m), random.uniform(0, 360))

def get_game_lootboxes(game):
    extras = get_game_extras(game)
    if not extras.get('dropboxes'):
        return []
    raw = SiteSetting.get(_lootboxes_key(game.id), '')
    try:
        boxes = json.loads(raw) if raw else []
    except Exception:
        boxes = []
    if isinstance(boxes, dict):
        boxes = boxes.get('boxes', [])
    pf = get_playfield(game)
    if boxes:
        if pf and len(pf.get('points') or []) >= 3:
            pts = pf['points']
            try:
                all_inside = bool(boxes) and all(
                    b.get('lat') is not None and b.get('lng') is not None
                    and _point_in_poly(float(b.get('lat')), float(b.get('lng')), pts)
                    for b in boxes
                )
            except Exception:
                all_inside = False
            if not all_inside:
                boxes = []
        if boxes:
            return boxes
    total = int(extras.get('dropboxes_global') or 0) + int(extras.get('dropboxes_per_team') or 0) * 2
    total = max(0, min(13, total))
    teams = (['all'] * int(extras.get('dropboxes_global') or 0) +
             ['hunter'] * int(extras.get('dropboxes_per_team') or 0) +
             ['runner'] * int(extras.get('dropboxes_per_team') or 0))
    boxes = []
    for i, team in enumerate(teams[:total], start=1):
        lat, lng = _random_lootbox_point(game)
        boxes.append({
            'id': i,
            'team': team,
            'lat': lat,
            'lng': lng,
            'status': 'available',
            'label': 'Algemeen' if team == 'all' else ('Hunters' if team == 'hunter' else 'Runners'),
        })
    SiteSetting.set(_lootboxes_key(game.id), json.dumps(boxes))
    return boxes

@app.route('/api/game/<code>/lootbox/<int:box_id>/claim', methods=['POST'])
@login_required
def api_claim_lootbox(code, box_id):
    game = Game.query.filter_by(code=code).first_or_404()
    me = GamePlayer.query.filter_by(game_id=game.id, user_id=current_user.id).first()
    if not me: return jsonify(error='Niet in spel'), 403
    if game.status != 'active': return jsonify(error='Spel niet actief'), 400
    if me.last_lat is None or me.last_lon is None:
        return jsonify(error='GPS nog niet klaar'), 400
    boxes = get_game_lootboxes(game)
    box = next((b for b in boxes if int(b.get('id', -1)) == box_id), None)
    if not box: return jsonify(error='Dropbox niet gevonden'), 404
    if box.get('team') not in ('all', me.role):
        return jsonify(error='Deze dropbox is niet voor jouw team'), 403
    dist = haversine(me.last_lat, me.last_lon, float(box['lat']), float(box['lng']))
    if dist > 10:
        return jsonify(error=f'Te ver weg: {round(dist)}m'), 400

    rewards = [
        ('points_small', 40), ('points_medium', 25), ('intel', 18),
        ('cooldown', 10), ('points_big', 5), ('shield', 2),
    ]
    count = random.choices([1, 2, 3], weights=[65, 28, 7], k=1)[0]
    effects = get_game_effects(game)
    messages = []
    total_points = 0
    rare_reward = False
    for _ in range(count):
        effect = random.choices([r[0] for r in rewards], weights=[r[1] for r in rewards], k=1)[0]
        if effect == 'points_small':
            pts = 1 if box.get('team') == 'all' else 2
            total_points += pts
            messages.append(f'+{pts} punten')
        elif effect == 'points_medium':
            pts = 3 if box.get('team') == 'all' else 4
            total_points += pts
            messages.append(f'+{pts} punten')
        elif effect == 'points_big':
            pts = 6 if box.get('team') == 'all' else 8
            total_points += pts
            rare_reward = True
            messages.append(f'zeldzame bonus +{pts} punten')
        elif effect == 'cooldown':
            effects.setdefault('cooldowns', {})[str(current_user.id)] = _now_ts()
            messages.append('class-power direct klaar')
        elif effect == 'intel':
            opp, d = _nearest_opponent(game, me)
            if opp:
                messages.append(f'intel: dichtste tegenstander {round(d)}m richting {_bearing_text(me.last_lat, me.last_lon, opp.last_lat, opp.last_lon)}')
            else:
                messages.append('intel: geen tegenstander met GPS gevonden')
        elif effect == 'shield':
            effects.setdefault('shields', {})[str(current_user.id)] = _now_ts() + 120
            rare_reward = True
            messages.append('zeldzaam schild voor 2 minuten')
    if total_points:
        me.points += total_points
        current_user.total_points += total_points
    award_lootbox_badges(current_user.id, rare_reward, game.id)
    save_game_effects(game, effects)
    msg = 'Dropbox geopend: ' + ', '.join(messages)

    new_lat, new_lng = _random_lootbox_point(game)
    box.update({'lat': new_lat, 'lng': new_lng, 'status': 'available', 'claimed_by': current_user.id})
    SiteSetting.set(_lootboxes_key(game.id), json.dumps(boxes))
    db.session.commit()
    hub.broadcast(code, 'lootbox_claimed', {
        'user_id': current_user.id,
        'codename': me.codename or current_user.username,
        'box_id': box_id,
        'message': msg,
    })
    return jsonify(success=True, message=msg, points=round(me.points, 2), lootboxes=boxes)

@app.route('/api/game/<code>/class_power', methods=['POST'])
@login_required
def api_class_power(code):
    game = Game.query.filter_by(code=code).first_or_404()
    me = GamePlayer.query.filter_by(game_id=game.id, user_id=current_user.id).first()
    if not me: return jsonify(error='Niet in spel'), 403
    if game.status != 'active': return jsonify(error='Spel niet actief'), 400
    if get_game_pause_state(game).get('active'):
        return jsonify(error='Pauze actief'), 400
    if game.countdown_until and datetime.utcnow() < game.countdown_until:
        return jsonify(error='Power kan pas na de countdown gebruikt worden'), 400
    if not game.is_headstart_over:
        return jsonify(error='Power kan pas na de voorsprong gebruikt worden'), 400
    cls = get_player_class(game, current_user.id)
    if not cls: return jsonify(error='Geen class actief'), 400
    if me.last_lat is None or me.last_lon is None:
        return jsonify(error='GPS nog niet klaar'), 400
    remaining = class_cooldown_remaining(game, current_user.id)
    if remaining > 0:
        return jsonify(error=f'Cooldown actief: nog {remaining}s', cooldown_remaining=remaining), 400

    effects = get_game_effects(game)
    cid = cls.get('id')
    msg = 'Power gebruikt'
    cooldown_sec = int(cls.get('cooldown_sec') or 180)
    cooldown_sec = max(cooldown_sec, {
        'codekraker': 300,
        'bomexpert': 300,
        'laserwachter': 300,
        'saboteur': 360,
        'glitcher': 300,
    }.get(cid, 180))
    payload = {'class': cls}

    if cid in ('signal_scout', 'spoorzoeker'):
        opp, dist = _nearest_opponent(game, me)
        if not opp:
            return jsonify(error='Geen tegenstander met GPS gevonden'), 400
        direction = _bearing_text(me.last_lat, me.last_lon, opp.last_lat, opp.last_lon)
        msg = f'Echo: dichtste tegenstander is {round(dist)}m richting {direction}'
        payload.update({'type': 'echo', 'distance': round(dist), 'direction': direction})

    elif cid == 'codekraker':
        opp, dist = _nearest_opponent(game, me)
        recent = (ChatMessage.query.filter_by(game_id=game.id)
                  .order_by(ChatMessage.created_at.desc()).limit(3).all())
        last_chat = recent[0].message[:80] if recent else 'geen chat gevonden'
        if opp:
            msg = f'Hack: {opp.codename or opp.user.username} laatst gezien op {round(dist)}m. Laatste chat: {last_chat}'
        else:
            msg = f'Hack: Laatste chat: {last_chat}'
        payload.update({'type': 'hack', 'intel': msg})

    elif cid in ('bomexpert', 'laserwachter', 'saboteur'):
        kind = {'bomexpert': 'landmine', 'laserwachter': 'laser', 'saboteur': 'tripwire'}[cid]
        if cid == 'bomexpert':
            for h in list(effects.get('hazards', [])):
                if h.get('kind') == 'landmine' and h.get('owner_role') != me.role:
                    try:
                        dist = haversine(me.last_lat, me.last_lon, float(h['lat']), float(h['lng']))
                    except Exception:
                        continue
                    if dist <= 45:
                        effects['hazards'].remove(h)
                        me.points += 4
                        db.session.commit()
                        save_game_effects(game, effects)
                        msg = 'Landmijn ontmanteld: +4 punten'
                        set_class_cooldown(game, current_user.id, cooldown_sec)
                        hub.broadcast(code, 'class_power', {
                            'user_id': current_user.id,
                            'codename': me.codename or current_user.username,
                            'class_name': cls.get('name'),
                            'message': msg,
                        })
                        return jsonify(success=True, message=msg, cooldown=cooldown_sec, type='disarm')
        hlat, hlng = me.last_lat, me.last_lon
        if cid == 'saboteur':
            boxes = get_game_lootboxes(game)
            nearby = []
            for b in boxes:
                try:
                    dbox = haversine(me.last_lat, me.last_lon, float(b['lat']), float(b['lng']))
                    if dbox <= 10:
                        nearby.append((dbox, b))
                except Exception:
                    pass
            if not nearby:
                return jsonify(error='Je moet binnen 10 meter van een dropbox staan om Tripwire te plaatsen'), 400
            _, b = min(nearby, key=lambda x: x[0])
            hlat, hlng = float(b['lat']), float(b['lng'])
        hazard = {
            'id': ''.join(random.choices(string.ascii_lowercase + string.digits, k=8)),
            'kind': kind,
            'owner_id': current_user.id,
            'owner_role': me.role,
            'codename': me.codename or current_user.username,
            'lat': hlat,
            'lng': hlng,
            'created_at': datetime.utcnow().isoformat(),
            'triggered_by': [],
        }
        effects.setdefault('hazards', []).append(hazard)
        save_game_effects(game, effects)
        labels = {'landmine': 'Landmijn geplaatst', 'laser': 'Laser detectie actief', 'tripwire': 'Tripwire geplaatst'}
        msg = labels[kind]
        payload.update({'type': kind, 'hazard': hazard})

    elif cid == 'glitcher':
        until = _now_ts() + 60
        effects.setdefault('glitches', {})[str(current_user.id)] = until
        save_game_effects(game, effects)
        msg = 'Glitch actief: jouw locatie wordt 60 seconden verstoord voor tegenstanders'
        payload.update({'type': 'glitch', 'expires_in': 60})

    else:
        return jsonify(error='Deze class heeft nog geen power'), 400

    set_class_cooldown(game, current_user.id, cooldown_sec)
    hub.broadcast(code, 'class_power', {
        'user_id': current_user.id,
        'codename': me.codename or current_user.username,
        'class_name': cls.get('name'),
        'message': msg,
    })
    return jsonify(success=True, message=msg, cooldown=cooldown_sec, **payload)

def normalize_playfield(raw_json):
    """Validate and normalize playfield data without requiring a database migration."""
    if not raw_json:
        return None
    try:
        data = json.loads(raw_json)
        points = data.get('points') or []
        if len(points) < 3:
            return None
        clean_points = []
        for p in points[:80]:
            lat = float(p.get('lat'))
            lng = float(p.get('lng'))
            if -90 <= lat <= 90 and -180 <= lng <= 180:
                clean_points.append({'lat': round(lat, 7), 'lng': round(lng, 7)})
        if len(clean_points) < 3:
            return None
        color = data.get('color') if data.get('color') in ('radiation','storm','nuclear','heat') else 'storm'
        return {
            'enabled': True,
            'color': color,
            'points': clean_points,
        }
    except Exception as e:
        app.logger.warning(f"Invalid playfield ignored: {e}")
        return None

def save_playfield(game, raw_json):
    """Store playfield settings for a specific game."""
    data = normalize_playfield(raw_json)
    if not data:
        return None
    try:
        SiteSetting.set(_playfield_key(game.id), json.dumps(data))
        return data
    except Exception as e:
        app.logger.warning(f"Invalid playfield ignored for game {game.id}: {e}")
        return None

def save_profile_playfield(user_id, raw_json):
    """Store the latest playfield on the creator profile for reuse."""
    data = normalize_playfield(raw_json)
    if not data:
        return None
    SiteSetting.set(_profile_playfield_key(user_id), json.dumps(data))
    return data

def get_profile_playfields_for_user(user_id):
    try:
        items = json.loads(SiteSetting.get(_profile_playfields_key(user_id), '[]') or '[]')
        return items if isinstance(items, list) else []
    except Exception:
        return []

def save_named_profile_playfield(user_id, raw_json, name):
    data = normalize_playfield(raw_json)
    clean_name = (name or '').strip()[:80]
    if not data or not clean_name:
        return None
    items = get_profile_playfields_for_user(user_id)
    signature = json.dumps(data, sort_keys=True)
    kept = [
        i for i in items
        if i.get('signature') != signature and (i.get('name') or '').strip().lower() != clean_name.lower()
    ]
    item = {
        'id': ''.join(random.choices(string.ascii_lowercase + string.digits, k=8)),
        'name': clean_name,
        'created_at': datetime.utcnow().isoformat(),
        'signature': signature,
        'data': data,
    }
    kept.insert(0, item)
    kept = kept[:25]
    SiteSetting.set(_profile_playfields_key(user_id), json.dumps(kept))
    SiteSetting.set(_profile_playfield_key(user_id), json.dumps(data))
    return item

def get_global_playfields():
    try:
        items = json.loads(SiteSetting.get(_global_playfields_key(), '[]') or '[]')
        return items if isinstance(items, list) else []
    except Exception:
        return []

def save_global_playfield(raw_json, name=None):
    data = normalize_playfield(raw_json)
    if not data:
        return None
    items = get_global_playfields()
    signature = json.dumps(data, sort_keys=True)
    if not any(i.get('signature') == signature for i in items):
        items.insert(0, {
            'id': ''.join(random.choices(string.ascii_lowercase + string.digits, k=8)),
            'name': name or f"Speelveld {len(items) + 1}",
            'created_at': datetime.utcnow().isoformat(),
            'signature': signature,
            'data': data,
        })
        items = items[:25]
        SiteSetting.set(_global_playfields_key(), json.dumps(items))
    return data

def get_latest_global_playfield():
    items = get_global_playfields()
    return items[0]['data'] if items else None

def game_to_template(game):
    extras = get_game_extras(game)
    pf = get_playfield(game)
    return {
        'id': ''.join(random.choices(string.ascii_lowercase + string.digits, k=8)),
        'name': game.name,
        'created_at': datetime.utcnow().isoformat(),
        'difficulty': game.difficulty,
        'duration_minutes': game.duration_minutes,
        'headstart_minutes': game.headstart_minutes,
        'hunter_interval_sec': game.hunter_interval_sec,
        'runner_interval_sec': game.runner_interval_sec,
        'show_distance': game.show_distance,
        'live_tracking': game.live_tracking,
        'target_enabled': game.target_enabled,
        'target_duration_sec': game.target_duration_sec,
        'target_cooldown_sec': game.target_cooldown_sec,
        'offline_button': game.offline_button,
        'offline_uses': game.offline_uses,
        'max_offline_sec': game.max_offline_sec,
        'pause_allowed': game.pause_allowed,
        'max_pause_sec': game.max_pause_sec,
        'team_mode': game.team_mode,
        'points_multiplier': game.points_multiplier,
        'extras': extras,
        'playfield': pf,
    }

def save_game_template_for_user(user_id, game):
    items = []
    try:
        items = json.loads(SiteSetting.get(_game_templates_key(user_id), '[]') or '[]')
        if not isinstance(items, list):
            items = []
    except Exception:
        items = []
    tpl = game_to_template(game)
    items.insert(0, tpl)
    items = items[:10]
    SiteSetting.set(_game_templates_key(user_id), json.dumps(items))
    return tpl

def get_game_templates_for_user(user_id):
    try:
        items = json.loads(SiteSetting.get(_game_templates_key(user_id), '[]') or '[]')
        return items if isinstance(items, list) else []
    except Exception:
        return []

def get_playfield(game):
    raw = SiteSetting.get(_playfield_key(game.id), '')
    if not raw:
        return None
    try:
        data = json.loads(raw)
        if data.get('enabled') and len(data.get('points') or []) >= 3:
            return data
    except Exception:
        return None
    return None

def get_profile_playfield(user_id):
    raw = SiteSetting.get(_profile_playfield_key(user_id), '')
    if raw:
        try:
            data = json.loads(raw)
            if data.get('enabled') and len(data.get('points') or []) >= 3:
                return data
        except Exception:
            pass

    # Fallback for maps created before profile storage existed.
    recent_games = (Game.query.filter_by(creator_id=user_id)
                    .order_by(Game.created_at.desc()).limit(10).all())
    for game in recent_games:
        data = get_playfield(game)
        if data:
            SiteSetting.set(_profile_playfield_key(user_id), json.dumps(data))
            return data
    return None

def site_context():
    return {
        'site_name':          SiteSetting.get('site_name',          'VenTrax'),
        'site_bg':            SiteSetting.get('site_bg',            ''),
        'site_logo':          SiteSetting.get('site_logo',          ''),
        'site_accent':        SiteSetting.get('site_accent',        '#e11d48'),
        'site_tagline':       SiteSetting.get('site_tagline',       'Het ultieme real-time jachtspel'),
        'site_font':          SiteSetting.get('site_font',          'Syne'),
        'site_font_body':     SiteSetting.get('site_font_body',     'DM Sans'),
        'site_bg_overlay':    SiteSetting.get('site_bg_overlay',    '0.82'),
        'site_border_radius': SiteSetting.get('site_border_radius', '12'),
        'diff_easy_img':      SiteSetting.get('diff_easy_img',      ''),
        'diff_medium_img':    SiteSetting.get('diff_medium_img',    ''),
        'diff_hard_img':      SiteSetting.get('diff_hard_img',      ''),
        'diff_custom_img':    SiteSetting.get('diff_custom_img',    ''),
    }

def open_game_for_user(user_id):
    cleanup_open_games_for_user(user_id)
    gp = (GamePlayer.query.filter_by(user_id=user_id, is_caught=False)
          .join(Game).filter(Game.status.in_(['lobby', 'active']))
          .order_by(GamePlayer.joined_at.desc()).first())
    return gp

def game_url_for_player(gp):
    if not gp:
        return url_for('dashboard')
    return url_for('lobby' if gp.game.status == 'lobby' else 'game_dashboard', code=gp.game.code)

def cleanup_open_games_for_user(user_id=None):
    now = datetime.utcnow()
    changed = False
    finished_ttl_sec = 15 * 60
    for g in Game.query.filter_by(status='finished').all():
        if g.ended_at and (now - g.ended_at).total_seconds() > finished_ttl_sec:
            db.session.delete(g)
            changed = True
    games = Game.query.filter(Game.status.in_(['lobby', 'active'])).all()
    for g in games:
        if g.status == 'lobby' and g.created_at and (now - g.created_at).total_seconds() > 2 * 86400:
            g.status = 'finished'
            g.ended_at = now
            changed = True
            continue
        if g.status == 'active':
            if g.is_finished:
                finish_game(g, 'time_up', broadcast=False)
                changed = True
                continue
            hunters = GamePlayer.query.filter_by(game_id=g.id, role='hunter', is_caught=False).count()
            runners = GamePlayer.query.filter_by(game_id=g.id, role='runner', is_caught=False).count()
            if hunters < 1 or runners < 1:
                finish_game(g, 'not_enough_players', broadcast=False)
                changed = True
                continue
            stale_ref = g.started_at or g.created_at
            if stale_ref and (now - stale_ref).total_seconds() > 3 * 86400:
                finish_game(g, 'stale_game', broadcast=False)
                changed = True
    if changed:
        db.session.commit()

@app.context_processor
def inject_site():
    ctx = site_context()
    ctx['current_year'] = datetime.utcnow().year
    # Add pending news count for admins
    if current_user.is_authenticated and current_user.is_admin:
        ctx['pending_news'] = NewsArticle.query.filter_by(status='pending').count()
    else:
        ctx['pending_news'] = 0
    # Active game for current user (for "back to game" banner)
    active_game = None
    if current_user.is_authenticated:
        gp = open_game_for_user(current_user.id)
        active_game = gp.game if gp else None
    ctx['active_game'] = active_game
    return ctx

def serialize_post(p, uid):
    liked = PostLike.query.filter_by(post_id=p.id, user_id=uid).first() is not None
    # Only show location if game is finished or share_location=True
    show_loc = p.share_location or (p.game and p.game.status == 'finished')
    show_author = current_user.is_admin
    return {
        'id': p.id,
        'username': p.author.username if show_author else ('Eigen foto' if p.user_id == uid else 'Speler'),
        'avatar': p.author.avatar_letter if show_author else 'F',
        'author_username': p.author.username if current_user.is_admin else None,
        'author_email': p.author.email if current_user.is_admin else None,
        'caption': p.caption, 'image': p.image_filename, 'audio': p.audio_filename,
        'lat': p.lat if show_loc else None,
        'lon': p.lon if show_loc else None,
        'likes': p.likes, 'liked': liked,
        'created_at': p.created_at.strftime('%H:%M'),
        'can_delete': p.user_id == uid or current_user.is_admin,
        'can_edit':   p.user_id == uid or current_user.is_admin,
        'approved': p.approved,
        'points': p.points_awarded,
    }

DIFFICULTY_PRESETS = {
    # Hunter POV: easy helps hunters, hard helps runners and rewards more points.
    'easy':   dict(multiplier=1.0,  hunter_interval=300, runner_interval=180,
                   show_distance=False, live_tracking=False, offline_button=False,
                   offline_uses=1, max_offline=60, pause_allowed=False, max_pause=300),
    'medium': dict(multiplier=1.25, hunter_interval=600,  runner_interval=600,
                   show_distance=False, live_tracking=False, offline_button=True,
                   offline_uses=1, max_offline=300, pause_allowed=False, max_pause=300),
    'hard':   dict(multiplier=1.5,  hunter_interval=900,  runner_interval=900,
                   show_distance=False, live_tracking=False, offline_button=True,
                   offline_uses=2, max_offline=300, pause_allowed=False,
                   target_enabled=False, max_pause=300),
    'custom': dict(multiplier=1.25, hunter_interval=600, runner_interval=600,
                   show_distance=False, live_tracking=False, offline_button=True,
                   offline_uses=1, max_offline=300, pause_allowed=False,
                   target_enabled=True, max_pause=300),
}

# Photo mission categories
PHOTO_MISSIONS = [
    {'id': 1, 'role': 'both',    'desc': 'Foto van een vrachtwagen',     'pts': 5},
    {'id': 2, 'role': 'both',    'desc': 'Foto van een gele auto',        'pts': 5},
    {'id': 3, 'role': 'both',    'desc': 'Foto van een Mini Cooper',      'pts': 5},
    {'id': 4, 'role': 'both',    'desc': 'Foto van een kat',              'pts': 5},
    {'id': 5, 'role': 'both',    'desc': 'Foto van een hond',             'pts': 5},
    {'id': 6, 'role': 'both',    'desc': 'Foto van een speeltuin',        'pts': 7},
    {'id': 7, 'role': 'both',    'desc': 'Foto van een fietspad',         'pts': 3},
    {'id': 8, 'role': 'both',    'desc': 'Selfie bij een groen busje',    'pts': 8},
    {'id': 9, 'role': 'hunter',  'desc': 'Foto van een Runner',           'pts': 10},
    {'id':10, 'role': 'runner',  'desc': 'Foto van een Hunter',           'pts': 10},
    {'id':11, 'role': 'both',    'desc': 'Foto van een rode auto',        'pts': 5},
    {'id':12, 'role': 'both',    'desc': 'Foto bij een kerk of toren',    'pts': 6},
    {'id':13, 'role': 'both',    'desc': 'Foto van een motor',            'pts': 5},
    {'id':14, 'role': 'both',    'desc': 'Foto van een brievenbus',       'pts': 4},
    {'id':15, 'role': 'both',    'desc': 'Foto bij water (sloot/vijver)',  'pts': 6},
]

# â”€â”€ Mail helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# -- Registration abuse protection --------------------------------------------
# All of this only ever affects NEW registration attempts. It never touches,
# blocks, re-verifies or cleans up existing accounts. See docs/CLOUDFLARE_SECURITY.md
# for the Cloudflare-side controls this complements (WAF rules, edge rate limiting).

def verify_turnstile(token, remote_ip):
    """Server-side Cloudflare Turnstile check. Always returns True/False; never trust
    a client-side-only check. With no TURNSTILE_SECRET_KEY configured (local dev, or
    before Cloudflare is set up), the check is skipped - loudly logged - rather than
    locking registration out entirely."""
    secret = app.config.get('TURNSTILE_SECRET_KEY')
    if not secret:
        app.logger.warning('TURNSTILE_SECRET_KEY not set - registration Turnstile check is DISABLED (dev mode).')
        return True
    if not token:
        return False
    try:
        resp = http_requests.post(
            'https://challenges.cloudflare.com/turnstile/v0/siteverify',
            data={'secret': secret, 'response': token, 'remoteip': remote_ip},
            timeout=6,
        )
        data = resp.json()
        return bool(data.get('success'))
    except Exception as e:
        app.logger.warning(f'Turnstile verify request failed: {e}')
        return False  # fail closed: a configured check that can't be reached does not pass

# Small, conservative list of well-known disposable/throwaway mail providers.
# Deliberately does NOT include any real Dutch or mainstream provider.
DISPOSABLE_EMAIL_DOMAINS = {
    'mailinator.com', 'guerrillamail.com', 'guerrillamail.info', 'sharklasers.com',
    '10minutemail.com', '10minutemail.net', 'tempmail.com', 'temp-mail.org',
    'yopmail.com', 'yopmail.fr', 'trashmail.com', 'throwawaymail.com',
    'getnada.com', 'dispostable.com', 'fakeinbox.com', 'maildrop.cc',
    'mintemail.com', 'mohmal.com', 'moakt.com', 'emailondeck.com',
}

def normalize_email(email):
    """Conservative normalization: trim + lowercase only. No provider-specific
    tricks (e.g. Gmail dot-stripping) - those cause false 'duplicate' hits."""
    return (email or '').strip().lower() or None

def is_disposable_email(email):
    email = normalize_email(email)
    if not email or '@' not in email:
        return False
    domain = email.rsplit('@', 1)[1]
    return domain in DISPOSABLE_EMAIL_DOMAINS

# In-memory, per-process sliding-window counters for registration attempts.
# Resets on restart - that's fine, Cloudflare Rate Limiting Rules (see the docs)
# provide the durable, edge-level backstop; this is just the app-side layer.
_register_attempts  = {}  # ip -> [timestamps of all POST attempts]
_register_successes = {}  # ip -> [timestamps of accounts actually created]
REGISTER_MAX_SUCCESS_PER_WINDOW = 3
REGISTER_MAX_ATTEMPTS_PER_WINDOW = 12  # guards against a flood of failed attempts too
REGISTER_WINDOW_SEC = 10 * 60

def _prune(bucket, now):
    return [t for t in bucket if now - t < REGISTER_WINDOW_SEC]

def check_register_rate_limit(ip):
    """Returns None if the attempt may proceed, or a Dutch error string if it's
    rate-limited. Does not record the attempt - call record_register_attempt()
    once the request has actually been handled."""
    now = time.time()
    attempts = _prune(_register_attempts.get(ip, []), now)
    successes = _prune(_register_successes.get(ip, []), now)
    if len(successes) >= REGISTER_MAX_SUCCESS_PER_WINDOW:
        return 'Te veel nieuwe accounts vanaf dit adres. Probeer het over een paar minuten opnieuw.'
    if len(attempts) >= REGISTER_MAX_ATTEMPTS_PER_WINDOW:
        return 'Te veel registratiepogingen vanaf dit adres. Probeer het over een paar minuten opnieuw.'
    return None

def record_register_attempt(ip, success):
    now = time.time()
    _register_attempts[ip] = _prune(_register_attempts.get(ip, []), now) + [now]
    if success:
        _register_successes[ip] = _prune(_register_successes.get(ip, []), now) + [now]

def log_register_blocked(reason, extra=None):
    """Compact abuse log entry: timestamp/IP are recorded by log_activity itself.
    Never logs passwords, Turnstile secrets, or the raw request body."""
    ua = (request.headers.get('User-Agent') or '')[:200]
    detail = f'reason={reason} ua={ua}'
    if extra:
        detail += f' {extra}'
    log_activity('register_blocked', detail, flag=True)
    db.session.commit()

def send_verify_email(user):
    if not app.config['MAIL_USERNAME']:
        return  # mail not configured
    token = user.get_verify_token()
    link  = f"{app.config['BASE_URL']}/verify/{token}"
    try:
        msg = Message('Bevestig je VenTrax account', recipients=[user.email])
        msg.html = f"""
        <div style="font-family:sans-serif;max-width:500px;margin:0 auto;padding:30px;background:#111;color:#f0f0f8;border-radius:12px">
          <h1 style="color:#e11d48">VenTrax</h1>
          <p>Hoi {user.username}! Bevestig je e-mailadres door op de link te klikken:</p>
          <a href="{link}" style="display:inline-block;background:#e11d48;color:#fff;padding:12px 24px;border-radius:8px;text-decoration:none;margin:16px 0">E-mail bevestigen</a>
          <p style="color:#888;font-size:12px">Link verloopt na 24 uur.</p>
        </div>"""
        mail.send(msg)
    except Exception as e:
        app.logger.warning(f"Mail send failed: {e}")

def send_reset_email(user):
    if not app.config['MAIL_USERNAME']:
        return False
    token = user.get_reset_token()
    link  = f"{app.config['BASE_URL']}/reset/{token}"
    try:
        msg = Message('VenTrax wachtwoord resetten', recipients=[user.email])
        msg.html = f"""
        <div style="font-family:sans-serif;max-width:500px;margin:0 auto;padding:30px;background:#111;color:#f0f0f8;border-radius:12px">
          <h1 style="color:#e11d48">VenTrax</h1>
          <p>Hoi {user.username}! Klik op de link om je wachtwoord te resetten:</p>
          <a href="{link}" style="display:inline-block;background:#e11d48;color:#fff;padding:12px 24px;border-radius:8px;text-decoration:none;margin:16px 0">Wachtwoord resetten</a>
          <p style="color:#888;font-size:12px">Link verloopt na 1 uur. Als je dit niet hebt aangevraagd, negeer deze mail.</p>
        </div>"""
        mail.send(msg)
        return True
    except Exception as e:
        app.logger.warning(f"Mail send failed: {e}")
        return False

def send_game_summary_email(game):
    """Send a readable game summary to all players with an e-mail address."""
    if not app.config['MAIL_USERNAME']:
        return False
    players = game.players.all()
    recipients = sorted({p.user.email for p in players if p.user and p.user.email})
    if not recipients:
        return False
    posts = Post.query.filter_by(game_id=game.id).order_by(Post.created_at.asc()).all()
    chats = ChatMessage.query.filter_by(game_id=game.id).order_by(ChatMessage.created_at.asc()).all()
    standings = sorted(players, key=lambda p: p.points or 0, reverse=True)
    end_result = get_game_end_result(game)
    winner_role = end_result.get('winner_role')
    winner = next((p for p in standings if p.role == winner_role), None) if winner_role else (standings[0] if standings else None)
    logo = SiteSetting.get('site_logo', '')
    if logo:
        logo_html = f'<img src="{app.config["BASE_URL"]}/backgrounds/{logo}" alt="VenTrax" style="max-height:72px;max-width:220px;object-fit:contain">'
    else:
        logo_html = '<div style="font-size:28px;font-weight:900;color:#e11d48">VenTrax</div>'
    if game.started_at and game.ended_at:
        duration_txt = f'{int((game.ended_at - game.started_at).total_seconds() // 60)} minuten'
    else:
        duration_txt = f'{game.duration_minutes} minuten'
    targets_by_hunter = {}
    targeted_by_runner = {}
    for t in Target.query.filter_by(game_id=game.id).all():
        targets_by_hunter[t.hunter_id] = targets_by_hunter.get(t.hunter_id, 0) + 1
        targeted_by_runner[t.runner_id] = targeted_by_runner.get(t.runner_id, 0) + 1
    def esc(v):
        return html.escape(str(v or ''), quote=True)
    def role_label(role):
        return 'Hunter' if role == 'hunter' else 'Runner'
    def result_label(p):
        if end_result.get('no_points'):
            return 'Geen punten'
        if winner_role:
            return 'Gewonnen' if p.role == winner_role else 'Verloren'
        return 'Afgelopen'
    def chat_channel(team):
        if team == 'all':
            return 'Global'
        if team == 'proxy':
            return 'Proxy'
        return 'Team'
    def chat_display_name(m):
        gp = GamePlayer.query.filter_by(game_id=game.id, user_id=m.user_id).first()
        if m.team in ('all', 'proxy'):
            return (gp.codename if gp and gp.codename else m.author.username)
        return m.author.username
    def caught_label(p):
        if not p.is_caught:
            return 'Nee'
        by = p.caught_user.username if p.caught_user else '?'
        when = p.caught_at.strftime('%H:%M') if p.caught_at else '?'
        return f'Ja (door {esc(by)} om {when})'
    story_bits = [f'De missie "{game.name}" is afgerond.', f'{len(players)} spelers deden mee.']
    if winner:
        story_bits.append(f'{winner.codename or winner.user.username} eindigde bovenaan met {(winner.points or 0):.2f} punten.')
    if posts:
        story_bits.append(f'Er werden {len(posts)} foto- en tekstmomenten vastgelegd.')
    if chats:
        story_bits.append(f'De teams stuurden samen {len(chats)} chatberichten.')
    story = ' '.join(story_bits)
    rows = ''.join(
        f'<tr><td style="padding:8px;border-bottom:1px solid #e2e8f0">{p.user.username}</td>'
        f'<td style="padding:8px;border-bottom:1px solid #e2e8f0">{p.role}</td>'
        f'<td style="padding:8px;border-bottom:1px solid #e2e8f0">{p.codename or ""}</td>'
        f'<td style="padding:8px;border-bottom:1px solid #e2e8f0"><strong>{p.points or 0:.2f}</strong></td>'
        f'<td style="padding:8px;border-bottom:1px solid #e2e8f0">{p.distance or 0:.0f}m</td></tr>'
        for p in standings
    )
    status_rows = ''.join(
        f'<tr>'
        f'<td style="padding:8px;border-bottom:1px solid #e2e8f0">{esc(p.user.username)}</td>'
        f'<td style="padding:8px;border-bottom:1px solid #e2e8f0">{role_label(p.role)}</td>'
        f'<td style="padding:8px;border-bottom:1px solid #e2e8f0">{esc(p.codename)}</td>'
        f'<td style="padding:8px;border-bottom:1px solid #e2e8f0">{result_label(p)}</td>'
        f'<td style="padding:8px;border-bottom:1px solid #e2e8f0">{p.distance or 0:.0f}m</td>'
        f'<td style="padding:8px;border-bottom:1px solid #e2e8f0">{max(0, int(game.offline_uses or 0) - int(p.offline_uses_left or 0))}</td>'
        f'<td style="padding:8px;border-bottom:1px solid #e2e8f0">{targets_by_hunter.get(p.user_id, 0)}</td>'
        f'<td style="padding:8px;border-bottom:1px solid #e2e8f0">{targeted_by_runner.get(p.user_id, 0)}</td>'
        f'<td style="padding:8px;border-bottom:1px solid #e2e8f0">{caught_label(p)}</td>'
        f'</tr>'
        for p in standings
    )
    most_distance = max(players, key=lambda p: p.distance or 0) if players else None
    team_distance = {}
    for p in players:
        team_distance[p.role] = team_distance.get(p.role, 0) + (p.distance or 0)
    photo_rows = ''
    inline_photos = []
    for idx, p in enumerate(posts, start=1):
        img_html = ''
        if p.image_filename:
            cid = f'photo{idx}'
            path = os.path.join(app.config['UPLOAD_FOLDER'], p.image_filename)
            if os.path.exists(path):
                inline_photos.append((cid, p.image_filename, path))
                public_url = f'{app.config["BASE_URL"]}/uploads/{p.image_filename}'
                img_html = f'<div style="margin-top:8px"><img src="{public_url}" alt="{esc(p.caption or p.image_filename)}" style="max-width:260px;max-height:180px;border-radius:10px;object-fit:cover;border:1px solid #e2e8f0"><div style="font-size:12px;color:#64748b;margin-top:4px"><a href="{public_url}" style="color:#2563eb">Foto openen</a></div></div>'
            else:
                img_html = f'<div style="margin-top:6px;color:#64748b">Foto niet gevonden op server: {esc(p.image_filename)}</div>'
        photo_rows += (
            f'<div style="padding:12px;border:1px solid #e2e8f0;border-radius:12px;margin:10px 0">'
            f'<strong>{p.created_at.strftime("%H:%M")}</strong> - {esc(p.author.username)}<br>'
            f'<span>{esc(p.caption or "(geen tekst)")}</span>{img_html}</div>'
        )
    if not photo_rows:
        photo_rows = '<p>Geen fotos geplaatst.</p>'
    chat_rows = ''.join(
        f'<li><strong>{m.created_at.strftime("%H:%M")}</strong> ({chat_channel(m.team)}) {esc(chat_display_name(m))}: {esc(m.message)}</li>'
        for m in chats
    ) or '<li>Geen chatberichten.</li>'

    # Audio fragments - can't reliably play inline in e-mail, so link to the
    # (still-public, no-login) /audio/<file> URL instead of embedding them.
    audio_posts = [p for p in posts if p.audio_filename]
    audio_rows = ''.join(
        f'<li><strong>{p.created_at.strftime("%H:%M")}</strong> - {esc(p.author.username)}: '
        f'<a href="{app.config["BASE_URL"]}/audio/{p.audio_filename}" style="color:#2563eb">geluidsfragment beluisteren</a>'
        f'{" - " + esc(p.caption) if p.caption else ""}</li>'
        for p in audio_posts
    ) or '<li>Geen geluidsfragmenten opgenomen.</li>'

    # Route sketches - a simple schematic line per player from their GPS breadcrumbs
    route_rows = ''
    inline_routes = []
    for idx, p in enumerate(standings, start=1):
        pings = (LocationPing.query.filter_by(game_id=game.id, user_id=p.user_id)
                 .order_by(LocationPing.recorded_at.asc()).all())
        if len(pings) < 2:
            continue
        png_bytes = render_route_sketch([(pp.lat, pp.lon) for pp in pings])
        if not png_bytes:
            continue
        cid = f'route{idx}'
        inline_routes.append((cid, png_bytes))
        route_rows += (
            f'<div style="display:inline-block;text-align:center;margin:8px;width:180px">'
            f'<img src="cid:{cid}" alt="route" style="width:180px;height:180px;border-radius:10px;border:1px solid #e2e8f0">'
            f'<div style="font-size:12px;color:#64748b;margin-top:4px">{esc(p.codename or p.user.username)} ({p.distance or 0:.0f}m)</div>'
            f'</div>'
        )
    if not route_rows:
        route_rows = '<p>Geen route-data beschikbaar.</p>'

    try:
        msg = Message(f'VenTrax missieverslag - {game.name}', recipients=recipients)
        msg.html = f'''
        <div style="font-family:Arial,sans-serif;background:#eef2f7;padding:24px;color:#111827">
          <div style="max-width:780px;margin:0 auto;background:#ffffff;border-radius:18px;overflow:hidden;border:1px solid #dbe3ef">
            <div style="padding:24px;background:#111827;color:#ffffff">
              {logo_html}
              <h1 style="margin:18px 0 6px;color:#ffffff;font-size:28px">Missieverslag</h1>
              <div style="color:#cbd5e1;font-size:14px">{game.name} - code {game.code}</div>
            </div>
            <div style="padding:24px">
              <p style="font-size:16px;line-height:1.6;margin-top:0">{story}</p>
              <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:12px;padding:14px;margin:18px 0">
                <strong>Einde:</strong> {(game.ended_at or datetime.utcnow()).strftime('%d-%m-%Y %H:%M')}<br>
                <strong>Speeltijd:</strong> {duration_txt}<br>
                <strong>Winnaar:</strong> {role_label(winner_role) if winner_role else 'Geen winnaar'}<br>
                <strong>Reden:</strong> {esc(end_result.get('message') or end_result.get('reason') or 'Spel afgelopen')}<br>
                <strong>Meeste afstand:</strong> {esc(most_distance.codename or most_distance.user.username) + f" ({most_distance.distance or 0:.0f}m)" if most_distance else '-'}<br>
                <strong>Totale afstand hunters:</strong> {team_distance.get('hunter', 0):.0f}m &nbsp;&middot;&nbsp; <strong>Totale afstand runners:</strong> {team_distance.get('runner', 0):.0f}m
              </div>
              <h2 style="color:#111827">Spelstatus</h2>
              <table style="width:100%;border-collapse:collapse;font-size:13px;color:#111827">
                <tr style="background:#f1f5f9"><th align="left" style="padding:8px">Speler</th><th align="left" style="padding:8px">Rol</th><th align="left" style="padding:8px">Schuilnaam</th><th align="left" style="padding:8px">Resultaat</th><th align="left" style="padding:8px">Afstand</th><th align="left" style="padding:8px">Offline</th><th align="left" style="padding:8px">Targets gebruikt</th><th align="left" style="padding:8px">Getarget</th><th align="left" style="padding:8px">Gepakt</th></tr>
                {status_rows}
              </table>
              <h2 style="color:#111827">Standen</h2>
              <table style="width:100%;border-collapse:collapse;font-size:14px;color:#111827">
                <tr style="background:#f1f5f9"><th align="left" style="padding:8px">Speler</th><th align="left" style="padding:8px">Rol</th><th align="left" style="padding:8px">Schuilnaam</th><th align="left" style="padding:8px">Punten</th><th align="left" style="padding:8px">Afstand</th></tr>
                {rows}
              </table>
              <h2 style="color:#111827">Routes</h2>
              <div style="text-align:center">{route_rows}</div>
              <h2 style="color:#111827">Fotos en momenten</h2>
              <div style="line-height:1.7;color:#111827">{photo_rows}</div>
              <h2 style="color:#111827">Geluidsfragmenten</h2>
              <ul style="line-height:1.7;color:#111827">{audio_rows}</ul>
              <h2 style="color:#111827">Chat</h2>
              <ul style="line-height:1.7;color:#111827">{chat_rows}</ul>
            </div>
          </div>
        </div>'''
        attach_total = 0
        for cid, filename, path in inline_photos:
            try:
                size = os.path.getsize(path)
                if attach_total + size > 12 * 1024 * 1024:
                    continue
                ctype = mimetypes.guess_type(filename)[0] or 'image/jpeg'
                with open(path, 'rb') as fh:
                    msg.attach(filename, ctype, fh.read(), disposition='inline',
                               headers={'Content-ID': f'<{cid}>'})
                attach_total += size
            except Exception as e:
                app.logger.warning(f"Photo attach failed for {filename}: {e}")
        for cid, png_bytes in inline_routes:
            try:
                if attach_total + len(png_bytes) > 12 * 1024 * 1024:
                    continue
                msg.attach(f'{cid}.png', 'image/png', png_bytes, disposition='inline',
                           headers={'Content-ID': f'<{cid}>'})
                attach_total += len(png_bytes)
            except Exception as e:
                app.logger.warning(f"Route sketch attach failed: {e}")
        mail.send(msg)
        return True
    except Exception as e:
        app.logger.warning(f"Game summary mail failed: {e}")
        return False

# â”€â”€ Auth routes â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@app.route('/')
def index():
    top_hunters = User.query.order_by(User.hunter_wins.desc()).limit(5).all()
    top_runners = User.query.order_by(User.runner_wins.desc()).limit(5).all()
    top_points  = User.query.order_by(User.total_points.desc()).limit(5).all()
    needs_setup = User.query.count() == 0
    recent_news = (NewsArticle.query.filter_by(status='approved')
                   .order_by(NewsArticle.created_at.desc()).limit(3).all())
    games_catalog = GameCatalog.query.order_by(GameCatalog.sort_order).all()
    total_games  = Game.query.filter_by(status='finished').count()
    total_users  = User.query.count()
    return render_template('index.html', top_hunters=top_hunters,
                           top_runners=top_runners, top_points=top_points,
                           needs_setup=needs_setup, recent_news=recent_news,
                           games_catalog=games_catalog,
                           total_games=total_games, total_users=total_users)

@app.route('/setup', methods=['GET', 'POST'])
def setup():
    if User.query.count() > 0: return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email    = request.form.get('email',    '').strip() or None
        password = request.form.get('password', '')
        confirm  = request.form.get('confirm_password', '')
        if len(username) < 3:    flash('Gebruikersnaam min. 3 tekens.', 'danger')
        elif len(password) < 6:  flash('Wachtwoord min. 6 tekens.', 'danger')
        elif password != confirm: flash('Wachtwoorden komen niet overeen.', 'danger')
        else:
            user = User(username=username, email=email, is_admin=True, is_owner=True,
                        email_verified=True)
            user.set_password(password)
            db.session.add(user); db.session.commit()
            login_user(user, remember=True)
            flash(f'Welkom {username}! Jij bent eigenaar en admin van VenTrax.', 'success')
            return redirect(url_for('dashboard'))
    return render_template('setup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if User.query.count() == 0: return redirect(url_for('setup'))
    if current_user.is_authenticated: return redirect(url_for('dashboard'))
    if request.method == 'POST':
        u = User.query.filter_by(username=request.form.get('username', '').strip()).first()
        if u and u.check_password(request.form.get('password', '')):
            if u.is_banned:
                flash('Dit account is geblokkeerd.', 'danger')
                return render_template('login.html')
            ip = get_client_ip()
            # Log the login
            log_activity('login', f'IP:{ip}', user_id=u.id)
            db.session.commit()
            login_user(u, remember=True)
            next_url = request.args.get('next') or url_for('dashboard')
            gp = open_game_for_user(u.id)
            if gp:
                return redirect(game_url_for_player(gp))
            return redirect(next_url)
        flash('Gebruikersnaam of wachtwoord onjuist.', 'danger')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if User.query.count() == 0: return redirect(url_for('setup'))
    if current_user.is_authenticated: return redirect(url_for('dashboard'))
    if request.method == 'POST':
        ip = get_client_ip()

        # Honeypot: a real visitor never fills this in (hidden off-screen, not
        # display:none). A bot that blindly fills every field trips it.
        if request.form.get('website'):
            log_register_blocked('honeypot')
            flash('Registreren is niet gelukt. Probeer het opnieuw.', 'danger')
            record_register_attempt(ip, success=False)
            return render_template('register.html', turnstile_site_key=app.config['TURNSTILE_SITE_KEY'])

        rl_error = check_register_rate_limit(ip)
        if rl_error:
            log_register_blocked('rate_limited')
            record_register_attempt(ip, success=False)
            flash(rl_error, 'danger')
            return render_template('register.html', turnstile_site_key=app.config['TURNSTILE_SITE_KEY']), 429

        turnstile_token = request.form.get('cf-turnstile-response', '')
        if not verify_turnstile(turnstile_token, ip):
            log_register_blocked('turnstile_failed')
            record_register_attempt(ip, success=False)
            flash('Bot-controle mislukt. Vernieuw de pagina en probeer het opnieuw.', 'danger')
            return render_template('register.html', turnstile_site_key=app.config['TURNSTILE_SITE_KEY'])

        username = request.form.get('username', '').strip()
        email    = normalize_email(request.form.get('email', ''))
        password = request.form.get('password', '')
        confirm  = request.form.get('confirm_password', '')

        if len(username) < 3:
            flash('Gebruikersnaam min. 3 tekens.', 'danger')
        elif User.query.filter_by(username=username).first():
            flash('Gebruikersnaam al in gebruik.', 'danger')
        elif not email:
            flash('E-mailadres is verplicht.', 'danger')
        elif User.query.filter_by(email=email).first():
            log_register_blocked('duplicate', f'email_domain={email.rsplit("@",1)[-1]}')
            flash('E-mail al in gebruik.', 'danger')
        elif is_disposable_email(email):
            log_register_blocked('disposable_email', f'email_domain={email.rsplit("@",1)[-1]}')
            flash('Tijdelijke/wegwerp-e-mailadressen zijn niet toegestaan. Gebruik een normaal e-mailadres.', 'danger')
        elif len(password) < 6:
            flash('Wachtwoord min. 6 tekens.', 'danger')
        elif password != confirm:
            flash('Wachtwoorden komen niet overeen.', 'danger')
        else:
            user = User(username=username, email=email, email_verified=False,
                        requires_email_verification=True)
            user.set_password(password)
            db.session.add(user); db.session.commit()
            record_register_attempt(ip, success=True)
            log_activity('register', f'email_domain={email.rsplit("@",1)[-1]}', user_id=user.id)
            db.session.commit()
            if app.config['MAIL_USERNAME']:
                send_verify_email(user)
                flash('Account aangemaakt! Bevestig je e-mailadres via de link die we je stuurden om spellen te kunnen maken of joinen.', 'info')
            else:
                # Mail not configured on this deployment - don't dead-end the user.
                flash(f'Welkom {username}! (E-mailverificatie is niet actief op deze server.)', 'success')
            login_user(user, remember=True)
            return redirect(url_for('dashboard'))
        record_register_attempt(ip, success=False)
    return render_template('register.html', turnstile_site_key=app.config['TURNSTILE_SITE_KEY'])

@app.route('/logout')
@login_required
def logout():
    logout_user(); return redirect(url_for('index'))

@app.route('/verify/<token>')
def verify_email(token):
    try:
        email = serializer.loads(token, salt='email-verify', max_age=86400)
        user  = User.query.filter_by(email=email).first()
    except Exception:
        flash('Ongeldige of verlopen verificatielink. Vraag desgewenst een nieuwe aan.', 'danger')
        return redirect(url_for('index'))
    if user:
        user.email_verified = True
        user.requires_email_verification = False
        db.session.commit()
        login_user(user, remember=True)
        flash(f'E-mail bevestigd! Welkom {user.username}!', 'success')
    return redirect(url_for('dashboard'))

@app.route('/resend-verification', methods=['POST'])
@login_required
def resend_verification():
    if not current_user.requires_email_verification:
        flash('Je account heeft geen verificatie nodig.', 'info')
        return redirect(url_for('dashboard'))
    if not current_user.email or not app.config['MAIL_USERNAME']:
        flash('Kan geen verificatiemail versturen (geen e-mailadres of mail niet geconfigureerd).', 'danger')
        return redirect(url_for('dashboard'))
    send_verify_email(current_user)
    flash('Verificatiemail opnieuw verstuurd. Check ook je spamfolder.', 'info')
    return redirect(url_for('dashboard'))

@app.route('/forgot', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        user  = User.query.filter_by(email=email).first()
        if user:
            ok = send_reset_email(user)
            if ok:
                flash('Resetlink verstuurd! Controleer je e-mail.', 'success')
            else:
                flash('E-mail kon niet verstuurd worden. Controleer SMTP instellingen.', 'danger')
        else:
            flash('E-mailadres niet gevonden.', 'danger')
    return render_template('forgot_password.html')

@app.route('/reset/<token>', methods=['GET', 'POST'])
def reset_password(token):
    try:
        email = serializer.loads(token, salt='pw-reset', max_age=3600)
        user  = User.query.filter_by(email=email).first()
    except Exception:
        flash('Ongeldige of verlopen resetlink.', 'danger')
        return redirect(url_for('forgot_password'))
    if not user:
        flash('Gebruiker niet gevonden.', 'danger')
        return redirect(url_for('forgot_password'))
    if request.method == 'POST':
        pw = request.form.get('password', '')
        if len(pw) < 6:
            flash('Wachtwoord min. 6 tekens.', 'danger')
        else:
            user.set_password(pw); db.session.commit()
            flash('Wachtwoord gewijzigd! Je kunt nu inloggen.', 'success')
            return redirect(url_for('login'))
    return render_template('reset_password.html')

# â”€â”€ Dashboard / Account â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@app.route('/dashboard')
@login_required
def dashboard():
    cleanup_open_games_for_user(current_user.id)
    my_games = (GamePlayer.query.filter_by(user_id=current_user.id, is_caught=False)
                .join(Game).filter(Game.status.in_(['lobby', 'active'])).all())
    earned_badges = Badge.query.filter_by(user_id=current_user.id).order_by(Badge.earned_at.desc()).limit(8).all()
    return render_template('dashboard.html', my_games=my_games, earned_badges=earned_badges,
                           badge_defs=BADGE_DEFS)

@app.route('/account')
@login_required
def account():
    recent      = (GamePlayer.query.filter_by(user_id=current_user.id)
                   .order_by(GamePlayer.joined_at.desc()).limit(15).all())
    my_articles = (NewsArticle.query.filter_by(user_id=current_user.id)
                   .order_by(NewsArticle.created_at.desc()).all())
    return render_template('account.html', recent=recent, my_articles=my_articles)

# â”€â”€ Game creation â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def require_verified_for_play():
    """Blocks creating/joining a game for a new (unverified) account. Never
    applies to existing accounts - see User.requires_email_verification."""
    if current_user.requires_email_verification:
        flash('Bevestig eerst je e-mailadres om een spel te maken of te joinen. '
              'Check je inbox (ook spam), of vraag op je account-pagina een nieuwe link aan.', 'warning')
        return redirect(url_for('dashboard'))
    return None

@app.route('/new_game', methods=['GET', 'POST'])
@login_required
def new_game():
    blocked = require_verified_for_play()
    if blocked: return blocked
    existing = open_game_for_user(current_user.id)
    if existing:
        flash(f'Je zit al in een spel. Je wordt doorgestuurd naar {existing.game.name}.', 'warning')
        return redirect(game_url_for_player(existing))
    if request.method == 'POST':
        f    = request.form
        diff = f.get('difficulty', 'custom')
        p    = DIFFICULTY_PRESETS.get(diff, DIFFICULTY_PRESETS['custom'])

        hi_val = f.get('hunter_interval', '600')
        hi_sec = int(f.get('hunter_interval_custom', 600)) if hi_val == 'custom' else int(hi_val)
        hi_sec = max(60, min(7200, hi_sec))
        if diff != 'custom': hi_sec = p.get('hunter_interval', hi_sec)

        ri_val = f.get('runner_interval', '600')
        if diff == 'hard' or ri_val == 'off':
            ri_sec = None
        elif ri_val == 'custom':
            ri_sec = max(60, min(7200, int(f.get('runner_interval_custom', 600))))
        else:
            ri_sec = int(ri_val)
        if diff in ('easy', 'medium'): ri_sec = p.get('runner_interval', ri_sec)

        multi = p.get('multiplier', 1.0)
        if diff == 'custom':
            multi = 1.4
            if f.get('offline_button') == 'on':  multi -= 0.05
            if f.get('live_tracking')  == 'on':  multi -= 0.05
            if f.get('show_distance')  == 'on':  multi -= 0.05
            if f.get('pause_allowed')  == 'on':  multi -= 0.05
            if ri_val == 'off':                  multi += 0.05
            if hi_sec >= 900:                    multi += 0.05
            if hi_sec >= 1200:                   multi += 0.05
            multi = round(max(0.7, min(2.0, multi)), 2)

        def _bool(key): return p.get(key, f.get(key) == 'on') if diff != 'custom' else f.get(key) == 'on'
        def _int(key, default, lo, hi):
            try:
                return max(lo, min(hi, int(f.get(key, default) or default)))
            except (TypeError, ValueError):
                return max(lo, min(hi, int(default)))
        def _int_select(key, custom_key, default, lo, hi):
            raw = f.get(key, default)
            if raw == 'custom':
                raw = f.get(custom_key, default)
            try:
                val = int(raw or default)
            except (TypeError, ValueError):
                val = int(default)
            return max(lo, min(hi, val))

        # Validate offline timing: max_offline_sec <= 20% of total duration
        duration_minutes = _int_select('duration', 'duration_custom', 120, 5, 300)
        headstart_minutes = _int_select('headstart', 'headstart_custom', 5, 0, 30)
        # Headstart shouldn't eat up more than a third of a (short) game
        headstart_minutes = min(headstart_minutes, max(0, duration_minutes // 3))
        dur_sec = duration_minutes * 60
        max_off = _int('max_offline', p.get('max_offline', 300), 30, 600)
        off_uses = _int('offline_uses', 1, 1, 5)
        if max_off * off_uses > dur_sec * 0.20:
            max_off = max(30, int(dur_sec * 0.20 / max(off_uses, 1)))

        game = Game(
            name              = (f.get('name') or f'{current_user.username} Spel {datetime.utcnow().strftime("%Y-%m-%d %H:%M")}').strip(),
            code              = gen_code(),
            creator_id        = current_user.id,
            difficulty        = diff,
            points_multiplier = multi,
            duration_minutes  = duration_minutes,
            headstart_minutes = headstart_minutes,
            hunter_interval_sec   = hi_sec,
            target_enabled        = _bool('target_enabled'),
            target_duration_sec   = _int('target_duration', 300, 60, 1800),
            target_cooldown_sec   = _int('target_cooldown', 600, 60, 3600),
            target_uses_per_runner= _int('target_uses_per_runner', 0, 0, 10),
            runner_interval_sec   = ri_sec,
            show_distance         = _bool('show_distance'),
            offline_uses          = off_uses,
            max_offline_sec       = max_off,
            offline_button        = _bool('offline_button'),
            team_mode             = f.get('team_mode') == 'on',
            live_tracking         = _bool('live_tracking'),
            pause_allowed         = _bool('pause_allowed'),
            max_pause_sec         = _int('max_pause', 120, 30, 600),
            feat_hacker           = f.get('feat_hacker') == 'on',
            feat_glitch           = f.get('feat_glitch') == 'on',
            feat_photo_missions   = f.get('feat_photo_missions') == 'on',
            feat_emergency        = True,
            bike_allowed          = f.get('bike_allowed') == 'on',
        )
        db.session.add(game); db.session.flush()
        codename = assign_codename(f.get('role', 'hunter'), game.id)
        db.session.add(GamePlayer(
            game_id=game.id, user_id=current_user.id,
            role=f.get('role', 'hunter'),
            codename=codename,
            offline_uses_left=game.offline_uses,
        ))
        saved_playfield = save_playfield(game, f.get('playfield_json', ''))
        if saved_playfield:
            save_profile_playfield(current_user.id, f.get('playfield_json', ''))
            if (f.get('playfield_name') or '').strip():
                save_named_profile_playfield(current_user.id, f.get('playfield_json', ''), f.get('playfield_name'))
            save_global_playfield(f.get('playfield_json', ''), (f.get('playfield_name') or game.name).strip())
        save_game_extras(game, f)
        save_game_template_for_user(current_user.id, game)
        db.session.commit()
        # Generate QR code
        generate_qr(game.code, app.config['BASE_URL'])
        return redirect(url_for('lobby', code=game.code))
    default_game_name = f'{site_context()["site_name"]} {datetime.now().strftime("%d-%m-%Y %H:%M")}'
    return render_template('new_game.html', default_game_name=default_game_name,
                           saved_playfield=get_profile_playfield(current_user.id) or get_latest_global_playfield(),
                           saved_playfields=get_global_playfields(),
                           profile_playfields=get_profile_playfields_for_user(current_user.id),
                           game_templates=get_game_templates_for_user(current_user.id))

# â”€â”€ Lobby â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@app.route('/api/profile/playfield', methods=['POST'])
@login_required
def api_profile_playfield():
    data = request.get_json(silent=True) or {}
    raw = json.dumps({
        'color': data.get('color'),
        'points': data.get('points'),
    })
    saved = save_profile_playfield(current_user.id, raw)
    if not saved:
        return jsonify(error='Speelveld heeft minimaal 3 geldige punten nodig'), 400
    named = None
    if data.get('save_named'):
        named = save_named_profile_playfield(current_user.id, raw, data.get('name'))
        if not named:
            return jsonify(error='Geef je speelveld eerst een naam'), 400
    return jsonify(
        success=True,
        playfield=saved,
        saved_item=named,
        profile_playfields=get_profile_playfields_for_user(current_user.id),
    )

@app.route('/join', methods=['GET', 'POST'])
@login_required
def join():
    blocked = require_verified_for_play()
    if blocked: return blocked
    existing = open_game_for_user(current_user.id)
    if existing:
        flash(f'Je zit al in een spel. Je wordt doorgestuurd naar {existing.game.name}.', 'warning')
        return redirect(game_url_for_player(existing))
    # Support ?code= from QR â€” auto-redirect if valid code given
    prefill = request.args.get('code', '').strip().upper()
    if prefill and request.method == 'GET':
        game = Game.query.filter_by(code=prefill).first()
        if game and game.status != 'finished':
            ex = GamePlayer.query.filter_by(game_id=game.id, user_id=current_user.id).first()
            if ex:
                return redirect(url_for('lobby' if game.status == 'lobby' else 'game_dashboard', code=prefill))
            return redirect(url_for('join_team', code=prefill))
    if request.method == 'POST':
        code = request.form.get('code', '').strip().upper()
        game = Game.query.filter_by(code=code).first()
        if not game:                    flash('Spel niet gevonden.', 'danger')
        elif game.status == 'finished': flash('Dit spel is al afgelopen.', 'warning')
        else:
            ex = GamePlayer.query.filter_by(game_id=game.id, user_id=current_user.id).first()
            if ex:
                return redirect(url_for('lobby' if game.status == 'lobby' else 'game_dashboard', code=code))
            return redirect(url_for('join_team', code=code))
    return render_template('join.html', prefill=prefill)

@app.route('/join/<code>/team', methods=['GET', 'POST'])
@login_required
def join_team(code):
    blocked = require_verified_for_play()
    if blocked: return blocked
    code = code.upper()
    existing = open_game_for_user(current_user.id)
    if existing and existing.game.code != code:
        flash(f'Je zit al in een spel. Je wordt doorgestuurd naar {existing.game.name}.', 'warning')
        return redirect(game_url_for_player(existing))
    game = Game.query.filter_by(code=code).first_or_404()
    if game.status == 'finished':
        flash('Spel al afgelopen.', 'warning'); return redirect(url_for('dashboard'))
    ex = GamePlayer.query.filter_by(game_id=game.id, user_id=current_user.id).first()
    if ex: return redirect(url_for('lobby' if game.status == 'lobby' else 'game_dashboard', code=code))
    if request.method == 'POST':
        existing = open_game_for_user(current_user.id)
        if existing and existing.game.code != code:
            flash(f'Je zit al in een spel. Je wordt doorgestuurd naar {existing.game.name}.', 'warning')
            return redirect(game_url_for_player(existing))
        role = request.form.get('role', 'runner')
        codename = assign_codename(role, game.id)
        db.session.add(GamePlayer(
            game_id=game.id, user_id=current_user.id, role=role,
            codename=codename, offline_uses_left=game.offline_uses,
        ))
        db.session.commit()
        hub.broadcast(code, 'player_joined', {
            'user_id': current_user.id,
            'username': current_user.username,
            'codename': codename,
            'role': role,
        })
        return redirect(url_for('lobby', code=code))
    hunters = GamePlayer.query.filter_by(game_id=game.id, role='hunter').count()
    runners = GamePlayer.query.filter_by(game_id=game.id, role='runner').count()
    return render_template('join_team.html', game=game, hunters=hunters, runners=runners)


@app.route('/api/game/<code>/lobby_state')
@login_required
def api_lobby_state(code):
    """Returns current lobby player list â€” used as WS fallback."""
    game = Game.query.filter_by(code=code).first_or_404()
    countdown_remaining = 0
    countdown_until = None
    if game.countdown_until and datetime.utcnow() < game.countdown_until:
        countdown_remaining = max(0, int(math.ceil((game.countdown_until - datetime.utcnow()).total_seconds())))
        countdown_until = utc_iso(game.countdown_until)
    players = []
    for p in game.players.all():
        players.append({
            'user_id':   p.user_id,
            'username':  p.user.username,
            'codename':  p.codename,
            'role':      p.role,
            'gps':       p.gps_enabled,
            'camera':    p.camera_enabled,
            'is_ready':  p.is_ready,
            'is_creator': p.user_id == game.creator_id,
        })
    return jsonify(
        players=players,
        status=game.status,
        countdown_remaining=countdown_remaining,
        countdown_until=countdown_until,
        headstart_minutes=game.headstart_minutes,
        ws_clients=hub.count(code),
    )

@app.route('/lobby/<code>')
@login_required
def lobby(code):
    game = Game.query.filter_by(code=code).first_or_404()
    me   = GamePlayer.query.filter_by(game_id=game.id, user_id=current_user.id).first()
    if not me: return redirect(url_for('join_team', code=code))
    if game.status == 'active' and me.gps_enabled:
        return redirect(url_for('game_dashboard', code=code))
    players = GamePlayer.query.filter_by(game_id=game.id).all()
    qr_file = f"qr_{code}.png"
    qr_path = os.path.join(os.path.dirname(__file__), 'static', 'qr', qr_file)
    if not os.path.exists(qr_path):
        generate_qr(code, app.config['BASE_URL'])
    join_url = f"{app.config['BASE_URL']}/join?code={code}"
    return render_template('lobby.html', game=game, me=me, players=players,
                           qr_file=qr_file, join_url=join_url,
                           game_extras=get_game_extras(game))

def game_settings_dict(game):
    return {
        'duration_minutes': game.duration_minutes,
        'headstart_minutes': game.headstart_minutes,
        'hunter_interval_sec': game.hunter_interval_sec,
        'runner_interval_sec': game.runner_interval_sec,
        'target_enabled': game.target_enabled,
        'target_duration_sec': game.target_duration_sec,
        'target_cooldown_sec': game.target_cooldown_sec,
        'target_uses_per_runner': game.target_uses_per_runner,
        'show_distance': game.show_distance,
        'live_tracking': game.live_tracking,
        'offline_button': game.offline_button,
        'offline_uses': game.offline_uses,
        'max_offline_sec': game.max_offline_sec,
        'team_mode': game.team_mode,
        'pause_allowed': game.pause_allowed,
        'max_pause_sec': game.max_pause_sec,
        'bike_allowed': game.bike_allowed,
        'feat_hacker': game.feat_hacker,
        'feat_glitch': game.feat_glitch,
        'feat_photo_missions': game.feat_photo_missions,
    }

@app.route('/lobby/<code>/settings', methods=['POST'])
@login_required
def lobby_settings(code):
    game = Game.query.filter_by(code=code).first_or_404()
    if game.creator_id != current_user.id:
        return jsonify(error='Alleen maker'), 403
    if game.status != 'lobby':
        return jsonify(error='Spel al gestart'), 400
    f = request.get_json() or {}
    def clamp_int(key, current, lo, hi):
        try:
            return max(lo, min(hi, int(f.get(key, current))))
        except (TypeError, ValueError):
            return current
    def bool_val(key, current):
        return bool(f[key]) if key in f else current
    if 'duration_minutes'    in f: game.duration_minutes    = clamp_int('duration_minutes', game.duration_minutes, 5, 300)
    if 'headstart_minutes'   in f: game.headstart_minutes   = clamp_int('headstart_minutes', game.headstart_minutes, 0, 30)
    if 'duration_minutes' in f or 'headstart_minutes' in f:
        # Headstart shouldn't eat up more than a third of a (short) game
        game.headstart_minutes = min(game.headstart_minutes, max(0, game.duration_minutes // 3))
    if 'hunter_interval_sec' in f: game.hunter_interval_sec = clamp_int('hunter_interval_sec', game.hunter_interval_sec, 60, 7200)
    if 'runner_interval_sec' in f:
        game.runner_interval_sec = None if f.get('runner_interval_sec') in (None, '', 'off') else clamp_int('runner_interval_sec', game.runner_interval_sec or 600, 60, 7200)
    if 'target_enabled'      in f: game.target_enabled      = bool_val('target_enabled', game.target_enabled)
    if 'target_duration_sec' in f: game.target_duration_sec = clamp_int('target_duration_sec', game.target_duration_sec, 60, 1800)
    if 'target_cooldown_sec' in f: game.target_cooldown_sec = clamp_int('target_cooldown_sec', game.target_cooldown_sec, 60, 3600)
    if 'target_uses_per_runner' in f: game.target_uses_per_runner = clamp_int('target_uses_per_runner', game.target_uses_per_runner, 0, 10)
    if 'show_distance'      in f: game.show_distance       = bool_val('show_distance', game.show_distance)
    if 'live_tracking'      in f: game.live_tracking       = bool_val('live_tracking', game.live_tracking)
    if 'offline_button'      in f: game.offline_button      = bool_val('offline_button', game.offline_button)
    if 'offline_uses'        in f: game.offline_uses        = clamp_int('offline_uses', game.offline_uses, 1, 5)
    if 'max_offline_sec'     in f: game.max_offline_sec     = clamp_int('max_offline_sec', game.max_offline_sec, 30, 600)
    if 'team_mode'           in f: game.team_mode           = bool_val('team_mode', game.team_mode)
    if 'pause_allowed'       in f: game.pause_allowed       = bool_val('pause_allowed', game.pause_allowed)
    if 'max_pause_sec'       in f: game.max_pause_sec       = clamp_int('max_pause_sec', game.max_pause_sec, 30, 1800)
    if 'bike_allowed'        in f: game.bike_allowed        = bool_val('bike_allowed', game.bike_allowed)
    if 'feat_hacker'         in f: game.feat_hacker         = bool_val('feat_hacker', game.feat_hacker)
    if 'feat_glitch'         in f: game.feat_glitch         = bool_val('feat_glitch', game.feat_glitch)
    if 'feat_photo_missions' in f: game.feat_photo_missions = bool_val('feat_photo_missions', game.feat_photo_missions)
    db.session.commit()
    hub.broadcast(code, 'settings_updated', {
        'duration': game.duration_minutes,
        'headstart': game.headstart_minutes,
        'hunter_interval': game.hunter_interval_sec,
        'runner_interval': game.runner_interval_sec,
    })
    return jsonify(success=True, settings=game_settings_dict(game))

@app.route('/game/<code>')
@login_required
def game_dashboard(code):
    game = Game.query.filter_by(code=code).first_or_404()
    ensure_game_finished_if_needed(game)
    me   = GamePlayer.query.filter_by(game_id=game.id, user_id=current_user.id).first()
    if not me: return redirect(url_for('join'))
    if game.status == 'lobby' or not me.gps_enabled:
        return redirect(url_for('lobby', code=code))
    missions = PHOTO_MISSIONS if game.feat_photo_missions else []
    return render_template('game_dashboard.html', game=game, me=me, missions=missions,
                           playfield=get_playfield(game),
                           my_class=get_player_class(game, current_user.id),
                           CATCH_MIN_PROGRESS_PCT=CATCH_MIN_PROGRESS_PCT)

# â”€â”€ API: Lobby â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@app.route('/api/game/<code>/gps_status', methods=['POST'])
@login_required
def api_gps_status(code):
    game = Game.query.filter_by(code=code).first_or_404()
    me   = GamePlayer.query.filter_by(game_id=game.id, user_id=current_user.id).first()
    if not me: return jsonify(error='Niet in spel'), 403
    d = request.get_json()
    me.gps_enabled    = d.get('gps', False)
    me.camera_enabled = d.get('camera', False)
    if me.gps_enabled:
        if d.get('lat') is not None and d.get('lon') is not None:
            me.last_lat = d.get('lat')
            me.last_lon = d.get('lon')
            me.last_accuracy = d.get('accuracy')
            me.last_seen = datetime.utcnow()
    else:
        me.is_ready = False
        if game.status == 'lobby':
            db.session.delete(me)
            db.session.commit()
            hub.broadcast(code, 'player_left', {'user_id': current_user.id, 'username': current_user.username, 'gps_denied': True})
            return jsonify(success=False, removed=True, redirect=url_for('dashboard'),
                           error='Locatie is verplicht. Je bent uit de lobby gehaald.'), 403
    db.session.commit()
    hub.broadcast(code, 'permissions_update', {
        'user_id': current_user.id,
        'gps': me.gps_enabled,
        'camera': me.camera_enabled,
    })
    return jsonify(success=True)

@app.route('/api/game/<code>/ready', methods=['POST'])
@login_required
def api_ready(code):
    game = Game.query.filter_by(code=code).first_or_404()
    me   = GamePlayer.query.filter_by(game_id=game.id, user_id=current_user.id).first()
    if not me: return jsonify(error='Niet in spel'), 403
    ready = request.get_json().get('ready', False)
    if ready and not me.gps_enabled: return jsonify(error='Zet eerst GPS aan'), 400
    me.is_ready = ready; db.session.commit()
    hub.broadcast(code, 'player_ready', {'user_id': current_user.id, 'is_ready': ready,
                                          'codename': me.codename})
    return jsonify(success=True)


@app.route('/api/game/<code>/switch_role', methods=['POST'])
@login_required
def api_switch_role(code):
    game = Game.query.filter_by(code=code).first_or_404()
    if game.status != 'lobby': return jsonify(error='Spel al gestart'), 400
    me   = GamePlayer.query.filter_by(game_id=game.id, user_id=current_user.id).first()
    if not me: return jsonify(error='Niet in spel'), 403
    new_role = request.get_json().get('role')
    if new_role not in ('hunter', 'runner'): return jsonify(error='Ongeldige rol'), 400
    me.role     = new_role
    me.is_ready = False  # reset ready on role change
    me.codename = assign_codename(new_role, game.id)
    db.session.commit()
    hub.broadcast(code, 'player_role_change', {
        'user_id': current_user.id,
        'username': current_user.username,
        'role': new_role,
        'codename': me.codename,
    })
    return jsonify(success=True, codename=me.codename)

@app.route('/api/game/<code>/start', methods=['POST'])
@login_required
def api_start_game(code):
    game = Game.query.filter_by(code=code).first_or_404()
    if game.creator_id != current_user.id: return jsonify(error='Alleen maker'), 403
    if game.status != 'lobby':             return jsonify(error='Al gestart'),   400
    f = request.get_json(silent=True) or {}
    force_start = bool(f.get('force_start'))
    players  = game.players.all()
    hunters  = [p for p in players if p.role == 'hunter']
    runners  = [p for p in players if p.role == 'runner']
    if not hunters: return jsonify(error='Minimaal 1 hunter nodig'), 400
    if not runners: return jsonify(error='Minimaal 1 runner nodig'), 400
    not_ready = [p for p in players if not p.is_ready]
    if not_ready:
        return jsonify(error='Niet klaar: ' + ', '.join(p.user.username for p in not_ready)), 400
    no_gps = [p for p in players if not p.gps_enabled or p.last_lat is None or p.last_lon is None]
    if no_gps:
        return jsonify(error='GPS ontbreekt bij: ' + ', '.join(p.user.username for p in no_gps)), 400
    missing_camera = [p.user.username for p in players if not p.camera_enabled]
    if game.feat_photo_missions and missing_camera and not force_start:
        return jsonify(
            warning='Niet alle spelers hebben hun camera gedeeld. Wil je het spel toch starten?',
            missing_camera=missing_camera,
            can_force_start=True,
        ), 409

    assign_game_classes(game)

    # Broadcast countdown to ALL players immediately (including maker)
    # Frontend handles the 5-second countdown locally
    import gevent
    game.countdown_until = datetime.utcnow() + timedelta(seconds=5)
    db.session.commit()

    # Broadcast RIGHT NOW so everyone (including maker) starts at the same time
    hub.broadcast(code, 'countdown_start', {
        'seconds': 5,
        'countdown_until': utc_iso(game.countdown_until),
        'headstart_minutes': game.headstart_minutes,
    })

    # Start game after 5s in background
    def _do_start():
        gevent.sleep(5)
        with app.app_context():
            g2 = Game.query.filter_by(code=code).first()
            if g2 and g2.status == 'lobby':
                g2.status = 'active'
                g2.started_at = datetime.utcnow()
                for p in g2.players.all():
                    p.user.total_games += 1
                db.session.commit()
                hub.broadcast(code, 'game_started', {
                    'code': code,
                    'headstart_minutes': g2.headstart_minutes,
                })
    gevent.spawn(_do_start)
    # Return countdown=0 so maker's frontend also waits for WS event
    return jsonify(success=True, countdown=5,
                   countdown_until=utc_iso(game.countdown_until),
                   headstart_minutes=game.headstart_minutes)

# â”€â”€ API: In-game state â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@app.route('/api/game/<code>/state')
@login_required
def api_state(code):
    game = Game.query.filter_by(code=code).first_or_404()
    ensure_game_finished_if_needed(game)
    me   = GamePlayer.query.filter_by(game_id=game.id, user_id=current_user.id).first()
    if not me: return jsonify(error='Niet in spel'), 403
    me.last_seen = datetime.utcnow()
    db.session.commit()
    pause_state = get_game_pause_state(game)
    if pause_state.get('active'):
        maybe_resume_game_from_pause(game)
        pause_state = get_game_pause_state(game)
    now = datetime.utcnow()

    # Check if in countdown phase
    in_countdown = (game.countdown_until and
                    game.status == 'lobby' and
                    now < game.countdown_until)
    elapsed   = game.effective_elapsed
    hs_left   = max(0, game.headstart_minutes * 60 - elapsed)
    time_left = max(0, game.duration_minutes  * 60 - elapsed)

    # Check active target on me (as runner)
    active_target = None
    if me.role == 'runner':
        t = (Target.query.filter_by(game_id=game.id, runner_id=current_user.id, is_active=True)
             .order_by(Target.activated_at.desc()).first())
        if t and t.expires_at and now < t.expires_at:
            # Find distance from hunter to me
            hunter_gp = GamePlayer.query.filter_by(game_id=game.id,
                                                    user_id=t.hunter_id).first()
            dist_to_hunter = None
            if hunter_gp and hunter_gp.last_lat and me.last_lat:
                dist_to_hunter = round(haversine(me.last_lat, me.last_lon,
                                                  hunter_gp.last_lat, hunter_gp.last_lon))
            active_target = {
                'hunter': t.hunter.username,
                'hunter_codename': hunter_gp.codename if hunter_gp else '?',
                'expires_in': max(0, int(math.ceil((t.expires_at - now).total_seconds()))),
                'duration': game.target_duration_sec,
                'expires_at': utc_iso(t.expires_at),
                'distance': dist_to_hunter,
            }
        elif t and t.is_active:
            t.is_active = False; db.session.commit()

    # Hunter cooldown
    hunter_cd = 0
    if me.role == 'hunter' and me.target_used_at and game.target_enabled:
        rem = game.target_cooldown_sec - (now - me.target_used_at).total_seconds()
        hunter_cd = max(0, int(math.ceil(rem)))

    hunter_active_target = None
    if me.role == 'hunter':
        ht = (Target.query.filter_by(game_id=game.id, hunter_id=current_user.id, is_active=True)
              .order_by(Target.activated_at.desc()).first())
        if not ht:
            ht = (Target.query.filter_by(game_id=game.id, is_active=True)
                  .order_by(Target.activated_at.desc()).first())
        if ht and ht.expires_at and now < ht.expires_at:
            runner_gp = GamePlayer.query.filter_by(game_id=game.id, user_id=ht.runner_id).first()
            hunter_active_target = {
                'runner_id': ht.runner_id,
                'runner_codename': runner_gp.codename if runner_gp else '?',
                'hunter_id': ht.hunter_id,
                'expires_in': max(0, int(math.ceil((ht.expires_at - now).total_seconds()))),
                'duration': game.target_duration_sec,
                'expires_at': utc_iso(ht.expires_at),
            }
        elif ht and ht.is_active:
            ht.is_active = False
            db.session.commit()

    # Enforce offline limit â€” auto come back online and broadcast location
    for op in game.players:
        if op.is_offline and op.offline_since and game.max_offline_sec > 0:
            if (now - op.offline_since).total_seconds() >= game.max_offline_sec:
                op.is_offline = False; op.offline_since = None
                db.session.commit()
                hub.broadcast(code, 'runner_online', {
                    'user_id': op.user_id,
                    'codename': op.codename,
                    'lat': op.last_lat,
                    'lon': op.last_lon,
                    'forced': True,
                })
                if op.last_lat is not None and op.last_lon is not None:
                    hub.broadcast(code, 'runner_location', {
                        'user_id': op.user_id,
                        'lat': op.last_lat,
                        'lon': op.last_lon,
                        'acc': op.last_accuracy,
                        'forced_online': True,
                    })

    effects = get_game_effects(game)
    players = []
    pause_active = bool(pause_state.get('active'))
    for p in game.players:
        pd = {
            'id': p.user_id,
            'username': p.user.username,
            'codename': p.codename or p.user.username,
            'real_revealed': p.real_name_revealed,
            'role': p.role,
            'is_ready': p.is_ready,
            'gps': p.gps_enabled,
            'points': round(p.points, 2),
            'distance': round(p.distance),
            'is_offline': p.is_offline,
            'is_paused': pause_active or p.is_paused,
            'is_caught': p.is_caught,
            'offline_uses_left': p.offline_uses_left,
            'offline_remaining': max(0, int(math.ceil(game.max_offline_sec - (now - p.offline_since).total_seconds()))) if p.is_offline and p.offline_since and game.max_offline_sec else 0,
            'offline_until': utc_iso(p.offline_since + timedelta(seconds=game.max_offline_sec)) if p.is_offline and p.offline_since and game.max_offline_sec else None,
            'last_seen': p.last_seen.isoformat() if p.last_seen else None,
        }
        # Hunters see runner positions (after headstart, not offline/paused)
        if (me.role == 'hunter' and p.role == 'runner' and game.is_headstart_over
                and not p.is_offline and not (pause_active or p.is_paused) and not p.is_caught
                and p.last_lat is not None):
            snap = get_runner_snapshot(game, p)
            if snap:
                pd['lat'] = snap['lat']; pd['lon'] = snap['lon']
                pd['location_live'] = bool(snap.get('live'))
                pd['location_slot'] = snap.get('slot')
            glitch_until = float(effects.get('glitches', {}).get(str(p.user_id), 0) or 0)
            if glitch_until > _now_ts():
                pd['lat'], pd['lon'] = _destination_point(pd['lat'], pd['lon'], 90, (p.user_id * 47) % 360)
                pd['glitched'] = True

        # Runners see distance to hunters
        if me.role == 'runner' and p.role == 'hunter' and p.last_lat and me.last_lat:
            pd['distance_to'] = round(haversine(me.last_lat, me.last_lon,
                                                 p.last_lat, p.last_lon))

        # Hacker: give fake coordinates if active
        if (me.role == 'hunter' and p.role == 'runner'
                and p.hacker_active and p.hacker_until
                and datetime.utcnow() < p.hacker_until and p.last_lat):
            pd['lat'] = p.last_lat + random.uniform(-0.005, 0.005)
            pd['lon'] = p.last_lon + random.uniform(-0.005, 0.005)

        players.append(pd)

    nearest_hunter = None
    if me.role == 'runner' and me.last_lat:
        dists = [haversine(me.last_lat, me.last_lon, p.last_lat, p.last_lon)
                 for p in game.players if p.role == 'hunter' and p.last_lat and not p.is_caught]
        if dists: nearest_hunter = round(min(dists))

    # Offline allowed? (last 10% of game = no offline)
    offline_allowed_now = me.offline_uses_left > 0 and game.progress_pct < 90
    # Can use offline? Not if targeted
    if active_target: offline_allowed_now = False
    if not game.is_headstart_over:
        offline_allowed_now = False
    if pause_active:
        offline_allowed_now = False
    end_result = get_game_end_result(game)

    return jsonify(
        status=game.status, players=players, elapsed=elapsed,
        server_now=utc_iso(now),
        hs_left=hs_left, headstart_over=game.is_headstart_over,
        time_left=time_left, progress_pct=round(game.progress_pct, 1),
        my_role=me.role, my_codename=me.codename,
        my_points=round(me.points, 2), my_distance=round(me.distance),
        my_gps=me.gps_enabled, is_finished=game.is_finished,
        winner_role=end_result.get('winner_role'), end_reason=end_result.get('reason'),
        end_message=end_result.get('message'), no_points=bool(end_result.get('no_points')),
        playfield_status=playfield_status(game, me.last_lat, me.last_lon) if me.last_lat is not None and me.last_lon is not None else 'unknown',
        zone_pressure=get_zone_pressure(game, current_user.id),
        is_offline=me.is_offline, is_paused=pause_active or me.is_paused, pause_active=pause_active,
        pause_reason=pause_state.get('reason'), is_caught=me.is_caught,
        offline_uses_left=me.offline_uses_left,
        offline_remaining=max(0, int(math.ceil(game.max_offline_sec - (now - me.offline_since).total_seconds()))) if me.is_offline and me.offline_since and game.max_offline_sec else 0,
        offline_until=utc_iso(me.offline_since + timedelta(seconds=game.max_offline_sec)) if me.is_offline and me.offline_since and game.max_offline_sec else None,
        nearest_hunter=nearest_hunter, active_target=active_target,
        hunter_active_target=hunter_active_target,
        in_countdown=in_countdown,
        hunter_target_cooldown=hunter_cd,
        pause_remaining=0,
        offline_allowed_now=offline_allowed_now,
        # game config
        hunter_interval=game.hunter_interval_sec,
        runner_interval=game.runner_interval_sec,
        target_enabled=game.target_enabled,
        offline_button=game.offline_button,
        live_tracking=game.live_tracking,
        pause_allowed=game.pause_allowed,
        show_distance=game.show_distance,
        feat_emergency=game.feat_emergency,
        team_mode=game.team_mode,
        lootboxes=get_game_lootboxes(game),
        my_class=get_player_class(game, current_user.id),
        class_cooldown=class_cooldown_remaining(game, current_user.id),
        hazards=[h for h in effects.get('hazards', []) if h.get('owner_id') == current_user.id],
    )

def _clear_gps(game):
    """Remove GPS coordinates when game ends."""
    for p in game.players:
        p.last_lat = None; p.last_lon = None; p.last_accuracy = None
    db.session.commit()

_last_ping_at = {}  # (game_id, user_id) -> time.time(), throttles LocationPing inserts
LOCATION_PING_INTERVAL_SEC = 20

def _maybe_log_location_ping(game, user_id, lat, lon):
    key = (game.id, user_id)
    now = time.time()
    if now - _last_ping_at.get(key, 0) < LOCATION_PING_INTERVAL_SEC:
        return
    _last_ping_at[key] = now
    db.session.add(LocationPing(game_id=game.id, user_id=user_id, lat=lat, lon=lon))

def finish_game(game, reason='manual', broadcast=True):
    """Finish a game once, clear locations, send summary mail and notify clients."""
    if not game or game.status == 'finished':
        return False
    hunters, runners = active_role_counts(game)
    active_total = hunters + runners
    winner_role = None
    no_points = False
    message = None
    if active_total == 0:
        no_points = True
        message = 'Alle spelers zijn uit het spel. Het spel is afgesloten.'
    if reason == 'time_up':
        winner_role = 'runner'
        message = 'De tijd is voorbij. Runners hebben gewonnen.'
    elif reason in ('player_left', 'not_enough_players', 'player_timeout') and active_total == 1:
        if game.progress_pct >= 75:
            winner_role = 'hunter' if hunters == 1 else 'runner'
            message = 'Iedereen heeft het spel verlaten. Jij bent als laatste over en hebt gewonnen.'
        else:
            no_points = True
            message = 'Iedereen heeft het spel verlaten. Helaas is er nog te kort gespeeld, waardoor je geen punten hebt gekregen.'
    elif active_total > 0 and runners < 1:
        winner_role = 'hunter'
        message = 'Er zijn geen actieve runners meer. Hunters hebben gewonnen.'
    elif active_total > 0 and hunters < 1:
        winner_role = 'runner'
        message = 'Er zijn geen actieve hunters meer. Runners hebben gewonnen.'
    game.status = 'finished'
    game.ended_at = datetime.utcnow()
    if winner_role in ('hunter', 'runner') and not no_points:
        for p in game.players:
            if p.role == winner_role:
                if winner_role == 'hunter':
                    p.user.hunter_wins += 1
                else:
                    p.user.runner_wins += 1
    SiteSetting.set(_game_end_result_key(game.id), json.dumps({
        'reason': reason,
        'winner_role': winner_role,
        'no_points': no_points,
        'message': message,
        'ended_at': game.ended_at.isoformat(),
    }))
    save_game_pause_state(game, {})
    for p in game.players:
        p.is_paused = False
        p.paused_since = None
        p.pause_reason = None
    db.session.commit()
    _clear_gps(game)
    for p in game.players:
        _last_ping_at.pop((game.id, p.user_id), None)
    send_game_summary_email(game)
    if broadcast:
        hub.broadcast(game.code, 'game_ended', {'code': game.code, 'reason': reason, 'winner_role': winner_role, 'no_points': no_points, 'message': message})
    return True

def active_role_counts(game):
    hunters = GamePlayer.query.filter_by(game_id=game.id, role='hunter', is_caught=False).count()
    runners = GamePlayer.query.filter_by(game_id=game.id, role='runner', is_caught=False).count()
    return hunters, runners

def ensure_game_finished_if_needed(game):
    """Close active games when time is up or one side no longer has players."""
    if not game or game.status != 'active':
        return False
    sweep_stale_players(game)
    if game.is_finished:
        return finish_game(game, 'time_up')
    hunters, runners = active_role_counts(game)
    if hunters < 1 or runners < 1:
        return finish_game(game, 'not_enough_players')
    return False

_last_active_game_sweep = None

@app.before_request
def sweep_finished_active_games():
    global _last_active_game_sweep
    if request.endpoint in ('static', 'uploaded_file', 'bg_file', 'qr_image'):
        return
    now = datetime.utcnow()
    if _last_active_game_sweep and (now - _last_active_game_sweep).total_seconds() < 60:
        return
    _last_active_game_sweep = now
    for g in Game.query.filter_by(status='active').all():
        sweep_stale_players(g)
        ensure_game_finished_if_needed(g)
    for g in Game.query.filter_by(status='finished').all():
        if g.ended_at and (now - g.ended_at).total_seconds() > 15 * 60:
            db.session.delete(g)
    db.session.commit()

@app.route('/api/game/<code>/location', methods=['POST'])
@login_required
def api_location(code):
    game = Game.query.filter_by(code=code).first_or_404()
    me   = GamePlayer.query.filter_by(game_id=game.id, user_id=current_user.id).first()
    if not me: return jsonify(error='Niet in spel'), 403
    if ensure_game_finished_if_needed(game):
        return jsonify(error='Spel afgelopen', status='finished'), 410
    if game.status != 'active': return jsonify(error='Spel niet actief'), 400
    d = request.get_json()
    lat = d.get('lat'); lon = d.get('lon'); acc = d.get('accuracy', 0)
    speed_ms = d.get('speed')  # speed in m/s from Geolocation API
    if lat is None or lon is None: return jsonify(error='Ongeldige locatie'), 400

    if me.last_lat and me.last_lon:
        dist = haversine(me.last_lat, me.last_lon, lat, lon)
        if 0 < dist < 500:  # sanity: max 500m per update
            pts = calc_points(dist, speed_ms, game.points_multiplier)
            # Double points if targeted
            if game.target_enabled:
                t = (Target.query.filter_by(game_id=game.id, is_active=True)
                     .filter((Target.hunter_id == current_user.id) |
                             (Target.runner_id == current_user.id)).first())
                if t and t.expires_at and datetime.utcnow() < t.expires_at:
                    pts *= 2
            me.distance += dist; me.points += pts
            current_user.total_distance += dist; current_user.total_points += pts

    me.last_lat = lat; me.last_lon = lon
    me.last_accuracy = acc; me.last_speed_ms = speed_ms
    me.last_seen = datetime.utcnow(); me.gps_enabled = True
    _maybe_log_location_ping(game, current_user.id, lat, lon)
    hazard_messages = check_hazard_triggers(game, me, code)
    outside_m = playfield_outside_distance_m(game, lat, lon)
    zone_pressure = update_zone_pressure(game, me, outside_m)
    if outside_m > 5:
        msg = 'Je bent buiten het speelveld. Ga direct terug!'
        hazard_messages.append(msg)
        # Not flagged as suspicious: leaving the playfield happens during normal play too.
        # Flagging is reserved for real anti-cheat signals (see 'high_speed' below).
        log_activity('playfield_violation', f'{me.codename or current_user.username} buiten speelveld in {game.code}')
        if zone_pressure.get('seconds', 0) >= zone_pressure.get('limit_sec', 30) and not me.is_caught:
            me.is_caught = True
            hazard_messages.append('Je was te lang buiten het speelveld en bent af.')
            hub.broadcast(code, 'player_zone_out', {
                'user_id': current_user.id,
                'codename': me.codename or current_user.username,
                'role': me.role,
            })
    # Anti-cheat: flag suspiciously high speed (>25 km/h = ~7 m/s)
    if speed_ms and speed_ms > 7.0:
        log_activity('high_speed', f'{speed_ms_to_kmh(speed_ms):.1f} km/h', flag=True)
    db.session.commit()
    maybe_resume_game_from_pause(game)

    if me.is_caught and ensure_game_finished_if_needed(game):
        return jsonify(error='Spel afgelopen', status='finished',
                       hazard_messages=hazard_messages,
                       zone_pressure=get_zone_pressure(game, current_user.id)), 410

    if me.role == 'runner' and not me.is_caught and not me.is_offline and not me.is_paused:
        hub.broadcast(code, 'runner_location',
                      {'user_id': current_user.id, 'lat': lat, 'lon': lon, 'acc': acc})
    elif me.role == 'hunter' and not me.is_caught:
        hub.broadcast(code, 'hunter_location',
                      {'user_id': current_user.id, 'lat': lat, 'lon': lon})
    return jsonify(success=True, points=round(me.points, 2), distance=round(me.distance, 1),
                   hazard_messages=hazard_messages,
                   zone_pressure=get_zone_pressure(game, current_user.id))

@app.route('/api/game/<code>/offline', methods=['POST'])
@login_required
def api_offline(code):
    game = Game.query.filter_by(code=code).first_or_404()
    me   = GamePlayer.query.filter_by(game_id=game.id, user_id=current_user.id).first()
    if not me or me.role != 'runner': return jsonify(error='Alleen runners'), 403
    if get_game_pause_state(game).get('active'):
        return jsonify(error='Pauze actief'), 400
    if not game.offline_button:       return jsonify(error='Offline knop uit'), 400
    if not game.is_headstart_over:
        return jsonify(error='Offline kan pas na de voorsprong gebruikt worden'), 400

    # Can't go offline if targeted
    active_t = Target.query.filter_by(game_id=game.id, runner_id=current_user.id,
                                       is_active=True).first()
    if active_t and active_t.expires_at and datetime.utcnow() < active_t.expires_at:
        return jsonify(error='Je bent een target â€” je kunt niet offline gaan!'), 400

    # Can't use in last 10% of game
    if game.progress_pct >= 90:
        return jsonify(error='Offline niet beschikbaar in de laatste 10% van het spel'), 400

    if me.is_offline:
        remaining = max(0, int(game.max_offline_sec - (datetime.utcnow() - me.offline_since).total_seconds())) if me.offline_since else 0
        return jsonify(error=f'Je bent al offline. Nog {remaining}s.'), 400

    # Going offline. Runner cannot manually turn this off again.
    if me.offline_uses_left <= 0:
        return jsonify(error='Geen offline knoppen meer over'), 400
    me.is_offline = True; me.offline_since = datetime.utcnow()
    me.offline_uses_left -= 1
    hub.broadcast(code, 'runner_offline', {
        'user_id':   current_user.id,
        'codename':  me.codename or current_user.username,
        'duration':  game.max_offline_sec,
        'uses_left': me.offline_uses_left,
        'offline_since': utc_iso(me.offline_since),
        'offline_until': utc_iso(me.offline_since + timedelta(seconds=game.max_offline_sec)),
    })
    db.session.commit()
    return jsonify(success=True, is_offline=me.is_offline,
                   offline_uses_left=me.offline_uses_left,
                   offline_remaining=game.max_offline_sec,
                   offline_until=utc_iso(me.offline_since + timedelta(seconds=game.max_offline_sec)))

@app.route('/api/game/<code>/pause', methods=['POST'])
@login_required
def api_pause(code):
    game = Game.query.filter_by(code=code).first_or_404()
    me   = GamePlayer.query.filter_by(game_id=game.id, user_id=current_user.id).first()
    if not me: return jsonify(error='Niet in spel'), 403
    if not game.pause_allowed: return jsonify(error='Pauze niet toegestaan'), 400
    d = request.get_json()
    pausing = d.get('pause', True)
    reason  = d.get('reason', '')
    pause_state = get_game_pause_state(game)
    if pausing:
        if pause_state.get('active'):
            return jsonify(success=True, is_paused=True, pause_active=True)
        snapshot = {}
        for p in game.players.all():
            if p.is_caught:
                continue
            snapshot[str(p.user_id)] = {
                'lat': p.last_lat,
                'lon': p.last_lon,
                'accuracy': p.last_accuracy,
            }
            p.is_paused = True
            p.paused_since = datetime.utcnow()
            p.pause_reason = reason
        pause_state = {
            'active': True,
            'started_at': datetime.utcnow().isoformat(),
            'paused_since': datetime.utcnow().isoformat(),
            'total_paused_sec': int(pause_state.get('total_paused_sec') or 0),
            'reason': reason,
            'initiator_user_id': current_user.id,
            'snapshot': snapshot,
        }
        save_game_pause_state(game, pause_state)
        db.session.commit()
        hub.broadcast(code, 'runner_paused', {
            'user_id': current_user.id,
            'codename': me.codename,
            'reason': reason,
            'game_paused': True,
        })
        return jsonify(success=True, is_paused=True, pause_active=True)

    if not pause_state.get('active'):
        return jsonify(success=True, is_paused=False, pause_active=False)
    if not _pause_snapshot_ready(game, pause_state):
        return jsonify(error='Nog niet iedereen staat binnen 10 meter van de pauze-positie'), 400
    started_at = pause_state.get('started_at')
    total_paused_sec = int(pause_state.get('total_paused_sec') or 0)
    if started_at:
        try:
            total_paused_sec += max(0, int((datetime.utcnow() - datetime.fromisoformat(started_at)).total_seconds()))
        except Exception:
            pass
    pause_state['active'] = False
    pause_state['paused_since'] = None
    pause_state['total_paused_sec'] = total_paused_sec
    pause_state['resumed_at'] = datetime.utcnow().isoformat()
    save_game_pause_state(game, pause_state)
    for p in game.players.all():
        p.is_paused = False
        p.paused_since = None
        p.pause_reason = None
    db.session.commit()
    hub.broadcast(code, 'runner_unpaused', {
        'user_id': current_user.id,
        'forced': False,
        'game_paused': False,
    })
    return jsonify(success=True, is_paused=False, pause_active=False)

@app.route('/api/game/<code>/target', methods=['POST'])
@login_required
def api_set_target(code):
    game = Game.query.filter_by(code=code).first_or_404()
    me   = GamePlayer.query.filter_by(game_id=game.id, user_id=current_user.id).first()
    if not me or me.role != 'hunter': return jsonify(error='Alleen hunters'), 403
    if get_game_pause_state(game).get('active'):
        return jsonify(error='Pauze actief'), 400
    if not game.target_enabled:       return jsonify(error='Target systeem uit'), 400
    if me.target_used_at:
        rem = game.target_cooldown_sec - (datetime.utcnow() - me.target_used_at).total_seconds()
        if rem > 0: return jsonify(error=f'Cooldown: nog {int(rem)}s'), 429

    runner_id = request.get_json().get('runner_id')
    runner = GamePlayer.query.filter_by(game_id=game.id, user_id=runner_id,
                                        role='runner').first()
    if not runner: return jsonify(error='Runner niet gevonden'), 404
    if runner.is_caught: return jsonify(error='Runner al gepakt'), 400

    # Check per-runner use limit
    if game.target_uses_per_runner > 0:
        used = json.loads(me.target_uses_on or '{}')
        count = used.get(str(runner_id), 0)
        if count >= game.target_uses_per_runner:
            return jsonify(error=f'Target limiet bereikt voor deze runner ({game.target_uses_per_runner}x)'), 400
        used[str(runner_id)] = count + 1
        me.target_uses_on = json.dumps(used)

    Target.query.filter_by(game_id=game.id, hunter_id=current_user.id,
                            is_active=True).update({'is_active': False})
    t = Target(game_id=game.id, hunter_id=current_user.id, runner_id=runner_id,
               expires_at=datetime.utcnow() + timedelta(seconds=game.target_duration_sec))
    db.session.add(t); me.target_used_at = datetime.utcnow(); db.session.commit()

    # Calculate initial distance to include in broadcast
    initial_distance = None
    if me.last_lat and runner.last_lat:
        initial_distance = round(haversine(
            runner.last_lat, runner.last_lon, me.last_lat, me.last_lon
        ))
    payload = {
        'hunter_id':       current_user.id,
        'hunter_codename': me.codename or current_user.username,
        'runner_id':       runner_id,
        'runner_codename': runner.codename or runner.user.username,
        'duration':        game.target_duration_sec,
        'expires_at':      utc_iso(t.expires_at),
        'expires_in':      game.target_duration_sec,
        'distance':        initial_distance,
    }
    hub.broadcast(code, 'target_set', payload)
    return jsonify(success=True, target=payload, target_cooldown=game.target_cooldown_sec)

@app.route('/api/game/<code>/catch', methods=['POST'])
@login_required
def api_catch_runner(code):
    """Hunter marks a runner as caught."""
    game = Game.query.filter_by(code=code).first_or_404()
    me   = GamePlayer.query.filter_by(game_id=game.id, user_id=current_user.id).first()
    if not me or me.role != 'hunter': return jsonify(error='Alleen hunters'), 403
    if game.status != 'active': return jsonify(error='Spel niet actief'), 400
    if game.progress_pct < CATCH_MIN_PROGRESS_PCT:
        return jsonify(error=f'Aantikken kan pas vanaf {CATCH_MIN_PROGRESS_PCT}% van de speeltijd.'), 400
    d = request.get_json()
    runner_id = d.get('runner_id')
    runner = GamePlayer.query.filter_by(game_id=game.id, user_id=runner_id,
                                        role='runner').first()
    if not runner: return jsonify(error='Runner niet gevonden'), 404
    if runner.is_caught: return jsonify(error='Al gepakt'), 400
    if me.last_lat is None or me.last_lon is None or runner.last_lat is None or runner.last_lon is None:
        return jsonify(error='Locatie onbekend, probeer opnieuw'), 400
    dist = haversine(me.last_lat, me.last_lon, runner.last_lat, runner.last_lon)
    if dist > CATCH_MAX_DISTANCE_M:
        return jsonify(error=f'Te ver weg ({round(dist)}m) - kom binnen {CATCH_MAX_DISTANCE_M}m van de runner.'), 400

    runner.is_caught = True; runner.caught_by = current_user.id
    runner.caught_at = datetime.utcnow()
    runner.real_name_revealed = True
    me.points += 10 * game.points_multiplier
    current_user.total_points += 10 * game.points_multiplier
    current_user.runners_caught += 1
    # Check speed badge (caught quickly)
    if game.started_at:
        elapsed_min = (datetime.utcnow() - game.started_at).total_seconds() / 60
        if elapsed_min < 15:
            award_badge(current_user.id, 'speed_hunter', game.id)
    db.session.commit()
    # Award badges
    new_badges = check_badges_after_game(current_user.id, game.id)
    hub.broadcast(code, 'runner_caught', {
        'runner_id': runner_id,
        'runner_codename': runner.codename,
        'runner_username': runner.user.username,
        'caught_by': current_user.username,
        'caught_by_codename': me.codename,
    })
    # Check if all runners are caught
    remaining = GamePlayer.query.filter_by(game_id=game.id, role='runner',
                                           is_caught=False).count()
    if remaining == 0:
        finish_game(game, 'all_caught')
    return jsonify(success=True, remaining=remaining)

@app.route('/api/game/<code>/emergency', methods=['POST'])
@login_required
def api_emergency(code):
    """Noodknop â€” broadcasts exact location to all players."""
    game = Game.query.filter_by(code=code).first_or_404()
    me   = GamePlayer.query.filter_by(game_id=game.id, user_id=current_user.id).first()
    if not me: return jsonify(error='Niet in spel'), 403
    me.emergency_at = datetime.utcnow(); db.session.commit()
    hub.broadcast(code, 'emergency', {
        'user_id': current_user.id,
        'username': current_user.username,
        'codename': me.codename,
        'lat': me.last_lat,
        'lon': me.last_lon,
        'message': 'ðŸš¨ NOODKNOP INGEDRUKT â€” Ga naar deze persoon!',
    })
    return jsonify(success=True)

@app.route('/api/game/<code>/end', methods=['POST'])
@login_required
def api_end_game(code):
    game = Game.query.filter_by(code=code).first_or_404()
    if game.creator_id != current_user.id and not current_user.is_admin:
        return jsonify(error='Geen rechten'), 403
    finish_game(game, 'manual')
    return jsonify(success=True)

@app.route('/api/game/<code>/chat', methods=['POST'])
@login_required
def api_chat(code):
    game = Game.query.filter_by(code=code).first_or_404()
    if ensure_game_finished_if_needed(game):
        return jsonify(error='Spel afgelopen', status='finished'), 410
    me   = GamePlayer.query.filter_by(game_id=game.id, user_id=current_user.id).first()
    if not me: return jsonify(error='Niet in spel'), 403
    d = request.get_json()
    msg_text = (d.get('message') or '').strip()[:500]
    if not msg_text: return jsonify(error='Leeg bericht'), 400
    team_req = d.get('team', 'team')  # 'team', 'all', or 'proxy'
    if team_req == 'all':
        team = 'all'
    elif team_req == 'proxy':
        team = 'proxy'
    else:
        team = me.role  # default: own team only
    msg  = ChatMessage(game_id=game.id, user_id=current_user.id,
                       team=team, message=msg_text)
    db.session.add(msg); db.session.commit()
    chat_data = {
        'team': team,
        'username': current_user.username,
        'codename': me.codename or current_user.username,
        'display_name': current_user.username if team not in ('all', 'proxy') else (me.codename or current_user.username),
        'message': msg_text,
        'time': msg.created_at.strftime('%H:%M'),
        'user_id': current_user.id,
    }
    hub.broadcast(code, 'chat', chat_data)
    return jsonify(success=True, msg=chat_data)


@app.route('/api/game/<code>/chat_history')
@login_required
def api_chat_history(code):
    game = Game.query.filter_by(code=code).first_or_404()
    ensure_game_finished_if_needed(game)
    me   = GamePlayer.query.filter_by(game_id=game.id, user_id=current_user.id).first()
    if not me: return jsonify(error='Niet in spel'), 403
    mode = request.args.get('mode', 'team')
    team_filter = 'all' if mode == 'all' else 'proxy' if mode == 'proxy' else me.role
    msgs = (ChatMessage.query.filter_by(game_id=game.id, team=team_filter)
            .order_by(ChatMessage.created_at.asc()).limit(100).all())
    items = []
    for m in msgs:
        gp = GamePlayer.query.filter_by(game_id=game.id, user_id=m.user_id).first()
        codename = gp.codename if gp and gp.codename else m.author.username
        display_name = m.author.username if m.team not in ('all', 'proxy') else codename
        items.append({
        'username': m.author.username,
        'codename': codename,
        'display_name': display_name,
        'message': m.message,
        'time': m.created_at.strftime('%H:%M'),
        'user_id': m.user_id,
        'team': m.team,
        })
    return jsonify(items)

# â”€â”€ Posts â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@app.route('/game/<code>/post', methods=['POST'])
@login_required
def create_post(code):
    game = Game.query.filter_by(code=code).first_or_404()
    me   = GamePlayer.query.filter_by(game_id=game.id, user_id=current_user.id).first()
    if not me: return jsonify(error='Niet in spel'), 403
    caption      = request.form.get('caption', '').strip()
    lat          = request.form.get('lat')
    lon          = request.form.get('lon')
    share_loc    = request.form.get('share_location') == '1'
    mission_id   = request.form.get('mission_id', type=int)
    filename = None
    if 'image' in request.files:
        f2 = request.files['image']
        if f2 and f2.filename:
            if not allowed_file(f2.filename):
                return jsonify(error='Alleen jpg, png of webp fotoâ€™s zijn toegestaan.'), 400
            if upload_too_large(f2):
                return jsonify(error='Foto is te groot. Maximaal 6 MB.'), 400
            try:
                filename = save_image(f2, app.config['UPLOAD_FOLDER'])
            except Exception as e:
                app.logger.exception(f"Post image upload failed: {e}")
                return jsonify(error='Foto kon niet worden verwerkt. Probeer een jpg/png/webp.'), 400
    audio_filename = None
    if 'audio' in request.files:
        f3 = request.files['audio']
        if f3 and f3.filename:
            try:
                audio_filename = save_audio(f3, AUDIO_FOLDER)
            except ValueError:
                return jsonify(error='Geluidsfragment kon niet worden opgeslagen (max 10 MB, webm/ogg/mp3/m4a/wav).'), 400
            except Exception as e:
                app.logger.exception(f"Post audio upload failed: {e}")
                return jsonify(error='Geluidsfragment kon niet worden verwerkt.'), 400
    if not filename and not audio_filename and not caption:
        return jsonify(error='Voeg een foto, geluidsfragment of tekst toe.'), 400
    post = Post(
        game_id=game.id, user_id=current_user.id,
        caption=caption or None, image_filename=filename,
        audio_filename=audio_filename,
        lat=float(lat) if lat else None, lon=float(lon) if lon else None,
        share_location=share_loc, mission_id=mission_id,
        approved=None,
    )
    db.session.add(post); db.session.commit()
    hub.broadcast(code, 'new_post', serialize_post(post, current_user.id))
    return jsonify(success=True, post=serialize_post(post, current_user.id))

@app.route('/api/game/<code>/posts')
@login_required
def api_posts(code):
    game  = Game.query.filter_by(code=code).first_or_404()
    posts = (Post.query.filter_by(game_id=game.id)
             .order_by(Post.created_at.desc())
             .all())
    return jsonify([serialize_post(p, current_user.id) for p in posts])

@app.route('/post/<int:pid>/like',   methods=['POST'])
@login_required
def like_post(pid):
    post = Post.query.get_or_404(pid)
    ex   = PostLike.query.filter_by(post_id=pid, user_id=current_user.id).first()
    if ex:
        db.session.delete(ex); post.likes = max(0, post.likes - 1); liked = False
    else:
        db.session.add(PostLike(post_id=pid, user_id=current_user.id))
        post.likes += 1; liked = True
    db.session.commit(); return jsonify(likes=post.likes, liked=liked)

@app.route('/post/<int:pid>/delete', methods=['POST'])
@login_required
def delete_post(pid):
    post = Post.query.get_or_404(pid)
    if post.user_id != current_user.id and not current_user.is_admin:
        return jsonify(error='Geen rechten'), 403
    if post.image_filename:
        try: os.remove(os.path.join(app.config['UPLOAD_FOLDER'], post.image_filename))
        except: pass
    db.session.delete(post); db.session.commit(); return jsonify(success=True)

@app.route('/post/<int:pid>/approve', methods=['POST'])
@login_required
@admin_required
def approve_post(pid):
    post = Post.query.get_or_404(pid)
    d    = request.get_json()
    post.approved = d.get('approved', True)
    if post.approved and post.mission_id:
        m = next((x for x in PHOTO_MISSIONS if x['id'] == post.mission_id), None)
        if m:
            gp = GamePlayer.query.filter_by(game_id=post.game_id,
                                             user_id=post.user_id).first()
            if gp:
                pts = m['pts'] * (post.game.points_multiplier if post.game else 1)
                gp.points += pts; post.points_awarded = pts
                post.author.total_points += pts
    db.session.commit(); return jsonify(success=True)

# â”€â”€ QR code â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@app.route('/qr/<code>.png')
def qr_image(code):
    fname = f"qr_{code}.png"
    fpath = os.path.join(os.path.dirname(__file__), 'static', 'qr', fname)
    if not os.path.exists(fpath):
        game = Game.query.filter_by(code=code).first_or_404()
        generate_qr(game.code, app.config['BASE_URL'])
    return send_from_directory(os.path.join(os.path.dirname(__file__), 'static', 'qr'), fname)



@app.route('/api/game/<code>/guess_name', methods=['POST'])
@login_required
def api_guess_name(code):
    """Hunter/Runner guesses real name of opponent. +3 correct, -10 wrong."""
    game = Game.query.filter_by(code=code).first_or_404()
    me   = GamePlayer.query.filter_by(game_id=game.id, user_id=current_user.id).first()
    if not me: return jsonify(error='Niet in spel'), 403
    d = request.get_json()
    target_player_id = d.get('target_player_id')  # the player whose name we're guessing
    guessed_username  = (d.get('guessed_username') or '').strip()
    # Find target player (must be opposite role, min 2 of their role)
    target_gp = GamePlayer.query.filter_by(game_id=game.id, user_id=target_player_id).first()
    if not target_gp: return jsonify(error='Speler niet gevonden'), 404
    if target_gp.role == me.role: return jsonify(error='Alleen tegenstanders raden'), 400
    # Check min 2 of that role
    role_count = GamePlayer.query.filter_by(game_id=game.id, role=target_gp.role).count()
    if role_count < 2: return jsonify(error='Minimaal 2 spelers van die rol vereist'), 400
    # Check not already revealed
    if target_gp.real_name_revealed:
        return jsonify(error='Naam al onthuld'), 400
    correct = target_gp.user.username.lower() == guessed_username.lower()
    pts = 3 if correct else -10
    me.points += pts
    current_user.total_points += pts
    if correct:
        target_gp.real_name_revealed = True
        hub.broadcast(code, 'name_revealed', {
            'guesser_codename': me.codename,
            'target_codename': target_gp.codename,
            'real_name': target_gp.user.username,
            'pts': pts,
        })
    log_activity('guess_name', f'{"correct" if correct else "wrong"}: {guessed_username}')
    db.session.commit()
    return jsonify(success=True, correct=correct, pts=pts,
                   real_name=target_gp.user.username if correct else None)


@app.route('/badges')
@login_required
def badges():
    """Show all badges â€” earned and locked."""
    earned = {b.badge_type: b for b in Badge.query.filter_by(user_id=current_user.id).all()}
    return render_template('badges.html', badge_defs=BADGE_DEFS, earned=earned,
                           user=current_user)

@app.route('/api/badges/check', methods=['POST'])
@login_required
def api_check_badges():
    """Check and award badges for current user. Called after game events."""
    new_badges = check_badges_after_game(current_user.id, None)
    result = [{'type': b, **BADGE_DEFS.get(b, {})} for b in new_badges]
    return jsonify(new_badges=result)

@app.route('/api/game/<code>/end_summary')
@login_required
def api_end_summary(code):
    """Get end-of-game summary with new badges for current user."""
    game = Game.query.filter_by(code=code).first_or_404()
    me   = GamePlayer.query.filter_by(game_id=game.id, user_id=current_user.id).first()
    if not me: return jsonify(error='Niet in spel'), 403
    end_result = get_game_end_result(game)
    no_points = bool(end_result.get('no_points'))
    new_badges = [] if no_points else check_badges_after_game(current_user.id, game.id)
    targets_used = Target.query.filter_by(game_id=game.id, hunter_id=current_user.id).count()
    targeted_count = Target.query.filter_by(game_id=game.id, runner_id=current_user.id).count()
    offline_used = max(0, int(game.offline_uses or 0) - int(me.offline_uses_left or 0))
    return jsonify(
        points=0 if no_points else round(me.points, 2),
        distance=round(me.distance),
        role=me.role,
        is_caught=me.is_caught,
        winner_role=end_result.get('winner_role'),
        end_reason=end_result.get('reason'),
        end_message=end_result.get('message'),
        no_points=no_points,
        offline_used=offline_used,
        targets_used=targets_used,
        targeted_count=targeted_count,
        new_badges=[{'type': b, **BADGE_DEFS.get(b, {})} for b in new_badges],
    )


@app.route('/api/game/<code>/leave', methods=['POST'])
@login_required
def api_leave_game(code):
    """Player leaves the game. If game becomes invalid (no hunters or no runners), stop it."""
    game = Game.query.filter_by(code=code).first_or_404()
    me   = GamePlayer.query.filter_by(game_id=game.id, user_id=current_user.id).first()
    if not me: return jsonify(error='Niet in spel'), 403
    if game.status == 'finished':
        return jsonify(success=True, redirect=url_for('dashboard'), status='finished')
    if game.status == 'lobby':
        # In lobby: just remove the player
        db.session.delete(me); db.session.commit()
        hub.broadcast(code, 'player_left', {'user_id': current_user.id, 'username': current_user.username})
        return jsonify(success=True, redirect=url_for('dashboard'))
    # During game: mark as left, check if game can continue
    me.is_caught = True  # treat as out
    db.session.commit()
    # Check remaining active players
    active_hunters = GamePlayer.query.filter_by(game_id=game.id, role='hunter', is_caught=False).count()
    active_runners = GamePlayer.query.filter_by(game_id=game.id, role='runner', is_caught=False).count()
    promoted = None
    if active_hunters == 0 and active_runners >= 2:
        promoted = (GamePlayer.query
                    .filter_by(game_id=game.id, role='runner', is_caught=False)
                    .order_by(GamePlayer.joined_at.asc())
                    .first())
        if promoted:
            old_codename = promoted.codename or promoted.user.username
            promoted.role = 'hunter'
            promoted.codename = assign_codename('hunter', game.id)
            promoted.is_offline = False
            promoted.offline_since = None
            promoted.is_paused = False
            promoted.paused_since = None
            promoted.pause_reason = None
            promoted.target_used_at = None
            promoted.target_uses_on = '{}'
            Target.query.filter_by(game_id=game.id, runner_id=promoted.user_id,
                                   is_active=True).update({'is_active': False})
            db.session.commit()
            active_hunters = GamePlayer.query.filter_by(game_id=game.id, role='hunter', is_caught=False).count()
            active_runners = GamePlayer.query.filter_by(game_id=game.id, role='runner', is_caught=False).count()
            hub.broadcast(code, 'runner_promoted', {
                'left_user_id': current_user.id,
                'left_username': current_user.username,
                'promoted_user_id': promoted.user_id,
                'promoted_username': promoted.user.username,
                'old_codename': old_codename,
                'new_codename': promoted.codename,
                'remaining_hunters': active_hunters,
                'remaining_runners': active_runners,
            })

    if active_hunters == 0 or active_runners == 0:
        # Game can no longer continue
        finish_game(game, 'player_left')
        end_result = get_game_end_result(game)
        return jsonify(
            success=True,
            game_ended=True,
            status='finished',
            redirect=url_for('dashboard'),
            end_reason=end_result.get('reason'),
            end_message=end_result.get('message'),
            winner_role=end_result.get('winner_role'),
            no_points=bool(end_result.get('no_points')),
        )
    else:
        hub.broadcast(code, 'player_left', {
            'user_id': current_user.id,
            'username': current_user.username,
            'promoted_user_id': promoted.user_id if promoted else None,
            'promoted_codename': promoted.codename if promoted else None,
            'remaining_hunters': active_hunters,
            'remaining_runners': active_runners,
        })
    return jsonify(success=True, redirect=url_for('dashboard'))

# â”€â”€ Reports â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@app.route('/report', methods=['GET', 'POST'])
@login_required
def report():
    if request.method == 'POST':
        rtype = request.form.get('type', 'bug')
        title = request.form.get('title', '').strip()
        desc  = request.form.get('description', '').strip()
        code  = request.form.get('game_code', '').strip().upper() or None
        if not title or not desc:
            flash('Titel en beschrijving zijn verplicht.', 'danger')
        else:
            r = Report(user_id=current_user.id, type=rtype, title=title,
                       description=desc, game_code=code)
            db.session.add(r)
            log_activity('report_submitted', f'{rtype}: {title}')
            db.session.commit()
            flash('Melding ingediend! Bedankt voor je feedback.', 'success')
            return redirect(url_for('dashboard'))
    return render_template('report.html')

@app.route('/admin/reports')
@login_required
@admin_required
def admin_reports():
    reports = Report.query.order_by(Report.created_at.desc()).all()
    return render_template('admin_reports.html', reports=reports)

@app.route('/admin/photos')
@login_required
@admin_required
def admin_photos():
    status = request.args.get('status', 'pending')
    q = Post.query.filter(db.or_(Post.image_filename.isnot(None),
                                  Post.audio_filename.isnot(None))).order_by(Post.created_at.desc())
    if status == 'pending':
        q = q.filter(Post.approved.is_(None))
    elif status == 'approved':
        q = q.filter(Post.approved.is_(True))
    elif status == 'rejected':
        q = q.filter(Post.approved.is_(False))
    photos = q.limit(300).all()
    return render_template('admin_photos.html', photos=photos, status=status)

@app.route('/admin/reports/<int:rid>/update', methods=['POST'])
@login_required
@admin_required
def admin_report_update(rid):
    r = Report.query.get_or_404(rid)
    d = request.get_json()
    if 'status' in d:  r.status     = d['status']
    if 'note' in d:    r.admin_note = d['note']
    if d.get('status') in ('resolved', 'closed'):
        r.resolved_at = datetime.utcnow()
    db.session.commit()
    return jsonify(success=True)

# â”€â”€ Activity log â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@app.route('/admin/log')
@login_required
@admin_required
def admin_log():
    page     = request.args.get('page', 1, type=int)
    flagged  = request.args.get('flagged', '')
    q        = ActivityLog.query.order_by(ActivityLog.created_at.desc())
    if flagged: q = q.filter_by(flag=True)
    logs     = q.limit(200).all()
    return render_template('admin_log.html', logs=logs, flagged=flagged)

@app.route('/admin/log/<int:lid>/flag', methods=['POST'])
@login_required
@admin_required
def admin_log_flag(lid):
    entry = ActivityLog.query.get_or_404(lid)
    entry.flag = not entry.flag
    db.session.commit()
    return jsonify(success=True, flag=entry.flag)

@app.route('/admin/user/<int:uid>/ban', methods=['POST'])
@login_required
@admin_required
def admin_ban_user(uid):
    user = User.query.get_or_404(uid)
    if user.is_owner: return jsonify(error='Owner kan niet gebanned worden'), 403
    d = request.get_json()
    pts_penalty = d.get('points_penalty', 0)
    if pts_penalty:
        user.total_points = max(0, user.total_points - pts_penalty)
    user.is_banned = True
    log_activity('user_banned', f'penalty:{pts_penalty}', user_id=uid, flag=True)
    db.session.commit()
    return jsonify(success=True)

@app.route('/admin/user/<int:uid>/unban', methods=['POST'])
@login_required
@admin_required
def admin_unban_user(uid):
    user = User.query.get_or_404(uid)
    user.is_banned = False
    log_activity('user_unbanned', '', user_id=uid, flag=True)
    db.session.commit()
    return jsonify(success=True)

# â”€â”€ Changelog â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@app.route('/changelog')
def changelog():
    entries = Changelog.query.filter_by(published=True).order_by(Changelog.created_at.desc()).all()
    return render_template('changelog.html', entries=entries)

@app.route('/admin/changelog', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_changelog():
    if request.method == 'POST':
        f = request.form
        entry = Changelog(
            version   = f.get('version', '').strip(),
            title     = f.get('title', '').strip(),
            body      = f.get('body', '').strip(),
            type      = f.get('type', 'update'),
            published = f.get('published') == 'on',
        )
        db.session.add(entry); db.session.commit()
        flash('Changelog entry toegevoegd!', 'success')
        return redirect(url_for('admin_changelog'))
    entries = Changelog.query.order_by(Changelog.created_at.desc()).all()
    return render_template('admin_changelog.html', entries=entries)

@app.route('/admin/changelog/<int:cid>/delete', methods=['POST'])
@login_required
@admin_required
def admin_changelog_delete(cid):
    db.session.delete(Changelog.query.get_or_404(cid))
    db.session.commit()
    return jsonify(success=True)

# Admin TODO overview
TODO_KEY = 'admin_todos_v1'

def default_admin_todos():
    rows = [
        (0, 'Test', 'GPS toestemming al in lobby controleren op mobiel', 'Live testen op iPhone/Android met nieuwe speler die toestemming weigert of wegklikt.'),
        (0, 'Test', 'Offline knop: runner kan niet zelf uitzetten', 'Live testen met runner + hunter en controleren dat beide countdowns goed lopen.'),
        (0, 'Test', 'Target countdown blijft zichtbaar en rustig', 'Runner ziet een vast rood targetscherm met live timer; hunters zien linksboven de targettimer zonder flikkeren.'),
        (0, 'Test', 'Automatisch spel stoppen of hunter wisselen bij Spel verlaten', 'Test: 1 runner/1 hunter, 2 runners/1 hunter, en verlaten via menu.'),
        (0, 'Test', 'Hunter ziet runners alleen per ingestelde interval', 'Live testen: bij 3 minuten mag runner-marker niet live meeschuiven. Alleen Live tracking mag live zijn.'),
        (0, 'Test', 'Eigen GPS blijft live zonder handmatige refresh', 'Dashboard gebruikt watchPosition plus fallback GPS-poll als mobiel even stopt met updates geven.'),
        (0, 'Test', 'Offline voorbij stuurt laatste locatie direct door', 'Als offline tijd afloopt moet hunter meteen een actuele runnerlocatie krijgen.'),
        (0, 'Test', 'Eindscherm bij tijd voorbij', 'Runners moeten groen gewonnen-scherm zien; hunters rood verloren-scherm. Na 10 minuten automatisch terug naar dashboard.'),
        (0, 'Test', 'Runner kaart zichtbaar tijdens voorsprong', 'Runner moet tijdens voorsprong de kaart en speelveldgrens kunnen zien.'),
        (0, 'Test', 'Verboden zone/speelveld waarschuwing', 'Buiten speelveld moet direct een waarschuwing geven en in admin log komen.'),
        (1, 'Open', 'Speelveld workflow herstellen/uitbreiden', 'Eerst buitenrand tekenen. Alles erbuiten is geen speelveld. Daarna verboden plekken toevoegen.'),
        (1, 'Test', 'Persoonlijk speelveld opslaan en laden', 'Maak een speelveld met eigen naam, sla op in profiel en laad het opnieuw via Mijn speelveld kiezen.'),
        (1, 'Open', 'Kruisende speelveldlijnen blokkeren', 'Nieuwe lijnen mogen bestaande lijnen niet kruisen.'),
        (1, 'Open', 'Verboden zones inkleuren met rondje', 'Maker kiest brush-grootte en klikt binnen speelveld om verboden locaties te tekenen.'),
        (1, 'Open', 'Speelveld hoeken visueel afronden', 'Polygon is nu puntig. Gewenst: afgeronde/smoother hoeken.'),
        (1, 'Open', 'Lootboxes vermijden op wegen en water', 'Vereist kaart/OSM-laag of externe geo-data.'),
        (2, 'Open', 'Tripwire op specifieke dropbox plaatsen', 'UX maken om dropbox te kiezen en tripwire zichtbaar/actief te maken.'),
        (2, 'Open', 'Laser detectie als duidelijke kaartactie', 'Plaatsing, detectiefeedback en teammelding afmaken/testen.'),
        (2, 'Open', 'Landmijn UX verbeteren', 'Duidelijke kaartknop, radius-feedback en ontmantelen in UI.'),
        (2, 'Open', 'Hacker onderschept chat/info als aparte actie', 'Keuzes zoals chat onderscheppen, locatiehint of cooldown-overzicht.'),
        (2, 'Open', 'Glitch effect zichtbaar maken op kaart', 'Spelers moeten zien wat glitch doet en wanneer het stopt.'),
        (2, 'Open', 'Echo als snelle kaartknop met cooldownstatus', 'Cooldown en uitleg prominenter op kaart.'),
        (2, 'Test', 'Lootbox openen op 10 meter', 'Claimafstand is 10 meter. Test op mobiel of te ver weg netjes fout geeft.'),
        (2, 'Test', 'Lootbox puntenbalans', 'Beloningen zijn verlaagd zodat dropboxes geen kilometers aan punten opleveren.'),
        (2, 'Test', 'Lootbox badges', 'Badges: Eerste Dropbox, Verzamelaar en Zeldzame Vondst.'),
        (2, 'Test', 'Powerknop status op kaart', 'Speciale powerknop is groen als hij klaar is en grijs met countdown tijdens cooldown.'),
        (2, 'Test', 'Tripwire alleen bij dropbox', 'Saboteur moet binnen 10 meter van een dropbox staan om tripwire te plaatsen.'),
        (2, 'Test', 'Zware powers langere cooldown', 'Hack, landmijn, laser, tripwire en glitch hebben langere minimum cooldown.'),
        (3, 'Later', 'Operation Dead Drop', 'Spionnen zoeken geheime documenten en extractiepunt. Hunters plaatsen lasers vooraf.'),
        (3, 'Later', 'Safe Zones', 'Veilige zones waar runners kort kunnen schuilen.'),
        (3, 'Later', 'Mystery Drops', 'Lootboxes met onbekend effect.'),
        (3, 'Later', 'Missiekaarten', 'Korte buitenopdrachten tijdens het spel.'),
        (3, 'Later', 'Ouder/Admin Live View', 'Aparte meekijkkaart zonder spelvoordeel.'),
    ]
    return [{
        'id': f'todo-{i+1}', 'prio': prio, 'status': status, 'title': title,
        'body': body, 'done': False, 'created_at': datetime.utcnow().strftime('%Y-%m-%d %H:%M')
    } for i, (prio, status, title, body) in enumerate(rows)]

def get_admin_todos():
    raw = SiteSetting.get(TODO_KEY, '')
    if raw:
        try:
            items = json.loads(raw)
            if isinstance(items, list):
                existing_titles = {i.get('title') for i in items}
                changed = False
                for item in default_admin_todos():
                    if item.get('title') not in existing_titles:
                        items.append(item)
                        changed = True
                if changed:
                    SiteSetting.set(TODO_KEY, json.dumps(items))
                    db.session.commit()
                return items
        except Exception:
            pass
    items = default_admin_todos()
    SiteSetting.set(TODO_KEY, json.dumps(items))
    db.session.commit()
    return items

def save_admin_todos(items):
    SiteSetting.set(TODO_KEY, json.dumps(items))
    db.session.commit()

@app.route('/admin/todo')
@login_required
@admin_required
def admin_todo():
    open_reports  = Report.query.filter_by(status='open').count()
    flagged_logs  = ActivityLog.query.filter_by(flag=True).count()
    pending_news  = NewsArticle.query.filter_by(status='pending').count()
    todos = sorted(get_admin_todos(), key=lambda x: (bool(x.get('done')), int(x.get('prio', 3)), x.get('created_at', '')))
    grouped_todos = {prio: [t for t in todos if int(t.get('prio', 3)) == prio] for prio in range(6)}
    p0_open_items = [t for t in grouped_todos[0] if not t.get('done')]
    p0_clipboard = '\n'.join(
        f"- {t.get('title', '')}: {t.get('body', '')}".rstrip(': ')
        for t in p0_open_items
    )
    return render_template('admin_todo.html', open_reports=open_reports,
                           flagged_logs=flagged_logs, pending_news=pending_news,
                           todos=todos, grouped_todos=grouped_todos,
                           p0_open=len(p0_open_items), p0_clipboard=p0_clipboard)

@app.route('/admin/todo/add', methods=['POST'])
@login_required
@admin_required
def admin_todo_add():
    items = get_admin_todos()
    title = request.form.get('title', '').strip()
    if not title:
        flash('TODO titel is verplicht.', 'danger')
        return redirect(url_for('admin_todo'))
    try:
        prio = max(0, min(5, int(request.form.get('prio', 3))))
    except ValueError:
        prio = 3
    items.append({
        'id': f'todo-{int(time.time() * 1000)}-{random.randint(100,999)}',
        'prio': prio,
        'status': request.form.get('status', 'Open'),
        'title': title,
        'body': request.form.get('body', '').strip(),
        'done': False,
        'created_at': datetime.utcnow().strftime('%Y-%m-%d %H:%M'),
    })
    save_admin_todos(items)
    flash('TODO toegevoegd.', 'success')
    return redirect(url_for('admin_todo'))

@app.route('/admin/todo/<todo_id>/update', methods=['POST'])
@login_required
@admin_required
def admin_todo_update(todo_id):
    items = get_admin_todos()
    for item in items:
        if item.get('id') == todo_id:
            if 'toggle_done' in request.form:
                item['done'] = not bool(item.get('done'))
            if 'prio' in request.form:
                item['prio'] = max(0, min(5, int(request.form.get('prio') or item.get('prio', 3))))
            if 'status' in request.form:
                item['status'] = request.form.get('status') or item.get('status', 'Open')
            if request.form.get('title', '').strip():
                item['title'] = request.form.get('title').strip()
            if 'body' in request.form:
                item['body'] = request.form.get('body', '').strip()
            break
    save_admin_todos(items)
    return redirect(url_for('admin_todo'))

@app.route('/admin/todo/<todo_id>/delete', methods=['POST'])
@login_required
@admin_required
def admin_todo_delete(todo_id):
    save_admin_todos([i for i in get_admin_todos() if i.get('id') != todo_id])
    return redirect(url_for('admin_todo'))

# â”€â”€ News â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@app.route('/news')
def news():
    if current_user.is_authenticated and current_user.is_admin:
        articles = NewsArticle.query.order_by(NewsArticle.created_at.desc()).all()
    else:
        articles = NewsArticle.query.filter_by(status='approved').order_by(
            NewsArticle.created_at.desc()).all()
    return render_template('news.html', articles=articles)

@app.route('/news/submit', methods=['GET', 'POST'])
@login_required
def news_submit():
    if request.method == 'POST':
        title   = request.form.get('title',   '').strip()
        content = request.form.get('content', '').strip()
        consent = request.form.get('photo_consent') == 'on'
        if not title or not content:
            flash('Titel en inhoud zijn verplicht.', 'danger')
            return redirect(url_for('news_submit'))
        filename = None
        if 'image' in request.files:
            f2 = request.files['image']
            if f2 and f2.filename and allowed_file(f2.filename):
                if not consent:
                    flash('Geef toestemming voor de afbeelding.', 'danger')
                    return redirect(url_for('news_submit'))
                filename = save_image(f2, app.config['UPLOAD_FOLDER'])
        article = NewsArticle(
            user_id=current_user.id, title=title, content=content,
            image_filename=filename, photo_consent=consent,
            status='approved' if current_user.is_admin else 'pending',
        )
        db.session.add(article); db.session.commit()
        hub.broadcast('__news__', 'new_article',
                      {'id': article.id, 'title': title, 'username': current_user.username})
        flash('Gepubliceerd!' if current_user.is_admin else 'Ingediend â€” wacht op goedkeuring.',
              'success' if current_user.is_admin else 'info')
        return redirect(url_for('news'))
    return render_template('news_submit.html')

@app.route('/news/<int:aid>/approve', methods=['POST'])
@login_required
@admin_required
def news_approve(aid):
    a = NewsArticle.query.get_or_404(aid)
    a.status = 'approved'; a.approved_by = current_user.id; a.approved_at = datetime.utcnow()
    db.session.commit()
    hub.broadcast('__news__', 'article_approved', {'id': a.id})
    return jsonify(success=True)

@app.route('/news/<int:aid>/reject', methods=['POST'])
@login_required
@admin_required
def news_reject(aid):
    a = NewsArticle.query.get_or_404(aid)
    a.status = 'rejected'; db.session.commit(); return jsonify(success=True)

@app.route('/news/<int:aid>/delete', methods=['POST'])
@login_required
def news_delete(aid):
    a = NewsArticle.query.get_or_404(aid)
    if a.user_id != current_user.id and not current_user.is_admin:
        return jsonify(error='Geen rechten'), 403
    if a.image_filename:
        try: os.remove(os.path.join(app.config['UPLOAD_FOLDER'], a.image_filename))
        except: pass
    db.session.delete(a); db.session.commit(); return jsonify(success=True)

@app.route('/news/<int:aid>/like', methods=['POST'])
@login_required
def news_like(aid):
    a  = NewsArticle.query.get_or_404(aid)
    ex = NewsLike.query.filter_by(article_id=aid, user_id=current_user.id).first()
    if ex:
        db.session.delete(ex); a.likes = max(0, a.likes - 1); liked = False
    else:
        db.session.add(NewsLike(article_id=aid, user_id=current_user.id))
        a.likes += 1; liked = True
    db.session.commit(); return jsonify(likes=a.likes, liked=liked)

# â”€â”€ Admin â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@app.route('/admin')
@login_required
@admin_required
def admin():
    users    = User.query.order_by(User.created_at.desc()).all()
    games    = Game.query.order_by(Game.created_at.desc()).all()
    settings = {s.key: s.value for s in SiteSetting.query.all()}
    catalog_games = GameCatalog.query.order_by(GameCatalog.sort_order, GameCatalog.name).all()
    return render_template('admin.html', users=users, games=games, settings=settings,
                           catalog_games=catalog_games)

@app.route('/admin/settings', methods=['POST'])
@login_required
@admin_required
def admin_settings():
    for key in ['site_name','site_accent','site_tagline','site_font',
                'site_font_body','site_bg_overlay','site_border_radius']:
        val = request.form.get(key,'').strip()
        if val: SiteSetting.set(key, val)
    if 'site_bg' in request.files:
        f2 = request.files['site_bg']
        if f2 and f2.filename and allowed_file(f2.filename):
            SiteSetting.set('site_bg', save_image(f2, app.config['BG_FOLDER'], (2560,1440)))
    elif request.form.get('clear_bg'): SiteSetting.set('site_bg','')
    if 'site_logo' in request.files:
        f2 = request.files['site_logo']
        if f2 and f2.filename and allowed_file(f2.filename):
            SiteSetting.set('site_logo', save_image(f2, app.config['BG_FOLDER'], (400,200)))
    elif request.form.get('clear_logo'): SiteSetting.set('site_logo','')
    for field, setting_key in [
        ('diff_easy_img', 'diff_easy_img'),
        ('diff_medium_img', 'diff_medium_img'),
        ('diff_hard_img', 'diff_hard_img'),
        ('diff_custom_img', 'diff_custom_img'),
    ]:
        if field in request.files:
            f2 = request.files[field]
            if f2 and f2.filename and allowed_file(f2.filename):
                SiteSetting.set(setting_key, save_image(f2, app.config['BG_FOLDER'], (900,600)))
        if request.form.get('clear_' + field):
            SiteSetting.set(setting_key, '')
    flash('Instellingen opgeslagen!','success')
    return redirect(url_for('admin'))

@app.route('/admin/catalog/<int:cid>/edit', methods=['POST'])
@login_required
@admin_required
def admin_catalog_edit(cid):
    catalog_game = GameCatalog.query.get_or_404(cid)
    catalog_game.name = request.form.get('name', '').strip() or catalog_game.name
    catalog_game.tagline = request.form.get('tagline', '').strip()
    catalog_game.description = request.form.get('description', '').strip()
    catalog_game.icon = request.form.get('icon', '').strip() or 'fa-gamepad'
    catalog_game.color = request.form.get('color', '').strip() or '#e11d48'
    try:
        catalog_game.sort_order = int(request.form.get('sort_order', catalog_game.sort_order) or 0)
    except ValueError:
        pass
    catalog_game.is_active = request.form.get('is_active') == 'on'
    catalog_game.coming_soon = request.form.get('coming_soon') == 'on'
    if request.form.get('clear_logo'):
        catalog_game.logo_file = ''
    if 'logo_file' in request.files:
        f2 = request.files['logo_file']
        if f2 and f2.filename and allowed_file(f2.filename):
            catalog_game.logo_file = save_image(f2, app.config['BG_FOLDER'], (1200, 800))
    db.session.commit()
    flash(f'Speltype "{catalog_game.name}" opgeslagen.', 'success')
    return redirect(url_for('admin') + '#catalog')

@app.route('/admin/user/<int:uid>/edit', methods=['POST'])
@login_required
@admin_required
def admin_edit_user(uid):
    user = User.query.get_or_404(uid)
    if user.is_owner and not current_user.is_owner:
        return jsonify(error='Owner kan niet aangepast worden'), 403
    d = request.get_json()
    if 'username' in d and d['username'].strip(): user.username = d['username'].strip()
    if 'email'    in d: user.email    = d['email'].strip() or None
    if 'is_admin' in d and not user.is_owner: user.is_admin = bool(d['is_admin'])
    if 'password' in d and d['password']: user.set_password(d['password'])
    for field in ('total_points','hunter_wins','runner_wins','total_games','runners_caught'):
        if field in d: setattr(user, field, float(d[field]) if field=='total_points' else int(d[field]))
    db.session.commit(); return jsonify(success=True)

@app.route('/admin/user/<int:uid>/delete', methods=['POST'])
@login_required
@admin_required
def admin_delete_user(uid):
    user = User.query.get_or_404(uid)
    if user.is_owner: return jsonify(error='Owner kan niet verwijderd worden'), 403
    if uid == current_user.id: return jsonify(error='Kan jezelf niet verwijderen'), 400
    db.session.delete(user); db.session.commit(); return jsonify(success=True)

@app.route('/admin/game/<int:gid>/delete', methods=['POST'])
@login_required
@admin_required
def admin_delete_game(gid):
    game = Game.query.get_or_404(gid)
    # Explicit cascade: delete children before game
    GamePlayer.query.filter_by(game_id=gid).delete()
    Target.query.filter_by(game_id=gid).delete()
    Post.query.filter_by(game_id=gid).delete()
    ChatMessage.query.filter_by(game_id=gid).delete()
    db.session.delete(game)
    db.session.commit()
    return jsonify(success=True)

@app.route('/admin/cleanup', methods=['POST'])
@login_required
@admin_required
def admin_cleanup():
    cutoff = datetime.utcnow() - timedelta(hours=24)
    paused_cutoff = datetime.utcnow() - timedelta(days=14)
    old = Game.query.filter(
        db.or_(
            db.and_(Game.status.in_(['finished','lobby']), Game.created_at < cutoff),
            db.and_(Game.status == 'paused', Game.created_at < paused_cutoff),
        )
    ).all()
    n = len(old)
    for g in old: db.session.delete(g)
    db.session.commit(); return jsonify(success=True, deleted=n)

# â”€â”€ Static files â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@app.route('/uploads/<fn>')
def uploaded_file(fn): return send_from_directory(app.config['UPLOAD_FOLDER'], fn)
@app.route('/audio/<fn>')
def audio_file(fn): return send_from_directory(AUDIO_FOLDER, fn)
@app.route('/backgrounds/<fn>')
def bg_file(fn): return send_from_directory(app.config['BG_FOLDER'], fn)
@app.route('/handleiding')
def handleiding():
    return render_template('handleiding.html')
@app.route('/gps_test')
@login_required
def gps_test(): return render_template('gps_test.html')
@app.route('/gps_help')
def gps_help(): return render_template('gps_help.html')

# â”€â”€ Init â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def ensure_column(table, column, coltype):
    """Lightweight SQLite auto-migration: add a column if it's missing.
    There's no Alembic in this project, so db.create_all() alone won't pick up
    new columns on tables that already exist - this keeps existing deployments
    in sync when a model gains a field."""
    try:
        existing = {row[1] for row in db.session.execute(sql_text(f'PRAGMA table_info({table})'))}
        if column not in existing:
            db.session.execute(sql_text(f'ALTER TABLE {table} ADD COLUMN {column} {coltype}'))
            db.session.commit()
    except Exception:
        db.session.rollback()
        app.logger.exception(f"ensure_column failed for {table}.{column}")

def init_db():
    with app.app_context():
        db.create_all()
        ensure_column('post', 'audio_filename', 'VARCHAR(256)')
        ensure_column('user', 'requires_email_verification', 'BOOLEAN DEFAULT 0')
        ensure_column('user', 'is_banned', 'BOOLEAN DEFAULT 0')
        os.makedirs(AUDIO_FOLDER, exist_ok=True)
        if not SiteSetting.get('site_logo'):
            SiteSetting.set('site_logo', 'logo_default.png')
        if not SiteSetting.get('site_bg'):
            SiteSetting.set('site_bg', 'bg_default.png')
        if not SiteSetting.get('site_bg_overlay'):
            SiteSetting.set('site_bg_overlay', '0.75')
        # Seed initial changelog if empty
        if Changelog.query.count() == 0:
            entries = [
                Changelog(version='1.0.0', title='Eerste release', type='feature',
                          body='â€¢ VenTrax platform gelanceerd\nâ€¢ VenTrax: GPS-gebaseerd jachtspel\nâ€¢ Hunter vs Runner gameplay\nâ€¢ Real-time satellietkaart\nâ€¢ Foto feed tijdens spel'),
                Changelog(version='1.1.0', title='Lobby & WebSocket fix', type='fix',
                          body='â€¢ WebSocket crash opgelost (flask-sock â†’ gevent-websocket)\nâ€¢ Nieuwe spelers verschijnen nu direct in lobby\nâ€¢ GPS toestemming vÃ³Ã³r start'),
                Changelog(version='1.2.0', title='Spel UI verbeterd', type='update',
                          body='â€¢ Fullscreen kaart op mobiel\nâ€¢ Schuilnamen (codenames) per speler\nâ€¢ 5-seconden countdown bij start\nâ€¢ Noodknop toegevoegd\nâ€¢ QR code voor lobby'),
                Changelog(version='1.3.0', title='Game dashboard fixes', type='fix',
                          body='â€¢ Navigatiebalk verwijderd tijdens spel\nâ€¢ Camera knoppen werken nu correct\nâ€¢ Hunter acties via klik op runner (target/pakken)\nâ€¢ Chat werkt en toont berichten\nâ€¢ Runner gepakt â†’ iedereen ziet melding\nâ€¢ Panel toggle (nogmaals klikken = sluiten)'),
                Changelog(version='1.4.0', title='Reports, Changelog & Anti-cheat', type='feature',
                          body='â€¢ Meldingssysteem voor bugs, tips en valsspelen\nâ€¢ Activiteitenlog voor admins\nâ€¢ Changelog pagina\nâ€¢ Snelheidspenalty verbeterd\nâ€¢ Disclaimer veilig spelen\nâ€¢ Admin TODO overzicht'),
                Changelog(version='1.5.0', title='VenTrax platform en spelcatalogus', type='feature',
                          body='â€¢ VenTrax is nu het platform voor meerdere speltypes\nâ€¢ Classic is het eerste GPS jachtspel\nâ€¢ Nieuwe platform homepage met spel-keuze\nâ€¢ Leaderboard prominent bovenaan homepage'),
            ]
            for e in entries:
                db.session.add(e)
            db.session.commit()
        if not Changelog.query.filter_by(version='1.6.0').first():
            db.session.add(Changelog(version='1.6.0', title='Codex herstelronde VenTrax', type='fix',
                          body='â€¢ Nieuw spel rolselectie en difficulty presets hersteld\nâ€¢ QR-code gebruikt logo_round.png\nâ€¢ Foto-upload foutmeldingen verbeterd\nâ€¢ Target, catch en naam raden robuuster\nâ€¢ Offline countdowns, chat badges en snelheid waarschuwing verbeterd\nâ€¢ Eindmail met fotoâ€™s, chat en standen toegevoegd\nâ€¢ Dashboard badges toegevoegd'))
            db.session.commit()
        if not Changelog.query.filter_by(version='1.6.1').first():
            db.session.add(Changelog(version='1.6.1', title='Dashboard hotfix en Binnenkort', type='fix',
                          body='â€¢ Dashboard 500 error opgelost\nâ€¢ Binnenkort-sectie toegevoegd voor spelers\nâ€¢ Nieuwe spelideeÃ«n toegevoegd: De Avonturier, Escape City en Player vs Player\nâ€¢ Extraâ€™s en speelveld zichtbaar gemaakt als toekomstige VenTrax uitbreiding'))
            db.session.commit()
        if not Changelog.query.filter_by(version='1.6.2').first():
            db.session.add(Changelog(version='1.6.2', title='Speelveld instellen Prio 1', type='feature',
                          body='- Spelmaker kan bij Nieuw Spel een speelveld tekenen op de kaart\n- Speelveld sluit automatisch vanaf 3 punten\n- Buitengebied-kleur toegevoegd: Radiation, Storm, Nuclear en Heat\n- Speelveld wordt per game opgeslagen en in het spel getoond\n- Kaart wordt begrensd tot speelveld plus buffer\n- Extra speelelementen verplaatst naar Prio 2'))
            db.session.commit()
        if not Changelog.query.filter_by(version='1.6.3').first():
            db.session.add(Changelog(version='1.6.3', title='Admin knop desktop hotfix', type='fix',
                          body='- Admin knop in de desktop navigatie is weer een directe link naar het Admin Panel\n- Admin dropdown blijft beschikbaar voor Admin TODO, activiteitenlog, meldingen en changelog beheer'))
            db.session.commit()
        if not Changelog.query.filter_by(version='1.6.4').first():
            db.session.add(Changelog(version='1.6.4', title='Spel verlaten en nieuwe hunter', type='fix',
                          body='- Spel Verlaten stopt het spel als er geen hunter of runner meer overblijft\n- Als de enige hunter vertrekt en er minimaal 2 runners zijn, wordt automatisch een runner gekozen als nieuwe hunter\n- Spelers krijgen hiervan direct een melding in beeld'))
            db.session.commit()
        if not Changelog.query.filter_by(version='1.6.5').first():
            db.session.add(Changelog(version='1.6.5', title='Speelveld bewaren in profiel', type='fix',
                          body='- Speelveld wordt automatisch opgeslagen bij het profiel van de spelmaker\n- Nieuw Spel laadt het laatst opgeslagen speelveld automatisch opnieuw\n- Eerder gemaakte speelvelden worden als fallback uit recente spellen teruggehaald'))
            db.session.commit()
        if not Changelog.query.filter_by(version='1.6.6').first():
            db.session.add(Changelog(version='1.6.6', title='Extra instellingen en Hunter difficulty', type='update',
                          body='- Moeilijkheidsgraad aangepast vanuit Hunter-oogpunt\n- Custom start nu op x1.25\n- Extra opties zoals dropboxes, landmijn, laser, tripwire, hacker, glitch en echo zijn aanvinkbaar bij Nieuw Spel\n- Lobby toont uitleg over gekozen extra opties\n- Buiten het speelveld is de gekleurde wolkenlaag ondoorzichtiger\n- Prio-labels en dubbele speelveldkleur verwijderd uit Nieuw Spel'))
            db.session.commit()
        if not Changelog.query.filter_by(version='2.0.0').first():
            db.session.add(Changelog(version='2.0.0', title='VenTrax v2.0 gameplay powers', type='feature',
                          body='- Class powers met cooldown toegevoegd\n- Dropboxes kunnen geopend worden en geven punten/effecten\n- Landmijnen, laser detectie en tripwires werken als GPS-triggers\n- Bomexpert kan landmijnen ontmantelen\n- Hacker, Echo en Glitch werken als echte powers\n- Spelstijl presets zoals Classic, Adventure, Battlefield en Shadow Ops toegevoegd'))
            db.session.commit()
        if not Changelog.query.filter_by(version='2.3.0').first():
            db.session.add(Changelog(version='2.3.0', title='VenTrax naam en veilige 2.2.6/2.2.7 herintroductie', type='fix',
                          body='- Projectmap en documentatie hernoemd naar VenTrax\n- 2.2.6 admin TODO en spelencatalogus veilig meegenomen\n- 2.2.7 badge/timer/tip fixes veilig meegenomen zonder countdown-engine te vervangen\n- Countdown en tips blijven op de stabiele 2.2.2 basis\n- Databasebestandsnaam blijft venfaye.db voor compatibiliteit'))
            db.session.commit()
        if not Changelog.query.filter_by(version='2.3.1').first():
            db.session.add(Changelog(version='2.3.1', title='Speelveld marge, target overlay en laatste speler', type='fix',
                          body='- Runners zien tijdens voorsprong de kaart met compacte teller\n- Buiten speelveld heeft nu 5 meter GPS-marge en een levensbalk\n- Te lang buiten het speelveld betekent af en kan het spel stoppen\n- Target overlay voor runners is fullscreen vastgezet\n- Hunters zien target countdown\n- Laatste actieve speler wint alleen als minimaal 75% van de speeltijd voorbij is'))
            db.session.commit()
        if not Changelog.query.filter_by(version='2.3.2').first():
            db.session.add(Changelog(version='2.3.2', title='Missieverslag, fotos en chatkanalen', type='update',
                          body='- Eindscherm toont status zoals resultaat, afstand, offline en targetgebruik\n- Missieverslag per mail bevat nu spelstatus per speler\n- Fotos worden inline en als bijlage meegestuurd waar mogelijk\n- Chat is gescheiden per Team, Globaal en Proxy\n- Teamchat toont echte naam; Globaal en Proxy tonen schuilnaam'))
            db.session.commit()
        if not Changelog.query.filter_by(version='2.3.3').first():
            db.session.add(Changelog(version='2.3.3', title='P0 lobby, GPS, countdown en chat hotfix', type='fix',
                          body='- Oude open spellen worden opgeschoond of afgesloten voordat je join/new game gebruikt\n- Bestaand geldig spel stuurt direct door naar lobby of game\n- GPS weigeren in lobby haalt speler uit het spel\n- Start vereist echte GPS-fix uit de lobby\n- QR scanner opent camera via join?scan=1\n- Powers zijn geblokkeerd tot na de voorsprong\n- Countdown ruimt zichzelf op en forceert refresh naar actieve game\n- Offline teller staat onder de offlineknop\n- Chat-rendering robuuster gemaakt\n- Mail toont foto via publieke upload-link plus bijlage waar mogelijk'))
            db.session.commit()
        # Seed game catalog if empty
        if GameCatalog.query.count() == 0:
            catalog = [
                GameCatalog(slug='ventrax', name='VenTrax', sort_order=1,
                            icon='fa-crosshairs', color='#e11d48',
                            logo_file='logo_round.png',
                            tagline='Het ultieme GPS jachtspel',
                            description='Hunter vs Runner â€” verstop je, word gezocht, pak ze of ontsnapt. Real-time GPS-tracking op een satellietkaart.',
                            is_active=True, coming_soon=False),
                GameCatalog(slug='venzoek', name='VenZoek', sort_order=2,
                            icon='fa-magnifying-glass', color='#7c3aed',
                            tagline='Zoek de locatie',
                            description='Herken je een plek aan een foto? Vind de exacte GPS-locatie en verdien punten. Binnenkort beschikbaar.',
                            is_active=False, coming_soon=True),
                GameCatalog(slug='venrace', name='VenRace', sort_order=3,
                            icon='fa-flag-checkered', color='#2563eb',
                            tagline='GPS Checkpoint Race',
                            description='Bereik checkpoints zo snel mogelijk. Binnenkort beschikbaar.',
                            is_active=False, coming_soon=True),
            ]
            for g in catalog:
                db.session.add(g)
            db.session.commit()
        classic_base = GameCatalog.query.filter_by(slug='ventrax').first()
        if classic_base:
            classic_base.name = 'Classic'
            classic_base.sort_order = 0
            classic_base.icon = classic_base.icon or 'fa-person-running'
            classic_base.tagline = 'De basis: vluchten, jagen en offline gaan'
            classic_base.description = 'De klassieke VenTrax-modus: runners proberen uit handen van de hunters te blijven. Simpel, snel te starten en ideaal voor het eerste spel.'
            classic_base.is_active = True
            classic_base.coming_soon = False
        extra_catalog = [
            dict(slug='operation-dead-drop', name='Operation Dead Drop', sort_order=2,
                 icon='fa-user-secret', color='#0f766e',
                 tagline='Spionnen, geheime documenten en extractie',
                 description='Runners zoeken geheime documenten en een extractiepunt. Hunters krijgen vooraf tijd om lasers te plaatsen en proberen de missie te onderscheppen.',
                 is_active=False, coming_soon=True),
            dict(slug='de-avonturier', name='De Avonturier', sort_order=4,
                 icon='fa-compass', color='#10b981', tagline='Ontdek wat dichtbij is',
                 description='Krijg informatie over bezienswaardigheden, winkels, musea, kerken, kastelen en natuur in de buurt van je GPS-locatie.',
                 is_active=False, coming_soon=True),
            dict(slug='escape-city', name='Escape City', sort_order=5,
                 icon='fa-key', color='#f59e0b', tagline='Vind de foto-locatie',
                 description='Gebruik veilige spelersfotoâ€™s en cryptische hints om echte locaties terug te vinden.',
                 is_active=False, coming_soon=True),
            dict(slug='player-vs-player', name='Player vs Player', sort_order=6,
                 icon='fa-bolt', color='#3b82f6', tagline='GPS strijd met power-ups',
                 description='Een avontuurlijk GPS-spel met dropboxes, acties en slimme power-ups.',
                 is_active=False, coming_soon=True),
        ]
        for item in extra_catalog:
            if not GameCatalog.query.filter_by(slug=item['slug']).first():
                db.session.add(GameCatalog(**item))
        db.session.commit()

if __name__ == '__main__':
    init_db()
    from gevent import pywsgi
    port = int(os.environ.get('PORT', 5000))
    print(f'\nVenTrax -> http://0.0.0.0:{port}\n')
    server = pywsgi.WSGIServer(('0.0.0.0', port), app,
                               handler_class=WebSocketHandler)
    server.serve_forever()

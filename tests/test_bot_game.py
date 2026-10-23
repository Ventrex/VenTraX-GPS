"""Bots in a game: lobby controls, accounts, and the running simulation (no network, accelerated clock)."""
import time
from datetime import datetime, timedelta

import gevent

import bots as botlib
from conftest import make_user

LAT, LON = 52.1000, 5.3800


def setup_lobby(appmodule, client):
    uid = make_user(appmodule, username="maker", email="maker@example.com")
    with appmodule.app.app_context():
        g = appmodule.Game(name="Bottest", code="BOT123", creator_id=uid, status="lobby",
                           headstart_minutes=5, duration_minutes=45, difficulty="hard")
        appmodule.db.session.add(g); appmodule.db.session.commit()
        appmodule.db.session.add(appmodule.GamePlayer(game_id=g.id, user_id=uid, role="hunter", codename="Wolf",
                                                      gps_enabled=True, last_lat=LAT, last_lon=LON, is_ready=True))
        appmodule.db.session.commit()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(uid); sess["_fresh"] = True
    return uid


def test_creator_adds_and_removes_bots(appmodule, client):
    setup_lobby(appmodule, client)
    r = client.post("/api/game/BOT123/bots", json={"role": "runner", "count": 2})
    assert r.status_code == 200 and r.get_json()["added"] == 2
    with appmodule.app.app_context():
        game = appmodule.Game.query.filter_by(code="BOT123").first()
        bots_ = appmodule.bot_players(game)
        assert len(bots_) == 2 and all(b.is_ready and b.gps_enabled and b.camera_enabled and b.role == "runner" for b in bots_)
        assert all(b.user.is_bot and b.user.email is None for b in bots_)
        uid = bots_[0].user_id
    state = client.get("/api/game/BOT123/lobby_state").get_json()
    assert sum(1 for p in state["players"] if p["is_bot"]) == 2
    assert client.post("/api/game/BOT123/bots/remove", json={"user_id": uid}).get_json()["success"]
    assert client.post("/api/game/BOT123/bots/remove", json={"user_id": 99999}).status_code == 404


def test_bot_rules_limits_and_permissions(appmodule, client):
    setup_lobby(appmodule, client)
    assert client.post("/api/game/BOT123/bots", json={"role": "wizard"}).status_code == 400
    for _ in range(appmodule.MAX_BOTS // 3):
        assert client.post("/api/game/BOT123/bots", json={"role": "runner", "count": 3}).status_code == 200
    assert client.post("/api/game/BOT123/bots", json={"role": "runner", "count": 3}).status_code == 400   # over the cap
    # other users cannot add bots
    other = make_user(appmodule, username="gast", email="gast@example.com")
    c2 = appmodule.app.test_client()
    with c2.session_transaction() as sess:
        sess["_user_id"] = str(other); sess["_fresh"] = True
    assert c2.post("/api/game/BOT123/bots", json={"role": "runner"}).status_code == 403


def test_bots_need_the_makers_gps_first(appmodule, client):
    setup_lobby(appmodule, client)
    with appmodule.app.app_context():
        gp = appmodule.GamePlayer.query.filter_by(codename="Wolf").first()
        gp.last_lat = None; gp.last_lon = None; appmodule.db.session.commit()
    r = client.post("/api/game/BOT123/bots", json={"role": "runner"})
    assert r.status_code == 400 and "GPS" in r.get_json()["error"]


def test_bots_cannot_log_in_and_stay_off_the_leaderboard(appmodule, client):
    setup_lobby(appmodule, client)
    client.post("/api/game/BOT123/bots", json={"role": "runner"})
    with appmodule.app.app_context():
        u = appmodule.User.query.filter_by(is_bot=True).first()
        u.hunter_wins = 99; u.total_points = 999; appmodule.db.session.commit()
        name = u.username
    anon = appmodule.app.test_client()
    assert "Bot" not in anon.get("/").get_data(as_text=True).split("Leaderboard")[1].split("Kies je spel")[0]
    r = anon.post("/login", data={"username": name, "password": "x"})
    assert r.status_code == 200 and "onjuist" in r.get_data(as_text=True)


def run_loop(appmodule, monkeypatch, seconds, difficulty="hard", runner_role="runner"):
    monkeypatch.setattr(appmodule, "BOT_TICK", 0.02)
    monkeypatch.setattr(appmodule, "BOT_TIME_SCALE", 100)          # 1 tick = 2 simulated seconds
    monkeypatch.setattr(botlib, "load_terrain", lambda bbox, url, pf=None, cache=None, http_post=None: botlib.open_terrain(bbox, pf))
    g = gevent.spawn(appmodule._bot_loop, "BOT123")
    gevent.sleep(seconds)
    return g


def test_runner_bot_runs_away_and_never_leaves_the_play_field(appmodule, client, monkeypatch):
    setup_lobby(appmodule, client)
    client.post("/api/game/BOT123/bots", json={"role": "runner"})
    with appmodule.app.app_context():
        game = appmodule.Game.query.filter_by(code="BOT123").first()
        pf = [(LAT - 0.002, LON - 0.003), (LAT - 0.002, LON + 0.003), (LAT + 0.002, LON + 0.003), (LAT + 0.002, LON - 0.003)]
        appmodule.SiteSetting.set(appmodule._playfield_key(game.id), appmodule.json.dumps(
            {"enabled": True, "color": "storm", "points": [{"lat": a, "lng": b} for a, b in pf]}))
        game.status = "active"; game.started_at = datetime.utcnow() - timedelta(minutes=10)   # head start is over
        appmodule.db.session.commit()
    g = run_loop(appmodule, monkeypatch, 2.5)
    with appmodule.app.app_context():
        game = appmodule.Game.query.filter_by(code="BOT123").first()
        bot = appmodule.bot_players(game)[0]
        assert bot.distance > 50, "the bot actually moved"
        assert LAT - 0.0021 <= bot.last_lat <= LAT + 0.0021 and LON - 0.0031 <= bot.last_lon <= LON + 0.0031
        assert (datetime.utcnow() - bot.last_seen).total_seconds() < 2        # stays "seen", so it is not swept as stale
        game.status = "finished"; appmodule.db.session.commit()
    gevent.sleep(0.3)
    assert g.dead or g.ready()


def test_hunter_bot_tags_a_runner_with_the_normal_rules_and_ends_the_game(appmodule, client, monkeypatch):
    uid = setup_lobby(appmodule, client)
    with appmodule.app.app_context():
        gp = appmodule.GamePlayer.query.filter_by(user_id=uid).first()
        gp.role = "runner"; gp.codename = "Vos"; gp.last_lat, gp.last_lon = LAT, LON
        appmodule.db.session.commit()
    client.post("/api/game/BOT123/bots", json={"role": "hunter"})
    with appmodule.app.app_context():
        game = appmodule.Game.query.filter_by(code="BOT123").first()
        game.status = "active"
        game.started_at = datetime.utcnow() - timedelta(minutes=5.5)           # head start over, but < 50% played
        appmodule.db.session.commit()
    run_loop(appmodule, monkeypatch, 3.0)
    with appmodule.app.app_context():
        runner = appmodule.GamePlayer.query.filter_by(user_id=uid).first()
        assert not runner.is_caught, "no tagging before 50% of the game time, same as for humans"
        game = appmodule.Game.query.filter_by(code="BOT123").first()
        hunter = appmodule.bot_players(game)[0]
        assert botlib.haversine(hunter.last_lat, hunter.last_lon, runner.last_lat, runner.last_lon) < 40, "but it closed in"
        game.started_at = datetime.utcnow() - timedelta(minutes=30)             # now past 50%
        appmodule.db.session.commit()
    gevent.sleep(3.0)
    with appmodule.app.app_context():
        runner = appmodule.GamePlayer.query.filter_by(user_id=uid).first()
        assert runner.is_caught
        assert appmodule.Game.query.filter_by(code="BOT123").first().status == "finished"


def test_hunter_bots_wait_for_the_head_start(appmodule, client, monkeypatch):
    uid = setup_lobby(appmodule, client)
    with appmodule.app.app_context():
        appmodule.GamePlayer.query.filter_by(user_id=uid).first().role = "runner"
        appmodule.db.session.commit()
    client.post("/api/game/BOT123/bots", json={"role": "hunter"})
    with appmodule.app.app_context():
        game = appmodule.Game.query.filter_by(code="BOT123").first()
        game.status = "active"; game.started_at = datetime.utcnow() - timedelta(minutes=1)    # head start is 5 min
        appmodule.db.session.commit()
    run_loop(appmodule, monkeypatch, 1.0)
    with appmodule.app.app_context():
        hunter = appmodule.bot_players(appmodule.Game.query.filter_by(code="BOT123").first())[0]
        assert hunter.distance == 0
        game = appmodule.Game.query.filter_by(code="BOT123").first()
        game.status = "finished"; appmodule.db.session.commit()
    gevent.sleep(0.3)


def test_lobby_shows_bots_panel_to_the_maker_only(appmodule, client):
    setup_lobby(appmodule, client)
    client.post("/api/game/BOT123/bots", json={"role": "hunter"})
    html = client.get("/lobby/BOT123").get_data(as_text=True)
    assert "addBots()" in html and "removeBot(" in html and "Bot Kees" in html and "fa-robot" in html

"""Regression tests for the 'game ends the moment it starts' bug and the hunter-near sound rules."""
import json
import os
import shutil
import subprocess
from datetime import datetime, timedelta

import pytest

from conftest import make_user


def make_active_game(appmodule, minutes_since_start, last_seen_minutes_ago):
    a = make_user(appmodule, username="jager", email="jager@example.com")
    b = make_user(appmodule, username="vos", email="vos@example.com")
    with appmodule.app.app_context():
        g = appmodule.Game(name="T", code="SWEEP1", creator_id=a, status="active",
                           started_at=datetime.utcnow() - timedelta(minutes=minutes_since_start),
                           headstart_minutes=5, duration_minutes=45)
        appmodule.db.session.add(g); appmodule.db.session.commit()
        for uid, role in ((a, "hunter"), (b, "runner")):
            appmodule.db.session.add(appmodule.GamePlayer(
                game_id=g.id, user_id=uid, role=role, gps_enabled=True, last_lat=52.1, last_lon=5.38,
                last_seen=datetime.utcnow() - timedelta(minutes=last_seen_minutes_ago)))
        appmodule.db.session.commit()
        return g.id


def test_players_who_waited_in_the_lobby_are_not_swept_the_moment_the_game_starts(appmodule):
    # phones lock their screen in the lobby: their last "seen" is far older than the sweep limit
    gid = make_active_game(appmodule, minutes_since_start=0.1, last_seen_minutes_ago=30)
    with appmodule.app.app_context():
        game = appmodule.db.session.get(appmodule.Game, gid)
        assert appmodule.sweep_stale_players(game, broadcast=False) == []
        assert appmodule.ensure_game_finished_if_needed(game) is False
        assert game.status == "active"


def test_players_who_really_disappear_are_still_swept_later(appmodule):
    gid = make_active_game(appmodule, minutes_since_start=30, last_seen_minutes_ago=30)
    with appmodule.app.app_context():
        game = appmodule.db.session.get(appmodule.Game, gid)
        assert len(appmodule.sweep_stale_players(game, broadcast=False)) == 2


def test_start_refreshes_last_seen(appmodule):
    src = open(os.path.join(os.path.dirname(appmodule.__file__), "app.py"), encoding="utf-8-sig").read()
    start = src[src.index("def _do_start():"):src.index("gevent.spawn(_do_start)")]
    assert "last_seen" in start


# ---- hunter-near sound: once per approach, re-armed only after a minute outside ---------------
NODE = shutil.which("node")
HARNESS = r"""
global.window = global; global.document = {addEventListener(){}, removeEventListener(){}, dispatchEvent(){}, visibilityState:'visible'};
global.CustomEvent = function(n, o){ this.type = n; this.detail = o && o.detail; };
global.localStorage = {getItem(){return null}, setItem(){}};
let t = 0; Date.now = () => t;
require(process.argv[2]);
const played = [];
const V = window.VXSound;
V.__test_hook(ev => played.push(ev));
V.init({theme: {id:1, skin:'classic', synth:true, volume:80, near_m:100, close_m:30, ambient_min:45, ambient_max:150, events:{}}});
const step = (sec, d) => { t += sec * 1000; V.nearby(d); };
const out = {};
step(0, 300);  step(10, 90);  out.first = played.length;                    // enters 100 m -> plays once
step(10, 80);  step(10, 95);  out.stillInside = played.length;              // keeps walking inside -> silent
step(10, 150); step(30, 90);  out.backAfter30s = played.length;             // left, back within a minute -> silent
step(10, 150); step(70, 150); step(5, 90); out.backAfter70s = played.length;// really left for >1 min -> plays again
step(10, 200); step(300, 200); step(5, 60); out.after5min = played.length;
step(5, 20);  out.close = played.length;                                    // 30 m -> the "close" sound once
step(5, 15);  out.closeAgain = played.length;
out.events = played;
console.log(JSON.stringify(out));
"""


@pytest.mark.skipif(not NODE, reason="node not installed")
def test_hunter_near_sound_plays_once_and_rearms_after_a_minute_outside(tmp_path):
    h = tmp_path / "harness.js"; h.write_text(HARNESS)
    js = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "js", "vxsound.js")
    res = subprocess.run([NODE, str(h), js], capture_output=True, text=True, timeout=20)
    assert res.returncode == 0, res.stderr
    out = json.loads(res.stdout.strip().splitlines()[-1])
    assert out["first"] == 1
    assert out["stillInside"] == 1
    assert out["backAfter30s"] == 1
    assert out["backAfter70s"] == 2
    assert out["after5min"] == 3
    assert out["close"] == 4 and out["closeAgain"] == 4
    assert out["events"][0] == "hunter_near" and out["events"][3] == "hunter_close"


# ---- fair points ----------------------------------------------------------------------------
def test_fair_points_follow_who_has_it_easier(appmodule):
    cm = appmodule.compute_multipliers
    assert cm("easy") == (1.0, 1.5)       # easy for hunters: hunters earn less, runners (harder) earn more
    assert cm("medium") == (1.25, 1.25)
    assert cm("hard") == (1.5, 1.0)
    base = cm("custom", target_enabled=False, offline_button=False)
    assert base == (1.25, 1.25)
    h, r = cm("custom", target_enabled=True, offline_button=False)            # target helps the hunters
    assert h < 1.25 < r
    h, r = cm("custom", target_enabled=False, offline_button=True)            # offline button helps the runners
    assert h > 1.25 > r
    h, r = cm("custom", target_enabled=False, offline_button=False, hunter_interval_sec=1200)   # hunters see little
    assert h > 1.25 > r and round(h - 1.25, 2) == round(1.25 - r, 2)
    h, r = cm("custom", target_enabled=True, offline_button=True, live_tracking=True, show_distance=True,
              pause_allowed=True, hunter_interval_sec=1800)
    assert 0.7 <= h <= 2.0 and 0.7 <= r <= 2.0


def test_game_pays_each_role_its_own_multiplier(appmodule):
    with appmodule.app.app_context():
        g = appmodule.Game(name="x", code="MULT01", creator_id=1, hunter_multiplier=1.0, runner_multiplier=1.5)
        assert g.multiplier_for("hunter") == 1.0 and g.multiplier_for("runner") == 1.5
        old = appmodule.Game(name="old", code="MULT02", creator_id=1, points_multiplier=1.25)   # created before this update
        assert old.multiplier_for("hunter") == old.multiplier_for("runner") == 1.25


def _login(client, appmodule, name="maker2"):
    uid = make_user(appmodule, username=name, email=f"{name}@example.com")
    with client.session_transaction() as sess:
        sess["_user_id"] = str(uid); sess["_fresh"] = True
    return uid


def test_new_game_page_renders_with_admin_images_and_info_buttons(appmodule, client):
    _login(client, appmodule)
    html = client.get("/new_game").get_data(as_text=True)
    for must in ("wz-bar", "ibtn", "Geluid &amp; sfeer", "Class-thema", "multiH", "Krimp" if False else "Spelstijl"):
        assert must in html, must
    with appmodule.app.app_context():
        appmodule.SiteSetting.set("img_role_hunter", "does-not-exist.png")       # missing file -> icon, no broken image
    assert "does-not-exist" not in client.get("/new_game").get_data(as_text=True)


def test_creating_a_game_stores_fair_multipliers(appmodule, client):
    _login(client, appmodule)
    base = {"name": "Eerlijk", "role": "hunter", "duration": "60", "headstart": "5", "hunter_interval": "600",
            "runner_interval": "600", "target_duration": "300", "target_cooldown": "600", "max_offline": "300"}
    r = client.post("/new_game", data={**base, "difficulty": "easy"})
    assert r.status_code == 302
    with appmodule.app.app_context():
        g = appmodule.Game.query.filter_by(name="Eerlijk").first()
        assert (g.hunter_multiplier, g.runner_multiplier) == (1.0, 1.5)
        db = appmodule.db
        db.session.delete(appmodule.GamePlayer.query.filter_by(game_id=g.id).first()); db.session.delete(g); db.session.commit()
    r = client.post("/new_game", data={**base, "name": "Eigen", "difficulty": "custom", "target_enabled": "on", "offline_button": "on"})
    with appmodule.app.app_context():
        g = appmodule.Game.query.filter_by(name="Eigen").first()
        assert (g.hunter_multiplier, g.runner_multiplier) == (1.25, 1.25)   # target (+) and offline button (-) cancel out


def test_admin_images_upload_and_clear(appmodule, client):
    uid = _login(client, appmodule, "beheer2")
    with appmodule.app.app_context():
        appmodule.db.session.get(appmodule.User, uid).is_admin = True; appmodule.db.session.commit()
    assert client.get("/admin/images").status_code == 200
    import io
    from PIL import Image
    buf = io.BytesIO(); Image.new("RGB", (40, 30), "red").save(buf, "PNG"); buf.seek(0)
    r = client.post("/admin/images/img_extra_landmine", data={"file": (buf, "mijn.png")}, content_type="multipart/form-data")
    assert r.status_code == 200 and r.get_json()["url"].startswith("/backgrounds/")
    assert r.get_json()["url"] in client.get("/new_game").get_data(as_text=True)
    assert client.post("/admin/images/nope", data={}).status_code == 404
    assert client.post("/admin/images/img_extra_landmine/clear").get_json()["success"]
    assert "/backgrounds/" not in client.get("/new_game").get_data(as_text=True).split("tiles")[1].split("dropboxOpts")[0]

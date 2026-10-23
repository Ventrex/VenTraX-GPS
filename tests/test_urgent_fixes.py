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

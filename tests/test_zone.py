"""Shrinking zone maths (zone.py) and the game wiring."""
import random

import zone

LAT, LON = 52.1, 5.38


def square(half_m):
    return zone.regular_polygon(LAT, LON, half_m, 4)


def test_new_zone_is_smaller_and_always_inside_the_old_one():
    rng = random.Random(1)
    pts = zone.regular_polygon(LAT, LON, 500, 16)
    for _ in range(50):
        new, center = zone.shrink_polygon(pts, 0.7, rng)
        assert zone.mean_radius_m(new) < zone.mean_radius_m(pts)
        assert abs(zone.mean_radius_m(new) / zone.mean_radius_m(pts) - 0.7) < 0.02
        assert all(zone.point_in_polygon(p["lat"], p["lng"], pts) for p in new)
        assert zone.point_in_polygon(center["lat"], center["lng"], pts)


def test_new_centre_moves_but_stays_inside_for_awkward_shapes():
    rng = random.Random(2)
    l_shape = [{"lat": LAT + a / 111320, "lng": LON + b / 68400} for a, b in
               [(0, 0), (0, 400), (150, 400), (150, 150), (400, 150), (400, 0)]]
    moved = False
    for _ in range(30):
        new, center = zone.shrink_polygon(l_shape, 0.6, rng)
        assert all(zone.point_in_polygon(p["lat"], p["lng"], l_shape) for p in new)
        moved |= abs(center["lat"] - zone.centroid(l_shape)[0]) > 1e-5
    assert moved


CFG = dict(headstart_sec=300, first_sec=600, interval_sec=480, warning_sec=90, factor=0.7)


def test_schedule_warns_then_shrinks_at_the_right_times():
    pts = zone.regular_polygon(LAT, LON, 600, 16)
    state, rng = {}, random.Random(3)
    t_first = 300 + 600
    state, ev = zone.step(state, t_first - 100, CFG, pts, rng)
    assert ev == []                                             # too early
    state, ev = zone.step(state, t_first - 90, CFG, pts, rng)
    assert [e[0] for e in ev] == ["warn"] and ev[0][1]["phase"] == 1 and ev[0][1]["in_sec"] == 90
    warned = ev[0][1]["points"]
    state, ev = zone.step(state, t_first - 30, CFG, pts, rng)
    assert ev == []                                             # warned once only
    state, ev = zone.step(state, t_first, CFG, pts, rng)
    assert [e[0] for e in ev] == ["shrink"] and ev[0][1]["points"] == warned    # exactly what was announced
    assert state["phase"] == 1 and state["pending"] is None
    pts = ev[0][1]["points"]
    state, ev = zone.step(state, t_first + 480 - 90, CFG, pts, rng)
    assert ev[0][0] == "warn" and ev[0][1]["phase"] == 2


def test_catching_up_after_a_server_restart_does_not_skip_the_announcement_logic():
    pts = zone.regular_polygon(LAT, LON, 600, 16)
    state, ev = zone.step({}, 5000, CFG, pts, random.Random(4))       # restarted very late: warn and shrink at once
    assert [e[0] for e in ev] == ["warn", "shrink"] and state["phase"] == 1


def test_it_stops_at_a_final_zone():
    pts = zone.regular_polygon(LAT, LON, 90, 16)
    state, ev = zone.step({}, 99999, CFG, pts, random.Random(5))        # 90 m * 0.7 = 63 m < the 70 m minimum
    assert [e[0] for e in ev] == ["final"]
    state, ev = zone.step(state, 999999, CFG, pts, random.Random(5))
    assert ev == []                                                      # and it says so only once


# ---- wiring in the app ------------------------------------------------------------------------
import json
from datetime import datetime, timedelta

import gevent

from conftest import make_user


def zone_game(appmodule, with_field, started_min_ago, first=1, interval=2):
    uid = make_user(appmodule, username="zoner", email="zoner@example.com")
    with appmodule.app.app_context():
        g = appmodule.Game(name="Z", code="ZON123", creator_id=uid, status="active", headstart_minutes=1,
                           duration_minutes=60, started_at=datetime.utcnow() - timedelta(minutes=started_min_ago))
        appmodule.db.session.add(g); appmodule.db.session.commit()
        appmodule.db.session.add(appmodule.GamePlayer(game_id=g.id, user_id=uid, role="runner", last_lat=LAT, last_lon=LON,
                                                      gps_enabled=True, last_seen=datetime.utcnow()))
        appmodule.SiteSetting.set(appmodule._extras_key(g.id), json.dumps(
            {"shrinking_zone": True, "zone_first_min": first, "zone_interval_min": interval,
             "zone_shrink_pct": 30, "zone_warning_sec": 60}))
        if with_field:
            appmodule.SiteSetting.set(appmodule._playfield_key(g.id), json.dumps(
                {"enabled": True, "color": "storm", "points": zone.regular_polygon(LAT, LON, 500, 12), "forbidden": []}))
        appmodule.db.session.commit()
        return g.id, uid


def run_zone_loop(appmodule, monkeypatch, seconds=0.6):
    sent = []
    monkeypatch.setattr(appmodule, "ZONE_TICK", 0.02)
    monkeypatch.setattr(appmodule.hub, "broadcast", lambda code, ev, data=None: sent.append((ev, data)))
    gevent.spawn(appmodule._zone_loop, "ZON123")
    gevent.sleep(seconds)
    return sent


def test_zone_loop_announces_then_shrinks_and_stores_the_new_field(appmodule, monkeypatch):
    gid, _ = zone_game(appmodule, True, started_min_ago=2.5)      # shrink time = 1 min headstart + 1 min = 2.0 min
    with appmodule.app.app_context():
        before = appmodule.get_playfield(appmodule.db.session.get(appmodule.Game, gid))["points"]
    sent = run_zone_loop(appmodule, monkeypatch)
    kinds = [e for e, _ in sent]
    assert kinds[:2] == ["zone_warning", "zone_shrunk"]
    with appmodule.app.app_context():
        game = appmodule.db.session.get(appmodule.Game, gid)
        after = appmodule.get_playfield(game)["points"]
        assert zone.mean_radius_m(after) < zone.mean_radius_m(before) * 0.75
        assert after == sent[1][1]["points"] == sent[0][1]["points"]            # announced = applied
        info = appmodule.zone_info(game)
        assert info["phase"] == 1 and info["pending"] is None and info["next_in"] > 0
        game.status = "finished"; appmodule.db.session.commit()


def test_players_outside_the_new_field_are_under_pressure(appmodule, monkeypatch):
    gid, uid = zone_game(appmodule, True, started_min_ago=2.5)
    run_zone_loop(appmodule, monkeypatch)
    with appmodule.app.app_context():
        game = appmodule.db.session.get(appmodule.Game, gid)
        edge = zone.regular_polygon(LAT, LON, 480, 12)[0]                # inside the old field, outside the new one
        assert appmodule.playfield_outside_distance_m(game, edge["lat"], edge["lng"]) > 5
        game.status = "finished"; appmodule.db.session.commit()


def test_without_a_field_a_circle_around_the_players_is_made(appmodule, monkeypatch):
    gid, _ = zone_game(appmodule, False, started_min_ago=0.5)
    run_zone_loop(appmodule, monkeypatch, 0.3)
    with appmodule.app.app_context():
        game = appmodule.db.session.get(appmodule.Game, gid)
        pf = appmodule.get_playfield(game)
        assert pf and 550 < zone.mean_radius_m(pf["points"]) < 650
        game.status = "finished"; appmodule.db.session.commit()


def test_state_endpoint_tells_late_joiners_about_the_zone(appmodule, client, monkeypatch):
    gid, uid = zone_game(appmodule, True, started_min_ago=1.2)       # in the warning window (shrink at 2.0, warn 60 s before)
    run_zone_loop(appmodule, monkeypatch, 0.3)
    with client.session_transaction() as sess:
        sess["_user_id"] = str(uid); sess["_fresh"] = True
    d = client.get("/api/game/ZON123/state").get_json()
    assert d["zone"]["pending"]["phase"] == 1 and len(d["zone_points"]) == 12
    with appmodule.app.app_context():
        game = appmodule.db.session.get(appmodule.Game, gid)
        game.status = "finished"; appmodule.db.session.commit()
    gevent.sleep(0.1)


def test_new_game_stores_the_zone_settings(appmodule, client):
    uid = make_user(appmodule, username="maker3", email="maker3@example.com")
    with client.session_transaction() as sess:
        sess["_user_id"] = str(uid); sess["_fresh"] = True
    r = client.post("/new_game", data={"name": "Krimp", "role": "hunter", "duration": "60", "headstart": "5", "difficulty": "medium",
                                       "hunter_interval": "600", "runner_interval": "600", "target_duration": "300",
                                       "target_cooldown": "600", "max_offline": "300", "shrinking_zone": "on",
                                       "zone_first_min": "15", "zone_interval_min": "10", "zone_shrink_pct": "40", "zone_warning_sec": "120"})
    assert r.status_code == 302
    with appmodule.app.app_context():
        g = appmodule.Game.query.filter_by(name="Krimp").first()
        ex = appmodule.get_game_extras(g)
        assert ex["shrinking_zone"] and ex["zone_first_min"] == 15 and ex["zone_shrink_pct"] == 40
        cfg = appmodule.zone_config(g)
        assert cfg["factor"] == 0.6 and cfg["first_sec"] == 900 and cfg["warning_sec"] == 120

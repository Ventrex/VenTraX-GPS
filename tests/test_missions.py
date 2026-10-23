"""Runner missions: reach a spot and hold it, so runners keep moving."""
import json
from datetime import datetime, timedelta

import bots
import zone
from conftest import make_user

LAT, LON = 52.1, 5.38


def setup_game(appmodule, started_min_ago=10, hunters_see=True, forbidden=None, runners=2):
    ids = {}
    hid = make_user(appmodule, username="jager", email="jager@example.com")
    with appmodule.app.app_context():
        g = appmodule.Game(name="M", code="MIS123", creator_id=hid, status="active", headstart_minutes=5,
                           duration_minutes=120, started_at=datetime.utcnow() - timedelta(minutes=started_min_ago))
        appmodule.db.session.add(g); appmodule.db.session.commit()
        appmodule.db.session.add(appmodule.GamePlayer(game_id=g.id, user_id=hid, role="hunter", last_lat=LAT, last_lon=LON,
                                                      gps_enabled=True, last_seen=datetime.utcnow()))
        runner_ids = []
        for i in range(runners):
            uid = make_user(appmodule, username=f"loper{i}", email=f"loper{i}@example.com")
            runner_ids.append(uid)
            appmodule.db.session.add(appmodule.GamePlayer(game_id=g.id, user_id=uid, role="runner", last_lat=LAT, last_lon=LON,
                                                          gps_enabled=True, last_seen=datetime.utcnow(), codename=f"Vos{i}"))
        appmodule.SiteSetting.set(appmodule._extras_key(g.id), json.dumps(
            {"missions": True, "mission_hold_sec": 45, "mission_duration_min": 10, "mission_points": 5,
             "mission_hunters_see": hunters_see}))
        pf = {"enabled": True, "color": "storm", "points": zone.regular_polygon(LAT, LON, 700, 16), "forbidden": forbidden or []}
        appmodule.SiteSetting.set(appmodule._playfield_key(g.id), json.dumps(pf))
        appmodule.db.session.commit()
        return g.id, hid, runner_ids


def test_no_missions_during_the_head_start_or_when_switched_off(appmodule):
    gid, _, _ = setup_game(appmodule, started_min_ago=2)
    with appmodule.app.app_context():
        g = appmodule.db.session.get(appmodule.Game, gid)
        assert appmodule.get_game_missions(g) == []
        g.started_at = datetime.utcnow() - timedelta(minutes=10)
        assert len(appmodule.get_game_missions(g)) == 1                   # 2 runners -> 1 mission
        appmodule.SiteSetting.set(appmodule._extras_key(g.id), json.dumps({"missions": False}))
        assert appmodule.mission_config(g) is None and appmodule.get_game_missions(g) == []


def test_missions_stay_in_the_field_out_of_forbidden_areas_and_move_around(appmodule):
    a, b = LAT, LON
    forbidden = [{"type": "circle", "lat": a, "lng": b, "radius": 300}]       # a big forbidden hole in the middle
    gid, _, _ = setup_game(appmodule, forbidden=forbidden)
    spots = []
    with appmodule.app.app_context():
        g = appmodule.db.session.get(appmodule.Game, gid)
        pf = appmodule.get_playfield(g)
        for _ in range(8):
            m = appmodule.get_game_missions(g)[0]
            assert zone.point_in_polygon(m["lat"], m["lng"], pf["points"])
            assert appmodule.forbidden_penetration_m(pf, m["lat"], m["lng"]) <= 0
            spots.append((m["lat"], m["lng"]))
            st = appmodule._load_missions(g); st["missions"] = []            # pretend it expired
            appmodule.SiteSetting.set(appmodule._missions_key(g.id), json.dumps(st))
        # not the same place again and again
        far = [bots.haversine(*spots[i], *spots[i + 1]) for i in range(len(spots) - 1)]
        assert min(far) > 100 and len({(round(x, 4), round(y, 4)) for x, y in spots}) == len(spots)


def test_holding_the_circle_completes_the_mission_and_pays_the_runner(appmodule, monkeypatch):
    gid, hid, rids = setup_game(appmodule)
    monkeypatch.setattr(appmodule.hub, "broadcast", lambda *a, **k: None)
    with appmodule.app.app_context():
        g = appmodule.db.session.get(appmodule.Game, gid)
        m = appmodule.get_game_missions(g)[0]
        me = appmodule.GamePlayer.query.filter_by(game_id=gid, user_id=rids[0]).first()
        user = appmodule.db.session.get(appmodule.User, rids[0])
        t = 1000.0
        r = appmodule.mission_progress(g, me, user, m["lat"], m["lng"], t)
        assert r["held"] == 0 and r["need"] == 45
        appmodule.mission_progress(g, me, user, m["lat"], m["lng"], t + 10)
        r = appmodule.mission_progress(g, me, user, m["lat"], m["lng"], t + 20)
        assert r["held"] == 20 and "done" not in r
        # a long gap between two GPS pings does not count as holding (max 15 s per update)
        r = appmodule.mission_progress(g, me, user, m["lat"], m["lng"], t + 120)
        assert r["held"] == 35
        # stepping out resets the hold
        appmodule.mission_progress(g, me, user, m["lat"] + 0.01, m["lng"], t + 130)
        r = appmodule.mission_progress(g, me, user, m["lat"], m["lng"], t + 140)
        assert r["held"] == 0
        for k in range(1, 4):
            r = appmodule.mission_progress(g, me, user, m["lat"], m["lng"], t + 140 + k * 15)
        assert r["done"] == round(5 * g.multiplier_for("runner"), 2)
        assert me.points == r["done"] and user.total_points == r["done"]
        new = appmodule.get_game_missions(g)
        assert len(new) == 1 and new[0]["id"] != m["id"]                      # the next one is somewhere else
        assert bots.haversine(new[0]["lat"], new[0]["lng"], m["lat"], m["lng"]) > 100


def test_hunters_never_progress_and_may_or_may_not_see_the_spot(appmodule):
    gid, hid, rids = setup_game(appmodule, hunters_see=True)
    with appmodule.app.app_context():
        g = appmodule.db.session.get(appmodule.Game, gid)
        assert len(appmodule.missions_for_role(g, "hunter")) == 1 and len(appmodule.missions_for_role(g, "runner")) == 1
        hunter = appmodule.GamePlayer.query.filter_by(game_id=gid, user_id=hid).first()
        m = appmodule.get_game_missions(g)[0]
        assert appmodule.mission_progress(g, hunter, appmodule.db.session.get(appmodule.User, hid), m["lat"], m["lng"], 5.0) is None
        appmodule.SiteSetting.set(appmodule._extras_key(g.id), json.dumps({"missions": True, "mission_hunters_see": False}))
        assert appmodule.missions_for_role(g, "hunter") == [] and len(appmodule.missions_for_role(g, "runner")) == 1


def test_expired_missions_are_replaced_on_game_time(appmodule, monkeypatch):
    gid, _, _ = setup_game(appmodule)
    monkeypatch.setattr(appmodule.hub, "broadcast", lambda *a, **k: None)
    with appmodule.app.app_context():
        g = appmodule.db.session.get(appmodule.Game, gid)
        first = appmodule.get_game_missions(g)[0]
        g.started_at = g.started_at - timedelta(minutes=11)                    # 10 minute missions
        second = appmodule.get_game_missions(g)[0]
        assert second["id"] != first["id"]


def test_state_and_location_endpoints_carry_the_mission(appmodule, client, monkeypatch):
    gid, hid, rids = setup_game(appmodule)
    monkeypatch.setattr(appmodule.hub, "broadcast", lambda *a, **k: None)
    with client.session_transaction() as sess:
        sess["_user_id"] = str(rids[0]); sess["_fresh"] = True
    state = client.get("/api/game/MIS123/state").get_json()
    m = state["missions"][0]
    assert m["hold_sec"] == 45 and m["points"] == 5 and 0 < m["expires_in"] <= 600
    r = client.post("/api/game/MIS123/location", json={"lat": m["lat"], "lon": m["lon"] if "lon" in m else m["lng"], "accuracy": 5}).get_json()
    assert r["mission"]["id"] == m["id"] and r["mission"]["need"] == 45


def test_new_game_saves_mission_settings(appmodule, client):
    uid = make_user(appmodule, username="mkr", email="mkr@example.com")
    with client.session_transaction() as sess:
        sess["_user_id"] = str(uid); sess["_fresh"] = True
    r = client.post("/new_game", data={"name": "Missie", "role": "runner", "duration": "60", "headstart": "5", "difficulty": "medium",
                                       "hunter_interval": "600", "runner_interval": "600", "target_duration": "300", "target_cooldown": "600",
                                       "max_offline": "300", "missions": "on", "mission_hold_sec": "60", "mission_duration_min": "15",
                                       "mission_points": "8"})
    assert r.status_code == 302
    with appmodule.app.app_context():
        g = appmodule.Game.query.filter_by(name="Missie").first()
        cfg = appmodule.mission_config(g)
        assert cfg == {"hold_sec": 60, "duration_sec": 900, "points": 8, "hunters_see": True}

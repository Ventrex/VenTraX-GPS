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


def _as(client, uid):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(uid); sess["_fresh"] = True


def test_reaching_a_point_offers_three_levels_and_skipping_moves_the_point(appmodule, client, monkeypatch):
    gid, hid, rids = setup_game(appmodule)
    monkeypatch.setattr(appmodule.hub, "broadcast", lambda *a, **k: None)
    with appmodule.app.app_context():
        g = appmodule.db.session.get(appmodule.Game, gid)
        m = appmodule.get_game_missions(g)[0]
    _as(client, rids[0])
    r = client.post("/api/game/MIS123/location", json={"lat": m["lat"], "lon": m["lng"], "accuracy": 5}).get_json()
    offer = r["mission"]["offer"]
    assert offer["point"] == m["id"] and [o["tier"] for o in offer["options"]] == ["easy", "medium", "hard"]
    pts = [o["points"] for o in offer["options"]]
    assert pts[1] == 2 * pts[0] and pts[2] == 3 * pts[0]                       # medium x2, hard x3
    # far away you cannot choose
    with appmodule.app.app_context():
        me = appmodule.GamePlayer.query.filter_by(game_id=gid, user_id=rids[0]).first()
        me.last_lat = m["lat"] + 0.01; appmodule.db.session.commit()
    assert client.post("/api/game/MIS123/mission/choose", json={"point": m["id"], "tier": "easy"}).status_code == 400
    client.post("/api/game/MIS123/location", json={"lat": m["lat"], "lon": m["lng"], "accuracy": 5})
    r = client.post("/api/game/MIS123/mission/choose", json={"point": m["id"], "tier": "skip"}).get_json()
    assert r["skipped"]
    with appmodule.app.app_context():
        g = appmodule.db.session.get(appmodule.Game, gid)
        new = appmodule.get_game_missions(g)
        assert len(new) == 1 and new[0]["id"] != m["id"]                      # the point moved somewhere else
        assert bots.haversine(new[0]["lat"], new[0]["lng"], m["lat"], m["lng"]) > 100
        assert appmodule._load_missions(g)["active"] == {}


def _pick_first(appmodule, monkeypatch):
    real = appmodule.random.choice
    monkeypatch.setattr(appmodule.random, "choice", lambda seq: seq[0] if seq and isinstance(seq[0], str) else real(seq))


def test_easy_hold_mission_completes_and_pays_the_runner(appmodule, client, monkeypatch):
    gid, hid, rids = setup_game(appmodule)
    monkeypatch.setattr(appmodule.hub, "broadcast", lambda *a, **k: None)
    _pick_first(appmodule, monkeypatch)                                        # easy = hold
    with appmodule.app.app_context():
        g = appmodule.db.session.get(appmodule.Game, gid)
        m = appmodule.get_game_missions(g)[0]
    _as(client, rids[0])
    client.post("/api/game/MIS123/location", json={"lat": m["lat"], "lon": m["lng"], "accuracy": 5})
    r = client.post("/api/game/MIS123/mission/choose", json={"point": m["id"], "tier": "easy"}).get_json()
    assert r["active"]["kind"] == "hold" and r["active"]["tier"] == "easy"
    with appmodule.app.app_context():
        g = appmodule.db.session.get(appmodule.Game, gid)
        assert all(x["id"] != m["id"] for x in appmodule.get_game_missions(g))   # the point is used up
        me = appmodule.GamePlayer.query.filter_by(game_id=gid, user_id=rids[0]).first()
        user = appmodule.db.session.get(appmodule.User, rids[0])
        start = me.points
        t = 1000.0
        r = appmodule.mission_progress(g, me, user, m["lat"], m["lng"], t)
        assert r["active"]["progress"] == 0
        r = appmodule.mission_progress(g, me, user, m["lat"], m["lng"], t + 15)
        r = appmodule.mission_progress(g, me, user, m["lat"], m["lng"], t + 30)
        assert 0 < r["active"]["progress"] < 1
        # stepping out (more than 10 m) starts over
        appmodule.mission_progress(g, me, user, m["lat"] + 0.0003, m["lng"], t + 40)
        r = appmodule.mission_progress(g, me, user, m["lat"], m["lng"], t + 45)
        assert r["active"]["progress"] == 0
        for k in range(1, 4):                                                  # 3 x 15 s = 45 s held
            r = appmodule.mission_progress(g, me, user, m["lat"], m["lng"], t + 45 + k * 15)
        assert r["done"] == round(5 * g.multiplier_for("runner"), 2)
        assert round(me.points - start, 2) == r["done"]
        assert appmodule._load_missions(g)["active"] == {}


def test_failing_a_mission_costs_nothing(appmodule, client, monkeypatch):
    gid, hid, rids = setup_game(appmodule)
    monkeypatch.setattr(appmodule.hub, "broadcast", lambda *a, **k: None)
    _pick_first(appmodule, monkeypatch)
    with appmodule.app.app_context():
        g = appmodule.db.session.get(appmodule.Game, gid)
        m = appmodule.get_game_missions(g)[0]
    _as(client, rids[0])
    client.post("/api/game/MIS123/location", json={"lat": m["lat"], "lon": m["lng"], "accuracy": 5})
    r = client.post("/api/game/MIS123/mission/choose", json={"point": m["id"], "tier": "medium"}).get_json()
    assert r["active"]["kind"] == "relay" and len(r["active"]["targets"]) == 1 and r["active"]["penalty"] == 0
    before = client.get("/api/game/MIS123/state").get_json()["my_points"]
    with appmodule.app.app_context():
        g = appmodule.db.session.get(appmodule.Game, gid)
        g.started_at = g.started_at - timedelta(minutes=9)                      # 8 minutes are over
        appmodule.db.session.commit()
    s = client.get("/api/game/MIS123/state").get_json()
    assert s["my_mission"] is None and "Geen straf" in s["mission_note"] and s["my_points"] == before
    assert client.get("/api/game/MIS123/state").get_json()["mission_note"] is None   # told only once
    # stopping is free as well
    assert client.post("/api/game/MIS123/mission/stop").status_code == 400            # nothing to stop now


def _start_scout(appmodule, client, monkeypatch, gid, hid, rids, hunter_dlat=0.004):
    with appmodule.app.app_context():
        g = appmodule.db.session.get(appmodule.Game, gid)
        m = appmodule.get_game_missions(g)[0]
        hunter = appmodule.GamePlayer.query.filter_by(game_id=gid, user_id=hid).first()
        hunter.last_lat, hunter.last_lon = m["lat"] + hunter_dlat, m["lng"]   # ~450 m north of the point
        appmodule.db.session.commit()
    real = appmodule.random.choice
    monkeypatch.setattr(appmodule.random, "choice", lambda seq: "scout" if "scout" in seq else real(seq))
    _as(client, rids[0])
    r = client.post("/api/game/MIS123/location", json={"lat": m["lat"], "lon": m["lng"], "accuracy": 5}).get_json()
    hard = r["mission"]["offer"]["options"][2]
    assert hard["kind"] == "scout" and hard["penalty"] == hard["points"]        # the offer says what failing costs
    r = client.post("/api/game/MIS123/mission/choose", json={"point": m["id"], "tier": "hard"}).get_json()
    return m, r["active"]


def test_scout_mission_shows_where_a_hunter_is_and_is_done_within_100_m(appmodule, client, monkeypatch):
    gid, hid, rids = setup_game(appmodule)
    monkeypatch.setattr(appmodule.hub, "broadcast", lambda *a, **k: None)
    m, active = _start_scout(appmodule, client, monkeypatch, gid, hid, rids)
    t = active["targets"][0]
    assert active["kind"] == "scout" and t["radius"] == 100
    assert abs(t["lat"] - (m["lat"] + 0.004)) < 1e-6                           # the runner got the hunter's spot
    r = client.post("/api/game/MIS123/location", json={"lat": m["lat"] + 0.002, "lon": m["lng"], "accuracy": 5}).get_json()
    assert r["mission"]["active"]["kind"] == "scout"                          # still 220 m away
    r = client.post("/api/game/MIS123/location", json={"lat": m["lat"] + 0.0033, "lon": m["lng"], "accuracy": 5}).get_json()
    assert r["mission"]["done"] > 0                                           # within 100 m


def test_failing_or_stopping_the_scout_mission_costs_points(appmodule, client, monkeypatch):
    gid, hid, rids = setup_game(appmodule)
    monkeypatch.setattr(appmodule.hub, "broadcast", lambda *a, **k: None)
    m, active = _start_scout(appmodule, client, monkeypatch, gid, hid, rids)
    before = client.get("/api/game/MIS123/state").get_json()["my_points"]
    r = client.post("/api/game/MIS123/mission/stop").get_json()               # took it, ran the other way
    assert "-" in r["message"] and round(before - r["points"], 2) == active["penalty"]
    # time running out costs the same
    with appmodule.app.app_context():
        g = appmodule.db.session.get(appmodule.Game, gid)
        m2 = appmodule.get_game_missions(g)[0]
    client.post("/api/game/MIS123/location", json={"lat": m2["lat"], "lon": m2["lng"], "accuracy": 5})
    active2 = client.post("/api/game/MIS123/mission/choose", json={"point": m2["id"], "tier": "hard"}).get_json()["active"]
    before = client.get("/api/game/MIS123/state").get_json()["my_points"]
    with appmodule.app.app_context():
        g = appmodule.db.session.get(appmodule.Game, gid)
        g.started_at = g.started_at - timedelta(minutes=11); appmodule.db.session.commit()
    s = client.get("/api/game/MIS123/state").get_json()
    assert s["my_mission"] is None and "punten" in s["mission_note"]
    assert round(before - s["my_points"], 2) == active2["penalty"]


def test_lootbox_mission_is_done_by_opening_a_lootbox(appmodule, client, monkeypatch):
    gid, hid, rids = setup_game(appmodule)
    monkeypatch.setattr(appmodule.hub, "broadcast", lambda *a, **k: None)
    with appmodule.app.app_context():
        g = appmodule.db.session.get(appmodule.Game, gid)
        ex = appmodule.get_game_extras(g); ex.update({"dropboxes": True, "dropboxes_per_team": 1, "dropboxes_global": 0})
        appmodule.SiteSetting.set(appmodule._extras_key(gid), json.dumps(ex))
        m = appmodule.get_game_missions(g)[0]
        box = next(b for b in appmodule.get_game_lootboxes(g) if b["team"] == "runner")
    real = appmodule.random.choice
    monkeypatch.setattr(appmodule.random, "choice", lambda seq: "lootbox" if "lootbox" in seq else real(seq))
    _as(client, rids[0])
    client.post("/api/game/MIS123/location", json={"lat": m["lat"], "lon": m["lng"], "accuracy": 5})
    r = client.post("/api/game/MIS123/mission/choose", json={"point": m["id"], "tier": "easy"}).get_json()
    assert r["active"]["kind"] == "lootbox"
    client.post("/api/game/MIS123/location", json={"lat": box["lat"], "lon": box["lng"], "accuracy": 5})
    r = client.post(f"/api/game/MIS123/lootbox/{box['id']}/claim").get_json()
    assert r["mission_done"] == round(10 * 1.0, 2) or r["mission_done"] > 0
    assert client.get("/api/game/MIS123/state").get_json()["my_mission"] is None


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


def test_state_endpoint_carries_the_mission_points(appmodule, client, monkeypatch):
    gid, hid, rids = setup_game(appmodule)
    monkeypatch.setattr(appmodule.hub, "broadcast", lambda *a, **k: None)
    _as(client, rids[0])
    state = client.get("/api/game/MIS123/state").get_json()
    m = state["missions"][0]
    assert m["hold_sec"] == 45 and m["points"] == 5 and 0 < m["expires_in"] <= 600
    assert state["my_mission"] is None


def test_new_game_saves_mission_settings(appmodule, client):
    uid = make_user(appmodule, username="mkr", email="mkr@example.com")
    with client.session_transaction() as sess:
        sess["_user_id"] = str(uid); sess["_fresh"] = True
    r = client.post("/new_game", data={"name": "Missie", "role": "runner", "duration": "60", "headstart": "5", "difficulty": "medium",
                                       "hunter_interval": "600", "runner_interval": "600", "target_duration": "300", "target_cooldown": "600",
                                       "max_offline": "300", "missions": "on", "mission_hold_sec": "60", "mission_duration_min": "15",
                                       "mission_points": "8", "catch_mode": "freeze", "extra_shelter": "on", "shelters": "3"})
    assert r.status_code == 302
    with appmodule.app.app_context():
        g = appmodule.Game.query.filter_by(name="Missie").first()
        cfg = appmodule.mission_config(g)
        assert cfg == {"hold_sec": 60, "duration_sec": 900, "points": 8, "hunters_see": True}
        ex = appmodule.get_game_extras(g)
        assert ex["catch_mode"] == "freeze" and ex["shelters"] == 3


def test_every_mission_type_can_be_started_and_shown(appmodule, monkeypatch):
    gid, hid, rids = setup_game(appmodule)
    monkeypatch.setattr(appmodule.hub, "broadcast", lambda *a, **k: None)
    with appmodule.app.app_context():
        g = appmodule.db.session.get(appmodule.Game, gid)
        ex = appmodule.get_game_extras(g); ex.update({"shelters": 2})
        appmodule.SiteSetting.set(appmodule._extras_key(gid), json.dumps(ex))
        assert len(appmodule.get_game_shelters(g)) == 2
        me = appmodule.GamePlayer.query.filter_by(game_id=gid, user_id=rids[0]).first()
        point = appmodule.get_game_missions(g)[0]
        tiers = {t["tier"] for t in appmodule.MISSION_TYPES.values()}
        assert tiers == {"easy", "medium", "hard"} and len(appmodule.MISSION_TYPES) >= 15
        for kind, t in appmodule.MISSION_TYPES.items():
            opt = {"tier": t["tier"], "kind": kind, "title": t["title"], "desc": t.get("desc", ""), "points": 5,
                   "minutes": t["minutes"], "need": t.get("need") or 45}
            a = appmodule._start_mission(g, me, opt, point, 100.0)
            view = appmodule._mission_view(a, 100.0)
            assert view["left"] == t["minutes"] * 60 and view["title"] == t["title"], kind
            if kind in appmodule.ROUTE_KINDS:
                assert len(view["targets"]) == 1, kind

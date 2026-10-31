"""Lokaas, EMP / Medkit from lootboxes, schuilkelders, and catching with a lasso or a freezegun."""
import json
from datetime import datetime, timedelta

import zone
from conftest import make_user

LAT, LON = 52.1, 5.38
CODE = "VNG123"


def setup_game(appmodule, extras=None, started_min_ago=70, duration=120, interval=600, runners=1):
    hid = make_user(appmodule, username="jager", email="jager@example.com")
    rids = []
    with appmodule.app.app_context():
        g = appmodule.Game(name="V", code=CODE, creator_id=hid, status="active", headstart_minutes=5,
                           duration_minutes=duration, hunter_interval_sec=interval,
                           started_at=datetime.utcnow() - timedelta(minutes=started_min_ago))
        appmodule.db.session.add(g); appmodule.db.session.commit()
        appmodule.db.session.add(appmodule.GamePlayer(game_id=g.id, user_id=hid, role="hunter", last_lat=LAT, last_lon=LON,
                                                      gps_enabled=True, last_seen=datetime.utcnow(), last_gps_at=datetime.utcnow(),
                                                      codename="Wolf"))
        for i in range(runners):
            uid = make_user(appmodule, username=f"loper{i}", email=f"loper{i}@example.com")
            rids.append(uid)
            appmodule.db.session.add(appmodule.GamePlayer(game_id=g.id, user_id=uid, role="runner", last_lat=LAT + 0.0001 * (i + 1),
                                                          last_lon=LON, gps_enabled=True, last_seen=datetime.utcnow(),
                                                          last_gps_at=datetime.utcnow(), codename=f"Vos{i}"))
        appmodule.SiteSetting.set(appmodule._extras_key(g.id), json.dumps(extras or {}))
        pf = {"enabled": True, "color": "storm", "points": zone.regular_polygon(LAT, LON, 700, 16), "forbidden": []}
        appmodule.SiteSetting.set(appmodule._playfield_key(g.id), json.dumps(pf))
        appmodule.db.session.commit()
        return g.id, hid, rids


def login(client, uid):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(uid); sess["_fresh"] = True


def move(appmodule, gid, uid, lat, lon):
    with appmodule.app.app_context():
        p = appmodule.GamePlayer.query.filter_by(game_id=gid, user_id=uid).first()
        p.last_lat, p.last_lon, p.last_seen = lat, lon, datetime.utcnow()
        p.last_gps_at = p.last_seen
        appmodule.db.session.commit()


def caught(appmodule, gid, uid):
    with appmodule.app.app_context():
        return appmodule.GamePlayer.query.filter_by(game_id=gid, user_id=uid).first().is_caught


# ---- Lasso ----------------------------------------------------------------------------------
def test_lasso_hits_the_nearest_runner_close_by_and_then_needs_to_reload(appmodule, client, monkeypatch):
    gid, hid, rids = setup_game(appmodule, {"catch_mode": "lasso"})
    monkeypatch.setattr(appmodule.hub, "broadcast", lambda *a, **k: None)
    login(client, hid)
    move(appmodule, gid, rids[0], LAT + 0.0003, LON)                          # ~33 m: out of reach
    r = client.post(f"/api/game/{CODE}/catch_action", json={"action": "lasso"})
    assert r.status_code == 400 and "20 m" in r.get_json()["error"]
    move(appmodule, gid, rids[0], LAT + 0.00005, LON)                         # ~6 m: always a hit
    r = client.post(f"/api/game/{CODE}/catch_action", json={"action": "lasso"}).get_json()
    assert r["caught"] and caught(appmodule, gid, rids[0])


def test_lasso_can_miss_far_away_and_has_a_cooldown(appmodule, client, monkeypatch):
    gid, hid, rids = setup_game(appmodule, {"catch_mode": "lasso"})
    monkeypatch.setattr(appmodule.hub, "broadcast", lambda *a, **k: None)
    monkeypatch.setattr(appmodule.random, "random", lambda: 0.99)            # unlucky throw
    login(client, hid)
    move(appmodule, gid, rids[0], LAT + 0.00017, LON)                         # ~19 m
    r = client.post(f"/api/game/{CODE}/catch_action", json={"action": "lasso"}).get_json()
    assert r["caught"] is False and r["cooldown"] == appmodule.LASSO_COOLDOWN_SEC and not caught(appmodule, gid, rids[0])
    r = client.post(f"/api/game/{CODE}/catch_action", json={"action": "lasso"})
    assert r.status_code == 400 and r.get_json()["cooldown"] > 0
    assert client.get(f"/api/game/{CODE}/state").get_json()["catch_cooldown"] > 0


def test_catching_from_a_distance_waits_until_half_time_and_follows_the_game_setting(appmodule, client, monkeypatch):
    gid, hid, rids = setup_game(appmodule, {"catch_mode": "lasso"}, started_min_ago=20)
    monkeypatch.setattr(appmodule.hub, "broadcast", lambda *a, **k: None)
    login(client, hid)
    move(appmodule, gid, rids[0], LAT + 0.00005, LON)
    assert client.post(f"/api/game/{CODE}/catch_action", json={"action": "lasso"}).status_code == 400
    with appmodule.app.app_context():
        appmodule.SiteSetting.set(appmodule._extras_key(gid), json.dumps({"catch_mode": "tag"}))
        g = appmodule.db.session.get(appmodule.Game, gid); g.started_at = datetime.utcnow() - timedelta(minutes=70)
        appmodule.db.session.commit()
    r = client.post(f"/api/game/{CODE}/catch_action", json={"action": "lasso"})
    assert r.status_code == 400 and "staat niet aan" in r.get_json()["error"]


def test_runners_with_an_old_gps_position_cannot_be_lassoed(appmodule, client, monkeypatch):
    gid, hid, rids = setup_game(appmodule, {"catch_mode": "lasso"})
    monkeypatch.setattr(appmodule.hub, "broadcast", lambda *a, **k: None)
    with appmodule.app.app_context():
        p = appmodule.GamePlayer.query.filter_by(game_id=gid, user_id=rids[0]).first()
        p.last_gps_at = datetime.utcnow() - timedelta(minutes=5)     # app still open (last_seen fresh), no GPS fix
        p.last_seen = datetime.utcnow(); appmodule.db.session.commit()
    login(client, hid)
    assert client.post(f"/api/game/{CODE}/catch_action", json={"action": "lasso"}).status_code == 400


# ---- Freezegun ------------------------------------------------------------------------------
def test_freeze_then_grab_within_8_metres(appmodule, client, monkeypatch):
    gid, hid, rids = setup_game(appmodule, {"catch_mode": "freeze"})
    monkeypatch.setattr(appmodule.hub, "broadcast", lambda *a, **k: None)
    login(client, hid)
    move(appmodule, gid, rids[0], LAT + 0.0002, LON)                          # ~22 m
    assert client.post(f"/api/game/{CODE}/catch_action", json={"action": "grab"}).status_code == 400   # nobody frozen
    r = client.post(f"/api/game/{CODE}/catch_action", json={"action": "freeze"}).get_json()
    assert r["frozen"] and r["seconds"] == appmodule.FREEZE_SEC
    s = client.get(f"/api/game/{CODE}/state").get_json()
    assert next(p for p in s["players"] if p["id"] == rids[0])["frozen_left"] > 0
    r = client.post(f"/api/game/{CODE}/catch_action", json={"action": "grab"})
    assert r.status_code == 400 and "8 m" in r.get_json()["error"]            # still 22 m away
    with appmodule.app.app_context():
        h = appmodule.GamePlayer.query.filter_by(game_id=gid, user_id=hid).first()
        h.last_lat = LAT + 0.00017; appmodule.db.session.commit()            # walked up: ~3 m
    r = client.post(f"/api/game/{CODE}/catch_action", json={"action": "grab"}).get_json()
    assert r["caught"] and caught(appmodule, gid, rids[0])


def test_walking_away_while_frozen_means_caught(appmodule, client, monkeypatch):
    gid, hid, rids = setup_game(appmodule, {"catch_mode": "freeze"})
    monkeypatch.setattr(appmodule.hub, "broadcast", lambda *a, **k: None)
    login(client, hid)
    move(appmodule, gid, rids[0], LAT + 0.0001, LON)
    client.post(f"/api/game/{CODE}/catch_action", json={"action": "freeze"})
    login(client, rids[0])
    s = client.get(f"/api/game/{CODE}/state").get_json()
    assert s["my_frozen"]["left"] > 0
    r = client.post(f"/api/game/{CODE}/location", json={"lat": LAT + 0.00015, "lon": LON, "accuracy": 5}).get_json()
    assert r["freeze"]["left"] > 0 and not caught(appmodule, gid, rids[0])  # a few metres of GPS wobble is fine
    r = client.post(f"/api/game/{CODE}/location", json={"lat": LAT + 0.0005, "lon": LON, "accuracy": 5})
    assert caught(appmodule, gid, rids[0])


def test_after_thawing_a_runner_cannot_be_frozen_again_right_away(appmodule, client, monkeypatch):
    gid, hid, rids = setup_game(appmodule, {"catch_mode": "freeze"})
    monkeypatch.setattr(appmodule.hub, "broadcast", lambda *a, **k: None)
    login(client, hid)
    client.post(f"/api/game/{CODE}/catch_action", json={"action": "freeze"})
    with appmodule.app.app_context():
        g = appmodule.db.session.get(appmodule.Game, gid)
        fx = appmodule.get_game_effects(g)
        fx["frozen"][str(rids[0])]["until"] = 0                                # time is up
        fx["catch_cd"] = {}
        appmodule.save_game_effects(g, fx)
    login(client, rids[0])
    r = client.post(f"/api/game/{CODE}/location", json={"lat": LAT + 0.0001, "lon": LON, "accuracy": 5}).get_json()
    assert r["freeze"] == {"thawed": True}
    login(client, hid)
    assert client.post(f"/api/game/{CODE}/catch_action", json={"action": "freeze"}).status_code == 400


# ---- Lokaas -----------------------------------------------------------------------------------
def test_lokvogel_is_a_runner_class_and_puts_a_second_runner_on_the_hunter_map(appmodule, client, monkeypatch):
    assert all(c["id"] != "lokvogel" for c in appmodule.class_loadouts_for("hunter"))
    assert any(c["id"] == "lokvogel" for c in appmodule.class_loadouts_for("runner"))
    gid, hid, rids = setup_game(appmodule, {"classes_enabled": True, "classes_runner": ["lokvogel"], "classes_hunter": ["lokvogel", "glitcher"]})
    monkeypatch.setattr(appmodule.hub, "broadcast", lambda *a, **k: None)
    with appmodule.app.app_context():
        g = appmodule.db.session.get(appmodule.Game, gid)
        assigned = appmodule.assign_game_classes(g)
        assert assigned[str(rids[0])]["id"] == "lokvogel" and assigned[str(hid)]["id"] == "glitcher"
    login(client, rids[0])
    r = client.post(f"/api/game/{CODE}/class_power", json={}).get_json()
    assert r["type"] == "decoy" and r["cooldown"] >= 300
    assert client.get(f"/api/game/{CODE}/state").get_json()["my_decoy"]["left"] > 0
    login(client, hid)
    runner = next(p for p in client.get(f"/api/game/{CODE}/state").get_json()["players"] if p["id"] == rids[0])
    spots = [(runner["lat"], runner["lon"]), (runner["alt"]["lat"], runner["alt"]["lon"])]
    with appmodule.app.app_context():
        g = appmodule.db.session.get(appmodule.Game, gid)
        dec = appmodule.get_game_effects(g)["decoys"][str(rids[0])]
    assert (dec["lat"], dec["lng"]) in spots and len(set(spots)) == 2


# ---- Items --------------------------------------------------------------------------------------
def test_lootbox_can_give_emp_and_medkit_and_they_work(appmodule, client, monkeypatch):
    gid, hid, rids = setup_game(appmodule, {"dropboxes": True, "dropboxes_global": 1, "dropboxes_per_team": 1,
                                            "classes_enabled": True})
    monkeypatch.setattr(appmodule.hub, "broadcast", lambda *a, **k: None)
    with appmodule.app.app_context():
        g = appmodule.db.session.get(appmodule.Game, gid)
        appmodule.assign_game_classes(g)
        box = next(b for b in appmodule.get_game_lootboxes(g) if b["team"] == "hunter")
    seq = iter(["emp", "medkit"])
    monkeypatch.setattr(appmodule.random, "choices", lambda pop, weights=None, k=1: [2] if pop == [1, 2, 3] else [next(seq)])
    login(client, hid)
    move(appmodule, gid, hid, box["lat"], box["lng"])
    r = client.post(f"/api/game/{CODE}/lootbox/{box['id']}/claim").get_json()
    assert {i["id"] for i in r["items"]} == {"emp", "medkit"}
    assert [x["type"] for x in r["rewards"]] == ["emp", "medkit"]               # what the reveal screen shows
    assert all(x["title"] and x["sub"] for x in r["rewards"])
    # medkit: only when the life bar is not full
    assert client.post(f"/api/game/{CODE}/item", json={"item": "medkit"}).status_code == 400
    with appmodule.app.app_context():
        appmodule.SiteSetting.set(appmodule._zone_state_key(gid), json.dumps({str(hid): {"seconds": 20, "limit_sec": 30}}))
    r = client.post(f"/api/game/{CODE}/item", json={"item": "medkit"}).get_json()
    assert r["zone_pressure"]["seconds"] == 0 and all(i["id"] != "medkit" for i in r["items"])
    # EMP: nobody near = kept
    move(appmodule, gid, rids[0], box["lat"] + 0.002, box["lng"])
    assert client.post(f"/api/game/{CODE}/item", json={"item": "emp"}).status_code == 400
    move(appmodule, gid, rids[0], box["lat"] + 0.0002, box["lng"])          # ~22 m
    with appmodule.app.app_context():
        g = appmodule.db.session.get(appmodule.Game, gid)
        fx = appmodule.get_game_effects(g)
        fx["hazards"] = [{"id": "x", "kind": "landmine", "owner_role": "runner", "owner_id": rids[0], "lat": box["lat"], "lng": box["lng"], "triggered_by": []}]
        appmodule.save_game_effects(g, fx)
    r = client.post(f"/api/game/{CODE}/item", json={"item": "emp"}).get_json()
    assert "1 tegenstander" in r["message"] and "1 val" in r["message"] and r["items"] == []
    with appmodule.app.app_context():
        g = appmodule.db.session.get(appmodule.Game, gid)
        assert appmodule.class_cooldown_remaining(g, rids[0]) >= 170 and appmodule.get_game_effects(g)["hazards"] == []


# ---- Schuilkelders ----------------------------------------------------------------------------
def test_shelters_are_visible_to_everybody_and_delay_one_location_update(appmodule, client, monkeypatch):
    # 5 min head start + 10 min interval: the update of slot 1 is at 15 min game time
    gid, hid, rids = setup_game(appmodule, {"shelters": 2}, started_min_ago=0)
    monkeypatch.setattr(appmodule.hub, "broadcast", lambda *a, **k: None)
    login(client, hid)
    shelters = client.get(f"/api/game/{CODE}/state").get_json()["shelters"]
    assert len(shelters) == 2
    s = shelters[0]

    def at_game_min(minutes):
        with appmodule.app.app_context():
            g = appmodule.db.session.get(appmodule.Game, gid)
            g.started_at = datetime.utcnow() - timedelta(minutes=minutes)
            appmodule.db.session.commit()

    def hunter_sees():
        login(client, hid)
        p = next(p for p in client.get(f"/api/game/{CODE}/state").get_json()["players"] if p["id"] == rids[0])
        return (round(p["lat"], 5), round(p["lon"], 5)), p.get("location_delayed", False)

    at_game_min(10)
    first, _ = hunter_sees()                                                 # slot 0 spot (start position)
    # 40 s before the update the runner walks into the shelter
    at_game_min(15 - 40 / 60)
    login(client, rids[0])
    r = client.post(f"/api/game/{CODE}/location", json={"lat": s["lat"], "lon": s["lng"], "accuracy": 5}).get_json()
    assert r["shelter"]["just_entered"] and r["shelter"]["protect_left"] >= 88
    # at the moment of the update the hunters still see the old spot
    at_game_min(15 + 5 / 60)
    spot, delayed = hunter_sees()
    assert spot == first and delayed
    login(client, rids[0])
    lv = client.get(f"/api/game/{CODE}/state").get_json()["loc_view"]
    assert 0 < lv["delayed_in"] <= 50
    # 90 s after entering (= 50 s after the update moment) the update comes, with where the runner is then
    move(appmodule, gid, rids[0], s["lat"] + 0.001, s["lng"])
    at_game_min(15 + 52 / 60)
    spot, delayed = hunter_sees()
    assert spot == (round(s["lat"] + 0.001, 5), round(s["lng"], 5)) and not delayed
    # the next update is on the normal clock again (25 min), and cannot be delayed right after
    login(client, rids[0])
    at_game_min(25 - 30 / 60)
    client.post(f"/api/game/{CODE}/location", json={"lat": s["lat"] + 0.0002, "lon": s["lng"], "accuracy": 5})
    client.post(f"/api/game/{CODE}/location", json={"lat": s["lat"], "lon": s["lng"], "accuracy": 5})
    at_game_min(25 + 2 / 60)
    spot, delayed = hunter_sees()
    assert spot == (round(s["lat"], 5), round(s["lng"], 5)) and not delayed


def test_entering_long_before_the_update_does_not_help(appmodule, client, monkeypatch):
    gid, hid, rids = setup_game(appmodule, {"shelters": 1}, started_min_ago=0)
    monkeypatch.setattr(appmodule.hub, "broadcast", lambda *a, **k: None)
    with appmodule.app.app_context():
        g = appmodule.db.session.get(appmodule.Game, gid)
        g.started_at = datetime.utcnow() - timedelta(minutes=10)
        appmodule.db.session.commit()
        s = appmodule.get_game_shelters(g)[0]
    login(client, rids[0])
    client.post(f"/api/game/{CODE}/location", json={"lat": s["lat"], "lon": s["lng"], "accuracy": 5})   # 5 min early
    with appmodule.app.app_context():
        g = appmodule.db.session.get(appmodule.Game, gid)
        g.started_at = datetime.utcnow() - timedelta(minutes=15, seconds=5)
        appmodule.db.session.commit()
    login(client, hid)
    p = next(p for p in client.get(f"/api/game/{CODE}/state").get_json()["players"] if p["id"] == rids[0])
    assert round(p["lat"], 5) == round(s["lat"], 5) and not p.get("location_delayed")


def test_no_shelters_with_live_tracking(appmodule):
    gid, hid, rids = setup_game(appmodule, {"shelters": 2})
    with appmodule.app.app_context():
        g = appmodule.db.session.get(appmodule.Game, gid)
        g.live_tracking = True
        assert appmodule.get_game_shelters(g) == []


def test_lobby_explains_the_catch_mode_shelters_and_missions(appmodule, client):
    gid, hid, rids = setup_game(appmodule, {"catch_mode": "lasso", "shelters": 2, "missions": True})
    with appmodule.app.app_context():
        g = appmodule.db.session.get(appmodule.Game, gid); g.status = "lobby"; g.started_at = None
        appmodule.db.session.commit()
    login(client, hid)
    html = client.get(f"/lobby/{CODE}").get_data(as_text=True)
    assert "Lasso: hunter gooit" in html and "Schuilkelders:" in html and "makkelijk, middel of moeilijk" in html


def test_freeze_button_still_freezes_when_someone_else_is_frozen_far_away(appmodule, client, monkeypatch):
    gid, hid, rids = setup_game(appmodule, {"catch_mode": "freeze"}, runners=2)
    monkeypatch.setattr(appmodule.hub, "broadcast", lambda *a, **k: None)
    move(appmodule, gid, rids[0], LAT + 0.003, LON)                           # far away, frozen by another hunter
    with appmodule.app.app_context():
        g = appmodule.db.session.get(appmodule.Game, gid)
        fx = appmodule.get_game_effects(g)
        fx["frozen"] = {str(rids[0]): {"until": appmodule._now_ts() + 15, "lat": LAT + 0.003, "lon": LON, "by": hid}}
        appmodule.save_game_effects(g, fx)
    move(appmodule, gid, rids[1], LAT + 0.0001, LON)                          # close by
    login(client, hid)
    r = client.post(f"/api/game/{CODE}/catch_action", json={"action": "freeze"}).get_json()
    assert r["frozen"]
    # not close enough yet (11 m): the button says how far, it does not freeze someone else
    r = client.post(f"/api/game/{CODE}/catch_action", json={"action": "freeze"})
    assert r.status_code == 400 and "8 m" in r.get_json()["error"]
    # the same button grabs the frozen runner once you are close
    move(appmodule, gid, hid, LAT + 0.00007, LON)
    move(appmodule, gid, rids[1], LAT + 0.0001, LON)
    r = client.post(f"/api/game/{CODE}/catch_action", json={"action": "freeze"}).get_json()
    assert r["caught"] and caught(appmodule, gid, rids[1])


def test_mission_spots_stay_inside_a_small_field(appmodule):
    gid, hid, rids = setup_game(appmodule)
    with appmodule.app.app_context():
        g = appmodule.db.session.get(appmodule.Game, gid)
        pf = {"enabled": True, "color": "storm", "points": zone.regular_polygon(LAT, LON, 60, 12), "forbidden": []}
        appmodule.SiteSetting.set(appmodule._playfield_key(gid), json.dumps(pf))
        for _ in range(20):
            lat, lng = appmodule._spot_from(g, LAT, LON, 150, 250)               # far bigger than the field
            assert zone.point_in_polygon(lat, lng, pf["points"])


def test_tracker_dart_shows_the_runner_live_to_all_hunters(appmodule, client, monkeypatch):
    assert any(c["id"] == "trackerschutter" for c in appmodule.class_loadouts_for("hunter"))
    assert all(c["id"] != "trackerschutter" for c in appmodule.class_loadouts_for("runner"))
    gid, hid, rids = setup_game(appmodule, {"classes_enabled": True, "classes_hunter": ["trackerschutter"],
                                            "classes_runner": ["lokvogel"]}, started_min_ago=10)
    monkeypatch.setattr(appmodule.hub, "broadcast", lambda *a, **k: None)
    with appmodule.app.app_context():
        appmodule.assign_game_classes(appmodule.db.session.get(appmodule.Game, gid))
    login(client, hid)
    seen = next(p for p in client.get(f"/api/game/{CODE}/state").get_json()["players"] if p["id"] == rids[0])
    move(appmodule, gid, rids[0], LAT + 0.003, LON)                           # runner walked away: hunters still see the old spot
    r = client.post(f"/api/game/{CODE}/class_power", json={})
    assert r.status_code == 400 and "25 m" in r.get_json()["error"]
    with appmodule.app.app_context():                                          # the dart was not spent
        assert appmodule.class_cooldown_remaining(appmodule.db.session.get(appmodule.Game, gid), hid) == 0
    move(appmodule, gid, rids[0], LAT + 0.0002, LON)                          # ~22 m: in range
    r = client.post(f"/api/game/{CODE}/class_power", json={}).get_json()
    assert r["type"] == "tracker" and r["runner_id"] == rids[0]
    move(appmodule, gid, rids[0], LAT + 0.0011, LON)                          # runs off: hunters follow live
    p = next(p for p in client.get(f"/api/game/{CODE}/state").get_json()["players"] if p["id"] == rids[0])
    assert p["tracked_left"] > 80 and abs(p["lat"] - (LAT + 0.0011)) < 1e-9 and (p["lat"], p["lon"]) != (seen["lat"], seen["lon"])
    login(client, rids[0])
    assert client.get(f"/api/game/{CODE}/state").get_json()["my_tracked"] > 80

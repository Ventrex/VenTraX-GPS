"""Life bar outside the playfield: drains, refills slowly, one warning, and 0% means out."""
import json
from datetime import datetime

import zone
from conftest import make_user

LAT, LON = 52.1, 5.38


def setup(appmodule, client, role="runner"):
    uid = make_user(appmodule, username="leven", email="l@example.com")
    other = make_user(appmodule, username="ander", email="a@example.com")
    with appmodule.app.app_context():
        g = appmodule.Game(name="L", code="LIV123", creator_id=uid, status="active", headstart_minutes=0,
                           duration_minutes=60, started_at=datetime.utcnow())
        appmodule.db.session.add(g); appmodule.db.session.commit()
        for u, r in ((uid, role), (other, "hunter" if role == "runner" else "runner")):
            appmodule.db.session.add(appmodule.GamePlayer(game_id=g.id, user_id=u, role=r, gps_enabled=True, last_seen=datetime.utcnow()))
        appmodule.SiteSetting.set(appmodule._playfield_key(g.id), json.dumps(
            {"enabled": True, "color": "storm", "points": zone.regular_polygon(LAT, LON, 200, 12), "forbidden": []}))
        appmodule.db.session.commit()
    with client.session_transaction() as s:
        s["_user_id"] = str(uid); s["_fresh"] = True
    return uid


def post(client, lat, lon):
    return client.post("/api/game/LIV123/location", json={"lat": lat, "lon": lon, "accuracy": 5})


def test_life_drains_outside_refills_slowly_and_warns_once(appmodule, client, monkeypatch):
    setup(appmodule, client)
    t = [1000.0]
    monkeypatch.setattr(appmodule, "_now_ts", lambda: t[0])
    outside = (LAT + 0.01, LON)
    assert post(client, LAT, LON).get_json()["zone_pressure"]["pct"] == 0
    msgs = []
    for _ in range(3):
        t[0] += 5
        d = post(client, *outside).get_json()
        msgs.append(len(d["hazard_messages"]))
    assert msgs == [1, 0, 0]                                   # one warning, not one per GPS update
    assert 40 < d["zone_pressure"]["pct"] < 60 and not d["eliminated"]
    t[0] += 10
    inside = post(client, LAT, LON).get_json()["zone_pressure"]["pct"]
    t[0] += 5
    later = post(client, LAT, LON).get_json()["zone_pressure"]["pct"]
    assert 0 < later < inside < 100                            # refills gradually, not at once


def test_empty_life_bar_means_out(appmodule, client, monkeypatch):
    uid = setup(appmodule, client)
    t = [2000.0]
    monkeypatch.setattr(appmodule, "_now_ts", lambda: t[0])
    outside = (LAT + 0.01, LON)
    d = None
    for _ in range(8):
        t[0] += 5
        d = post(client, *outside).get_json()
        if d["eliminated"]:
            break
    assert d["eliminated"] and d["zone_pressure"]["pct"] == 100
    with appmodule.app.app_context():
        assert appmodule.GamePlayer.query.filter_by(user_id=uid).first().is_caught


def test_a_new_game_never_inherits_state_of_a_deleted_game_with_the_same_id(appmodule, client):
    uid = setup(appmodule, client)
    with appmodule.app.app_context():
        g = appmodule.Game.query.filter_by(code="LIV123").first()
        gid = g.id
        appmodule.SiteSetting.set(appmodule._zone_state_key(gid), json.dumps({str(uid): {"seconds": 12, "outside": True}}))
        appmodule.db.session.delete(g); appmodule.db.session.commit()
        assert appmodule.SiteSetting.get(appmodule._zone_state_key(gid)) is None
        # and a stale leftover is also cleaned when a game is created
        appmodule.SiteSetting.set(appmodule._zone_state_key(gid), "{}")
        appmodule.purge_game_state(gid); appmodule.db.session.commit()
        assert appmodule.SiteSetting.get(appmodule._zone_state_key(gid)) is None

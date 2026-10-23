"""Play field v2: forbidden areas, saving every game's field, sharing by code."""
import json

import bots
from conftest import make_user

LAT, LON = 52.1000, 5.3800
KX = 111320 * 0.6141


def ll(north_m, east_m):
    return LAT + north_m / 111320, LON + east_m / KX


def field(forbidden=None):
    pts = [ll(-300, -300), ll(-300, 300), ll(300, 300), ll(300, -300)]
    return {"enabled": True, "color": "storm", "points": [{"lat": a, "lng": b} for a, b in pts],
            "forbidden": forbidden or []}


def circle(n, e, r):
    a, b = ll(n, e)
    return {"type": "circle", "lat": a, "lng": b, "radius": r}


def rail(n, e0, e1, width=12, gap=None):
    a, b = ll(n, e0); c, d = ll(n, e1)
    return {"type": "line", "points": [{"lat": a, "lng": b}, {"lat": c, "lng": d}], "width": width}


def make_game(appmodule, pf):
    uid = make_user(appmodule, username="veld", email="veld@example.com")
    with appmodule.app.app_context():
        g = appmodule.Game(name="Veld", code="FLD123", creator_id=uid, status="active")
        appmodule.db.session.add(g); appmodule.db.session.commit()
        appmodule.SiteSetting.set(appmodule._playfield_key(g.id), json.dumps(pf))
        return g.id, uid


def test_forbidden_shapes_are_cleaned_and_limited(appmodule):
    out = appmodule.normalize_forbidden([
        {"type": "circle", "lat": 52.1, "lng": 5.38, "radius": 9999},       # radius capped
        {"type": "circle", "lat": 999, "lng": 5.38, "radius": 30},          # impossible coordinate
        {"type": "line", "points": [{"lat": 52.1, "lng": 5.3}], "width": 10},   # a line needs 2 points
        {"type": "line", "points": [{"lat": 52.1, "lng": 5.3}, {"lat": 52.1, "lng": 5.31}], "width": 1},
        {"type": "star"}, "junk", None,
    ])
    assert [o["type"] for o in out] == ["circle", "line"]
    assert out[0]["radius"] == 500 and out[1]["width"] == 6
    assert len(appmodule.normalize_forbidden([circle(0, 0, 20)] * 100)) == 30


def test_mast_and_railway_are_forbidden_but_the_tunnel_gap_is_not(appmodule):
    pf = field([circle(100, 100, 40),
                rail(-150, -300, -20), rail(-150, 20, 300)])      # gap between east -20 and +20 = the tunnel
    gid, _ = make_game(appmodule, pf)
    with appmodule.app.app_context():
        g = appmodule.db.session.get(appmodule.Game, gid)
        assert appmodule.playfield_status(g, *ll(0, 0)) == "inside"
        assert appmodule.playfield_status(g, *ll(100, 100)) == "forbidden"          # on the mast
        assert appmodule.playfield_status(g, *ll(100, 130)) == "forbidden"          # still within 40 m
        assert appmodule.playfield_status(g, *ll(100, 160)) == "inside"             # 60 m away is fine
        assert appmodule.playfield_status(g, *ll(-150, -150)) == "forbidden"        # on the rails
        assert appmodule.playfield_status(g, *ll(-150, 0)) == "inside"              # through the tunnel gap
        assert appmodule.playfield_status(g, *ll(-150, 100)) == "forbidden"
        assert appmodule.playfield_status(g, *ll(-143, 100)) == "inside"            # 7 m from the rails, corridor is 12 m
        assert appmodule.playfield_status(g, *ll(-400, 0)) == "outside"
        # forbidden counts as past the 5 m GPS margin, so the pressure bar starts
        assert appmodule.playfield_outside_distance_m(g, *ll(100, 100)) > 5
        assert appmodule.playfield_outside_distance_m(g, *ll(0, 0)) == 0


def test_forbidden_survives_saving_and_reading_back(appmodule):
    gid, uid = make_game(appmodule, field([circle(10, 10, 25)]))
    with appmodule.app.app_context():
        g = appmodule.db.session.get(appmodule.Game, gid)
        back = appmodule.get_playfield(g)
        assert back["forbidden"][0]["radius"] == 25
        saved = appmodule.normalize_playfield(json.dumps(field([circle(10, 10, 25)])))
        assert saved["forbidden"][0]["type"] == "circle"


def test_bots_never_walk_through_forbidden_areas(appmodule):
    bbox = bots.bbox_of([ll(-300, -300), ll(300, 300)], margin_m=0)
    pf = [ll(-300, -300), ll(-300, 300), ll(300, 300), ll(300, -300)]
    t = bots.build_terrain([], bbox, pf, forbidden=[circle(0, 0, 60), rail(100, -300, 300)])
    assert t.at(*t.to_xy(*ll(0, 0))) == bots.BLOCKED and t.at(*t.to_xy(*ll(100, 50))) == bots.BLOCKED
    assert bots.route_latlon(t, ll(-200, 0), ll(200, 0)) is None            # the rail corridor cannot be crossed
    t2 = bots.build_terrain([], bbox, pf, forbidden=[rail(100, -300, -20), rail(100, 20, 300)])
    route = bots.route_latlon(t2, ll(-200, 0), ll(200, 0))
    assert route and all(t2.at(*t2.to_xy(a, b)) != bots.BLOCKED for a, b, _ in route)   # only through the gap


# ---- saving and sharing ---------------------------------------------------------------------
def login(client, appmodule, name="deler"):
    uid = make_user(appmodule, username=name, email=f"{name}@example.com")
    with client.session_transaction() as sess:
        sess["_user_id"] = str(uid); sess["_fresh"] = True
    return uid


def create_game_with_field(client, name="Parkspel", pf_name=""):
    return client.post("/new_game", data={
        "name": name, "role": "hunter", "duration": "60", "headstart": "5", "difficulty": "medium",
        "hunter_interval": "600", "runner_interval": "600", "target_duration": "300", "target_cooldown": "600",
        "max_offline": "300", "playfield_name": pf_name,
        "playfield_json": json.dumps({"color": "storm", "points": field()["points"], "forbidden": [circle(0, 0, 30)]})})


def test_every_games_field_is_saved_in_my_fields(appmodule, client):
    uid = login(client, appmodule)
    assert create_game_with_field(client).status_code == 302
    with appmodule.app.app_context():
        items = appmodule.get_profile_playfields_for_user(uid)
        assert [i["name"] for i in items] == ["Parkspel"]                       # named after the game
        assert items[0]["data"]["forbidden"][0]["radius"] == 30
        # a zone made for a game is NOT pushed to the public list any more
        assert appmodule.get_global_playfields() == []


def test_share_a_field_with_a_friend_by_code_and_link(appmodule, client):
    uid = login(client, appmodule)
    create_game_with_field(client, name="Mijn park", pf_name="Parkroute")
    with appmodule.app.app_context():
        pid = appmodule.get_profile_playfields_for_user(uid)[0]["id"]
    shared = client.post(f"/api/profile/playfield/{pid}/share").get_json()
    code = shared["code"]
    assert len(code) == 6 and code in shared["url"]
    assert client.post(f"/api/profile/playfield/{pid}/share").get_json()["code"] == code      # same code every time

    friend = appmodule.app.test_client()
    fid = make_user(appmodule, username="vriendin", email="vriendin@example.com")
    with friend.session_transaction() as sess:
        sess["_user_id"] = str(fid); sess["_fresh"] = True
    got = friend.get(f"/api/playfield/share/{code.lower()}").get_json()
    assert got["name"] == "Parkroute" and got["owner"] == "deler" and got["data"]["forbidden"][0]["type"] == "circle"
    assert friend.get("/api/playfield/share/NOPE99").status_code == 404
    page = friend.get(f"/new_game?zone={code}").get_data(as_text=True)
    assert "IMPORT_ZONE" in page and "Parkroute" in page
    assert appmodule.app.test_client().get(f"/api/playfield/share/{code}").status_code in (302, 401)   # login required

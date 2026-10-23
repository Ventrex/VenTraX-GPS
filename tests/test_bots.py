"""Tests for bots.py: terrain from OpenStreetMap data, routes, speeds and bot behaviour (no network)."""
import random

import bots
from bots import BLOCKED, NORMAL, BRUSH

LAT0, LON0 = 52.1000, 5.3800
KX = bots.M_LAT * 0.6141          # metres per degree longitude at ~52.1 N


def ll(north_m, east_m):
    """Coordinate `north_m` / `east_m` metres from the test origin."""
    return (LAT0 + north_m / bots.M_LAT, LON0 + east_m / KX)


def way(points, **tags):
    return {"type": "way", "tags": tags, "geometry": [{"lat": a, "lon": b} for a, b in points]}


def rect(n0, e0, n1, e1):
    pts = [ll(n0, e0), ll(n0, e1), ll(n1, e1), ll(n1, e0), ll(n0, e0)]
    return pts


BBOX = bots.bbox_of([ll(0, 0), ll(300, 300)], margin_m=0)


def terrain(elements, playfield=None):
    return bots.build_terrain(elements, BBOX, playfield)


def cell(t, north_m, east_m):
    return t.at(*t.to_xy(*ll(north_m, east_m)))


# ---- terrain --------------------------------------------------------------------------------
def test_water_and_buildings_are_blocked_woods_are_brush():
    t = terrain([
        way(rect(100, 20, 140, 280), natural="water"),
        way(rect(200, 20, 230, 60), building="yes"),
        way(rect(20, 100, 80, 200), natural="wood"),
    ])
    assert cell(t, 120, 150) == BLOCKED
    assert cell(t, 215, 40) == BLOCKED
    assert cell(t, 50, 150) == BRUSH
    assert cell(t, 250, 250) == NORMAL


def test_bridge_footpath_is_walkable_over_water_and_brush_paths_stay_normal():
    t = terrain([
        way(rect(100, 0, 140, 300), natural="water"),
        way([ll(90, 150), ll(150, 150)], highway="footway", bridge="yes"),
        way(rect(20, 100, 80, 200), natural="wood"),
        way([ll(30, 150), ll(70, 150)], highway="path"),
    ])
    assert cell(t, 120, 150) == NORMAL          # on the bridge
    assert cell(t, 120, 60) == BLOCKED          # next to it is still water
    assert cell(t, 50, 150) == NORMAL           # path through the woods
    assert cell(t, 50, 120) == BRUSH


def test_rails_streams_and_motorways_block_but_tunnels_do_not():
    t = terrain([
        way([ll(60, 0), ll(60, 300)], railway="rail"),
        way([ll(120, 0), ll(120, 300)], waterway="stream"),
        way([ll(180, 0), ll(180, 300)], highway="motorway"),
        way([ll(240, 0), ll(240, 300)], railway="rail", tunnel="yes"),
    ])
    assert cell(t, 60, 100) == BLOCKED and cell(t, 120, 100) == BLOCKED and cell(t, 180, 100) == BLOCKED
    assert cell(t, 240, 100) == NORMAL


def test_multipolygon_with_island_and_split_outer_ring():
    outer_a = {"role": "outer", "geometry": [{"lat": a, "lon": b} for a, b in [ll(50, 50), ll(50, 250), ll(150, 250)]]}
    outer_b = {"role": "outer", "geometry": [{"lat": a, "lon": b} for a, b in [ll(150, 250), ll(150, 50), ll(50, 50)]]}
    island = {"role": "inner", "geometry": [{"lat": a, "lon": b} for a, b in rect(90, 130, 110, 170)]}
    t = terrain([{"type": "relation", "tags": {"type": "multipolygon", "natural": "water"},
                  "members": [outer_a, outer_b, island]}])
    assert cell(t, 70, 80) == BLOCKED
    assert cell(t, 100, 150) == NORMAL          # the island is dry land


def test_playfield_blocks_everything_outside():
    pf = [ll(50, 50), ll(50, 250), ll(250, 250), ll(250, 50)]
    t = terrain([], playfield=pf)
    assert cell(t, 150, 150) == NORMAL and cell(t, 10, 10) == BLOCKED and cell(t, 290, 150) == BLOCKED


def test_missing_map_data_falls_back_to_open_ground_and_says_so():
    def boom(*a, **k):
        raise OSError("no network")
    t = bots.load_terrain(BBOX, "http://invalid", http_post=boom)
    assert t.degraded and cell(t, 150, 150) == NORMAL


# ---- routes ---------------------------------------------------------------------------------
def river_with_bridge():
    return terrain([
        way(rect(120, 0, 150, 300), natural="water"),
        way([ll(100, 280), ll(170, 280)], highway="footway", bridge="yes"),
    ])


def test_route_goes_over_the_bridge_not_through_the_water():
    t = river_with_bridge()
    route = bots.route_latlon(t, ll(20, 20), ll(280, 20))
    assert route, "a route exists via the bridge"
    for lat, lon, _ in route:
        assert t.at(*t.to_xy(lat, lon)) != BLOCKED
    assert max(lon for _, lon, _ in route) > ll(0, 250)[1], "had to detour to the bridge at the east side"


def test_no_route_when_there_is_no_crossing():
    t = terrain([way(rect(120, 0, 150, 300), natural="water")])
    assert bots.route_latlon(t, ll(20, 20), ll(280, 20)) is None


def test_route_cannot_squeeze_diagonally_through_a_thin_wall():
    t = terrain([way([ll(0, 0), ll(300, 300)], railway="rail")])     # a diagonal line of blocked cells
    assert bots.route_latlon(t, ll(250, 20), ll(20, 250)) is None


def test_route_avoids_bushes_when_a_clear_way_around_is_not_much_longer():
    t = terrain([way(rect(100, 100, 200, 140), natural="scrub")])
    route = bots.route_latlon(t, ll(150, 40), ll(150, 220))
    assert all(t.at(*t.to_xy(a, b)) != BRUSH for a, b, _ in route[:3])
    assert sum(1 for _, _, f in route if f < 1) <= 2          # went around instead of through


def test_bushes_halve_the_speed():
    t = terrain([way(rect(0, 0, 300, 300), natural="scrub")])
    bot = bots.Bot(1, "runner", *ll(150, 20), difficulty="medium")
    bot.set_route(bots.route_latlon(t, ll(150, 20), ll(150, 280)))
    bot.walk(10)
    assert abs(bot.moved_m - 7.0) < 0.5            # 1.4 m/s * 0.5 * 10 s

    open_t = terrain([])
    bot2 = bots.Bot(2, "runner", *ll(150, 20), difficulty="medium")
    bot2.set_route(bots.route_latlon(open_t, ll(150, 20), ll(150, 280)))
    bot2.walk(10)
    assert abs(bot2.moved_m - 14.0) < 0.5


def test_difficulty_sets_walking_speed():
    assert bots.SPEEDS["easy"] < bots.SPEEDS["medium"] < bots.SPEEDS["hard"]
    assert bots.SPEEDS["hard"] * 3.6 < 9          # brisk walking, never running
    t = terrain([])
    moved = {}
    for d in ("easy", "medium", "hard"):
        b = bots.Bot(1, "runner", *ll(150, 20), difficulty=d)
        b.set_route(bots.route_latlon(t, ll(150, 20), ll(150, 280)))
        b.walk(20)
        moved[d] = b.moved_m
    assert moved["easy"] < moved["medium"] < moved["hard"]


def test_start_inside_a_building_is_snapped_to_walkable_ground():
    t = terrain([way(rect(100, 100, 140, 140), building="yes")])
    route = bots.route_latlon(t, ll(120, 120), ll(250, 250))
    assert route and t.at(*t.to_xy(route[0][0], route[0][1])) != BLOCKED


# ---- brains ---------------------------------------------------------------------------------
def test_runner_flees_away_from_the_hunter():
    t = terrain([])
    rng = random.Random(1)
    runner = bots.Bot(1, "runner", *ll(150, 150), seed=1)
    hunter = ll(150, 100)
    start_d = bots.haversine(runner.lat, runner.lon, *hunter)
    assert bots.plan(t, runner, [hunter], now=0, rng=rng)
    runner.walk(30)
    assert bots.haversine(runner.lat, runner.lon, *hunter) > start_d + 10


def test_hunter_closes_in_on_the_runner():
    t = terrain([])
    hunter = bots.Bot(2, "hunter", *ll(20, 20), difficulty="hard", seed=2)
    prey = ll(250, 250)
    before = bots.haversine(hunter.lat, hunter.lon, *prey)
    bots.plan(t, hunter, [prey], now=0)
    hunter.walk(60)
    assert bots.haversine(hunter.lat, hunter.lon, *prey) < before - 60


def test_bots_wait_with_replanning_until_it_is_time():
    t = terrain([])
    hunter = bots.Bot(2, "hunter", *ll(20, 20), seed=2)
    assert bots.plan(t, hunter, [ll(250, 250)], now=0)
    assert not bots.plan(t, hunter, [ll(250, 250)], now=5)
    assert bots.plan(t, hunter, [ll(250, 250)], now=13)


def test_overpass_result_is_cached_on_disk(tmp_path):
    calls = []

    class Resp:
        def raise_for_status(self): pass
        def json(self): return {"elements": [way(rect(10, 10, 20, 20), building="yes")]}

    def post(url, **kw):
        calls.append(url); return Resp()

    a = bots.fetch_elements(BBOX, "http://o", cache_dir=str(tmp_path), http_post=post)
    b = bots.fetch_elements(BBOX, "http://o", cache_dir=str(tmp_path), http_post=post)
    assert a == b and len(calls) == 1


def test_hunter_bot_reaches_a_standing_runner_within_tagging_range():
    t = terrain([way(rect(100, 100, 140, 200), building="yes")])        # something to walk around
    hunter = bots.Bot(2, "hunter", *ll(20, 20), difficulty="hard", seed=3)
    prey = ll(250, 250)
    now = 0.0
    for _ in range(400):                                                # 400 ticks of 2 s
        bots.plan(t, hunter, [prey], now)
        hunter.walk(2.0)
        now += 2.0
        if bots.haversine(hunter.lat, hunter.lon, *prey) <= 6:
            break
    assert bots.haversine(hunter.lat, hunter.lon, *prey) <= 6

"""Game report: routes on a street map. Sounds: every game event has a (built-in) sound."""
import io
import os

from PIL import Image


class FakeResp:
    def __init__(self, content, status=200):
        self.content = content
        self.status_code = status


def tile_png(color=(200, 170, 120)):
    buf = io.BytesIO()
    Image.new("RGB", (256, 256), color).save(buf, format="PNG")
    return buf.getvalue()


ROUTE = [(52.1000, 5.3800), (52.1010, 5.3815), (52.1022, 5.3820), (52.1030, 5.3840)]


def test_route_is_drawn_on_map_tiles_and_tiles_are_cached(appmodule, monkeypatch, tmp_path):
    monkeypatch.setattr(appmodule, "ROUTE_TILE_DIR", str(tmp_path / "tiles"))
    calls = []
    monkeypatch.setattr(appmodule.http_requests, "get", lambda url, **k: calls.append(url) or FakeResp(tile_png()))
    png = appmodule.render_route_sketch(ROUTE, size=(480, 480))
    img = Image.open(io.BytesIO(png)).convert("RGB")
    assert img.size == (480, 480)
    corner = img.getpixel((5, 5))
    assert corner != (241, 245, 249)                                    # a map, not the plain background
    assert calls and all("/tile/" in u for u in calls)
    zooms = {u.split("/tile/")[1].split("/")[0] for u in calls}
    assert len(zooms) == 1 and 15 <= int(zooms.pop()) <= 18             # zoomed in on a walk of a few hundred metres
    n = len(calls)
    appmodule.render_route_sketch(ROUTE, size=(480, 480))
    assert len(calls) == n                                              # second time: from the cache


def test_without_internet_the_route_is_still_drawn(appmodule, monkeypatch, tmp_path):
    monkeypatch.setattr(appmodule, "ROUTE_TILE_DIR", str(tmp_path / "tiles"))
    calls = []

    def boom(url, **k):
        calls.append(url)
        raise OSError("no network")
    monkeypatch.setattr(appmodule.http_requests, "get", boom)
    png = appmodule.render_route_sketch(ROUTE, size=(360, 360))
    img = Image.open(io.BytesIO(png)).convert("RGB")
    assert img.getpixel((3, 3)) == (241, 245, 249)
    assert len(calls) <= 3                                              # gives up quickly, the e-mail is not held up


def test_all_routes_together_with_the_field(appmodule, monkeypatch, tmp_path):
    monkeypatch.setattr(appmodule, "ROUTE_TILE_DIR", str(tmp_path / "tiles"))
    monkeypatch.setattr(appmodule.http_requests, "get", lambda url, **k: FakeResp(tile_png()))
    field = {"points": [{"lat": 52.099, "lng": 5.379}, {"lat": 52.104, "lng": 5.379}, {"lat": 52.104, "lng": 5.386}]}
    png = appmodule.render_route_sketch(None, size=(640, 480), playfield=field, routes=[
        {"points": ROUTE, "color": appmodule.ROUTE_COLORS["hunter"]},
        {"points": [(52.1005, 5.3830), (52.1015, 5.3850)], "color": appmodule.ROUTE_COLORS["runner"]},
    ])
    assert Image.open(io.BytesIO(png)).size == (640, 480)
    assert appmodule.render_route_sketch(None, routes=[{"points": [(52.1, 5.38)]}]) is None   # one point: no route


def test_every_game_event_has_a_sound_slot_and_a_built_in_sound(appmodule):
    keys = set(appmodule.SOUND_EVENT_KEYS)
    for ev in ("zone_out", "zone_back", "zone_shrink", "location_reveal", "freeze", "tracked", "item",
               "mission_fail", "shelter", "player_left"):
        assert ev in keys
    js = open(os.path.join(os.path.dirname(appmodule.__file__), "static", "js", "vxsound.js"), encoding="utf-8").read()
    classic = js[js.index("    classic: {"):js.index("function synthFor")]
    for ev in keys - {"site_music", "ambient"}:
        assert f"      {ev}: function" in classic, ev                 # never silent when no clip is uploaded
    assert "OPTIONAL = {site_music: 1, ambient: 1}" in js

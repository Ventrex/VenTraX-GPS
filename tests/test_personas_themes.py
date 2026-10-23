"""Seasonal themes, per-theme pictures and lobby personas (characters)."""
import io

from conftest import make_user
from test_themes_pages import login


def png_bytes():
    from PIL import Image
    buf = io.BytesIO(); Image.new("RGB", (20, 20), "red").save(buf, "PNG"); buf.seek(0)
    return buf


def test_seasonal_themes_are_seeded_once_and_copyable(appmodule):
    with appmodule.app.app_context():
        slugs = {t.slug for t in appmodule.SoundTheme.query.all()}
        assert {"pasen", "sinterklaas", "kerst", "oudennieuw", "koningsdag", "zomer", "neon"} <= slugs
        kerst = appmodule.SoundTheme.query.filter_by(slug="kerst").first()
        assert kerst.accent and kerst.skin == "classic"
        appmodule.db.session.delete(kerst); appmodule.db.session.commit()
        appmodule.init_db()                                   # a deleted theme stays deleted
        assert appmodule.SoundTheme.query.filter_by(slug="kerst").first() is None


def test_picture_per_theme_wins_over_general(appmodule, client):
    login(client, appmodule)
    with appmodule.app.app_context():
        halloween = appmodule.SoundTheme.query.filter_by(slug="halloween").first().id
        default = appmodule.get_default_sound_theme().id
    r = client.post("/admin/images/img_role_hunter", data={"file": (png_bytes(), "a.png")}, content_type="multipart/form-data")
    general = r.get_json()["url"]
    r = client.post(f"/admin/images/img_role_hunter?theme={halloween}", data={"file": (png_bytes(), "b.png")}, content_type="multipart/form-data")
    own = r.get_json()["url"]
    assert general != own
    with appmodule.app.app_context():
        assert appmodule.site_image("img_role_hunter", halloween) == own
        assert appmodule.site_image("img_role_hunter", default) == general      # themes without their own use the general one
    assert client.get(f"/admin/images?theme={halloween}").status_code == 200
    client.post(f"/admin/images/img_role_hunter/clear?theme={halloween}")
    with appmodule.app.app_context():
        assert appmodule.site_image("img_role_hunter", halloween) == general


def lobby_game(appmodule, theme_slug="halloween"):
    uid = make_user(appmodule, username="spel", email="spel@example.com")
    with appmodule.app.app_context():
        th = appmodule.SoundTheme.query.filter_by(slug=theme_slug).first()
        g = appmodule.Game(name="P", code="PRS123", creator_id=uid, status="lobby")
        appmodule.db.session.add(g); appmodule.db.session.commit()
        appmodule.db.session.add(appmodule.GamePlayer(game_id=g.id, user_id=uid, role="hunter", codename="x"))
        appmodule.db.session.commit()
        return g.id, uid, th.id


def test_players_pick_a_persona_for_their_side(appmodule, client, monkeypatch):
    gid, uid, tid = lobby_game(appmodule)
    monkeypatch.setattr(appmodule, "get_game_sound_theme", lambda game: appmodule.db.session.get(appmodule.SoundTheme, tid))
    with client.session_transaction() as s:
        s["_user_id"] = str(uid); s["_fresh"] = True
    d = client.get("/api/game/PRS123/personas").get_json()
    assert d["kind"] == "good"                                          # hunters pick from the good characters (default)
    assert len(d["personas"]) == 10 and {p["gender"] for p in d["personas"]} == {"guy", "girl"}
    assert sum(p["gender"] == "guy" for p in d["personas"]) == 5 and sum(p["gender"] == "girl" for p in d["personas"]) == 5
    names = {p["name"]: p for p in d["personas"]}
    assert "Sidney Prescott" in names and "Ghostface" not in names
    r = client.post("/api/game/PRS123/persona", json={"id": names["Sidney Prescott"]["id"]})
    assert r.get_json()["persona"]["name"] == "Sidney Prescott"
    assert client.get("/api/game/PRS123/lobby_state").get_json()["players"][0]["persona"]["name"] == "Sidney Prescott"
    with appmodule.app.app_context():
        bad = appmodule.ThemePersona.query.filter_by(name="Ghostface").first().id
    assert client.post("/api/game/PRS123/persona", json={"id": bad}).status_code == 400   # a bad character, hunter player
    client.post("/api/game/PRS123/switch_role", json={"role": "runner"})
    with appmodule.app.app_context():
        assert appmodule.GamePlayer.query.first().persona_id is None   # role change clears the persona
    d = client.get("/api/game/PRS123/personas").get_json()
    assert d["kind"] == "bad" and "Ghostface" in {p["name"] for p in d["personas"]}          # runners pick from the bad ones
    # the maker can swap who picks from whom
    client.post("/admin/personas/map", data={"theme_id": tid, "hunter": "bad"})


def test_admin_manages_personas(appmodule, client):
    login(client, appmodule)
    with appmodule.app.app_context():
        tid = appmodule.SoundTheme.query.filter_by(slug="kerst").first().id
    assert client.get(f"/admin/personas?theme={tid}").status_code == 200
    r = client.post("/admin/personas/save", data={"theme_id": tid, "name": "Kerstman", "kind": "good", "gender": "guy", "icon": "fa-tree",
                                                  "image": (png_bytes(), "k.png")}, content_type="multipart/form-data")
    assert r.status_code == 302
    with appmodule.app.app_context():
        p = appmodule.ThemePersona.query.filter_by(name="Kerstman").first()
        assert p.kind == "good" and p.gender == "guy" and p.image and p.icon == "fa-tree"
        pid = p.id
    client.post(f"/admin/personas/{pid}/delete")
    with appmodule.app.app_context():
        assert appmodule.ThemePersona.query.filter_by(name="Kerstman").first() is None


def test_classes_are_chosen_per_side_and_each_side_keeps_at_least_one(appmodule, client):
    uid = make_user(appmodule, username="cl", email="cl@example.com")
    other = make_user(appmodule, username="cl2", email="cl2@example.com")
    with appmodule.app.app_context():
        g = appmodule.Game(name="C", code="CLS123", creator_id=uid, status="lobby")
        appmodule.db.session.add(g); appmodule.db.session.commit()
        appmodule.db.session.add(appmodule.GamePlayer(game_id=g.id, user_id=uid, role="hunter"))
        appmodule.db.session.add(appmodule.GamePlayer(game_id=g.id, user_id=other, role="runner"))
        appmodule.db.session.commit()
        from werkzeug.datastructures import MultiDict
        form = MultiDict([("classes_enabled", "on"), ("classes_hunter", "codekraker"), ("classes_hunter", "glitcher")])   # runner side left empty
        ex = appmodule.save_game_extras(g, form)
        assert ex["classes_hunter"] == ["codekraker", "glitcher"]
        assert len(ex["classes_runner"]) == len(appmodule.CLASS_LOADOUTS)            # empty side falls back to all
        assigned = appmodule.assign_game_classes(g)
        assert assigned[str(uid)]["id"] in ("codekraker", "glitcher")
        assert assigned[str(other)]["id"] in {c["id"] for c in appmodule.CLASS_LOADOUTS}


def test_picture_slots_for_field_modes_colours_and_theme_cards(appmodule, client):
    login(client, appmodule)
    with appmodule.app.app_context():
        tid = appmodule.SoundTheme.query.filter_by(slug="kerst").first().id
    for key in ("img_pf_field", "img_pf_circle", "img_pf_line", "img_pfcolor_storm", "img_style_custom", f"img_soundtheme_{tid}"):
        r = client.post(f"/admin/images/{key}", data={"file": (png_bytes(), "a.png")}, content_type="multipart/form-data")
        assert r.get_json().get("success"), key
    assert client.post("/admin/images/img_unknown", data={}).status_code == 404
    html = client.get("/new_game").get_data(as_text=True)
    assert 'class="pf-ico"' in html and "img_pfcolor" not in html


def test_halloween_has_five_of_each_group_and_pasting_lists_works(appmodule, client):
    login(client, appmodule)
    with appmodule.app.app_context():
        tid = appmodule.SoundTheme.query.filter_by(slug="halloween").first().id
        rows = [appmodule.persona_dict(p) for p in appmodule.ThemePersona.query.filter_by(theme_id=tid)]
    groups = {}
    for r in rows:
        groups[(r["kind"], r["gender"])] = groups.get((r["kind"], r["gender"]), 0) + 1
    assert groups == {("good", "guy"): 5, ("bad", "guy"): 5, ("good", "girl"): 5, ("bad", "girl"): 5}
    text = "Pennywise | slecht | jongen | IT\nPoltergeist heks | slecht | meisje\nGhostface | slecht | jongen | Scream"
    client.post("/admin/personas/bulk", data={"theme_id": tid, "text": text})
    with appmodule.app.app_context():
        got = {p.name: (persona_kind, p.gender, p.blurb) for p, persona_kind in
               [(p, appmodule.persona_kind(p)) for p in appmodule.ThemePersona.query.filter_by(theme_id=tid)]}
        assert got["Pennywise"] == ("bad", "guy", "IT") and got["Poltergeist heks"][:2] == ("bad", "girl")
        assert sum(1 for p in appmodule.ThemePersona.query.filter_by(theme_id=tid, name="Ghostface")) == 1      # no duplicate
    old_table = "| Film | Slecht | Goed |\n|---|---|---|\n| **Poltergeist** | The Beast | Diane Freeling |"
    assert [(r["name"], r["kind"]) for r in appmodule.parse_persona_table(old_table)] == [("The Beast", "bad"), ("Diane Freeling", "good")]

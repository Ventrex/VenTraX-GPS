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


def test_codenames_come_from_the_theme_characters(appmodule, client):
    uid = make_user(appmodule, username="cn", email="cn@example.com")
    with appmodule.app.app_context():
        hw = appmodule.SoundTheme.query.filter_by(slug="halloween").first()
        g = appmodule.Game(name="CN", code="CDN123", creator_id=uid, status="lobby")
        appmodule.db.session.add(g); appmodule.db.session.commit()
        appmodule.SiteSetting.set(appmodule._extras_key(g.id), '{"sound_theme": "%d"}' % hw.id)
        good = {p.name for p in appmodule.ThemePersona.query.filter_by(theme_id=hw.id) if appmodule.persona_kind(p) == "good"}
        bad = {p.name for p in appmodule.ThemePersona.query.filter_by(theme_id=hw.id) if appmodule.persona_kind(p) == "bad"}
        assert len(good) == 10 and len(bad) == 10
        assert appmodule.assign_codename("hunter", g.id) in good                    # hunters: from the goeden (default map)
        assert appmodule.assign_codename("runner", g.id) in bad
        names = {appmodule.assign_codename("hunter", g.id) for _ in range(30)}
        assert names <= good and len(names) > 1                                        # random, from the scary list
        appmodule.db.session.add(appmodule.GamePlayer(game_id=g.id, user_id=uid, role="runner", codename="Freddy Krueger"))
        appmodule.db.session.commit()
        gp = appmodule.GamePlayer.query.filter_by(game_id=g.id).first()
        assert appmodule.persona_of(gp)["name"] == "Freddy Krueger"                  # picture for the map comes from the name
        # a game without themed characters keeps the hero names (John Wick, Marvel ...)
        g.sound = None
        appmodule.SiteSetting.set(appmodule._extras_key(g.id), '')
        assert appmodule.assign_codename("hunter", g.id) in appmodule.CODENAMES_HUNTERS


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
        # empty side falls back to every class of that side (Lokvogel is runner-only, Trackerschutter hunter-only)
        assert ex["classes_runner"] == [c["id"] for c in appmodule.class_loadouts_for("runner")]
        assert "lokvogel" in ex["classes_runner"] and "trackerschutter" not in ex["classes_runner"]
        assigned = appmodule.assign_game_classes(g)
        assert assigned[str(uid)]["id"] in ("codekraker", "glitcher")
        assert assigned[str(other)]["id"] in {c["id"] for c in appmodule.class_loadouts_for("runner")}


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


def test_transparent_icons_stay_transparent_and_reach_the_game_page(appmodule, client):
    from PIL import Image
    login(client, appmodule)
    buf = io.BytesIO(); Image.new("RGBA", (30, 30), (255, 0, 0, 0)).save(buf, "PNG"); buf.seek(0)    # fully transparent
    r = client.post("/admin/images/img_loot_emp", data={"file": (buf, "emp.png")}, content_type="multipart/form-data").get_json()
    assert r["success"]
    with appmodule.app.app_context():
        path = appmodule.os.path.join(appmodule.app.config["BG_FOLDER"], r["url"].rsplit("/", 1)[1])
        im = Image.open(path)
        assert im.mode == "RGBA" and im.getpixel((5, 5))[3] == 0
        assert appmodule.game_icons()["loot_emp"] == r["url"]
    r2 = client.post("/admin/images/img_marker_hunter", data={"file": (png_bytes(), "h.png")}, content_type="multipart/form-data").get_json()
    assert r2["success"]


def test_theme_atmosphere_and_calm_switch_render(appmodule, client):
    with appmodule.app.app_context():
        for t in appmodule.SoundTheme.query.all():
            t.is_default = t.slug == "kerst"
        appmodule.db.session.commit()
    html = client.get("/login", follow_redirects=True).get_data(as_text=True)
    assert 'class="fx-layer"' in html and "fx-fall" in html and 'id="vxCalm"' in html
    with appmodule.app.app_context():
        for t in appmodule.SoundTheme.query.all():
            t.is_default = t.slug == "klassiek"
        appmodule.db.session.commit()
    assert 'class="fx-layer"' not in client.get("/login", follow_redirects=True).get_data(as_text=True)      # the classic theme stays calm


def test_new_game_with_halloween_gives_the_creator_a_scary_name(appmodule, client):
    login(client, appmodule)
    with appmodule.app.app_context():
        hw = appmodule.SoundTheme.query.filter_by(slug="halloween").first().id
    base = {"name": "Eng", "role": "runner", "duration": "60", "headstart": "5", "difficulty": "medium", "hunter_interval": "600",
            "runner_interval": "600", "target_duration": "300", "target_cooldown": "600", "max_offline": "300", "sound_theme": str(hw)}
    assert client.post("/new_game", data=base).status_code == 302
    with appmodule.app.app_context():
        g = appmodule.Game.query.filter_by(name="Eng").first()
        gp = appmodule.GamePlayer.query.filter_by(game_id=g.id).first()
        bad = {p.name for p in appmodule.ThemePersona.query.filter_by(theme_id=hw) if appmodule.persona_kind(p) == "bad"}
        assert gp.codename in bad                                                  # runner = a scary character

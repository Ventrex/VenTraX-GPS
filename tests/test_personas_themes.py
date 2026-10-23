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


def test_players_pick_a_persona_for_their_role(appmodule, client, monkeypatch):
    gid, uid, tid = lobby_game(appmodule)
    monkeypatch.setattr(appmodule, "get_game_sound_theme", lambda game: appmodule.db.session.get(appmodule.SoundTheme, tid))
    with client.session_transaction() as s:
        s["_user_id"] = str(uid); s["_fresh"] = True
    d = client.get("/api/game/PRS123/personas").get_json()
    names = {p["name"]: p for p in d["personas"]}
    assert set(names) == {"Leatherface", "Ghostface"}                  # hunter personas only
    r = client.post("/api/game/PRS123/persona", json={"id": names["Ghostface"]["id"]})
    assert r.get_json()["persona"]["name"] == "Ghostface"
    assert client.get("/api/game/PRS123/lobby_state").get_json()["players"][0]["persona"]["name"] == "Ghostface"
    with appmodule.app.app_context():
        sid = appmodule.ThemePersona.query.filter_by(name="Sidney").first().id
    assert client.post("/api/game/PRS123/persona", json={"id": sid}).status_code == 400   # runner persona, hunter player
    client.post("/api/game/PRS123/switch_role", json={"role": "runner"})
    with appmodule.app.app_context():
        assert appmodule.GamePlayer.query.first().persona_id is None   # role change clears the persona


def test_admin_manages_personas(appmodule, client):
    login(client, appmodule)
    with appmodule.app.app_context():
        tid = appmodule.SoundTheme.query.filter_by(slug="kerst").first().id
    assert client.get(f"/admin/personas?theme={tid}").status_code == 200
    r = client.post("/admin/personas/save", data={"theme_id": tid, "name": "Kerstman", "role": "runner", "icon": "fa-tree",
                                                  "image": (png_bytes(), "k.png")}, content_type="multipart/form-data")
    assert r.status_code == 302
    with appmodule.app.app_context():
        p = appmodule.ThemePersona.query.filter_by(name="Kerstman").first()
        assert p.role == "runner" and p.image and p.icon == "fa-tree"
        pid = p.id
    client.post(f"/admin/personas/{pid}/delete")
    with appmodule.app.app_context():
        assert appmodule.ThemePersona.query.filter_by(name="Kerstman").first() is None

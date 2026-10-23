"""
Tests for the Halloween update: sound themes (admin portal + player API), editable
pages/texts, the image fallback and the PWA files. Run with: pytest tests/
"""
import io

from conftest import make_user


def login(client, appmodule, admin=True, username="boss"):
    uid = make_user(appmodule, username=username, email=f"{username}@example.com")
    with appmodule.app.app_context():
        user = appmodule.db.session.get(appmodule.User, uid)
        user.is_admin = admin
        appmodule.db.session.commit()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(uid)
        sess["_fresh"] = True
    return uid


def test_default_themes_are_seeded(appmodule):
    with appmodule.app.app_context():
        names = {t.slug: t for t in appmodule.SoundTheme.query.all()}
        assert names["halloween"].is_default and names["halloween"].skin == "halloween"
        assert "klassiek" in names


def test_sound_theme_payload_lists_uploaded_clips(appmodule):
    with appmodule.app.app_context():
        theme = appmodule.get_default_sound_theme()
        appmodule.db.session.add(appmodule.SoundClip(theme_id=theme.id, event="intro", filename="x.mp3", label="x", volume=70))
        appmodule.db.session.commit()
        payload = appmodule.sound_theme_payload(theme)
        assert payload["events"]["intro"][0]["url"] == "/audio/themes/x.mp3"
        assert payload["events"]["intro"][0]["volume"] == 70
        assert payload["skin"] == "halloween"


def test_every_event_is_unique_and_documented(appmodule):
    keys = [e[0] for e in appmodule.SOUND_EVENTS]
    assert len(keys) == len(set(keys))
    for needed in ("intro", "go", "end", "lootbox_open", "hunter_near", "zone_out",
                   "offline_start", "offline_end", "target_start", "target_end"):
        assert needed in keys


def test_admin_can_upload_and_delete_a_clip(appmodule, client):
    login(client, appmodule)
    with appmodule.app.app_context():
        tid = appmodule.get_default_sound_theme().id
    resp = client.post(f"/admin/sounds/theme/{tid}/upload",
                       data={"event": "intro", "file": (io.BytesIO(b"ID3fake-mp3-bytes"), "muziek.mp3")},
                       content_type="multipart/form-data")
    assert resp.status_code == 200, resp.data
    data = resp.get_json()
    assert data["success"] and data["url"].startswith("/audio/themes/")
    served = client.get(data["url"])
    assert served.status_code == 200
    assert "immutable" in served.headers["Cache-Control"]

    assert client.post(f"/admin/sounds/clip/{data['id']}/save", json={"volume": 40}).get_json()["volume"] == 40
    assert client.post(f"/admin/sounds/clip/{data['id']}/delete").get_json()["success"]
    assert client.get(data["url"]).status_code == 404


def test_upload_rejects_non_audio_and_unknown_events(appmodule, client):
    login(client, appmodule)
    with appmodule.app.app_context():
        tid = appmodule.get_default_sound_theme().id
    bad_ext = client.post(f"/admin/sounds/theme/{tid}/upload",
                          data={"event": "intro", "file": (io.BytesIO(b"<?php"), "evil.php")},
                          content_type="multipart/form-data")
    assert bad_ext.status_code == 400
    bad_event = client.post(f"/admin/sounds/theme/{tid}/upload",
                            data={"event": "../../etc", "file": (io.BytesIO(b"x"), "a.mp3")},
                            content_type="multipart/form-data")
    assert bad_event.status_code == 400


def test_non_admin_cannot_manage_sounds(appmodule, client):
    login(client, appmodule, admin=False, username="speler")
    with appmodule.app.app_context():
        tid = appmodule.get_default_sound_theme().id
    assert client.get("/admin/sounds").status_code in (302, 403)
    assert client.post(f"/admin/sounds/theme/{tid}/upload", data={}).status_code in (302, 403)


def test_new_theme_default_and_delete_rules(appmodule, client):
    login(client, appmodule)
    client.post("/admin/sounds/theme/new", data={"name": "Zombie Apocalypse", "skin": "halloween"})
    with appmodule.app.app_context():
        zombie = appmodule.SoundTheme.query.filter_by(slug="zombie-apocalypse").first()
        assert zombie and not zombie.is_default
        zid = zombie.id
    client.post(f"/admin/sounds/theme/{zid}/default")
    with appmodule.app.app_context():
        assert appmodule.SoundTheme.query.filter_by(is_default=True).count() == 1
        assert appmodule.get_default_sound_theme().id == zid
    client.post(f"/admin/sounds/theme/{zid}/delete")
    with appmodule.app.app_context():
        # deleting the default hands the crown to another theme instead of leaving none
        assert appmodule.SoundTheme.query.filter_by(is_default=True).count() == 1


def test_admin_pages_render(appmodule, client):
    login(client, appmodule)
    for url in ("/admin/sounds", "/admin/pages", "/admin/pages?new=1", "/admin/texts", "/admin"):
        assert client.get(url).status_code == 200, url


def test_cms_page_is_sanitised_and_publishable(appmodule, client):
    login(client, appmodule)
    resp = client.post("/admin/pages/save", data={
        "title": "Regels", "published": "on", "show_in_nav": "on",
        "body": '<h2>Hoi</h2><script>alert(1)</script><a href="javascript:alert(1)" onclick="x()">link</a><img src=x onerror=alert(1)>',
    })
    assert resp.status_code == 302
    anon = appmodule.app.test_client()
    page = anon.get("/p/regels")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    body = html[html.index('class="cms-body"'):html.index("</main>")]   # only the admin-written part
    assert "<h2>Hoi</h2>" in body
    assert "alert(1)" not in body and "onclick" not in body and "javascript:" not in body and "onerror" not in body
    assert "<script" not in body
    assert "/p/regels" in anon.get("/").get_data(as_text=True)   # shows up in the menu


def test_unpublished_page_is_hidden_from_visitors(appmodule, client):
    login(client, appmodule)
    client.post("/admin/pages/save", data={"title": "Geheim", "body": "<p>x</p>"})
    assert appmodule.app.test_client().get("/p/geheim").status_code == 404
    assert client.get("/p/geheim").status_code == 200   # admin still sees the draft


def test_editable_texts_override_and_reset(appmodule, client):
    login(client, appmodule)
    client.post("/admin/texts", data={"txt__home.hero_sub": "Welkom in het donker", "txt__home.banner": "Halloween!"})
    home = appmodule.app.test_client().get("/").get_data(as_text=True)
    assert "Welkom in het donker" in home and "Halloween!" in home
    client.post("/admin/texts", data={"txt__home.hero_sub": "", "txt__home.banner": ""})
    home = appmodule.app.test_client().get("/").get_data(as_text=True)
    assert "Welkom in het donker" not in home
    assert "Het echte GPS-jachtspel" in home


def test_missing_logo_and_background_fall_back_to_shipped_images(appmodule, client):
    # old databases point at files that were never uploaded
    assert client.get("/backgrounds/logo_default.png").status_code == 200
    assert client.get("/backgrounds/bg_default.png").status_code == 404      # old branding art is gone
    assert "bg_default" not in client.get("/").get_data(as_text=True)         # ... and no longer requested
    assert client.get("/backgrounds/does-not-exist.png").status_code == 404
    assert client.get("/backgrounds/..%2fapp.py").status_code == 404


def test_homepage_uses_halloween_skin_by_default(appmodule, client):
    html = client.get("/").get_data(as_text=True)
    assert 'data-skin="halloween"' in html
    assert "VenFaye" not in html


def test_pwa_files(appmodule, client):
    manifest = client.get("/manifest.webmanifest")
    assert manifest.status_code == 200 and manifest.get_json()["display"] == "standalone"
    sw = client.get("/sw.js")
    assert sw.status_code == 200 and sw.headers["Service-Worker-Allowed"] == "/"
    assert client.get("/static/img/icon-192.png").status_code == 200

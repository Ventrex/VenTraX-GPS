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
        assert names["klassiek"].is_default and names["klassiek"].skin == "classic"   # Klassiek is the base
        assert names["klassiek"].bg_color == "#000000" and names["klassiek"].accent == "#c4161c"
        assert names["halloween"].skin == "halloween" and names["halloween"].accent == "#ff6a13"


def test_sound_theme_payload_lists_uploaded_clips(appmodule):
    with appmodule.app.app_context():
        theme = appmodule.get_default_sound_theme()
        appmodule.db.session.add(appmodule.SoundClip(theme_id=theme.id, event="intro", filename="x.mp3", label="x", volume=70))
        appmodule.db.session.commit()
        payload = appmodule.sound_theme_payload(theme)
        assert payload["events"]["intro"][0]["url"] == "/audio/themes/x.mp3"
        assert payload["events"]["intro"][0]["volume"] == 70
        assert payload["skin"] == "classic"


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
    for url in ("/admin/sounds", "/admin/pages", "/admin/pages?new=1", "/admin/texts", "/admin",
                "/admin?tab=users", "/admin?tab=games", "/admin?tab=catalog", "/admin/log", "/admin/reports",
                "/admin/photos", "/admin/changelog", "/admin/todo"):
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


def test_homepage_uses_classic_oled_by_default(appmodule, client):
    html = client.get("/").get_data(as_text=True)
    assert 'data-skin="classic"' in html
    assert "--bg:#000000" in html and "--accent:  #c4161c" in html.replace("--accent: #c4161c", "--accent:  #c4161c")
    assert "VenFaye" not in html


def test_pwa_files(appmodule, client):
    manifest = client.get("/manifest.webmanifest")
    assert manifest.status_code == 200 and manifest.get_json()["display"] == "standalone"
    sw = client.get("/sw.js")
    assert sw.status_code == 200 and sw.headers["Service-Worker-Allowed"] == "/"
    assert client.get("/static/img/icon-192.png").status_code == 200


def test_switching_default_theme_changes_the_whole_site(appmodule, client):
    login(client, appmodule)
    with appmodule.app.app_context():
        hid = appmodule.SoundTheme.query.filter_by(slug="halloween").first().id
    client.post(f"/admin/sounds/theme/{hid}/default")
    html = client.get("/").get_data(as_text=True)
    assert 'data-skin="halloween"' in html and "#ff6a13" in html and "--bg:#06040a" in html


def test_new_theme_copies_klassiek_including_sounds(appmodule, client):
    login(client, appmodule)
    with appmodule.app.app_context():
        kl = appmodule.SoundTheme.query.filter_by(slug="klassiek").first()
        kid = kl.id
    up = client.post(f"/admin/sounds/theme/{kid}/upload",
                     data={"event": "intro", "file": (io.BytesIO(b"ID3x"), "a.mp3")}, content_type="multipart/form-data").get_json()
    client.post(f"/admin/sounds/theme/{kid}/save", data={"name": "Klassiek", "accent": "#112233", "bg_color": "#000000",
                                                       "skin": "classic", "synth": "on", "volume": "55"})
    client.post("/admin/sounds/theme/new", data={"name": "Zombie", "copy_from": ""})   # "" = Klassiek
    with appmodule.app.app_context():
        z = appmodule.SoundTheme.query.filter_by(slug="zombie").first()
        assert z.accent == "#112233" and z.volume == 55 and z.skin == "classic"
        assert len(z.clips) == 1 and z.clips[0].filename != up["url"].rsplit("/", 1)[1]   # own file copy
        copy_id = z.clips[0].id
    # deleting the copy's clip must not break Klassiek's
    assert client.post(f"/admin/sounds/clip/{copy_id}/delete").get_json()["success"]
    assert client.get(up["url"]).status_code == 200


def test_theme_appearance_is_saved_and_validated(appmodule, client):
    login(client, appmodule)
    with appmodule.app.app_context():
        tid = appmodule.SoundTheme.query.filter_by(slug="klassiek").first().id
    client.post(f"/admin/sounds/theme/{tid}/save", data={
        "name": "Klassiek", "accent": "javascript:alert(1)", "bg_color": "#0a0a0f", "font_head": "Orbitron",
        "font_body": "Hacker Font", "radius": "99", "bg_overlay": "10", "skin": "classic", "volume": "80"})
    with appmodule.app.app_context():
        t = appmodule.db.session.get(appmodule.SoundTheme, tid)
        assert t.accent == "#c4161c"            # invalid colour ignored
        assert t.bg_color == "#0a0a0f" and t.font_head == "Orbitron"
        assert t.font_body == "DM Sans"          # unknown font ignored
        assert t.radius == 24 and t.bg_overlay == 30   # clamped


def test_admin_hub_has_one_menu_and_everything_in_the_panel(appmodule, client):
    login(client, appmodule)
    import html as htmllib
    html = client.get("/admin?tab=users").get_data(as_text=True)
    assert "adm-nav" in html
    text = htmllib.unescape(html)
    for label in ("Thema's & geluiden", "Pagina's", "Teksten", "Nieuws", "Gebruikers", "Meldingen", "Changelog", "TODO"):
        assert label in text, label
    assert 'class="dd-menu"' not in html          # the duplicate Admin dropdown is gone
    assert 'id="tab-site"' not in html            # "Site & Thema" moved into Thema's


def _klassiek_id(appmodule):
    with appmodule.app.app_context():
        return appmodule.SoundTheme.query.filter_by(slug="klassiek").first().id


def test_google_font_url_only_asks_for_weights_that_exist(appmodule):
    with appmodule.app.app_context():
        ui = appmodule.theme_ui(None)
    ui["font_head"] = "Creepster"          # only has weight 400; asking for 700 would make Google reject everything
    url, faces, head, body = appmodule.font_assets(ui)
    assert "family=Creepster:wght@400" in url and "700" not in url.split("Creepster")[1].split("&")[0]
    assert faces == "" and head == "Creepster" and body == "DM Sans"


def test_uploaded_font_overrides_and_is_validated(appmodule, client):
    login(client, appmodule)
    tid = _klassiek_id(appmodule)
    base = {"name": "Klassiek", "skin": "classic", "volume": "80"}
    bad = client.post(f"/admin/sounds/theme/{tid}/save",
                      data={**base, "font_head_upload": (io.BytesIO(b"<?php echo 1;"), "evil.woff2")},
                      content_type="multipart/form-data")
    with appmodule.app.app_context():
        assert not appmodule.db.session.get(appmodule.SoundTheme, tid).font_head_file   # fake header rejected
    good = client.post(f"/admin/sounds/theme/{tid}/save",
                       data={**base, "font_head_upload": (io.BytesIO(b"wOF2" + b"\x00" * 64), "Horror.woff2")},
                       content_type="multipart/form-data")
    with appmodule.app.app_context():
        fn = appmodule.db.session.get(appmodule.SoundTheme, tid).font_head_file
        assert fn and fn.endswith(".woff2")
    html = client.get("/").get_data(as_text=True)
    assert "@font-face{font-family:'VX Head'" in html and f"/static/fonts/{fn}" in html
    assert "--hfont:'VX Head'" in html
    # removing it deletes the file and goes back to the Google font
    client.post(f"/admin/sounds/theme/{tid}/save", data={**base, "clear_font_head_upload": "1"}, content_type="multipart/form-data")
    import os
    assert not os.path.exists(os.path.join(appmodule.FONT_FOLDER, fn))
    assert "VX Head" not in client.get("/").get_data(as_text=True)


def test_select_options_are_readable_and_default_font_is_not_syne(appmodule, client):
    html = client.get("/").get_data(as_text=True)
    assert "color-scheme:dark" in html and "select option" in html
    assert "--hfont:'Space Grotesk'" in html
    assert "'Syne'" not in html

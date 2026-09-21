"""
Tests for the anti-bot / registration-security changes: Turnstile, rate
limiting, honeypot, disposable-email guard, and the new-accounts-only
e-mail verification gate. Run with: pytest tests/
"""
import time

from conftest import make_user


def register_payload(**overrides):
    payload = dict(
        username="newplayer",
        email="newplayer@example.com",
        password="hunter22",
        confirm_password="hunter22",
        website="",  # honeypot, empty = human
        **{"cf-turnstile-response": "ok-token"},
    )
    payload.update(overrides)
    return payload


def test_valid_registration_succeeds(appmodule, client, monkeypatch):
    make_user(appmodule, username="seed_owner")  # so /register doesn't redirect to /setup
    monkeypatch.setattr(appmodule, "verify_turnstile", lambda token, ip: True)

    resp = client.post("/register", data=register_payload(), follow_redirects=False)

    assert resp.status_code == 302
    with appmodule.app.app_context():
        user = appmodule.User.query.filter_by(username="newplayer").first()
        assert user is not None
        assert user.requires_email_verification is True
        assert user.email_verified is False


def test_missing_turnstile_token_is_rejected(appmodule, client, monkeypatch):
    make_user(appmodule, username="seed_owner")
    # No token in the payload at all - verify_turnstile itself must reject an empty token.
    resp = client.post(
        "/register",
        data=register_payload(**{"cf-turnstile-response": ""}),
        follow_redirects=False,
    )
    assert resp.status_code == 200  # re-renders the form with a flash, not a redirect
    with appmodule.app.app_context():
        assert appmodule.User.query.filter_by(username="newplayer").first() is None


def test_invalid_turnstile_token_is_rejected(appmodule, client, monkeypatch):
    make_user(appmodule, username="seed_owner")
    monkeypatch.setattr(appmodule, "verify_turnstile", lambda token, ip: False)

    resp = client.post("/register", data=register_payload(), follow_redirects=False)

    assert resp.status_code == 200
    with appmodule.app.app_context():
        assert appmodule.User.query.filter_by(username="newplayer").first() is None
        blocked = appmodule.ActivityLog.query.filter_by(event="register_blocked").first()
        assert blocked is not None
        assert "turnstile_failed" in blocked.detail


def test_honeypot_filled_is_rejected(appmodule, client, monkeypatch):
    make_user(appmodule, username="seed_owner")
    monkeypatch.setattr(appmodule, "verify_turnstile", lambda token, ip: True)

    resp = client.post(
        "/register",
        data=register_payload(website="http://spam.example"),
        follow_redirects=False,
    )

    assert resp.status_code == 200
    with appmodule.app.app_context():
        assert appmodule.User.query.filter_by(username="newplayer").first() is None
        blocked = appmodule.ActivityLog.query.filter_by(event="register_blocked").first()
        assert blocked is not None
        assert "honeypot" in blocked.detail


def test_disposable_email_is_rejected(appmodule, client, monkeypatch):
    make_user(appmodule, username="seed_owner")
    monkeypatch.setattr(appmodule, "verify_turnstile", lambda token, ip: True)

    resp = client.post(
        "/register",
        data=register_payload(email="throwaway@mailinator.com"),
        follow_redirects=False,
    )

    assert resp.status_code == 200
    with appmodule.app.app_context():
        assert appmodule.User.query.filter_by(username="newplayer").first() is None


def test_rate_limit_blocks_after_max_successes(appmodule, client, monkeypatch):
    make_user(appmodule, username="seed_owner")
    monkeypatch.setattr(appmodule, "verify_turnstile", lambda token, ip: True)

    # Pretend this IP already used up its allowance in this window.
    test_ip = "127.0.0.1"
    now = time.time()
    appmodule._register_successes[test_ip] = [now, now, now]

    resp = client.post("/register", data=register_payload(), follow_redirects=False)

    assert resp.status_code == 429
    with appmodule.app.app_context():
        assert appmodule.User.query.filter_by(username="newplayer").first() is None


def test_existing_user_still_logs_in_after_migration(appmodule, client):
    """Simulates a pre-existing account: created without ever setting
    requires_email_verification, exactly like a row that existed before this
    column was added. It must log in exactly as before - no new obligation."""
    make_user(appmodule, username="legacy_player", email="legacy@example.com",
              password="oldpassword1", email_verified=False)  # never verified, pre-existing

    with appmodule.app.app_context():
        user = appmodule.User.query.filter_by(username="legacy_player").first()
        assert user.requires_email_verification is False  # column default, no new gate

    resp = client.post(
        "/login",
        data={"username": "legacy_player", "password": "oldpassword1"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "/login" not in resp.headers["Location"]


def test_unverified_new_user_has_limited_access(appmodule, client, monkeypatch):
    make_user(appmodule, username="seed_owner")
    uid = make_user(appmodule, username="unverified_player", email="uv@example.com",
                     password="hunter22", requires_verification=True, email_verified=False)

    with client.session_transaction() as sess:
        sess["_user_id"] = str(uid)
        sess["_fresh"] = True

    resp = client.get("/new_game", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/dashboard")

    resp = client.get("/join", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/dashboard")


def test_verified_user_has_full_access(appmodule, client):
    uid = make_user(appmodule, username="verified_player", email="vp@example.com",
                     password="hunter22", requires_verification=False, email_verified=True)

    with client.session_transaction() as sess:
        sess["_user_id"] = str(uid)
        sess["_fresh"] = True

    resp = client.get("/new_game", follow_redirects=False)
    assert resp.status_code == 200  # form renders, not blocked

    resp = client.get("/join", follow_redirects=False)
    assert resp.status_code == 200


def test_verify_link_clears_the_gate(appmodule, client):
    uid = make_user(appmodule, username="about_to_verify", email="verify-me@example.com",
                     password="hunter22", requires_verification=True, email_verified=False)
    with appmodule.app.app_context():
        user = appmodule.db.session.get(appmodule.User, uid)
        token = user.get_verify_token()

    resp = client.get(f"/verify/{token}", follow_redirects=False)
    assert resp.status_code == 302

    with appmodule.app.app_context():
        user = appmodule.db.session.get(appmodule.User, uid)
        assert user.email_verified is True
        assert user.requires_email_verification is False

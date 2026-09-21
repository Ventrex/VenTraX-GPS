import os
import sys
import importlib

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture()
def appmodule(tmp_path, monkeypatch):
    """Fresh import of app.py against an isolated, throwaway SQLite DB.

    app.py builds the Flask app / DB / mail objects at import time, so each
    test gets a clean module (and therefore a clean in-memory rate-limit
    state) by re-importing after setting the env vars it reads at import time.
    """
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-for-prod")
    monkeypatch.setenv("MAIL_USERNAME", "")  # mail disabled unless a test opts in
    monkeypatch.setenv("TURNSTILE_SECRET_KEY", "test-turnstile-secret")
    monkeypatch.setenv("BASE_URL", "http://localhost:5001")

    if "app" in sys.modules:
        del sys.modules["app"]
    module = importlib.import_module("app")
    module.app.config["TESTING"] = True
    module.app.config["SERVER_NAME"] = "localhost"
    with module.app.app_context():
        module.init_db()
    yield module
    with module.app.app_context():
        module.db.session.remove()
        module.db.drop_all()


@pytest.fixture()
def client(appmodule):
    return appmodule.app.test_client()


def make_user(appmodule, username="existing_user", email="existing@example.com",
              password="hunter22", requires_verification=None, email_verified=True):
    """Create a user directly, bypassing /register - simulates an account
    that was already there before this deploy (or a controlled fixture user)."""
    with appmodule.app.app_context():
        kwargs = dict(username=username, email=email, email_verified=email_verified)
        if requires_verification is not None:
            kwargs["requires_email_verification"] = requires_verification
        user = appmodule.User(**kwargs)
        user.set_password(password)
        appmodule.db.session.add(user)
        appmodule.db.session.commit()
        return user.id

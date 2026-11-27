from datetime import datetime, timezone

import pytest

from flask_artisan import DB, Route
from flask_artisan.auth import Authenticate, EnsureEmailIsVerified, MustVerifyEmail
from flask_artisan.auth.notifications import VerifyEmail
from flask_artisan.database import Mapped, Model
from flask_artisan.notifications import Notification

from .models import VePlain, VeUser


def routes():
    Route.get("/secret", lambda: "secret").middleware(Authenticate, EnsureEmailIsVerified)
    Route.get("/login", lambda: "login").name("login")
    Route.get("/verify-email", lambda: "notice").name("verification.notice")


@pytest.fixture
def make(auth_app):
    def _make(model=VeUser):
        app = auth_app(routes, model=model)
        return app, app.test_client()

    return _make


def create(app, model=VeUser, **extra):
    with app.app_context():
        return model.create(email="ada@x.org", password="secret", **extra)


def test_column_and_methods(make):
    app, _ = make()
    with app.app_context():
        user = VeUser.create(email="ada@x.org", password="secret")
        assert user.email_verified_at is None
        assert not user.has_verified_email()
        user.mark_email_as_verified()
        DB.session.expunge_all()  # relecture complète, comme une nouvelle requête
        reloaded = VeUser.find(user.id)
        assert reloaded.has_verified_email()
        assert reloaded.email_verified_at.tzinfo is not None


def test_model_before_mixin_is_refused():
    with pytest.raises(TypeError, match="MustVerifyEmail"):

        class VeWrong(Model, MustVerifyEmail):
            email: Mapped[str | None]


def test_unverified_user_is_redirected_to_notice(make):
    app, client = make()
    client.acting_as(create(app))
    client.get("/secret").assert_redirect("/verify-email")


def test_unverified_user_gets_json_on_api(make):
    app, client = make()
    client.acting_as(create(app))
    response = client.get("/secret", headers={"Accept": "application/json"})
    assert response.status_code == 403
    assert response.get_json() == {"message": "Your email address is not verified."}


def test_verified_user_passes(make):
    app, client = make()
    user = create(app)
    with app.app_context():
        VeUser.find(user.id).mark_email_as_verified()
    client.acting_as(user)
    client.get("/secret").assert_ok()


def test_model_without_mixin_passes(make):
    app, client = make(model=VePlain)
    client.acting_as(create(app, model=VePlain))
    client.get("/secret").assert_ok()


def test_email_verified_at_not_mass_assignable(make):
    app, _ = make()
    user = create(app, email_verified_at=datetime.now(timezone.utc))
    assert user.email_verified_at is None


def test_send_verification_notification(make):
    app, _ = make()
    with app.app_context(), Notification.fake() as fake:
        user = VeUser.create(email="ada@x.org", password="secret")
        user.send_email_verification_notification()
        fake.assert_sent_to(user, VerifyEmail)

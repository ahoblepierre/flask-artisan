import subprocess
import sys

import pytest

from flask_artisan import Mail, Route, ValidateSignature
from flask_artisan.auth.notifications import ResetPassword, VerifyEmail

from .conftest import AUTH_CONFIG
from .models import AMember, PwUser

MAIL_CONFIG = (
    "config = {'default': 'array', 'mailers': {'array': {'transport': 'array'}},\n"
    "          'from': {'address': 'app@x.org', 'name': 'App'}}\n"
)


@pytest.fixture
def app(db_app):
    from flask_artisan.providers import ServiceProvider

    def routes():
        Route.get("/reset-password/<token>", lambda token: token).name("password.reset")
        Route.get("/verify-email/<int:id>/<hash>", lambda id, hash: "verified").name(
            "verification.verify"
        ).middleware(ValidateSignature)

    app = db_app(
        "flask_artisan.auth.AuthServiceProvider",
        configs={"auth": AUTH_CONFIG, "mail": MAIL_CONFIG},
    )
    app.make("config").set("auth.model", PwUser)
    app.register(type("Routes", (ServiceProvider,), {"boot": lambda self: routes()}))
    return app


def sent_text(app, user, notification):
    with app.test_request_context():
        user.notify(notification)
    [message] = Mail.transport("array").messages
    return message, message.get_body(("plain",)).get_content()


def test_reset_password_mail(app):
    with app.app_context():
        user = PwUser.create(email="ada@x.org", password="secret")
        message, text = sent_text(app, user, ResetPassword("abc"))
    assert message["Subject"] == "Réinitialisation du mot de passe"
    assert message["To"] == "ada@x.org"
    assert "http://localhost/reset-password/abc?email=ada@x.org" in text


def test_verify_email_mail_has_signed_link(app):
    with app.app_context():
        user = PwUser.create(email="ada@x.org", password="secret")
        message, text = sent_text(app, user, VerifyEmail())
    assert message["Subject"] == "Vérifiez votre adresse e-mail"
    url = next(word for word in text.split() if word.startswith("http://localhost/"))
    assert "expires=" in url
    response = app.test_client().get(url.removeprefix("http://localhost"))
    assert response.get_data(as_text=True) == "verified"


def test_project_can_override_template(app):
    emails = app.base_path("resources/views/flask_artisan/emails")
    emails.mkdir(parents=True)
    (emails / "reset_password.txt").write_text("Maison : {{ url }}")
    with app.app_context():
        user = PwUser.create(email="ada@x.org", password="secret")
        _, text = sent_text(app, user, ResetPassword("abc"))
    assert text.startswith("Maison : http://localhost/reset-password/abc")


def test_reset_link_requires_notifiable(app):
    with app.app_context():
        member = AMember.create(email="b@x.org", password="secret")
        with pytest.raises(TypeError, match="Notifiable"):
            member.send_password_reset_notification("x")


def test_auth_import_does_not_load_notifications():
    code = (
        "import sys, flask_artisan.auth\n"
        "print([m for m in ('flask_artisan.auth.notifications', 'flask_artisan.auth.passwords')"
        " if m in sys.modules])"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "[]"

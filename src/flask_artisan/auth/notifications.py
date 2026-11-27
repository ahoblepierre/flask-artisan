import hashlib

from flask import url_for

from flask_artisan.helpers import config
from flask_artisan.mail import Mailable
from flask_artisan.notifications import Notification
from flask_artisan.signing import signed_url


def _absolute(relative: str) -> str:
    # Jamais l'en-tête Host de la requête : un attaquant recevrait le jeton de la victime.
    base = config("app.url")
    if not base:
        raise RuntimeError(
            "Définissez APP_URL (config app.url, ex. https://exemple.fr) : les liens envoyés "
            "par e-mail ne doivent pas dépendre de l'en-tête Host de la requête."
        )
    return str(base).rstrip("/") + relative


def reset_url(notifiable, token: str) -> str:
    return _absolute(url_for("password.reset", token=token, email=notifiable.email))


def verification_url(notifiable) -> str:
    return _absolute(
        signed_url(
            "verification.verify",
            expires=config("auth.verification.expire", 60) * 60,
            id=notifiable.id,
            hash=hashlib.sha1(notifiable.email.encode()).hexdigest(),
        )
    )


class AuthMail(Mailable):
    def __init__(self, url: str, expire: int):
        self.url = url
        self.expire = expire


class ResetPasswordMail(AuthMail):
    subject = "Réinitialisation du mot de passe"
    view = "flask_artisan/emails/reset_password.html"
    text = "flask_artisan/emails/reset_password.txt"


class VerifyEmailMail(AuthMail):
    subject = "Vérifiez votre adresse e-mail"
    view = "flask_artisan/emails/verify_email.html"
    text = "flask_artisan/emails/verify_email.txt"


class ResetPassword(Notification):
    """Lien vers la route `password.reset` (installée par `flask auth:install`)."""

    def __init__(self, token: str):
        self.token = token

    def via(self, notifiable) -> list[str]:
        return ["mail"]

    def to_mail(self, notifiable) -> Mailable:
        expire = config("auth.passwords.expire", 60)
        return ResetPasswordMail(reset_url(notifiable, self.token), expire)


class VerifyEmail(Notification):
    """Lien signé vers la route `verification.verify` (installée par `flask auth:install`)."""

    def via(self, notifiable) -> list[str]:
        return ["mail"]

    def to_mail(self, notifiable) -> Mailable:
        expire = config("auth.verification.expire", 60)
        return VerifyEmailMail(verification_url(notifiable), expire)

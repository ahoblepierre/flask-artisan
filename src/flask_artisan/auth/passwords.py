"""Réinitialisation du mot de passe. Importé à l'usage : l'import enregistre la table."""

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import DateTime, String, delete

from flask_artisan.database import Mapped, Model, column
from flask_artisan.database.model import _commit, _db
from flask_artisan.helpers import config


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


class PasswordResetToken(Model):
    """Un jeton par e-mail ; seule l'empreinte SHA-256 est stockée."""

    timestamps = False

    email: Mapped[str] = column(String(255), primary_key=True)
    token: Mapped[str] = column(String(64))
    created_at: Mapped[datetime] = column(DateTime(timezone=True))


class Password:
    """`Password.send_reset_link(email)`, `Password.reset(email, token, password)` → statut."""

    RESET_LINK_SENT = "passwords.sent"
    RESET_THROTTLED = "passwords.throttled"
    INVALID_USER = "passwords.user"
    INVALID_TOKEN = "passwords.token"
    PASSWORD_RESET = "passwords.reset"

    @staticmethod
    def _user(email: str):
        return config("auth.model").where("email", email).first()

    @classmethod
    def send_reset_link(cls, email: str) -> str:
        user = cls._user(email)
        if user is None:
            return cls.INVALID_USER
        db = _db()
        row = db.session.get(PasswordResetToken, email)
        throttle = timedelta(seconds=config("auth.passwords.throttle", 60))
        if row is not None and _aware(row.created_at) + throttle > _now():
            return cls.RESET_THROTTLED
        token = secrets.token_hex(32)
        if row is None:
            row = PasswordResetToken()
            row.email = email
            db.session.add(row)
        row.token = _digest(token)
        row.created_at = _now()
        _commit(db)
        user.send_password_reset_notification(token)
        return cls.RESET_LINK_SENT

    @classmethod
    def reset(cls, email: str, token: str, password: str) -> str:
        user = cls._user(email)
        if user is None:
            return cls.INVALID_USER
        db = _db()
        row = db.session.get(PasswordResetToken, email)
        expire = timedelta(minutes=config("auth.passwords.expire", 60))
        if (
            row is None
            or _aware(row.created_at) + expire <= _now()
            or not hmac.compare_digest(row.token, _digest(token))
        ):
            return cls.INVALID_TOKEN
        user.password = password
        from flask_artisan.auth.authenticatable import HasApiTokens

        if isinstance(user, HasApiTokens):
            # Un token d'API volé ne doit pas survivre à la réinitialisation.
            from flask_artisan.auth.tokens import PersonalAccessToken

            db.session.execute(
                delete(PersonalAccessToken).where(PersonalAccessToken.user_id == user.id)
            )
        db.session.delete(row)
        user.save()
        return cls.PASSWORD_RESET

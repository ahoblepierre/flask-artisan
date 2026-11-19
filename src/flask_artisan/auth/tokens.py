import hashlib
import hmac
import secrets
from datetime import datetime, timezone

from sqlalchemy import String, update

from flask_artisan.database import Mapped, Model, column
from flask_artisan.database.model import _commit, _db


class PersonalAccessToken(Model):
    """Token d'API façon Sanctum : seule l'empreinte SHA-256 du secret est stockée."""

    # Pas de clé étrangère : la table des utilisateurs n'est pas figée par le framework.
    user_id: Mapped[int] = column(index=True)
    name: Mapped[str]
    token: Mapped[str] = column(String(64), unique=True)
    last_used_at: Mapped[datetime | None]

    fillable = ("user_id", "name", "token")
    hidden = ("token",)


def _digest(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def issue_token(user_id: int, name: str) -> str:
    secret = secrets.token_urlsafe(40)
    row = PersonalAccessToken.create(user_id=user_id, name=name, token=_digest(secret))
    return f"{row.id}|{secret}"


def find_token(plain: str) -> PersonalAccessToken | None:
    """Le token correspondant à `"<id>|<secret>"`, sinon None ; met à jour `last_used_at`."""
    token_id, _, secret = (plain or "").partition("|")
    if not token_id.isdigit() or not secret:
        return None
    row = PersonalAccessToken.find(int(token_id))
    if row is None or not hmac.compare_digest(row.token, _digest(secret)):
        return None
    # UPDATE direct : save() toucherait updated_at.
    db = _db()
    db.session.execute(
        update(PersonalAccessToken)
        .where(PersonalAccessToken.id == row.id)
        .values(last_used_at=datetime.now(timezone.utc))
    )
    _commit(db)
    return row

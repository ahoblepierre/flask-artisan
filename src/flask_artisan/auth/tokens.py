import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import String, update

from flask_artisan.database import Mapped, Model, column
from flask_artisan.database.model import _commit, _db

LAST_USED_THROTTLE = timedelta(minutes=1)


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
    """Le token correspondant à `"<id>|<secret>"`, sinon None.

    Met à jour `last_used_at` au plus une fois par minute, et jamais si la session a des
    changements en attente (on ne valide pas le travail du handler à sa place).
    """
    token_id, _, secret = (plain or "").partition("|")
    # isascii : "²".isdigit() est vrai ; 18 chiffres tiennent dans un BIGINT.
    if not (token_id.isascii() and token_id.isdigit()) or len(token_id) > 18 or not secret:
        return None
    db = _db()
    # Avant toute requête : une transaction ouverte ou des changements en attente
    # appartiennent au handler, on ne les valide pas à sa place.
    busy = db.session.in_transaction() or db.session.new or db.session.dirty or db.session.deleted
    with db.session.no_autoflush:
        row = PersonalAccessToken.find(int(token_id))
    if row is None or not hmac.compare_digest(row.token, _digest(secret)):
        return None
    now = datetime.now(timezone.utc)
    last = row.last_used_at
    if last is not None and last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)  # SQLite relit les dates sans fuseau
    if busy or (last is not None and now - last < LAST_USED_THROTTLE):
        return row
    # UPDATE direct : save() toucherait updated_at.
    db.session.execute(
        update(PersonalAccessToken).where(PersonalAccessToken.id == row.id).values(last_used_at=now)
    )
    _commit(db)
    return row

import hashlib
import re

import pytest

from flask_artisan import DB
from flask_artisan.auth import Authenticatable, HasApiTokens, PersonalAccessToken, find_token
from flask_artisan.database import Mapped, Model


class ATokenUser(Authenticatable, HasApiTokens, Model):
    email: Mapped[str]
    password: Mapped[str | None]


@pytest.fixture
def user(db_app):
    app = db_app()
    with app.app_context():
        yield ATokenUser.create(email="a@x", password="secret")


def test_create_token_stores_only_hash(user):
    plain = user.create_token("mobile")
    assert re.fullmatch(r"\d+\|.{40,}", plain)
    token_id, secret = plain.split("|", 1)
    row = PersonalAccessToken.find(int(token_id))
    assert row.user_id == user.id and row.name == "mobile"
    assert row.token == hashlib.sha256(secret.encode()).hexdigest()
    assert secret not in row.token


def test_find_token_returns_row_and_touches_last_used(user):
    plain = user.create_token("mobile")
    found = find_token(plain)
    assert found.user_id == user.id
    DB.remove()
    assert PersonalAccessToken.find(found.id).last_used_at is not None


@pytest.mark.parametrize(
    "plain", ["abc", "1|", "x|y", "999|secret", "", "WRONG", "²|x", "99999999999999999999999|x"]
)
def test_find_token_rejects_malformed(user, plain):
    real = user.create_token("mobile")
    if plain == "WRONG":
        plain = real.split("|")[0] + "|wrong"
    assert find_token(plain) is None


def test_revoked_token_is_rejected(user):
    plain = user.create_token("mobile")
    PersonalAccessToken.find(int(plain.split("|")[0])).delete()
    assert find_token(plain) is None


def test_tokens_lists_user_tokens(user):
    other = ATokenUser.create(email="b@x", password="secret")
    user.create_token("a")
    user.create_token("b")
    other.create_token("c")
    assert len(user.tokens().get()) == 2


def test_current_access_token_defaults_to_none(user):
    assert user.current_access_token() is None


def test_hard_deleting_user_revokes_tokens(user):
    plain = user.create_token("mobile")
    user.delete()
    assert find_token(plain) is None
    assert PersonalAccessToken.count() == 0


def _set_last_used(token_id, value):
    from sqlalchemy import update

    DB.session.execute(
        update(PersonalAccessToken)
        .where(PersonalAccessToken.id == token_id)
        .values(last_used_at=value)
    )
    DB.session.commit()
    DB.remove()


def test_last_used_at_is_throttled_to_one_minute(user):
    from datetime import datetime, timedelta, timezone

    plain = user.create_token("mobile")
    token_id = int(plain.split("|")[0])
    recent = datetime.now(timezone.utc) - timedelta(seconds=30)
    _set_last_used(token_id, recent)
    find_token(plain)
    DB.remove()
    stored = PersonalAccessToken.find(token_id).last_used_at
    assert stored.replace(tzinfo=None) == recent.replace(tzinfo=None)

    _set_last_used(token_id, recent - timedelta(minutes=2))
    find_token(plain)
    DB.remove()
    stored = PersonalAccessToken.find(token_id).last_used_at.replace(tzinfo=timezone.utc)
    assert stored > recent


def test_find_token_never_commits_pending_changes(user):
    plain = user.create_token("mobile")
    user.email = "changed@x"  # modifié, pas sauvé
    assert find_token(plain) is not None
    DB.remove()  # fin de requête : rollback de ce qui n'a pas été sauvé
    assert ATokenUser.find(user.id).email == "a@x"

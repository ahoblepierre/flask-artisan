import pytest

from flask_artisan import DB
from flask_artisan.auth import Authenticatable
from flask_artisan.database import Mapped, Model


class AUser(Authenticatable, Model):
    email: Mapped[str]
    password: Mapped[str | None]


@pytest.fixture
def app(db_app):
    app = db_app()
    with app.app_context():
        yield app


def test_create_hashes_password(app):
    u = AUser.create(email="a@x", password="secret")
    assert u.password.startswith("scrypt:")
    assert u.check_password("secret")
    assert not u.check_password("nope")


def test_assignment_update_and_fill_hash(app):
    u = AUser.create(email="a@x", password="p0")
    u.password = "p1"
    assert u.password != "p1" and u.check_password("p1")
    u.update(password="p2")
    assert u.check_password("p2")
    u.fill(password="p3")
    assert u.check_password("p3")


def test_already_hashed_value_is_kept(app):
    other = AUser.create(email="o@x", password="secret")
    u = AUser.create(email="a@x", password="x")
    u.password = other.password
    assert u.password == other.password
    assert u.check_password("secret")


def test_reload_does_not_rehash(app):
    u = AUser.create(email="a@x", password="secret")
    stored = u.password
    DB.remove()
    again = AUser.find(u.id)
    assert again is not u
    assert again.password == stored
    assert again.check_password("secret")


def test_none_stays_none(app):
    u = AUser(email="b@x", password=None)
    assert u.password is None
    assert u.check_password("x") is False


def test_plaintext_with_hash_prefix_is_hashed(app):
    u = AUser.create(email="a@x", password="pbkdf2:hunter2")
    assert u.password != "pbkdf2:hunter2"
    assert u.check_password("pbkdf2:hunter2")

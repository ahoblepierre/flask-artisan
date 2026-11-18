import pytest
from sqlalchemy import text

from flask_artisan import DB
from flask_artisan.database import Mapped, Model, SoftDeletes


class SUser(Model, SoftDeletes):
    name: Mapped[str]


@pytest.fixture
def deleted(db_app):
    db_app()
    SUser.create(name="kept")
    user = SUser.create(name="gone")
    user.delete()
    DB.remove()
    return user


def raw_count():
    return DB.session.execute(text("select count(*) from s_users")).scalar()


def test_delete_hides_but_keeps_row(deleted):
    assert SUser.find(deleted.id) is None
    assert raw_count() == 2
    assert deleted.trashed()


def test_queries_exclude_trashed(deleted):
    assert [u.name for u in SUser.all()] == ["kept"]
    assert SUser.count() == 1
    assert SUser.where("name", "gone").exists() is False


def test_with_and_only_trashed(deleted):
    assert SUser.with_trashed().count() == 2
    assert [u.name for u in SUser.only_trashed().get()] == ["gone"]
    assert SUser.with_trashed().where("name", "gone").first().trashed()


def test_restore(deleted):
    user = SUser.with_trashed().where("name", "gone").first()
    user.restore()
    DB.remove()
    assert SUser.count() == 2 and not user.trashed()


def test_force_delete(deleted):
    SUser.only_trashed().first().force_delete()
    assert raw_count() == 1


def test_with_trashed_does_not_leak(deleted):
    SUser.with_trashed().get()
    assert SUser.count() == 1
    assert [u.name for u in SUser.all()] == ["kept"]

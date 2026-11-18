import pytest
from werkzeug.exceptions import NotFound

from flask_artisan.database import Mapped, Model


class QUser(Model):
    name: Mapped[str]
    age: Mapped[int | None]


@pytest.fixture
def users(db_app):
    db_app()
    for name, age in [("ana", 20), ("bob", 30), ("cy", 40), ("dee", None), ("eve", 30)]:
        QUser.create(name=name, age=age)


def names(rows):
    return [u.name for u in rows]


@pytest.mark.parametrize(
    "args,expected",
    [
        (("age", 30), ["bob", "eve"]),
        (("age", "=", 30), ["bob", "eve"]),
        (("age", "!=", 30), ["ana", "cy"]),
        (("age", "<", 30), ["ana"]),
        (("age", "<=", 30), ["ana", "bob", "eve"]),
        (("age", ">", 30), ["cy"]),
        (("age", ">=", 30), ["bob", "cy", "eve"]),
        (("name", "like", "%e%"), ["dee", "eve"]),
    ],
)
def test_where_operators(users, args, expected):
    assert names(QUser.where(*args).order_by("name").get()) == expected


def test_invalid_operator_raises(users):
    with pytest.raises(ValueError, match="<>"):
        QUser.where("age", "<>", 1)


def test_unknown_column_raises(users):
    with pytest.raises(ValueError, match="nope"):
        QUser.where("nope", 1)


def test_or_where(users):
    assert names(QUser.where("name", "ana").or_where("age", ">", 30).get()) == ["ana", "cy"]


def test_where_in_null(users):
    assert names(QUser.where_in("name", ["ana", "cy"]).get()) == ["ana", "cy"]
    assert names(QUser.where_null("age").get()) == ["dee"]
    assert len(QUser.where_not_null("age").get()) == 4


def test_order_limit_offset_latest(users):
    assert names(QUser.order_by("name", "desc").limit(2).get()) == ["eve", "dee"]
    assert names(QUser.order_by("name").offset(3).get()) == ["dee", "eve"]
    assert QUser.latest("id").first().name == "eve"


def test_execution(users):
    assert QUser.where("age", 30).first().name == "bob"
    assert QUser.where("age", 99).first() is None
    with pytest.raises(NotFound):
        QUser.where("age", 99).first_or_fail()
    assert QUser.where("age", 30).count() == 2
    assert QUser.where("age", 30).exists() and not QUser.where("age", 99).exists()
    assert QUser.order_by("name").pluck("name") == ["ana", "bob", "cy", "dee", "eve"]


def test_builder_is_immutable(users):
    base = QUser.where("age", ">", 1)
    base.where("name", "ana")
    assert base.count() == 4


def test_class_level_proxies(users):
    assert names(QUser.where("age", 30).get()) == names(QUser.query().where("age", 30).get())


def test_injection_safe(users):
    assert QUser.where("name", "x' OR '1'='1").count() == 0

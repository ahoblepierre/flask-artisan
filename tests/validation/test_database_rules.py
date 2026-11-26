import pytest

from flask_artisan import DB
from flask_artisan.database import Mapped, Model
from flask_artisan.validation import Validator


class VUser(Model):
    email: Mapped[str]


TABLE = VUser.__tablename__


@pytest.fixture
def app(db_app):
    app = db_app()
    with app.app_context():
        yield app


def errors(data, rules):
    return Validator(data, rules).errors()


def test_unique(app):
    u = VUser.create(email="a@x")
    assert errors({"email": "a@x"}, {"email": f"unique:{TABLE}"}) == {
        "email": ["The email has already been taken."]
    }
    assert errors({"email": "b@x"}, {"email": f"unique:{TABLE},email"}) == {}
    assert errors({"email": "a@x"}, {"email": f"unique:{TABLE},email,{u.id}"}) == {}
    assert errors({"mail": "a@x"}, {"mail": f"unique:{TABLE},email,{u.id},id"}) == {}


def test_unique_sees_uncommitted_rows(app):
    with DB.transaction():
        VUser.create(email="t@x")
        assert errors({"email": "t@x"}, {"email": f"unique:{TABLE}"}) != {}


def test_exists(app):
    VUser.create(email="a@x")
    assert errors({"email": "a@x"}, {"email": f"exists:{TABLE}"}) == {}
    assert errors({"owner": "z@x"}, {"owner": f"exists:{TABLE},email"}) == {
        "owner": ["The selected owner is invalid."]
    }


@pytest.mark.parametrize(
    "rule", [f"unique:{TABLE};drop,email", f"exists:{TABLE},e mail", "unique", "exists:"]
)
def test_bad_identifiers_rejected(app, rule):
    with pytest.raises(ValueError):
        Validator({"email": "a@x"}, {"email": rule}).fails()


def test_none_fails_unique_without_nullable(app):
    assert errors({"email": None}, {"email": f"unique:{TABLE}"}) != {}


@pytest.mark.parametrize("value", [["a@x"], {"x": 1}])
@pytest.mark.parametrize("rule", ["unique", "exists"])
def test_list_or_dict_value_fails_db_rules_without_query(app, rule, value):
    assert errors({"email": value}, {"email": f"{rule}:{TABLE}"}) != {}

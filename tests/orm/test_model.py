from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from flask_artisan import DB, Route, ServiceProvider
from flask_artisan.database import Mapped, MassAssignmentError, Model, column


class MUser(Model):
    name: Mapped[str]
    email: Mapped[str | None]
    password: Mapped[str | None]
    is_admin: Mapped[bool] = column(default=False)
    hidden = ["password"]


class MGuarded(Model):
    name: Mapped[str]
    is_admin: Mapped[bool] = column(default=False)
    fillable = ["name"]


class MCategory(Model):
    timestamps = False
    name: Mapped[str]


class MBox(Model):
    pass


class MBlogPost(Model):
    pass


class MCode(Model):
    __tablename__ = "m_codes_table"
    code: Mapped[str] = column(primary_key=True)


def test_tablename():
    assert MUser.__tablename__ == "m_users"
    assert MCategory.__tablename__ == "m_categories"
    assert MBox.__tablename__ == "m_boxes"
    assert MBlogPost.__tablename__ == "m_blog_posts"
    assert MCode.__tablename__ == "m_codes_table"


def test_id_added_unless_primary_key_declared():
    assert MUser.__table__.c.id.primary_key
    assert "id" not in MCode.__table__.c


def test_timestamps(db_app):
    db_app()
    user = MUser.create(name="a")
    assert user.created_at.tzinfo is not None
    before = user.updated_at
    user.name = "b"
    user.save()
    assert user.updated_at > before
    assert "created_at" not in MCategory.__table__.c


def test_create_find_all(db_app):
    db_app()
    user = MUser.create(name="a")
    MUser.create(name="b")
    DB.remove()
    assert MUser.find(user.id).name == "a"
    assert MUser.find(999) is None
    assert [u.name for u in MUser.all()] == ["a", "b"]


def find_missing():
    return MUser.find_or_fail(999)


class MissingRoute(ServiceProvider):
    def boot(self):
        Route.get("/missing", find_missing)


def test_find_or_fail_404(db_app):
    app = db_app("orm.test_model.MissingRoute")
    assert app.test_client().get("/missing").status_code == 404


def test_fillable_ignores_other_keys(db_app):
    db_app()
    user = MGuarded.create(name="a", csrf_token="x", is_admin=True)
    assert user.name == "a" and user.is_admin is False
    user.update(name="b", csrf_token="y")
    assert MGuarded.find(user.id).name == "b"


def test_without_fillable_unknown_key_raises(db_app):
    db_app()
    with pytest.raises(MassAssignmentError, match="csrf_token"):
        MUser.create(name="a", csrf_token="x")


def test_protected_fields_never_mass_assigned(db_app):
    db_app()
    old = datetime(2000, 1, 1, tzinfo=timezone.utc)
    user = MUser.create(id=50, name="a", created_at=old)
    assert user.id != 50 and user.created_at != old


def test_save_commits_whole_session(db_app):
    db_app()
    a = MUser.create(name="a")
    b = MUser.create(name="b")
    a.name = "changed"
    b.save()
    DB.remove()
    assert MUser.find(a.id).name == "changed"


def test_save_inside_transaction_only_flushes(db_app):
    db_app()
    with pytest.raises(ValueError), DB.transaction():
        MUser.create(name="a")
        raise ValueError
    DB.remove()
    assert MUser.all() == []


def test_update_delete_refresh(db_app):
    db_app()
    user = MUser.create(name="a")
    user.update(name="b")
    DB.session.execute(text("update m_users set name = 'c'"))
    DB.session.commit()
    assert user.refresh().name == "c"
    user.delete()
    assert MUser.find(user.id) is None


def test_reserved_name_raises():
    with pytest.raises(TypeError, match="count|save"):

        class MBad(Model):
            save: Mapped[int]


def test_to_dict_hidden_and_iso_dates(db_app):
    db_app()
    data = MUser.create(name="a", password="secret").to_dict()
    assert "password" not in data and data["name"] == "a"
    datetime.fromisoformat(data["created_at"])


def show_user():
    return MUser.find(1)


def list_users():
    return MUser.all()


class JsonRoutes(ServiceProvider):
    def boot(self):
        Route.get("/user", show_user)
        Route.get("/users", list_users)


def test_controller_returns_model_and_list(db_app):
    app = db_app("orm.test_model.JsonRoutes")
    MUser.create(name="a", password="secret")
    client = app.test_client()
    one = client.get("/user").get_json()
    assert one["name"] == "a" and "password" not in one
    datetime.fromisoformat(one["created_at"])
    assert [u["name"] for u in client.get("/users").get_json()] == ["a"]


def test_serializable_after_session_closed(db_app):
    app = db_app()
    user = MUser.create(name="a")
    DB.remove()
    with app.app_context():
        assert app.json.dumps(user)

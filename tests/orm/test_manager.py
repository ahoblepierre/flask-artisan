import pytest
from sqlalchemy import text

from flask_artisan import DB, Route, ServiceProvider
from flask_artisan.database import DatabaseManager


def count(table="t"):
    return DB.session.execute(text(f"select count(*) from {table}")).scalar()


def create_table():
    DB.session.execute(text("create table t(x int)"))
    DB.session.commit()


def test_db_registered(db_app):
    app = db_app()
    assert app.make("db") is app.make(DatabaseManager)
    assert DB.engine.dialect.name == "sqlite"


def test_memory_shared_connection(db_app):
    db_app()
    create_table()
    DB.remove()
    assert count() == 0


def insert_without_commit():
    DB.session.execute(text("insert into t values (1)"))
    return "ok"


class InsertRoute(ServiceProvider):
    def boot(self):
        Route.get("/insert", insert_without_commit)


def test_session_removed_on_teardown(db_app):
    app = db_app("orm.test_manager.InsertRoute")
    create_table()
    assert app.test_client().get("/insert").status_code == 200
    assert count() == 0


def test_transaction_commits_and_rolls_back(db_app):
    db_app()
    create_table()
    db = DB
    with db.transaction():
        assert db.in_transaction()
        db.session.execute(text("insert into t values (1)"))
    assert not db.in_transaction()
    with pytest.raises(ValueError), db.transaction():
        db.session.execute(text("insert into t values (2)"))
        raise ValueError
    DB.remove()
    assert count() == 1


def test_nested_transaction_joins(db_app):
    db_app()
    create_table()
    with pytest.raises(ValueError), DB.transaction():
        with DB.transaction():
            DB.session.execute(text("insert into t values (1)"))
        assert DB.in_transaction()
        raise ValueError
    DB.remove()
    assert count() == 0


def test_two_apps_two_databases(db_app):
    a = db_app(database="a.sqlite", subdir="a")
    b = db_app(database="b.sqlite", subdir="b")
    with a.app_context():
        create_table()
    with b.app_context():
        assert not DB.engine.dialect.has_table(DB.session.connection(), "t")

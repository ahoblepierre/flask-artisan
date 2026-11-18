import sys
from pathlib import Path

import pytest

from flask_artisan.database import DatabaseError
from flask_artisan.database.connection import connection_url

BASE = Path("/projet")


def test_sqlite_relative_resolved_from_base():
    url = connection_url({"driver": "sqlite", "database": "database/database.sqlite"}, BASE)
    assert url == "sqlite:////projet/database/database.sqlite"


def test_sqlite_memory():
    assert connection_url({"driver": "sqlite", "database": ":memory:"}, BASE) == "sqlite://"


SERVER = {"host": "h", "username": "u", "password": "p", "database": "db"}


@pytest.mark.parametrize("driver", ["mysql", "mariadb"])
def test_mysql_and_mariadb(driver):
    url = connection_url({"driver": driver, "port": 3306, **SERVER}, BASE)
    assert url == "mysql+pymysql://u:p@h:3306/db"


def test_pgsql():
    url = connection_url({"driver": "pgsql", "port": 5432, **SERVER}, BASE)
    assert url == "postgresql+psycopg://u:p@h:5432/db"


def test_password_is_escaped():
    url = connection_url({"driver": "pgsql", **SERVER, "password": "a@b/c"}, BASE)
    assert "a@b/c" not in url and "a%40b%2Fc" in url


def test_url_wins():
    conn = {"driver": "pgsql", **SERVER, "url": "sqlite:///x.db"}
    assert connection_url(conn, BASE) == "sqlite:///x.db"


def test_unknown_driver_raises():
    with pytest.raises(DatabaseError, match="oracle"):
        connection_url({"driver": "oracle"}, BASE)


def test_missing_driver_names_extra(make_project, monkeypatch):
    from flask_artisan import Application
    from flask_artisan.database import DatabaseServiceProvider  # noqa: F401

    monkeypatch.setitem(sys.modules, "pymysql", None)
    root = make_project(
        providers="[DatabaseServiceProvider]",
        extra="from flask_artisan.database import DatabaseServiceProvider",
    )
    (root / "config" / "database.py").write_text(
        "config = {'default': 'mysql', 'connections': {'mysql': "
        "{'driver': 'mysql', 'host': 'h', 'database': 'd', 'username': 'u', 'password': 'p'}}}\n"
    )
    app = Application(root)
    with pytest.raises(DatabaseError, match=r"flask-artisan\[mysql\]"):
        app.make("db").engine  # noqa: B018

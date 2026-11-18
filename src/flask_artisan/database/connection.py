from pathlib import Path

from sqlalchemy.engine import URL


class DatabaseError(Exception):
    pass


DRIVERS = {"sqlite": "sqlite", "mysql": "mysql+pymysql", "mariadb": "mysql+pymysql"}
DRIVERS["pgsql"] = "postgresql+psycopg"
EXTRAS = {"mysql": "mysql", "mariadb": "mysql", "pgsql": "pgsql"}


def connection_url(conn: dict, base_path: Path) -> str:
    """URL SQLAlchemy d'une connexion de config/database.py (`url` gagne si présente)."""
    if conn.get("url"):
        return conn["url"]
    driver = conn.get("driver")
    if driver not in DRIVERS:
        raise DatabaseError(
            f"Driver de base inconnu '{driver}' : choisissez parmi {', '.join(DRIVERS)}."
        )
    if driver == "sqlite":
        database = conn.get("database", ":memory:")
        if database == ":memory:":
            return "sqlite://"
        path = Path(database)
        full = path if path.is_absolute() else base_path / path
        return URL.create("sqlite", database=str(full)).render_as_string()
    url = URL.create(
        DRIVERS[driver],
        username=conn.get("username"),
        password=conn.get("password"),
        host=conn.get("host"),
        port=conn.get("port"),
        database=conn.get("database"),
    )
    return url.render_as_string(hide_password=False)

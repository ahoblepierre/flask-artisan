import pytest
from cache.conftest import clock  # noqa: F401 — fixture partagée

CACHE = {
    "default": "array",
    "stores": {"array": {"driver": "array"}, "other": {"driver": "array"}},
    "prefix": "t:",
}


@pytest.fixture
def limiter_app(db_app):
    app = db_app()
    app.make("config").set("cache", dict(CACHE))
    with app.app_context():
        yield app

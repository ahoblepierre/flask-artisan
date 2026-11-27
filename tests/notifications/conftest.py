import pytest


@pytest.fixture
def app(db_app):
    app = db_app()
    from . import models  # noqa: F401 — tables NUser, NTeam, notifications

    app.make("db").create_all()
    with app.app_context():
        yield app

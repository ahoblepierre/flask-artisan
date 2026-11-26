import pytest


@pytest.fixture
def queue_app(db_app):
    app = db_app()
    from . import models  # noqa: F401 — table QPodcast dans Model.metadata

    app.make("db").create_all()
    with app.app_context():
        yield app

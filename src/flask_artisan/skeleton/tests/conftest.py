import os

# Avant l'import de l'app (le .env ne les écrase pas) : base en mémoire, recréée à chaque
# test, et cache en mémoire pour que le throttle de /api/login ne persiste pas entre deux runs.
os.environ["DB_CONNECTION"] = "sqlite"
os.environ["DB_DATABASE"] = ":memory:"
os.environ["DB_URL"] = ""
os.environ["CACHE_STORE"] = "array"

import pytest
from wsgi import app

from flask_artisan import DB, Cache


@pytest.fixture
def client():
    with app.app_context():
        DB.create_all()
    yield app.test_client()
    with app.app_context():
        DB.drop_all()
        Cache.flush()

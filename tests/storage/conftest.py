import pytest

from flask_artisan import Application
from flask_artisan.filesystem import LocalDisk

DRIVERS = ["local", "fake"]


@pytest.fixture
def app(make_project):
    return Application(make_project())


@pytest.fixture(params=DRIVERS)
def disk(request, tmp_path, app):
    if request.param == "local":
        yield LocalDisk(tmp_path / "d", url="/files")
        return
    manager = app.make("filesystem")
    yield manager.fake("public")
    manager.restore()

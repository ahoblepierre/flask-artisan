from contextlib import contextmanager

import pytest

from flask_artisan import Application
from flask_artisan.filesystem import LocalDisk, S3Disk

DRIVERS = ["local", "fake", "s3"]


@pytest.fixture
def app(make_project):
    return Application(make_project())


@pytest.fixture(params=DRIVERS)
def disk(request, tmp_path, app):
    if request.param == "local":
        yield LocalDisk(tmp_path / "d", url="/files")
        return
    if request.param == "s3":
        with s3_bucket():
            yield S3Disk("bucket", "us-east-1", root="app")
        return
    manager = app.make("filesystem")
    yield manager.fake("public")
    manager.restore()


@contextmanager
def s3_bucket(name="bucket"):
    boto3 = pytest.importorskip("boto3")
    moto = pytest.importorskip("moto")
    with moto.mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=name)
        yield boto3.client("s3", region_name="us-east-1")

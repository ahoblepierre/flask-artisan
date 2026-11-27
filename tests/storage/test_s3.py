import sys

import pytest

from flask_artisan.filesystem import S3Disk

from .conftest import s3_bucket


@pytest.fixture
def s3():
    with s3_bucket() as client:
        yield client


def test_s3_keys_under_root(s3):
    S3Disk("bucket", "us-east-1", root="app").put("x.txt", "1")
    assert s3.get_object(Bucket="bucket", Key="app/x.txt")["Body"].read() == b"1"


def test_s3_url_variants():
    assert (
        S3Disk("bucket", "us-east-1", root="app").url("x.png")
        == "https://bucket.s3.us-east-1.amazonaws.com/app/x.png"
    )
    assert (
        S3Disk("bucket", "us-east-1", endpoint="http://minio:9000/", root="app").url("x.png")
        == "http://minio:9000/bucket/app/x.png"
    )
    assert (
        S3Disk("bucket", "us-east-1", url="https://cdn.example/", root="app").url("x.png")
        == "https://cdn.example/app/x.png"
    )
    assert (
        S3Disk("bucket", "us-east-1")
        .url("a b.png")
        .endswith("/bucket.s3.us-east-1.amazonaws.com/a%20b.png")
    )


def test_s3_safe_type_inline(s3):
    S3Disk("bucket", "us-east-1").put("a.png", b"x")
    head = s3.head_object(Bucket="bucket", Key="a.png")
    assert head["ContentType"] == "image/png"
    assert "ContentDisposition" not in head


@pytest.mark.parametrize("name", ["a.html", "a.svg", "noext"])
def test_s3_unsafe_type_is_attachment(s3, name):
    S3Disk("bucket", "us-east-1").put(name, b"x")
    assert s3.head_object(Bucket="bucket", Key=name)["ContentDisposition"].startswith("attachment")


def test_s3_path_unsupported():
    with pytest.raises(RuntimeError):
        S3Disk("bucket", "us-east-1").path("x")


def test_missing_boto3_message(monkeypatch):
    monkeypatch.setitem(sys.modules, "boto3", None)
    with pytest.raises(RuntimeError, match=r"flask-artisan\[s3\]"):
        S3Disk("bucket", "us-east-1").exists("x")


def test_manager_builds_s3(make_project, s3):
    from flask_artisan import Application

    app = Application(make_project())
    app.make("config").set(
        "filesystems.disks",
        {"s3": {"driver": "s3", "bucket": "bucket", "region": "us-east-1", "root": "r"}},
    )
    app.make("filesystem").disk("s3").put("x.txt", "1")
    assert s3.get_object(Bucket="bucket", Key="r/x.txt")["Body"].read() == b"1"


def test_s3_files_skip_folder_markers(s3):
    s3.put_object(Bucket="bucket", Key="app/dir/", Body=b"")
    disk = S3Disk("bucket", "us-east-1", root="app")
    disk.put("dir/x.txt", "1")
    assert disk.files("dir") == ["dir/x.txt"]


def test_s3_attachment_has_filename(s3):
    S3Disk("bucket", "us-east-1").put("a.html", b"x")
    assert (
        'filename="a.html"' in s3.head_object(Bucket="bucket", Key="a.html")["ContentDisposition"]
    )


def test_s3_missing_bucket_message(make_project):
    from flask_artisan import Application

    app = Application(make_project())
    app.make("config").set("filesystems.disks", {"s3": {"driver": "s3", "bucket": None}})
    with pytest.raises(ValueError, match="AWS_BUCKET"):
        app.make("filesystem").disk("s3")

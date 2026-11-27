import io

import pytest
from werkzeug.datastructures import FileStorage

from flask_artisan import Route
from flask_artisan.validation import FormRequest, ValidationError, validate


def upload(name="a.png", mimetype="image/png", size=1):
    return FileStorage(stream=io.BytesIO(b"x" * size), filename=name, content_type=mimetype)


def errors(data, rules):
    try:
        validate(data, rules)
    except ValidationError as exc:
        return exc.errors
    return {}


def test_file_rule():
    assert errors({"f": upload()}, {"f": "file"}) == {}
    assert "f" in errors({"f": "texte"}, {"f": "file"})


@pytest.mark.parametrize(
    ("name", "mimetype", "ok"),
    [
        ("a.PNG", "image/png", True),
        ("a.svg", "image/svg+xml", False),
        ("a.png", "text/html", False),
    ],
)
def test_image_rule(name, mimetype, ok):
    assert (errors({"f": upload(name, mimetype)}, {"f": "image"}) == {}) is ok


@pytest.mark.parametrize(("name", "ok"), [("a.jpeg", True), ("b.PDF", True), ("c.png", False)])
def test_mimes_rule(name, ok):
    assert (errors({"f": upload(name)}, {"f": "mimes:jpg,pdf"}) == {}) is ok


def test_max_kilobytes():
    big = upload(size=2049 * 1024)
    big.stream.seek(10)
    found = errors({"f": big}, {"f": "max:2048"})
    assert "kilobytes" in found["f"][0]
    assert big.stream.tell() == 10
    assert errors({"f": upload(size=2048 * 1024)}, {"f": "max:2048"}) == {}
    assert "kilobytes" in errors({"f": upload(size=10)}, {"f": "min:1|between:2,3"})["f"][0]


def test_empty_file_input_is_missing():
    found = errors({"f": FileStorage(stream=io.BytesIO(b""), filename="")}, {"f": "required|file"})
    assert found["f"] == ["The f field is required."]


class AvatarRequest(FormRequest):
    def rules(self):
        return {"avatar": "required|image|max:10"}


def store(request: AvatarRequest):
    file = request.validated()["avatar"]
    return {"name": file.filename, "type": type(file).__name__}


def test_form_request_reads_files(routed_app):
    client = routed_app(lambda: Route.post("/avatar", store)).test_client()
    response = client.post(
        "/avatar",
        data={"avatar": (io.BytesIO(b"x"), "a.png", "image/png")},
        headers={"Accept": "application/json"},
    )
    response.assert_ok().assert_json({"name": "a.png", "type": "FileStorage"})
    client.post(
        "/avatar", data={}, headers={"Accept": "application/json"}
    ).assert_json_validation_errors(["avatar"])

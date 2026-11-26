import pytest

from flask_artisan.application import Application

MAIL_CONFIG = """
config = {
    "default": "array",
    "mailers": {"array": {"transport": "array"}, "log": {"transport": "log"}},
    "from": {"address": "shop@x.org", "name": "Shop"},
}
"""


@pytest.fixture
def mail_app(make_project):
    base = make_project()
    views = base / "resources" / "views" / "emails"
    views.mkdir(parents=True)
    (views / "hello.html").write_text("<p>Hello {{ name }}</p>")
    (views / "hello.txt").write_text("Hello {{ name }}")
    (base / "config" / "mail.py").write_text(MAIL_CONFIG)
    app = Application(base)
    with app.app_context():
        yield app

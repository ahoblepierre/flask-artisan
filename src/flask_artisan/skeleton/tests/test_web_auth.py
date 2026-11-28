import pytest
from app.models.user import User
from wsgi import app

LOGIN_PAGE = {"Referer": "http://localhost/login"}


@pytest.fixture
def ada(client):
    with app.app_context():
        user = User.create(name="Ada", email="ada@example.org", password="secret")
        if hasattr(user, "mark_email_as_verified"):  # /dashboard peut exiger "verified"
            user.mark_email_as_verified()
        return user


def test_dashboard_requires_login(client):
    client.get("/dashboard").assert_redirect("/login")


def test_login_page(client):
    assert 'name="_token"' in client.get("/login").assert_ok().get_data(as_text=True)


def test_bad_login_redirects_back_with_errors(client, ada):
    client.post(
        "/login", data={"email": "ada@example.org", "password": "bad"}, headers=LOGIN_PAGE
    ).assert_redirect("http://localhost/login")
    page = client.get("/login").get_data(as_text=True)
    assert "Ces identifiants" in page
    assert 'value="ada@example.org"' in page


def test_login_then_logout(client, ada):
    client.post("/login", data={"email": "ada@example.org", "password": "secret"}).assert_redirect(
        "/dashboard"
    )
    assert "Ada" in client.get("/dashboard").assert_ok().get_data(as_text=True)
    client.post("/logout").assert_redirect("/")
    client.get("/dashboard").assert_redirect("/login")

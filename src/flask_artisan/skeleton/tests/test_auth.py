from app.models.user import User
from wsgi import app


def test_user_endpoint(client):
    with app.app_context():
        user = User.create(name="Ada", email="ada@example.org", password="secret")
    client.acting_as(user, "api").get("/api/user").assert_ok().assert_json(
        {"email": "ada@example.org"}
    )


def test_login_requires_email(client):
    client.post("/api/login", json={}).assert_status(422).assert_json_validation_errors(
        ["email", "password"]
    )

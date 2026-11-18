from wsgi import app


def test_home_responds():
    assert app.test_client().get("/").status_code == 200

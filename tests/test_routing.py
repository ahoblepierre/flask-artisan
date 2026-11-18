import pytest
from flask import Blueprint, url_for

from flask_artisan import Route, RouteError


class Service:
    pass


class UserController:
    built = 0

    def __init__(self, svc: Service):
        self.svc = svc
        UserController.built += 1

    def index(self):
        return {"users": []}

    def show(self, id, svc: Service):
        return {"id": id, "svc": type(svc).__name__}

    def kind(self):
        return type(self.svc).__name__


class Base:
    def index(self):
        return type(self).__name__


class Child(Base):
    pass


def ping(svc: Service):
    return "pong"


def get(app, url, method="get"):
    return getattr(app.test_client(), method)(url)


def test_get_with_controller_method(routed_app):
    app = routed_app(lambda: Route.get("/users", UserController.index))
    r = get(app, "/users")
    assert r.status_code == 200 and r.get_json() == {"users": []}


def test_url_values_and_injection(routed_app):
    app = routed_app(lambda: Route.get("/users/<int:id>", UserController.show))
    assert get(app, "/users/5").get_json() == {"id": 5, "svc": "Service"}


def test_url_value_stays_string(routed_app):
    app = routed_app(lambda: Route.get("/x/<id>", UserController.show))
    assert get(app, "/x/5").get_json()["id"] == "5"


def test_controller_constructor_injection(routed_app):
    app = routed_app(lambda: Route.get("/k", UserController.kind))
    assert get(app, "/k").get_data(as_text=True) == "Service"


def test_controller_built_per_request(routed_app):
    app = routed_app(lambda: Route.get("/users", UserController.index))
    UserController.built = 0
    get(app, "/users")
    get(app, "/users")
    assert UserController.built == 2


def test_tuple_handler_with_inherited_method(routed_app):
    app = routed_app(lambda: Route.get("/c", (Child, "index")))
    assert get(app, "/c").get_data(as_text=True) == "Child"


def test_plain_function_handler(routed_app):
    app = routed_app(lambda: Route.get("/ping", ping))
    assert get(app, "/ping").get_data(as_text=True) == "pong"


def test_local_function_handler(routed_app):
    def local():
        return "ok"

    app = routed_app(lambda: Route.get("/l", local))
    assert get(app, "/l").get_data(as_text=True) == "ok"


def test_local_class_method_requires_tuple(routed_app):
    class Local:
        def index(self):
            return "x"

    with pytest.raises(RouteError, match="tuple"):
        routed_app(lambda: Route.get("/l", Local.index))


def test_invalid_handler_raises(routed_app):
    with pytest.raises(RouteError, match="/bad"):
        routed_app(lambda: Route.get("/bad", 42))


def test_name_is_endpoint(routed_app):
    app = routed_app(lambda: Route.get("/users", UserController.index).name("users.index"))
    with app.test_request_context():
        assert url_for("users.index") == "/users"


def test_unnamed_routes_get_unique_endpoints(routed_app):
    def declare():
        Route.get("/a", UserController.index)
        Route.get("/b", UserController.index)

    app = routed_app(declare)
    endpoints = {r.endpoint for r in app.url_map.iter_rules() if r.rule in ("/a", "/b")}
    assert len(endpoints) == 2
    assert all("." not in e for e in endpoints)
    assert get(app, "/b").status_code == 200


def test_duplicate_name_raises(routed_app):
    def declare():
        Route.get("/a", UserController.index).name("dup")
        Route.get("/b", UserController.index).name("dup")

    with pytest.raises(RouteError, match="dup"):
        routed_app(declare)


def test_name_clashing_with_blueprint_raises(make_project):
    from flask_artisan import Application, ServiceProvider

    app = Application(make_project())
    app.register_blueprint(Blueprint("admin", __name__))

    class P(ServiceProvider):
        def boot(self):
            Route.get("/d", ping).name("admin.dashboard")

    with pytest.raises(RouteError, match="admin"):
        app.register(P)


def test_methods(routed_app):
    def declare():
        Route.post("/p", ping)
        Route.put("/p", ping)
        Route.patch("/p", ping)
        Route.delete("/p", ping)

    app = routed_app(declare)
    for verb in ("post", "put", "patch", "delete"):
        assert get(app, "/p", verb).status_code == 200
    assert get(app, "/p").status_code == 405


def test_route_after_boot_raises(routed_app):
    routed_app(lambda: None)
    with pytest.raises(RouteError, match="boot"):
        Route.get("/late", ping)


def test_native_route_still_works(routed_app):
    app = routed_app(lambda: None)
    app.add_url_rule("/n", "n", lambda: "native")
    assert get(app, "/n").get_data(as_text=True) == "native"


def test_routes_do_not_leak_between_apps(routed_app):
    a = routed_app(lambda: Route.get("/a", ping))
    b = routed_app(lambda: Route.get("/b", ping))
    assert get(a, "/b").status_code == 404
    assert get(b, "/a").status_code == 404
    assert get(b, "/b").status_code == 200


def test_appears_in_url_map(routed_app):
    app = routed_app(lambda: Route.get("/users", UserController.index))
    assert "/users" in [r.rule for r in app.url_map.iter_rules()]

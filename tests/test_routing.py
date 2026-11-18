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


# --- groupes ---


def test_prefix_group(routed_app):
    def declare():
        with Route.prefix("/admin"):
            Route.get("/users", ping)

    assert get(routed_app(declare), "/admin/users").status_code == 200


def test_nested_groups_concatenate(routed_app):
    def declare():
        with Route.prefix("/a"), Route.prefix("/b").name("b."):
            Route.get("/c", ping).name("x")

    app = routed_app(declare)
    assert get(app, "/a/b/c").status_code == 200
    with app.test_request_context():
        assert url_for("b.x") == "/a/b/c"


def test_group_name_prefix_nests(routed_app):
    def declare():
        with Route.name("admin."), Route.name("users."):
            Route.get("/u", ping).name("index")

    app = routed_app(declare)
    assert "admin.users.index" in app.view_functions


def test_group_middleware_recorded_outer_first(routed_app):
    routes = []

    def declare():
        with Route.middleware("a"), Route.middleware("b"):
            routes.append(Route.get("/m", ping).middleware("c"))
        routes[0].middleware_stack_snapshot = list(routes[0].middleware_stack)
        routes[0].middleware_stack.clear()  # pas de kernel ici : on ne teste que l'ordre

    routed_app(declare)
    assert routes[0].middleware_stack_snapshot == ["a", "b", "c"]


def test_group_exits_cleanly_on_exception(routed_app):
    def declare():
        with pytest.raises(ValueError), Route.prefix("/g"):
            raise ValueError
        Route.get("/after", ping)

    assert get(routed_app(declare), "/after").status_code == 200


class PhotoController:
    def index(self):
        return "index"

    def create(self):
        return "create"

    def store(self):
        return "store"

    def show(self, id):
        return f"show {id}"

    def edit(self, id):
        return f"edit {id}"

    def update(self, id):
        return f"update {id}"

    def destroy(self, id):
        return f"destroy {id}"


class ApiPhotoController:
    def index(self):
        return "index"

    def show(self, id):
        return f"show {id}"


def test_resource_full(routed_app):
    app = routed_app(lambda: Route.resource("photos", PhotoController))
    expected = [
        ("get", "/photos", "index"),
        ("get", "/photos/create", "create"),
        ("post", "/photos", "store"),
        ("get", "/photos/7", "show 7"),
        ("get", "/photos/7/edit", "edit 7"),
        ("put", "/photos/7", "update 7"),
        ("patch", "/photos/7", "update 7"),
        ("delete", "/photos/7", "destroy 7"),
    ]
    for verb, url, body in expected:
        assert get(app, url, verb).get_data(as_text=True) == body, (verb, url)
    with app.test_request_context():
        assert url_for("photos.index") == "/photos"
        assert url_for("photos.create") == "/photos/create"
        assert url_for("photos.show", id=3) == "/photos/3"
        assert url_for("photos.edit", id=3) == "/photos/3/edit"
        for name in ("store", "update", "destroy"):
            assert f"photos.{name}" in app.view_functions


def test_resource_only_defined_methods(routed_app):
    app = routed_app(lambda: Route.resource("photos", ApiPhotoController))
    assert "photos.create" not in app.view_functions
    assert get(app, "/photos/create").get_data(as_text=True) == "show create"


def test_resource_inside_prefix_group(routed_app):
    def declare():
        with Route.prefix("/admin").name("admin."):
            Route.resource("photos", PhotoController)

    app = routed_app(declare)
    assert get(app, "/admin/photos").get_data(as_text=True) == "index"
    assert "admin.photos.index" in app.view_functions

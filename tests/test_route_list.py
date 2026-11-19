from flask_artisan import HttpKernel, Middleware, Route


class Dummy(Middleware):
    pass


class Kernel(HttpKernel):
    middleware = {"auth": Dummy}
    groups = {"web": [], "api": []}


class HomeCtl:
    def index(self):
        return {}


class PhotoCtl:
    def index(self):
        return []

    def update(self, id):
        return {}


def ping():
    return "pong"


def route_list(routed_app, declare):
    app = routed_app(declare, kernel=Kernel)
    result = app.test_cli_runner().invoke(args=["route:list"])
    assert result.exit_code == 0, result.output
    return result.output.splitlines()


def line_for(lines, uri):
    return next(line for line in lines if f" {uri} " in f" {line} ")


def test_route_list_controller_and_function(routed_app):
    def routes():
        Route.get("/", HomeCtl.index).name("home")
        Route.post("/ping", ping)

    lines = route_list(routed_app, routes)
    assert lines[0].split() == ["Méthodes", "URI", "Nom", "Action", "Middlewares"]
    assert line_for(lines, "/").split() == ["GET", "/", "home", "HomeCtl@index"]
    assert line_for(lines, "/ping").split() == ["POST", "/ping", "ping"]


def test_route_list_middlewares_with_params(routed_app):
    def routes():
        with Route.prefix("/api").middleware("auth:api"):
            Route.get("/me", ping).name("api.me")

    lines = route_list(routed_app, routes)
    assert line_for(lines, "/api/me").split() == ["GET", "/api/me", "api.me", "ping", "Dummy:api"]


def test_route_list_resource(routed_app):
    lines = route_list(routed_app, lambda: Route.resource("photos", PhotoCtl))
    assert line_for(lines, "/photos").split() == [
        "GET",
        "/photos",
        "photos.index",
        "PhotoCtl@index",
    ]
    assert line_for(lines, "/photos/<id>").split() == [
        "PUT|PATCH",
        "/photos/<id>",
        "photos.update",
        "PhotoCtl@update",
    ]


def test_route_list_sorted_and_no_head_options(routed_app):
    def routes():
        Route.get("/z", ping)
        Route.get("/a", HomeCtl.index)

    lines = route_list(routed_app, routes)
    body = "\n".join(lines)
    assert "HEAD" not in body and "OPTIONS" not in body
    assert [line.split()[1] for line in lines[1:]] == ["/a", "/z"]


def test_route_list_empty(routed_app):
    lines = route_list(routed_app, lambda: None)
    assert lines == ["Aucune route déclarée."]

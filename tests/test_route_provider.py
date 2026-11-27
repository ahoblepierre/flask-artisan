import pytest

from flask_artisan import (
    Application,
    HttpKernel,
    Middleware,
    Route,
    RouteError,
    RouteServiceProvider,
    ServiceProvider,
)


class Header(Middleware):
    def handle(self, request, next):
        response = next(request)
        response.headers["X-Group"] = "api"
        return response


class Kernel(HttpKernel):
    middleware = {"header": Header}
    groups = {"web": [], "api": ["header"]}


class Routes(RouteServiceProvider):
    kernel = Kernel


class V1Routes(Routes):
    api_prefix = "/v1"


def ping():
    return "pong"


class EarlyProvider(ServiceProvider):
    def boot(self):
        Route.get("/early", ping).middleware("header")


IMPORT = "from test_route_provider import Routes, V1Routes, EarlyProvider"
ROUTE_FILE = "from flask_artisan import Route\n\n\ndef ping():\n    return 'pong'\n\n\n{}\n"


def project(make_project, providers="[Routes]", web=None, api=None):
    base = make_project(providers=providers, extra=IMPORT)
    for name, body in (("web", web), ("api", api)):
        if body is not None:
            (base / "routes").mkdir(exist_ok=True)
            (base / "routes" / f"{name}.py").write_text(body)
    return base


def test_web_routes_loaded(make_project):
    base = project(make_project, web=ROUTE_FILE.format('Route.get("/", ping)'))
    assert Application(base).test_client().get("/").get_data(as_text=True) == "pong"


def test_api_prefix_and_group(make_project):
    base = project(make_project, api=ROUTE_FILE.format('Route.get("/ping", ping)'))
    r = Application(base).test_client().get("/api/ping")
    assert r.status_code == 200 and r.headers["X-Group"] == "api"


def test_missing_files_ignored(make_project):
    Application(project(make_project))


def test_import_error_names_file(make_project):
    with pytest.raises(RouteError, match="api.py"):
        Application(project(make_project, api="raise ValueError('cassé')\n"))


def test_kernel_known_before_other_providers_boot(make_project):
    app = Application(project(make_project, providers="[EarlyProvider, Routes]"))
    assert app.test_client().get("/early").headers["X-Group"] == "api"


def test_custom_api_prefix(make_project):
    base = project(
        make_project, providers="[V1Routes]", api=ROUTE_FILE.format('Route.get("/ping", ping)')
    )
    assert Application(base).test_client().get("/v1/ping").status_code == 200


class WebOnlyKernel(HttpKernel):
    groups = {"web": []}


class WebOnlyRoutes(RouteServiceProvider):
    kernel = WebOnlyKernel


def test_kernel_without_api_group_still_boots(make_project):
    base = make_project(
        providers="[WebOnlyRoutes]",
        extra="from test_route_provider import WebOnlyRoutes",
    )
    (base / "routes").mkdir()
    (base / "routes" / "api.py").write_text(ROUTE_FILE.format('Route.get("/ping", ping)'))
    assert Application(base).test_client().get("/api/ping").status_code == 200


def test_api_provider_marks_json(make_project):
    from flask_artisan.routing import Router

    base = project(
        make_project,
        web=ROUTE_FILE.format('Route.get("/", ping)'),
        api=ROUTE_FILE.format('Route.get("/ping", ping)'),
    )
    flags = {route.rule: route.json for route, _, _ in Application(base).make(Router).registered}
    assert flags == {"/": False, "/api/ping": True, "/storage/<path:path>": False}


class WebKernel(HttpKernel):
    middleware = {"header": Header}
    groups = {"web": ["header"], "api": []}


class WebRoutes(RouteServiceProvider):
    kernel = WebKernel


def test_auth_routes_file_is_loaded_with_web_group(make_project):
    base = make_project(providers="[WebRoutes]", extra="from test_route_provider import WebRoutes")
    (base / "routes").mkdir()
    (base / "routes" / "auth.py").write_text(
        ROUTE_FILE.format('Route.get("/hello", ping).name("hello")')
    )
    r = Application(base).test_client().get("/hello")
    assert r.get_data(as_text=True) == "pong"
    assert r.headers["X-Group"] == "api"  # le middleware du groupe web


def test_missing_auth_routes_file_is_fine(make_project):
    base = project(make_project, web=ROUTE_FILE.format('Route.get("/", ping)'))
    Application(base).test_client().get("/").assert_ok()

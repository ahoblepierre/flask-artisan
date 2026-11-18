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

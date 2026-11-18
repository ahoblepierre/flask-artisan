import pytest

from flask_artisan import HttpKernel, Middleware, Route, RouteError

trace: list[str] = []


@pytest.fixture(autouse=True)
def clear_trace():
    trace.clear()


class Service:
    pass


def tracer(label):
    class Tracer(Middleware):
        def handle(self, request, next):
            trace.append(f"{label}>")
            response = next(request)
            trace.append(f"<{label}")
            return response

    return Tracer


G, A, B = tracer("G"), tracer("a"), tracer("b")


class Stop(Middleware):
    def handle(self, request, next):
        return {"error": "x"}, 415


class ReadsHeaders(Middleware):
    def handle(self, request, next):
        response = next(request)
        response.headers["X-Seen"] = response.headers.get("Content-Type", "")
        return response


class AddsHeader(Middleware):
    def handle(self, request, next):
        response = next(request)
        response.headers["X-Api"] = "1"
        return response


class Tag(Middleware):
    def handle(self, request, next, *params):
        trace.append(",".join(params))
        return next(request)


class Injected(Middleware):
    built = 0

    def __init__(self, svc: Service):
        self.svc = svc
        Injected.built += 1

    def handle(self, request, next):
        trace.append(type(self.svc).__name__)
        return next(request)


class Catches(Middleware):
    def handle(self, request, next):
        try:
            return next(request)
        except ValueError:
            return "caught", 400


class Kernel(HttpKernel):
    global_middleware = [G]
    middleware = {
        "a": A,
        "b": B,
        "stop": Stop,
        "reads": ReadsHeaders,
        "header": AddsHeader,
        "tag": Tag,
        "injected": Injected,
        "catches": Catches,
    }
    groups = {"web": [], "api": ["tag:x"]}


def handler():
    trace.append("handler")
    return "ok"


def boom():
    raise ValueError


def client(routed_app, declare):
    return routed_app(declare, kernel=Kernel).test_client()


def test_onion_order(routed_app):
    def declare():
        with Route.middleware("a"):
            Route.get("/", handler).middleware("b")

    assert client(routed_app, declare).get("/").status_code == 200
    assert trace == ["G>", "a>", "b>", "handler", "<b", "<a", "<G"]


def test_short_circuit_dict(routed_app):
    r = client(routed_app, lambda: Route.get("/", handler).middleware("reads", "stop")).get("/")
    assert r.status_code == 415 and r.get_json() == {"error": "x"}
    assert r.headers["X-Seen"] == "application/json"
    assert "handler" not in trace


def test_after_can_modify_response(routed_app):
    r = client(routed_app, lambda: Route.get("/", handler).middleware("header")).get("/")
    assert r.headers["X-Api"] == "1"


def test_params(routed_app):
    client(routed_app, lambda: Route.get("/", handler).middleware("tag:60,1")).get("/")
    assert "60,1" in trace


def test_group_alias_expands(routed_app):
    client(routed_app, lambda: Route.get("/", handler).middleware("api")).get("/")
    assert "x" in trace


def test_class_in_group_and_route(routed_app):
    def declare():
        with Route.middleware(A):
            Route.get("/", handler).middleware(B)

    client(routed_app, declare).get("/")
    assert trace[:3] == ["G>", "a>", "b>"]


def test_duplicate_runs_once(routed_app):
    def declare():
        with Route.middleware("a"):
            Route.get("/", handler).middleware("a", A)

    client(routed_app, declare).get("/")
    assert trace.count("a>") == 1


def test_unknown_alias_raises_at_registration(routed_app):
    with pytest.raises(RouteError, match="nope"):
        routed_app(lambda: Route.get("/x", handler).middleware("nope"), kernel=Kernel)


def test_middleware_injected_and_built_per_request(routed_app):
    c = client(routed_app, lambda: Route.get("/", handler).middleware("injected"))
    Injected.built = 0
    c.get("/")
    c.get("/")
    assert Injected.built == 2 and "Service" in trace


def test_exception_traverses_middleware(routed_app):
    def declare():
        Route.get("/caught", boom).middleware("catches")
        Route.get("/handled", boom)

    app = routed_app(declare, kernel=Kernel)
    app.register_error_handler(ValueError, lambda e: ("teapot", 418))
    c = app.test_client()
    assert c.get("/caught").status_code == 400
    assert c.get("/handled").status_code == 418


def test_global_not_applied_to_native_routes(routed_app):
    app = routed_app(lambda: None, kernel=Kernel)
    app.add_url_rule("/n", "n", handler)
    app.test_client().get("/n")
    assert trace == ["handler"]


def test_no_kernel_means_no_middleware(routed_app):
    routed_app(lambda: Route.get("/", handler)).test_client().get("/")
    assert trace == ["handler"]

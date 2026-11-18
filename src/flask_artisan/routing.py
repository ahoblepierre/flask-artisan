import inspect
import sys
from collections.abc import Callable
from contextlib import contextmanager
from typing import Any

from flask import request

from flask_artisan.middleware import HttpKernel, resolve


class RouteError(Exception):
    pass


class PendingRoute:
    """Une route déclarée, poussée dans Flask à la fin du boot (pour que `.name()` s'applique)."""

    def __init__(self, rule: str, methods: list[str], handler: tuple, name_prefix: str = ""):
        self.rule = rule
        self.methods = methods
        self.handler = handler
        self.name_prefix = name_prefix
        self.endpoint_name: str | None = None
        self.middleware_stack: list = []

    def name(self, name: str) -> "PendingRoute":
        self.endpoint_name = self.name_prefix + name
        return self

    def middleware(self, *items) -> "PendingRoute":
        self.middleware_stack.extend(items)
        return self


class RouteGroup:
    """Attributs partagés par les routes déclarées dans un bloc `with`."""

    def __init__(self, router: "Router", prefix: str = "", name: str = "", middleware=()):
        self._router = router
        self._prefix = prefix
        self._name = name
        self._middleware = list(middleware)

    def prefix(self, prefix: str) -> "RouteGroup":
        self._prefix += prefix
        return self

    def name(self, name: str) -> "RouteGroup":
        self._name += name
        return self

    def middleware(self, *items) -> "RouteGroup":
        self._middleware.extend(items)
        return self

    def __enter__(self) -> "RouteGroup":  # noqa: PYI034 (typing.Self exige 3.11)
        self._router._groups.append(self)
        return self

    def __exit__(self, *exc) -> None:
        self._router._groups.remove(self)


_RESOURCE = [
    ("index", ["GET"], ""),
    ("create", ["GET"], "/create"),
    ("store", ["POST"], ""),
    ("show", ["GET"], "/<id>"),
    ("edit", ["GET"], "/<id>/edit"),
    ("update", ["PUT", "PATCH"], "/<id>"),
    ("destroy", ["DELETE"], "/<id>"),
]


class Router:
    """Collecte les routes déclarées avec la façade `Route` et les enregistre dans Flask."""

    def __init__(self, app):
        self._app = app
        self._pending: list[PendingRoute] = []
        self._collecting = 0
        self._groups: list[RouteGroup] = []
        self._kernel: type[HttpKernel] = HttpKernel

    def use_kernel(self, kernel: type[HttpKernel]) -> None:
        self._kernel = kernel

    def prefix(self, prefix: str) -> RouteGroup:
        return RouteGroup(self, prefix=prefix)

    def name(self, name: str) -> RouteGroup:
        return RouteGroup(self, name=name)

    def middleware(self, *items) -> RouteGroup:
        return RouteGroup(self, middleware=items)

    def group(self, prefix: str = "", middleware=(), name: str = "") -> RouteGroup:
        return RouteGroup(self, prefix=prefix, name=name, middleware=middleware)

    def resource(self, name: str, controller: type) -> None:
        """Routes CRUD pour les méthodes que `controller` définit (index, show, store…)."""
        base = "/" + name.strip("/")
        for method, verbs, suffix in _RESOURCE:
            if callable(getattr(controller, method, None)):
                route = self._add(base + suffix, verbs, (controller, method))
                route.name(f"{name.strip('/').replace('/', '.')}.{method}")

    def get(self, rule: str, handler) -> PendingRoute:
        return self._add(rule, ["GET"], handler)

    def post(self, rule: str, handler) -> PendingRoute:
        return self._add(rule, ["POST"], handler)

    def put(self, rule: str, handler) -> PendingRoute:
        return self._add(rule, ["PUT"], handler)

    def patch(self, rule: str, handler) -> PendingRoute:
        return self._add(rule, ["PATCH"], handler)

    def delete(self, rule: str, handler) -> PendingRoute:
        return self._add(rule, ["DELETE"], handler)

    @contextmanager
    def collecting(self):
        """Fenêtre pendant laquelle on peut déclarer des routes ; à la sortie, flush()."""
        self._collecting += 1
        try:
            yield
        except BaseException:
            self._pending.clear()
            raise
        finally:
            self._collecting -= 1
        if not self._collecting:
            self.flush()

    def flush(self) -> None:
        pending, self._pending = self._pending, []
        for route in pending:
            endpoint = route.endpoint_name
            if endpoint is None:
                endpoint = self._auto_endpoint(route)
            else:
                self._check_name(route, endpoint)
            try:
                stack = resolve(
                    self._kernel, [*self._kernel.global_middleware, *route.middleware_stack]
                )
            except LookupError as exc:
                raise RouteError(
                    f"Middleware inconnu '{exc.args[0]}' sur la route {route.rule} : "
                    "déclarez-le dans `middleware` ou `groups` du kernel."
                ) from None
            view = self._view(route, stack)
            self._app.add_url_rule(route.rule, endpoint, view, methods=route.methods)

    def _add(self, rule: str, methods: list[str], handler) -> PendingRoute:
        if not self._collecting:
            raise RouteError(
                f"Route {rule} déclarée hors du boot : déclarez vos routes dans routes/*.py "
                "ou dans boot() d'un provider."
            )
        rule = _join(*(g._prefix for g in self._groups), rule)
        name_prefix = "".join(g._name for g in self._groups)
        route = PendingRoute(rule, methods, _resolve_handler(rule, handler), name_prefix)
        route.middleware_stack = [m for g in self._groups for m in g._middleware]
        self._pending.append(route)
        return route

    def _check_name(self, route: PendingRoute, endpoint: str) -> None:
        if endpoint in self._app.view_functions:
            raise RouteError(f"Le nom de route '{endpoint}' est déjà pris ({route.rule}).")
        # Flask lit ce qui précède un point comme un nom de blueprint (hooks, error handlers).
        parts = endpoint.split(".")
        for i in range(1, len(parts)):
            blueprint = ".".join(parts[:i])
            if blueprint in self._app.blueprints:
                raise RouteError(
                    f"Le nom de route '{endpoint}' ({route.rule}) commence par le nom du "
                    f"blueprint '{blueprint}' : Flask lui appliquerait les hooks de ce blueprint."
                )

    def _auto_endpoint(self, route: PendingRoute) -> str:
        cls, target = route.handler
        base = f"{cls.__name__}@{target}" if cls else getattr(target, "__name__", "route")
        endpoint, n = base, 1
        while endpoint in self._app.view_functions:
            n += 1
            endpoint = f"{base}_{n}"
        return endpoint

    def _view(self, route: PendingRoute, stack: list) -> Callable:
        app = self._app
        cls, target = route.handler

        def view(**values):
            def run(i, req):
                if i == len(stack):
                    fn = getattr(app.make(cls), target) if cls else target
                    return app.make_response(app.call(fn, **values))
                middleware, params = stack[i]
                # make_response : un middleware peut renvoyer un dict ou un tuple comme une vue.
                return app.make_response(
                    app.make(middleware).handle(req, lambda r: run(i + 1, r), *params)
                )

            return run(0, request._get_current_object())

        return view


def _join(*parts: str) -> str:
    """Concatène préfixes et URL : ("/admin", "/") → "/admin", ("/api", "/users/") → "/api/users/"."""
    joined = "/" + "/".join(p.strip("/") for p in parts if p.strip("/"))
    return joined + "/" if parts[-1].endswith("/") and joined != "/" else joined


def _resolve_handler(rule: str, handler: Any) -> tuple:
    """Renvoie (classe, nom de méthode) pour un controller, ou (None, fonction)."""
    if (
        isinstance(handler, tuple)
        and len(handler) == 2
        and isinstance(handler[0], type)
        and isinstance(handler[1], str)
    ):
        cls, attr = handler
        if not callable(getattr(cls, attr, None)):
            raise RouteError(f"Route {rule} : {cls.__name__} n'a pas de méthode '{attr}'.")
        return cls, attr

    if inspect.isfunction(handler):
        parts = handler.__qualname__.split(".")
        if len(parts) == 1 or parts[-2] == "<locals>":
            return None, handler
        owner = None if "<locals>" in parts else sys.modules.get(handler.__module__)
        for part in parts[:-1]:
            owner = getattr(owner, part, None)
        if not isinstance(owner, type):
            raise RouteError(
                f"Route {rule} : impossible de retrouver la classe de {handler.__qualname__} "
                f'(classe locale ?). Utilisez la forme tuple ({parts[-2]}, "{parts[-1]}").'
            )
        return owner, parts[-1]

    raise RouteError(
        f"Route {rule} : handler invalide {handler!r}. Attendu Controller.methode, "
        '(Controller, "methode") ou une fonction.'
    )

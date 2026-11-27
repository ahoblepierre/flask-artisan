import importlib.util
import inspect
import json
import logging
import sys
import types
import typing
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from flask import redirect, request, session
from werkzeug.exceptions import Forbidden

from flask_artisan.middleware import HttpKernel, expects_json, resolve
from flask_artisan.validation import AuthorizationError, FormRequest, ValidationError

# Jamais gardés en session pour old() (comme dontFlash de Laravel).
DONT_FLASH = {"password", "password_confirmation", "current_password", "_token"}
# Budget des saisies flashées, en JSON échappé (\uXXXX) comme dans le cookie de session :
# au-delà d'environ 4 Ko, le navigateur ignorerait le cookie. Les plus grosses sautent d'abord.
MAX_OLD_BYTES = 2000


logger = logging.getLogger(__name__)


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
        self.json = False  # route d'API : erreurs toujours en JSON, jamais de redirection

    def name(self, name: str) -> "PendingRoute":
        self.endpoint_name = self.name_prefix + name
        return self

    def middleware(self, *items) -> "PendingRoute":
        self.middleware_stack.extend(items)
        return self


class RouteGroup:
    """Attributs partagés par les routes déclarées dans un bloc `with`."""

    def __init__(
        self, router: "Router", prefix: str = "", name: str = "", middleware=(), json=False
    ):
        self._router = router
        self._json = json
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
        # (route, endpoint, middlewares résolus) de chaque route poussée dans Flask : route:list.
        self.registered: list[tuple[PendingRoute, str, list]] = []

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

    def load(self, path: Path, prefix: str = "", middleware=(), json: bool = False) -> None:
        """Exécute un fichier de routes dans un groupe ; un fichier absent est ignoré."""
        path = Path(path)
        if not path.exists():
            return
        spec = importlib.util.spec_from_file_location(f"flask_artisan_routes_{path.stem}", path)
        module = importlib.util.module_from_spec(spec)
        with RouteGroup(self, prefix=prefix, middleware=middleware, json=json):
            try:
                spec.loader.exec_module(module)
            except Exception as exc:
                raise RouteError(f"Erreur dans {path} : {exc}") from exc

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
            _check_form_request_defaults(self._app, route)
            view = self._view(route, stack)
            self._app.add_url_rule(route.rule, endpoint, view, methods=route.methods)
            self.registered.append((route, endpoint, stack))

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
        route.json = any(g._json for g in self._groups)
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
                    try:
                        rv = app.call(fn, **values)
                    except (ValidationError, AuthorizationError) as exc:
                        # Réponse rendue ici pour que les middlewares la voient (comme Laravel).
                        if route.json or expects_json(req):
                            return exc.get_response()
                        if isinstance(exc, AuthorizationError):
                            return Forbidden().get_response()
                        return _redirect_back(req, exc.errors)
                    return app.make_response(_jsonable(app, rv))
                middleware, params = stack[i]
                # make_response : un middleware peut renvoyer un dict ou un tuple comme une vue.
                return app.make_response(
                    app.make(middleware).handle(req, lambda r: run(i + 1, r), *params)
                )

            if route.json:
                request.environ["flask_artisan.route_json"] = True  # lu par Authenticate
            return run(0, request._get_current_object())

        return view


def _check_form_request_defaults(app, route: PendingRoute) -> None:
    """Une FormRequest avec valeur par défaut : le conteneur prendrait le défaut, sans valider."""
    cls, target = route.handler
    fn = getattr(cls, target) if cls else target
    try:
        hints = typing.get_type_hints(fn)
    except Exception as exc:  # noqa: BLE001 (le conteneur échouera à l'appel : on prévient tôt)
        logger.warning(
            "Route %s : annotations illisibles (%s) ; l'appel échouera, et une FormRequest "
            "avec valeur par défaut n'a pas pu être vérifiée.",
            route.rule,
            exc,
        )
        return
    for name, param in inspect.signature(fn).parameters.items():
        hint = hints.get(name)
        # StoreRequest | None, Optional[...] (et, en 3.10, tout `= None` : get_type_hints l'ajoute).
        union = typing.get_origin(hint) in (typing.Union, types.UnionType)
        candidates = typing.get_args(hint) if union else (hint,)
        if not union and app.bound(hint):
            continue  # liée explicitement : le conteneur la construit (et la valide) avant le défaut
        if param.default is not param.empty and any(
            isinstance(c, type) and issubclass(c, FormRequest) for c in candidates
        ):
            raise RouteError(
                f"Route {route.rule} : le paramètre '{name}' (FormRequest) ne doit pas avoir "
                "de valeur par défaut : le conteneur la prendrait et la validation serait sautée."
            )


def _redirect_back(req, errors: dict):
    """Erreurs et saisies flashées pour la requête suivante, retour à la page précédente."""
    data = {**req.args.to_dict(), **req.form.to_dict()}
    session["_flash_errors"] = errors
    candidates = sorted(
        (
            (len(json.dumps(k)) + len(json.dumps(v)), k, v)
            for k, v in data.items()
            if k not in DONT_FLASH
        ),
    )
    old, total = {}, 0
    for size, key, value in candidates:
        total += size
        if total > MAX_OLD_BYTES:
            break
        old[key] = value
    session["_flash_old"] = old
    referrer = req.referrer or ""
    # Même site seulement : jamais de redirection ouverte.
    return redirect(referrer if referrer.startswith(req.host_url) else req.script_root + "/", 302)


def _jsonable(app, rv: Any) -> Any:
    """Un objet sérialisable (ex. un modèle, avec `to_dict`) devient une réponse JSON."""
    body = rv[0] if isinstance(rv, tuple) else rv
    if not hasattr(body, "to_dict") or isinstance(body, (dict, list, str, bytes)):
        return rv
    response = app.json.response(body)
    return (response, *rv[1:]) if isinstance(rv, tuple) else response


def _join(*parts: str) -> str:
    """Concatène préfixes et URL : ("/admin", "/") → "/admin", ("/api", "/users/") → "/api/users/"."""
    joined = "/" + "/".join(p.strip("/") for p in parts if p.strip("/"))
    keep_slash = parts[-1].endswith("/") and parts[-1].strip("/") != ""
    return joined + "/" if keep_slash else joined


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

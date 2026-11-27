from typing import ClassVar


def expects_json(request) -> bool:
    # Type préféré seulement : un `*/*` (curl, navigateurs) ne réclame pas du JSON.
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return True  # comme expectsJson de Laravel : un appel AJAX
    return request.is_json or "json" in (request.accept_mimetypes.best or "")


class Middleware:
    """Middleware en oignon : agit avant `next(request)`, après, ou court-circuite."""

    def handle(self, request, next):
        return next(request)


class HttpKernel:
    """Déclare les middlewares du projet : globaux, alias et groupes."""

    global_middleware: ClassVar[list] = []
    middleware: ClassVar[dict] = {}
    groups: ClassVar[dict] = {"web": [], "api": []}


def resolve(kernel: type[HttpKernel], items) -> list[tuple[type, tuple[str, ...]]]:
    """Convertit alias, "alias:p1,p2", groupes et classes en (classe, paramètres), sans doublon.

    Lève LookupError(alias) pour un alias inconnu.
    """
    entries = []
    for item in items:
        if isinstance(item, str) and item in kernel.groups:
            entries.extend(_entry(kernel, sub) for sub in kernel.groups[item])
        else:
            entries.append(_entry(kernel, item))
    return list(dict.fromkeys(entries))


def _entry(kernel: type[HttpKernel], item) -> tuple[type, tuple[str, ...]]:
    if isinstance(item, type):
        return item, ()
    alias, _, raw = item.partition(":")
    if alias not in kernel.middleware:
        raise LookupError(alias)
    return kernel.middleware[alias], tuple(raw.split(",")) if raw else ()

from flask import current_app, redirect, url_for
from werkzeug.routing import BuildError

from flask_artisan.auth.manager import AuthManager, TokenGuard
from flask_artisan.middleware import Middleware

UNAUTHENTICATED = ({"message": "Unauthenticated."}, 401)


def expects_json(request) -> bool:
    # Type préféré seulement : un `*/*` (curl, navigateurs) ne réclame pas du JSON.
    return request.is_json or "json" in (request.accept_mimetypes.best or "")


class Authenticate(Middleware):
    """`auth`, `auth:api`, `auth:web,api` : laisse passer si un des guards trouve un utilisateur."""

    def handle(self, request, next, *guards):
        auth = current_app.make(AuthManager)
        tried = []
        for name in guards or (None,):
            guard = auth.guard(name)
            tried.append(guard)
            if guard.user() is not None:
                if name is not None:
                    auth.should_use(name)
                return next(request)
        # Que des guards token (auth:api) : un client d'API, jamais de page de login.
        api_only = all(isinstance(g, TokenGuard) for g in tried)
        if api_only or expects_json(request) or "login" not in current_app.view_functions:
            return UNAUTHENTICATED
        try:
            return redirect(url_for("login"))
        except BuildError:  # route login qui attend des paramètres
            return UNAUTHENTICATED

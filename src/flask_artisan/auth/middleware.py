from flask import current_app, redirect, url_for

from flask_artisan.auth.manager import AuthManager
from flask_artisan.middleware import Middleware

UNAUTHENTICATED = ({"message": "Unauthenticated."}, 401)


def expects_json(request) -> bool:
    # Type préféré seulement : un `*/*` (curl, navigateurs) ne réclame pas du JSON.
    return request.is_json or "json" in (request.accept_mimetypes.best or "")


class Authenticate(Middleware):
    """`auth`, `auth:api`, `auth:web,api` : laisse passer si un des guards trouve un utilisateur."""

    def handle(self, request, next, *guards):
        auth = current_app.make(AuthManager)
        for name in guards or (None,):
            if auth.guard(name).user() is not None:
                if name is not None:
                    auth.should_use(name)
                return next(request)
        if not expects_json(request) and "login" in current_app.view_functions:
            return redirect(url_for("login"))
        return UNAUTHENTICATED

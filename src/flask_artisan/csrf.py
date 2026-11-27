"""Protection CSRF façon Laravel : champ `_token` ou en-tête `X-CSRF-TOKEN`, statut 419."""

import hmac

from flask import current_app, session
from werkzeug.wrappers import Response

from flask_artisan.middleware import Middleware, expects_json

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

PAGE_EXPIRED = (
    "<!doctype html><title>419 Page expirée</title><h1>Page expirée</h1>"
    "<p>Le formulaire a expiré. Rechargez la page et réessayez.</p>"
)


def _running_tests() -> bool:
    # TESTING seul ne suffit pas (un TESTING oublié en production couperait le CSRF) :
    # il faut aussi APP_ENV=testing, comme runningUnitTests de Laravel.
    return current_app.testing and current_app.make("config").get("app.env") == "testing"


class VerifyCsrfToken(Middleware):
    def handle(self, request, next):
        if request.method in SAFE_METHODS or _running_tests():
            return next(request)
        sent = request.form.get("_token") or request.headers.get("X-CSRF-TOKEN") or ""
        # session.get, jamais csrf_token() : un jeton créé ici ne protégerait rien.
        expected = session.get("_token") or ""
        if sent and expected and hmac.compare_digest(sent.encode(), expected.encode()):
            return next(request)
        if expects_json(request):
            return {"message": "CSRF token mismatch."}, 419
        return Response(PAGE_EXPIRED, status=419, mimetype="text/html")

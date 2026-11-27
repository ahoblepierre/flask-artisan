import hashlib
import hmac
import time

from flask import current_app, url_for

from flask_artisan.middleware import Middleware

INVALID = ({"message": "Invalid signature."}, 403)


def _now() -> float:
    return time.time()


def _sign(message: str) -> str:
    key = str(current_app.config["SECRET_KEY"]).encode()
    return hmac.new(key, message.encode(), hashlib.sha256).hexdigest()


def signed_url(endpoint: str, expires: int | None = None, **values) -> str:
    """URL de `endpoint` signée par APP_KEY ; `expires` : durée de validité en secondes.

    On signe le chemin et la requête, pas l'hôte : un proxy qui réécrit l'hôte ne casse pas le lien.
    """
    external = values.pop("_external", False)
    if expires is not None:
        values["expires"] = int(_now()) + expires
    relative = url_for(endpoint, **values)
    signature = _sign(relative)
    if external:
        # Même chemin, même ordre des paramètres : signature ajoutée en dernier.
        return url_for(endpoint, **values, signature=signature, _external=True)
    return f"{relative}{'&' if '?' in relative else '?'}signature={signature}"


def has_valid_signature(req) -> bool:
    params = req.query_string.decode().split("&") if req.query_string else []
    signatures = [p for p in params if p.startswith("signature=")]
    if len(signatures) != 1 or params[-1] != signatures[0]:
        return False
    rest = params[:-1]
    message = req.path + ("?" + "&".join(rest) if rest else "")
    if not hmac.compare_digest(signatures[0].removeprefix("signature="), _sign(message)):
        return False
    for param in rest:
        if param.startswith("expires="):
            try:
                return int(param.removeprefix("expires=")) > _now()
            except ValueError:
                return False
    return True


class ValidateSignature(Middleware):
    """`signed` : 403 si l'URL n'a pas été produite par `signed_url` ou a expiré."""

    def handle(self, request, next):
        if not has_valid_signature(request):
            return INVALID
        return next(request)

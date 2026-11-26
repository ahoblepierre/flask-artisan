"""Limitation de débit façon Laravel : `RateLimiter` et le middleware `throttle`.

Les compteurs vivent dans le cache (store `cache.limiter`, sinon le store par défaut).
"""

import hashlib
import time

from flask import current_app

from flask_artisan.middleware import Middleware

__all__ = ["RateLimiter", "ThrottleRequests"]


class RateLimiter:
    """Le service `"limiter"` (façade `RateLimiter`) : compte des tentatives sur une fenêtre."""

    def __init__(self, app):
        self._app = app

    def _store(self):
        return self._app.make("cache").store(self._app.make("config").get("cache.limiter"))

    def hit(self, key: str, decay_seconds: int = 60) -> int:
        store = self._store()
        store.add(key + ":timer", int(time.time()) + decay_seconds, decay_seconds)
        added = store.add(key, 0, decay_seconds)
        hits = store.increment(key)
        if not added and hits == 1:  # la clé a expiré entre add et increment : sinon, sans TTL
            store.put(key, 1, decay_seconds)
        return hits

    def attempts(self, key: str) -> int:
        return self._store().get(key, 0)

    def too_many_attempts(self, key: str, max_attempts: int) -> bool:
        if self.attempts(key) >= max_attempts:
            if self._store().has(key + ":timer"):
                return True
            self.clear(key)
        return False

    def remaining(self, key: str, max_attempts: int) -> int:
        return max(0, max_attempts - self.attempts(key))

    def available_in(self, key: str) -> int:
        return max(0, self._store().get(key + ":timer", 0) - int(time.time()))

    def clear(self, key: str) -> None:
        store = self._store()
        store.forget(key)
        store.forget(key + ":timer")

    def attempt(self, key: str, max_attempts: int, callback, decay_seconds: int = 60):
        if self.too_many_attempts(key, max_attempts):
            return False
        self.hit(key, decay_seconds)
        result = callback()
        return True if result is None else result


def _positive(value, what: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = 0
    if number <= 0:
        raise ValueError(
            f"throttle : {what} doit être un entier positif (throttle:<max>,<minutes>), "
            f"reçu {value!r}."
        )
    return number


def _identity(request) -> str:
    # Seulement un utilisateur déjà résolu par un guard (middleware `auth` placé avant) :
    # throttle ne lit ni session ni token lui-même (pas de requête SQL, pas de Vary: Cookie).
    for name, user in request.environ.get("flask_artisan.auth", {}).items():
        if name.startswith("user:") and user is not None:
            return f"{name}:{user.id}"  # "user:<guard>:<id>" : deux modèles, deux compteurs
    return f"ip:{request.remote_addr}"


class ThrottleRequests(Middleware):
    """`throttle:<max>,<minutes>` : au-delà de `max` requêtes par fenêtre, réponse 429."""

    def handle(self, request, next, max_attempts="60", decay_minutes="1"):
        limit = _positive(max_attempts, "le nombre de requêtes")
        minutes = _positive(decay_minutes, "la durée en minutes")
        signature = f"{limit}|{minutes}|{_identity(request)}"
        key = "throttle:" + hashlib.sha1(signature.encode()).hexdigest()
        limiter = current_app.make(RateLimiter)

        refused = limiter.too_many_attempts(key, limit)
        if not refused and limiter.hit(key, minutes * 60) > limit:
            # Rafale : d'autres requêtes ont compté entre la lecture et le hit (atomique).
            limiter._store().decrement(key)  # une requête refusée ne compte pas
            refused = True
        if refused:
            retry = limiter.available_in(key)
            headers = {
                "Retry-After": str(retry),
                "X-RateLimit-Limit": str(limit),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(int(time.time()) + retry),
            }
            return current_app.make_response(({"message": "Too Many Attempts."}, 429, headers))

        response = next(request)
        # setdefault : un throttle plus proche de la route (plus strict) a déjà répondu.
        response.headers.setdefault("X-RateLimit-Limit", str(limit))
        response.headers.setdefault("X-RateLimit-Remaining", str(limiter.remaining(key, limit)))
        return response

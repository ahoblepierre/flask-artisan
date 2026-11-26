"""Limitation de débit façon Laravel : `RateLimiter` et le middleware `throttle`.

Les compteurs vivent dans le cache (store `cache.limiter`, sinon le store par défaut).
"""

import time

__all__ = ["RateLimiter"]


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

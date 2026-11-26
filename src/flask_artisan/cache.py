"""Cache façon Laravel : `Cache.get/put/remember/…`, stores `array`, `file` et `redis`.

Valeurs en JSON (jamais de pickle), avec la sérialisation des queues : un modèle est stocké par
son identifiant et relu en base à la lecture.
"""

import json
import logging
import math
import re
import time
from datetime import timedelta

from flask_artisan.queue.serialization import dump, load

__all__ = ["ArrayStore", "CacheManager", "Store"]

logger = logging.getLogger("flask_artisan.cache")

_MISSING = object()
PUBLIC = (
    "get",
    "put",
    "add",
    "forever",
    "remember",
    "remember_forever",
    "has",
    "missing",
    "pull",
    "forget",
    "increment",
    "decrement",
    "flush",
)


def _seconds(ttl) -> int | None:
    """Durée en secondes entières (arrondie au-dessus) ; None = sans expiration."""
    if ttl is None:
        return None
    if isinstance(ttl, timedelta):
        ttl = ttl.total_seconds()
    if isinstance(ttl, bool) or not isinstance(ttl, (int, float)):
        raise TypeError(f"TTL invalide : {ttl!r} (secondes, timedelta ou None).")
    return math.ceil(ttl)


class Store:
    """Logique commune ; chaque pilote ne stocke que du texte JSON (méthodes `_…`)."""

    def __init__(self, prefix: str):
        self.prefix = prefix

    # --- stockage brut, par pilote (clé déjà préfixée) ---

    def _get(self, k: str) -> str | None:
        raise NotImplementedError

    def _put(self, k: str, text: str, seconds: int | None) -> None:
        raise NotImplementedError

    def _add(self, k: str, text: str, seconds: int | None) -> bool:
        raise NotImplementedError

    def _delete(self, k: str) -> bool:
        raise NotImplementedError

    def _pull(self, k: str) -> str | None:
        raise NotImplementedError

    def _increment(self, k: str, by: int) -> int:
        raise NotImplementedError

    def _flush(self) -> None:
        raise NotImplementedError

    # --- encodage ---

    def _key(self, key) -> str:
        if not isinstance(key, str):
            raise TypeError(f"Une clé de cache est une chaîne, pas {key!r}.")
        if not key:
            raise ValueError("Une clé de cache ne peut pas être vide.")
        return self.prefix + key

    @staticmethod
    def _encode(key: str, value) -> str:
        return json.dumps(dump(value, f"clé {key!r}"))

    def _decode(self, k: str, key: str, text: str | None):
        if text is None:
            return _MISSING
        from flask_artisan.database.query import ModelNotFound

        try:
            return load(json.loads(text))
        except (ModelNotFound, TypeError, ValueError) as exc:
            # Modèle supprimé, classe déplacée, donnée corrompue : absent, jamais une 404.
            logger.warning("Cache : valeur illisible pour %r, supprimée (%s).", key, exc)
            self._delete(k)
            return _MISSING

    # --- API publique ---

    def get(self, key, default=None):
        value = self._decode(self._key(key), key, self._get(self._key(key)))
        if value is _MISSING or value is None:
            return default() if callable(default) else default
        return value

    def put(self, key, value, ttl=None) -> bool:
        k, seconds = self._key(key), _seconds(ttl)
        if value is None or (seconds is not None and seconds <= 0):
            self._delete(k)
            return True
        self._put(k, self._encode(key, value), seconds)
        return True

    def add(self, key, value, ttl=None) -> bool:
        k, seconds = self._key(key), _seconds(ttl)
        if value is None or (seconds is not None and seconds <= 0):
            return False
        return self._add(k, self._encode(key, value), seconds)

    def forever(self, key, value) -> bool:
        return self.put(key, value)

    def remember(self, key, ttl, callback):
        value = self.get(key, _MISSING)
        if value is not _MISSING:
            return value
        value = callback()
        if value is not None:
            self.put(key, value, ttl)
        return value

    def remember_forever(self, key, callback):
        return self.remember(key, None, callback)

    def has(self, key) -> bool:
        return self.get(key) is not None

    def missing(self, key) -> bool:
        return not self.has(key)

    def pull(self, key, default=None):
        k = self._key(key)
        value = self._decode(k, key, self._pull(k))
        if value is _MISSING or value is None:
            return default() if callable(default) else default
        return value

    def forget(self, key) -> bool:
        return self._delete(self._key(key))

    def increment(self, key, by: int = 1) -> int:
        if isinstance(by, bool) or not isinstance(by, int):
            raise TypeError(f"increment attend un entier, pas {by!r}.")
        return self._increment(self._key(key), by)

    def decrement(self, key, by: int = 1) -> int:
        return self.increment(key, -by)

    def flush(self) -> None:
        self._flush()


def _as_int(k: str, text: str) -> int:
    value = json.loads(text)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"increment : la valeur de {k!r} n'est pas un entier.")  # noqa: TRY004 — même erreur que redis (INCRBY)
    return value


class ArrayStore(Store):
    """En mémoire du processus : tests, ou cache local d'un seul processus."""

    def __init__(self, prefix: str):
        super().__init__(prefix)
        self._data: dict[str, tuple[float | None, str]] = {}

    def _alive(self, k: str):
        entry = self._data.get(k)
        if entry is not None and entry[0] is not None and entry[0] <= time.time():
            del self._data[k]
            return None
        return entry

    def _get(self, k):
        entry = self._alive(k)
        return entry[1] if entry else None

    def _put(self, k, text, seconds):
        self._data[k] = (None if seconds is None else time.time() + seconds, text)

    def _add(self, k, text, seconds):
        if self._alive(k):
            return False
        self._put(k, text, seconds)
        return True

    def _delete(self, k):
        return self._data.pop(k, None) is not None

    def _pull(self, k):
        text = self._get(k)
        self._data.pop(k, None)
        return text

    def _increment(self, k, by):
        entry = self._alive(k)
        expires, value = (entry[0], _as_int(k, entry[1])) if entry else (None, 0)
        self._data[k] = (expires, json.dumps(value + by))
        return value + by

    def _flush(self):
        self._data.clear()


DEFAULT_STORES = {
    "array": {"driver": "array"},
    "file": {"driver": "file", "path": "storage/cache"},
    "redis": {"driver": "redis", "url": "redis://127.0.0.1:6379/0"},
}


def default_prefix(app_name: str | None) -> str:
    return re.sub(r"\W+", "_", (app_name or "flask_artisan").lower()).strip("_") + "_cache:"


class CacheManager:
    """Le service `"cache"` (façade `Cache`) : ses méthodes visent le store par défaut."""

    def __init__(self, app):
        self._app = app
        self._arrays: dict[str, ArrayStore] = {}  # seuls les `array` gardent un état

    def _config(self, key: str, default=None):
        return self._app.make("config").get(f"cache.{key}", default)

    def store(self, name: str | None = None) -> Store:
        name = name or self._config("default", "file")
        stores = self._config("stores", DEFAULT_STORES)
        if name not in stores:
            raise ValueError(f"Store de cache inconnu : {name!r} (config cache.stores).")
        options = stores[name]
        prefix = self._config("prefix") or default_prefix(self._app.make("config").get("app.name"))
        driver = options.get("driver")
        if driver == "array":
            store = self._arrays.get(name)
            if store is None or store.prefix != prefix:
                store = self._arrays[name] = ArrayStore(prefix)
            return store
        raise ValueError(f"Pilote de cache inconnu : {driver!r} (store {name!r}).")

    def __getattr__(self, name: str):
        if name in PUBLIC:
            return getattr(self.store(), name)
        raise AttributeError(name)

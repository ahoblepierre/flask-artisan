"""Cache façon Laravel : `Cache.get/put/remember/…`, stores `array`, `file` et `redis`.

Valeurs en JSON (jamais de pickle), avec la sérialisation des queues : un modèle est stocké par
son identifiant et relu en base à la lecture.
"""

import hashlib
import json
import logging
import math
import os
import re
import secrets
import tempfile
import threading
import time
from contextlib import contextmanager
from datetime import timedelta
from functools import cache
from pathlib import Path

import click
from flask import current_app
from flask.cli import with_appcontext

from flask_artisan.queue.serialization import dump, load

try:
    import fcntl
except ImportError:  # Windows
    fcntl = None

__all__ = [
    "ArrayStore",
    "CacheManager",
    "FileStore",
    "Lock",
    "LockTimeoutError",
    "RedisStore",
    "Store",
    "default_prefix",
]

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
    "prune",
    "lock",
    "restore_lock",
)


def _seconds(ttl) -> int | None:
    """Durée en secondes entières (arrondie au-dessus) ; None = sans expiration."""
    if ttl is None:
        return None
    if isinstance(ttl, timedelta):
        ttl = ttl.total_seconds()
    if isinstance(ttl, bool) or not isinstance(ttl, (int, float)) or not math.isfinite(ttl):
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

    def _delete_if(self, k: str, text: str) -> bool:
        """Supprime seulement si la valeur stockée vaut `text` (atomique)."""
        raise NotImplementedError

    def _flush(self) -> None:
        raise NotImplementedError

    def _prune(self) -> int:
        """Supprime les entrées expirées, renvoie leur nombre."""
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
        except (ModelNotFound, TypeError, ValueError, ArithmeticError) as exc:
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

    def prune(self) -> int:
        return self._prune()

    def lock(self, name: str, seconds=0, owner: str | None = None) -> "Lock":
        return Lock(self, name, seconds, owner)

    def restore_lock(self, name: str, owner: str) -> "Lock":
        """Le verrou `name` de `owner` (pris ailleurs : autre requête, job) pour le libérer."""
        return Lock(self, name, 0, owner)


class LockTimeoutError(Exception):
    """Verrou toujours pris : `block` a attendu en vain, ou `with` l'a trouvé pris."""


class Lock:
    """Verrou dans le cache : pris par `add`, libéré seulement par son propriétaire."""

    def __init__(self, store: Store, name: str, seconds=0, owner: str | None = None):
        if not isinstance(name, str):
            raise TypeError(f"Un nom de verrou est une chaîne, pas {name!r}.")
        if not name:
            raise ValueError("Un nom de verrou ne peut pas être vide.")
        if owner is not None and not isinstance(owner, str):
            raise TypeError(f"Le propriétaire d'un verrou est une chaîne, pas {owner!r}.")
        if owner == "":
            raise ValueError("Le propriétaire d'un verrou ne peut pas être vide.")
        seconds = _seconds(seconds)
        if seconds is not None and seconds < 0:
            raise ValueError(f"Durée de verrou négative : {seconds} (0 = sans expiration).")
        self.store, self.name = store, name
        self.owner = owner or secrets.token_hex(16)
        self._ttl = seconds or None  # 0 : sans expiration
        self._k = store._key("lock:" + name)
        self._text = store._encode(name, self.owner)  # JSON : la lecture tolérante le lit

    def _run(self, callback):
        try:
            return callback()
        finally:
            self.release()

    def get(self, callback=None):
        acquired = self.store._add(self._k, self._text, self._ttl)
        if callback is None or not acquired:
            return acquired
        return self._run(callback)

    def block(self, seconds, callback=None):
        deadline = time.time() + seconds
        while not self.store._add(self._k, self._text, self._ttl):
            if time.time() >= deadline:
                raise LockTimeoutError(f"Verrou {self.name!r} toujours pris après {seconds} s.")
            time.sleep(0.25)
        return True if callback is None else self._run(callback)

    def release(self) -> bool:
        return self.store._delete_if(self._k, self._text)

    def force_release(self) -> None:
        self.store._delete(self._k)

    def __enter__(self):
        if not self.get():
            raise LockTimeoutError(f"Verrou {self.name!r} déjà pris.")
        return self

    def __exit__(self, *exc):
        self.release()


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
        # Un processus servi par plusieurs threads ; réentrant : _pull et _delete_if appellent _get.
        self._mutex = threading.RLock()

    def _alive(self, k: str):
        entry = self._data.get(k)
        if entry is not None and entry[0] is not None and entry[0] <= time.time():
            self._data.pop(k, None)  # pop : un autre thread a pu la supprimer
            return None
        return entry

    def _get(self, k):
        with self._mutex:  # _alive supprime une clé expirée : jamais pendant un add concurrent
            entry = self._alive(k)
            return entry[1] if entry else None

    def _put(self, k, text, seconds):
        self._data[k] = (None if seconds is None else time.time() + seconds, text)

    def _add(self, k, text, seconds):
        with self._mutex:
            if self._alive(k):
                return False
            self._put(k, text, seconds)
            return True

    def _delete(self, k):
        return self._data.pop(k, None) is not None

    def _pull(self, k):
        with self._mutex:
            text = self._get(k)
            self._data.pop(k, None)
            return text

    def _increment(self, k, by):
        with self._mutex:
            entry = self._alive(k)
            expires, value = (entry[0], _as_int(k, entry[1])) if entry else (None, 0)
            self._data[k] = (expires, json.dumps(value + by))
            return value + by

    def _delete_if(self, k, text):
        with self._mutex:
            if self._get(k) != text:
                return False
            return self._delete(k)

    def _flush(self):
        self._data.clear()

    def _prune(self):
        with self._mutex:
            return sum(self._alive(k) is None for k in list(self._data))


_STALE = object()  # FileStore._read : clé expirée ou corrompue, à supprimer sous le verrou
_CORRUPT = object()  # FileStore._load : fichier illisible
CACHE_FILE = re.compile(r"[0-9a-f]{64}")


class FileStore(Store):
    """Un fichier JSON par clé dans `directory`, nommé par le SHA-256 de la clé."""

    def __init__(self, prefix: str, directory: Path):
        super().__init__(prefix)
        self.directory = Path(directory)

    def _path(self, k: str) -> Path:
        return self.directory / hashlib.sha256(k.encode()).hexdigest()

    @staticmethod
    def _unlink_if_same(path: Path, inode: int | None) -> None:
        """Supprime seulement le fichier lu : un os.replace concurrent a pu en mettre un neuf."""
        try:
            if inode is None or os.stat(path).st_ino == inode:
                path.unlink(missing_ok=True)
        except FileNotFoundError:
            pass

    @staticmethod
    def _load(path: Path):
        """(inode, entrée), sans rien supprimer : entrée None si absente, _CORRUPT si illisible,
        _STALE si expirée, sinon (expiration, texte)."""
        inode = None
        try:
            with open(path) as f:
                inode = os.fstat(f.fileno()).st_ino
                entry = json.loads(f.read())
            expires, text = entry["expires"], entry["value"]
            if not isinstance(text, str) or not (
                expires is None or isinstance(expires, (int, float))
            ):
                raise TypeError("format inattendu")
        except FileNotFoundError:
            return None, None
        except (OSError, ValueError, KeyError, TypeError):
            return inode, _CORRUPT
        if expires is not None and expires <= time.time():
            return inode, _STALE
        return inode, (expires, text)

    def _read(self, k: str, clean: bool = True):
        """(expiration, texte), ou None si absente. `clean=False` : une clé expirée ou corrompue
        renvoie _STALE au lieu d'être supprimée, pour la supprimer sous le verrou."""
        path = self._path(k)
        inode, entry = self._load(path)
        if entry is _CORRUPT or entry is _STALE:
            if not clean:
                return _STALE
            self._unlink_if_same(path, inode)
            if entry is _CORRUPT:
                logger.warning("Cache : fichier illisible pour %r, supprimé.", k)
            return None
        return entry

    def _write(self, k: str, expires: float | None, text: str) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        # Fichier temporaire puis os.replace : un lecteur ne voit jamais un fichier tronqué.
        fd, tmp = tempfile.mkstemp(dir=self.directory, prefix=".tmp-")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump({"expires": expires, "value": text}, f)
            os.chmod(
                tmp, 0o644
            )  # mkstemp crée en 0600 : un cron sous un autre utilisateur doit lire
            os.replace(tmp, self._path(k))
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def _get(self, k):
        # Jamais appelé sous _locked (flock non réentrant) : les sections critiques lisent par _read.
        entry = self._read(k, clean=False)
        if entry is _STALE:
            with self._locked():  # suppression sous le verrou : jamais une écriture concurrente
                entry = self._read(k)
        return entry[1] if entry else None

    def _put(self, k, text, seconds):
        self._write(k, None if seconds is None else time.time() + seconds, text)

    @contextmanager
    def _locked(self):
        """Section critique entre processus d'une même machine : flock sur `.lock` du dossier."""
        if fcntl is None:
            # shortcut: pas de flock sous Windows, add/increment/verrous non atomiques entre
            # processus ; store redis si besoin.
            yield
            return
        self.directory.mkdir(parents=True, exist_ok=True)
        # Lecture seule (créé s'il manque) : flock suffit, même pour un cron sous un autre utilisateur.
        fd = os.open(self.directory / ".lock", os.O_RDONLY | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)  # libère le flock

    def _add(self, k, text, seconds):
        with self._locked():
            if self._read(k):
                return False
            self._put(k, text, seconds)
            return True

    def _delete(self, k):
        path = self._path(k)
        existed = self._read(k) is not None
        path.unlink(missing_ok=True)
        return existed

    def _pull(self, k):
        with self._locked():
            entry = self._read(k)
            self._path(k).unlink(missing_ok=True)
            return entry[1] if entry else None

    def _increment(self, k, by):
        with self._locked():
            entry = self._read(k)
            expires, value = (entry[0], _as_int(k, entry[1])) if entry else (None, 0)
            self._write(k, expires, json.dumps(value + by))
            return value + by

    def _delete_if(self, k, text):
        with self._locked():
            entry = self._read(k)
            if entry is None or entry[1] != text:
                return False
            self._path(k).unlink(missing_ok=True)
            return True

    def _flush(self):
        # Seulement nos fichiers (nom = SHA-256) : ni un .gitignore, ni un log, ni une écriture
        # en cours (.tmp-…) dont le os.replace échouerait.
        if self.directory.is_dir():
            for path in self.directory.iterdir():
                if CACHE_FILE.fullmatch(path.name) and path.is_file():
                    path.unlink(missing_ok=True)

    def _prune(self):
        if not self.directory.is_dir():
            return 0
        count = 0
        for path in self.directory.iterdir():
            if not (CACHE_FILE.fullmatch(path.name) and path.is_file()):
                continue
            if self._load(path)[1] not in (_STALE, _CORRUPT):
                continue
            # Verrou par fichier, jamais sur tout le parcours : un gros dossier ne doit pas
            # bloquer les requêtes limitées. On relit sous le verrou : une écriture a pu passer.
            with self._locked():
                inode, entry = self._load(path)
                if entry is _STALE or entry is _CORRUPT:
                    self._unlink_if_same(path, inode)
                    count += 1
        return count


@cache
def _redis(url: str):
    """Client Redis, un par URL et par processus (point de remplacement des tests)."""
    try:
        from redis import Redis
    except ImportError:
        raise RuntimeError(
            'Le store redis demande redis-py : pip install "flask-artisan[redis]".'
        ) from None
    return Redis.from_url(url)


def _text(raw) -> str | None:
    """bytes ou str selon `decode_responses` du client."""
    return raw.decode() if isinstance(raw, bytes) else raw


DELETE_IF = """
if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end
"""


class RedisStore(Store):
    """Redis : TTL, `SET NX` et `INCRBY` natifs ; `flush` limité aux clés du préfixe."""

    def __init__(self, prefix: str, client):
        super().__init__(prefix)
        self.client = client

    def _get(self, k):
        return _text(self.client.get(k))

    def _put(self, k, text, seconds):
        self.client.set(k, text, px=None if seconds is None else seconds * 1000)

    def _add(self, k, text, seconds):
        px = None if seconds is None else seconds * 1000
        return bool(self.client.set(k, text, nx=True, px=px))

    def _delete(self, k):
        return bool(self.client.delete(k))

    def _delete_if(self, k, text):
        # register_script est local (objet Script, EVALSHA avec repli sur EVAL) : pas d'aller-retour.
        return bool(self.client.register_script(DELETE_IF)(keys=[k], args=[text]))

    def _pull(self, k):
        # GET + DEL dans une transaction : atomique sans exiger GETDEL (Redis ≥ 6.2).
        pipe = self.client.pipeline(transaction=True)
        pipe.get(k)
        pipe.delete(k)
        raw, _ = pipe.execute()
        return _text(raw)

    def _increment(self, k, by):
        from redis.exceptions import ResponseError

        try:
            return int(self.client.incrby(k, by))  # garde le TTL
        except ResponseError as exc:
            raise ValueError(f"increment : la valeur de {k!r} n'est pas un entier.") from exc

    def _prune(self):
        return 0  # Redis applique lui-même le TTL

    def _flush(self):
        # Préfixe échappé : un * ou un [ dans le préfixe ne doit pas élargir le motif.
        pattern = re.sub(r"([*?\[\]\\])", r"\\\1", self.prefix) + "*"
        batch = []
        for key in self.client.scan_iter(match=pattern, count=500):
            batch.append(key)
            if len(batch) >= 500:
                self.client.delete(*batch)
                batch = []
        if batch:
            self.client.delete(*batch)


DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/0"

DEFAULT_STORES = {
    "array": {"driver": "array"},
    "file": {"driver": "file", "path": "storage/cache"},
    "redis": {"driver": "redis"},  # url : REDIS_URL, sinon DEFAULT_REDIS_URL
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
        if driver == "file":
            return FileStore(prefix, self._app.base_path(options.get("path", "storage/cache")))
        if driver == "redis":
            url = options.get("url") or os.environ.get("REDIS_URL", DEFAULT_REDIS_URL)
            return RedisStore(prefix, _redis(url))
        raise ValueError(f"Pilote de cache inconnu : {driver!r} (store {name!r}).")

    def __getattr__(self, name: str):
        if name in PUBLIC:
            return getattr(self.store(), name)
        raise AttributeError(name)


@contextmanager
def _cli_errors():
    """Erreurs de store attendues (inconnu, disque, Redis) → message propre, code 1."""
    try:
        yield
    except (ValueError, RuntimeError, OSError) as exc:
        raise click.ClickException(str(exc)) from None
    except Exception as exc:
        if type(exc).__module__.startswith("redis"):  # Redis injoignable, refus d'authentification…
            raise click.ClickException(f"Redis : {exc}") from None
        raise


@click.command("cache:clear")
@click.argument("store_name", required=False)
@with_appcontext
def cache_clear(store_name):
    """Vide un store de cache (défaut : le store par défaut)."""
    manager = current_app.make("cache")
    name = store_name or manager._config("default", "file")
    with _cli_errors():
        manager.store(name).flush()
    click.echo(f"Cache vidé : {name}.")


@click.command("cache:prune")
@click.argument("store_name", required=False)
@with_appcontext
def cache_prune(store_name):
    """Supprime les entrées expirées (défaut : le store par défaut et celui des compteurs)."""
    manager = current_app.make("cache")
    names = [store_name or manager._config("default", "file")]
    limiter = manager._config("limiter")
    if not store_name and limiter and limiter != names[0]:
        names.append(limiter)  # compteurs de throttle dans un store à part
    for name in names:
        with _cli_errors():
            count = manager.store(name).prune()
        click.echo(f"{count} entrée(s) expirée(s) supprimée(s) du store {name}.")

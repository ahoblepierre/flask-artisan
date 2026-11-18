import sys
from contextlib import contextmanager

import pytest

from flask_artisan.application import Application
from flask_artisan.providers import ServiceProvider

DEFAULT_APP = {
    "name": "'Blog'",
    "env": "'testing'",
    "debug": "False",
    "key": "'test-key'",
    "providers": "[]",
}


@pytest.fixture
def make_project(tmp_path):
    """Écrit config/app.py (valeurs Python sous forme de source) et un .env optionnel."""

    def _make(env_file: str | None = None, extra: str = "", **overrides) -> "Path":  # noqa: F821
        values = {**DEFAULT_APP, **overrides}
        body = ",\n".join(f"    {k!r}: {v}" for k, v in values.items())
        (tmp_path / "config").mkdir(exist_ok=True)
        (tmp_path / "config" / "app.py").write_text(
            f"from flask_artisan import env\n{extra}\nconfig = {{\n{body},\n}}\n"
        )
        if env_file is not None:
            (tmp_path / ".env").write_text(env_file)
        return tmp_path

    return _make


@pytest.fixture(autouse=True)
def reset_application():
    yield
    Application.set_instance(None)


@pytest.fixture
def routed_app(make_project):
    """App sans providers, puis un provider ajouté à chaud dont boot() appelle `declare()`."""

    def _make(declare, kernel=None):
        app = Application(make_project())
        if kernel is not None:
            from flask_artisan.routing import Router

            app.make(Router).use_kernel(kernel)
        app.register(type("RoutesProvider", (ServiceProvider,), {"boot": lambda self: declare()}))
        return app

    return _make


@pytest.fixture
def db_app(make_project):
    """App avec DatabaseServiceProvider sur SQLite (:memory: par défaut), tables créées.

    `providers` : chemins "module.Classe" de providers en plus ; `subdir` : projet dans un
    sous-dossier (pour avoir deux apps distinctes dans un même test).
    """
    import shutil

    def _make(*providers: str, database: str = ":memory:", subdir: str | None = None):
        names = [p.rsplit(".", 1) for p in providers]
        extra = "from flask_artisan.database import DatabaseServiceProvider\n" + "".join(
            f"from {mod} import {cls}\n" for mod, cls in names
        )
        listing = ", ".join(["DatabaseServiceProvider", *(cls for _, cls in names)])
        root = make_project(providers=f"[{listing}]", extra=extra)
        if subdir:
            root = shutil.copytree(root, root / subdir, ignore=shutil.ignore_patterns(subdir))
        (root / "config" / "database.py").write_text(
            "config = {\n"
            "    'default': 'sqlite',\n"
            f"    'connections': {{'sqlite': {{'driver': 'sqlite', 'database': {database!r}}}}},\n"
            "}\n"
        )
        app = Application(root)
        app.make("db").create_all()
        return app

    return _make


@contextmanager
def project_modules(root, cache: dict | None = None):
    """Isole le paquet `app` d'un projet de test dans sys.modules.

    `cache` garde ses modules d'un test à l'autre : un modèle n'est déclaré qu'une fois
    (registre SQLAlchemy global).
    """

    def ours():
        return {k: v for k, v in sys.modules.items() if k == "app" or k.startswith("app.")}

    saved = ours()
    for name in saved:
        del sys.modules[name]
    sys.modules.update(cache or {})
    sys.path.insert(0, str(root))
    try:
        yield
    finally:
        sys.path.remove(str(root))
        if cache is not None:
            cache.update(ours())
        for name in ours():
            del sys.modules[name]
        sys.modules.update(saved)

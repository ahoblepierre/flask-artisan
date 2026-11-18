from typing import Any

from flask_artisan.application import Application


class FacadeMeta(type):
    def __getattr__(cls, name: str) -> Any:
        if name == "accessor":
            raise AttributeError(f"La façade {cls.__name__} doit définir `accessor`.")
        # Pas de cache : chaque appel repasse par le conteneur (pas d'instance périmée entre tests).
        return getattr(Application.get_instance().make(cls.accessor), name)


class Facade(metaclass=FacadeMeta):
    """Accès statique à un service du conteneur : `Config.get("app.name")`."""

    accessor: str | type


class App(Facade):
    accessor = "app"


class Config(Facade):
    accessor = "config"

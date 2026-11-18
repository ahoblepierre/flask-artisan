from __future__ import annotations

from pathlib import Path

from flask import Flask

from flask_artisan.config import Repository
from flask_artisan.container import Container
from flask_artisan.env import load_env_file
from flask_artisan.providers import ServiceProvider


class Application(Flask, Container):
    """Une application Flask qui est aussi le conteneur de services."""

    _current: Application | None = None

    def __init__(self, base_path: str | Path):
        base = Path(base_path).resolve()
        Container.__init__(self)
        Flask.__init__(
            self,
            import_name=base.name,
            root_path=str(base),
            instance_path=str(base / "instance"),
        )
        self._base_path = base
        self._providers: dict[type, ServiceProvider] = {}
        self._booted = False

        load_env_file(base / ".env")
        repository = Repository.from_directory(base / "config")
        self._bridge_flask_config(repository)

        self.instance("app", self)
        self.instance(Application, self)
        self.instance("config", repository)
        self.instance(Repository, repository)
        Application.set_instance(self)

        for provider in repository.get("app.providers", []):
            self.register(provider)
        self.boot()

    def _bridge_flask_config(self, repository: Repository) -> None:
        key = repository.get("app.key")
        if not key:
            raise RuntimeError(
                "APP_KEY manquant dans .env : ajoutez une clé secrète "
                '(ex. python -c "import secrets; print(secrets.token_hex(32))").'
            )
        self.config["SECRET_KEY"] = key
        self.config["DEBUG"] = bool(repository.get("app.debug", False))
        self.config.update(repository.get("flask", {}))

    def register(self, provider_class: type[ServiceProvider]) -> ServiceProvider:
        if provider_class in self._providers:
            return self._providers[provider_class]
        provider = provider_class(self)
        provider.register()
        self._providers[provider_class] = provider
        if self._booted:
            provider.boot()
        return provider

    def boot(self) -> None:
        if self._booted:
            return
        self._booted = True
        for provider in list(self._providers.values()):
            provider.boot()

    def base_path(self, path: str = "") -> Path:
        return self._base_path / path

    def config_path(self, path: str = "") -> Path:
        return self._base_path / "config" / path

    def app_path(self, path: str = "") -> Path:
        return self._base_path / "app" / path

    def environment(self) -> str:
        return self.make("config").get("app.env", "production")

    @classmethod
    def get_instance(cls) -> Application:
        if Application._current is None:
            raise RuntimeError("Aucune application flask-artisan n'a été créée.")
        return Application._current

    @classmethod
    def set_instance(cls, app: Application | None) -> None:
        Application._current = app

from __future__ import annotations

from pathlib import Path

from flask import Flask, current_app, has_app_context
from jinja2 import ChoiceLoader, FileSystemLoader
from werkzeug.middleware.proxy_fix import ProxyFix

from flask_artisan.cache import CacheManager
from flask_artisan.config import Repository
from flask_artisan.console import COMMANDS, ArtisanGroup
from flask_artisan.container import Container
from flask_artisan.env import load_env_file
from flask_artisan.events import Dispatcher
from flask_artisan.filesystem import FilesystemManager, serve_view, served_disks
from flask_artisan.mail import Mailer
from flask_artisan.providers import ServiceProvider
from flask_artisan.queue import QueueManager
from flask_artisan.rate_limiting import RateLimiter
from flask_artisan.routing import Router
from flask_artisan.scheduling import Schedule
from flask_artisan.testing import TestClient
from flask_artisan.views import age_flash, template_context


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
        # Vues de Laravel d'abord, puis le dossier de Flask, puis les vues du framework (mails
        # d'auth, surchargeables par le projet) ; affecté à l'instance (pas de redéfinition de
        # Flask.jinja_loader dans la classe).
        self.jinja_loader = ChoiceLoader(
            [
                FileSystemLoader(base / "resources" / "views"),
                FileSystemLoader(base / "templates"),
                FileSystemLoader(Path(__file__).parent / "resources" / "views"),
            ]
        )
        self.test_client_class = TestClient  # à l'instance, comme jinja_loader
        self.before_request(age_flash)
        self.context_processor(template_context)
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
        router = Router(self)
        self.instance("router", router)
        self.instance(Router, router)
        events = Dispatcher(self)
        self.instance("events", events)
        self.instance(Dispatcher, events)
        mailer = Mailer(self)
        # Résolu à la demande : importer les notifications enregistre leur table.
        self.singleton("notifications", _notification_sender)
        self.instance("mail", mailer)
        self.instance(Mailer, mailer)
        queue = QueueManager(self)
        self.instance("queue", queue)
        self.instance(QueueManager, queue)
        cache = CacheManager(self)
        self.instance("cache", cache)
        self.instance(CacheManager, cache)
        filesystem = FilesystemManager(self)
        self.instance("filesystem", filesystem)
        self.instance(FilesystemManager, filesystem)
        limiter = RateLimiter(self)
        self.instance("limiter", limiter)
        self.instance(RateLimiter, limiter)
        schedule = Schedule(self)
        self.instance("schedule", schedule)
        self.instance(Schedule, schedule)
        Application.set_instance(self)

        self.cli = ArtisanGroup(self.name, app=self)
        for command in COMMANDS:
            self.cli.add_command(command)

        # Dans son propre contexte : façades et helpers visent cette app, même si une autre
        # app a un contexte actif (fixtures de tests).
        with self.app_context():
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
        self.config["DEBUG"] = _flag(repository.get("app.debug", False))
        self.config.update(repository.get("flask", {}))
        proxies = _trusted_proxies(repository.get("app.trusted_proxies", 0))
        if proxies:
            # IP et schéma seulement : nginx ne pose pas X-Forwarded-Host par défaut, et un hôte
            # choisi par le client empoisonnerait les url_for(_external=True) (liens des mails).
            self.wsgi_app = ProxyFix(self.wsgi_app, x_for=proxies, x_proto=proxies)

    def register(self, provider_class: type[ServiceProvider]) -> ServiceProvider:
        if provider_class in self._providers:
            return self._providers[provider_class]
        provider = provider_class(self)
        provider.register()
        self._providers[provider_class] = provider
        if self._booted:
            with self.app_context(), self.make(Router).collecting():
                provider.boot()
        return provider

    def boot(self) -> None:
        if self._booted:
            return
        self._booted = True
        # Les routes déclarées pendant les boot() sont poussées dans Flask à la fin.
        router = self.make(Router)
        with router.collecting():
            for provider in list(self._providers.values()):
                provider.boot()
            # Après les providers : une route /storage/... du projet, déclarée avant, gagne.
            for disk, url in served_disks(self).items():
                router.get(f"{url}/<path:path>", serve_view(disk)).name(f"storage.{disk}")

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
        # Pendant une requête, l'app courante gagne (plusieurs apps dans un même processus).
        if has_app_context():
            current = current_app._get_current_object()
            if isinstance(current, Application):
                return current
        if Application._current is None:
            raise RuntimeError("Aucune application flask-artisan n'a été créée.")
        return Application._current

    @classmethod
    def set_instance(cls, app: Application | None) -> None:
        Application._current = app


def _flag(value) -> bool:
    """Même lecture que Flask pour FLASK_DEBUG : "0", "false", "no" et "" valent False."""
    if isinstance(value, str):
        return value.strip().lower() not in ("0", "false", "no", "")
    return bool(value)


def _trusted_proxies(value) -> int:
    try:
        number = None if isinstance(value, bool) else int(value or 0)
    except (TypeError, ValueError):
        number = None
    if number is None or number < 0:
        raise ValueError(
            f"app.trusted_proxies (TRUSTED_PROXIES) : entier ≥ 0 attendu, reçu {value!r}."
        )
    return number


def _notification_sender(app):
    from flask_artisan.notifications.sender import NotificationSender

    return NotificationSender(app)

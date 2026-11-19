import pytest

from flask_artisan.providers import ServiceProvider
from flask_artisan.routing import Router

from .models import AMember

AUTH_CONFIG = (
    "config = {\n"
    "    'defaults': {'guard': 'web'},\n"
    "    'guards': {'web': {'driver': 'session'}, 'api': {'driver': 'token'}},\n"
    "}\n"
)


@pytest.fixture
def auth_app(db_app):
    """App avec base + AuthServiceProvider ; `declare()` déclare des routes, `model` l'utilisateur."""

    def _make(declare=None, kernel=None, model=AMember):
        app = db_app("flask_artisan.auth.AuthServiceProvider", configs={"auth": AUTH_CONFIG})
        app.make("config").set("auth.model", model)
        if kernel is not None:
            app.make(Router).use_kernel(kernel)
        if declare is not None:
            app.register(type("Routes", (ServiceProvider,), {"boot": lambda self: declare()}))
        return app

    return _make

from flask_artisan import HttpKernel
from flask_artisan.auth import Authenticate


class Kernel(HttpKernel):
    # Exécutés sur toutes les routes déclarées avec Route.
    global_middleware = []

    # Alias utilisables dans les routes : Route.get(...).middleware("auth") ou "auth:api"
    middleware = {
        "auth": Authenticate,
    }

    # Appliqués automatiquement à routes/web.py et routes/api.py.
    groups = {
        "web": [],
        "api": [],
    }

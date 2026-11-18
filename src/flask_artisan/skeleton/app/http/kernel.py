from flask_artisan import HttpKernel


class Kernel(HttpKernel):
    # Exécutés sur toutes les routes déclarées avec Route.
    global_middleware = []

    # Alias utilisables dans les routes : Route.get(...).middleware("json")
    # ex. from app.http.middleware.ensure_json import EnsureJson ; middleware = {"json": EnsureJson}
    middleware = {}

    # Appliqués automatiquement à routes/web.py et routes/api.py.
    groups = {
        "web": [],
        "api": [],
    }

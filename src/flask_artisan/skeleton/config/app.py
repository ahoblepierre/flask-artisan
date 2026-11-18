from app.providers.app_service_provider import AppServiceProvider
from app.providers.route_service_provider import RouteServiceProvider

from flask_artisan import env

config = {
    "name": env("APP_NAME", "Flask-Artisan"),
    "env": env("APP_ENV", "production"),
    "debug": env("APP_DEBUG", False),
    "key": env("APP_KEY", ""),
    # Enregistrés dans l'ordre (register), puis tous bootés (boot).
    "providers": [
        AppServiceProvider,
        RouteServiceProvider,
    ],
}

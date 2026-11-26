from app.providers.app_service_provider import AppServiceProvider
from app.providers.event_service_provider import EventServiceProvider
from app.providers.route_service_provider import RouteServiceProvider

from flask_artisan import env
from flask_artisan.auth import AuthServiceProvider
from flask_artisan.database import DatabaseServiceProvider

config = {
    "name": env("APP_NAME", "Flask-Artisan"),
    "env": env("APP_ENV", "production"),
    "debug": env("APP_DEBUG", False),
    "key": env("APP_KEY", ""),
    # Nombre de proxys devant l'app (nginx, load balancer) : l'IP du client est lue dans
    # X-Forwarded-For. 0 sans proxy, sinon un client pourrait falsifier son IP.
    "trusted_proxies": env("TRUSTED_PROXIES", 0),
    # Enregistrés dans l'ordre (register), puis tous bootés (boot).
    "providers": [
        DatabaseServiceProvider,
        AuthServiceProvider,
        EventServiceProvider,
        AppServiceProvider,
        RouteServiceProvider,
    ],
}

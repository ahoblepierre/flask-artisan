from flask_artisan.auth.authenticatable import AuthenticationError
from flask_artisan.auth.manager import AuthManager
from flask_artisan.providers import ServiceProvider


class AuthServiceProvider(ServiceProvider):
    """Enregistre l'authentification (`"auth"`, façade Auth)."""

    def register(self):
        if not self.app.make("config").has("auth"):
            raise AuthenticationError(
                "Configuration manquante : créez config/auth.py (guards et modèle utilisateur)."
            )
        manager = AuthManager(self.app)
        self.app.instance("auth", manager)
        self.app.instance(AuthManager, manager)

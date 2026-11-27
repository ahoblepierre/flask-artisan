from flask_artisan.middleware import HttpKernel
from flask_artisan.providers import ServiceProvider
from flask_artisan.routing import Router


class RouteServiceProvider(ServiceProvider):
    """Branche le kernel HTTP et charge routes/web.py, routes/auth.py et routes/api.py."""

    kernel: type[HttpKernel] = HttpKernel
    api_prefix = "/api"

    def register(self):
        # Dans register() : les alias sont connus avant le boot() de tout provider.
        self.app.make(Router).use_kernel(self.kernel)

    def boot(self):
        router = self.app.make(Router)
        router.load(self.app.base_path("routes/web.py"), middleware=self._group("web"))
        # Créé par flask auth:install ; ignoré s'il n'existe pas.
        router.load(self.app.base_path("routes/auth.py"), middleware=self._group("web"))
        router.load(
            self.app.base_path("routes/api.py"),
            prefix=self.api_prefix,
            middleware=self._group("api"),
            json=True,
        )

    def _group(self, name: str) -> tuple:
        # Un kernel qui omet le groupe "web" ou "api" ne doit pas empêcher l'app de démarrer.
        return (name,) if name in self.kernel.groups else ()

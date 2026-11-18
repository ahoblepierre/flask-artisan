from flask_artisan import ServiceProvider


class AppServiceProvider(ServiceProvider):
    def register(self):
        # Déclarez vos bindings ici : self.app.singleton(Service, lambda app: Service(...))
        pass

    def boot(self):
        # Code exécuté une fois tous les providers enregistrés (extensions Flask, etc.).
        pass

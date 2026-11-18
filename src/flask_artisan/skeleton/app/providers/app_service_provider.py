from flask_artisan import ServiceProvider, config


class AppServiceProvider(ServiceProvider):
    def register(self):
        # Déclarez vos bindings ici : self.app.singleton(Service, lambda app: Service(...))
        pass

    def boot(self):
        # Route de démonstration en Flask standard (le routage façon Laravel arrive ensuite).
        @self.app.route("/")
        def home():
            return {"app": config("app.name")}

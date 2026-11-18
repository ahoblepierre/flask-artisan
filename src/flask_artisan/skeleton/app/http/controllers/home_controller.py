from flask_artisan import config


class HomeController:
    def index(self):
        return {"app": config("app.name")}

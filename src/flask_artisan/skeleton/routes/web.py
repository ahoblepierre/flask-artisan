from app.http.controllers.home_controller import HomeController

from flask_artisan import Route

Route.get("/", HomeController.index).name("home")

from app.http.controllers.dashboard_controller import DashboardController
from app.http.controllers.home_controller import HomeController
from app.http.controllers.session_controller import SessionController

from flask_artisan import Route

# Routes avec le groupe de middlewares "web" du kernel (protection CSRF).

Route.get("/", HomeController.index).name("home")

Route.get("/login", SessionController.create).name("login")
# Même compteur que /api/login : 5 tentatives par minute et par IP, en tout.
Route.post("/login", SessionController.store).middleware("throttle:5,1")

with Route.middleware("auth"):
    Route.post("/logout", SessionController.destroy).name("logout")
    Route.get("/dashboard", DashboardController.index).name("dashboard")

# Upload : formulaire enctype="multipart/form-data", FormRequest {"avatar": "required|image|max:2048"},
# puis dans le controller :
#     path = Storage.disk("public").put_file("avatars", request.validated()["avatar"])
#     url = Storage.disk("public").url(path)   # /storage/avatars/<nom aléatoire>.png

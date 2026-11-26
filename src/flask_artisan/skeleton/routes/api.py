from app.http.controllers.auth_controller import AuthController

from flask_artisan import Route

# Routes préfixées par /api, avec le groupe de middlewares "api" du kernel.

# 5 tentatives par minute : contre le test de mots de passe en boucle.
Route.post("/login", AuthController.login).name("api.login").middleware("throttle:5,1")

with Route.middleware("auth:api"):
    Route.post("/logout", AuthController.logout).name("api.logout")
    Route.get("/user", AuthController.user).name("api.user")

# Autres exemples :
#
# from app.http.controllers.photo_controller import PhotoController
#
# Route.resource("photos", PhotoController)
# with Route.prefix("/admin").middleware("auth:api"):
#     Route.post("/users", UserController.store)

from flask_artisan import Route  # noqa: F401

# Routes préfixées par /api, avec le groupe de middlewares "api" du kernel. Exemples :
#
# from app.http.controllers.user_controller import UserController
#
# Route.get("/users", UserController.index).name("users.index")
# Route.resource("photos", PhotoController)
# with Route.prefix("/admin").middleware("auth"):
#     Route.post("/users", UserController.store)

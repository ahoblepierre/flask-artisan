from flask_artisan import Auth, HttpKernel, Route
from flask_artisan.auth import Authenticate
from flask_artisan.routing import RouteGroup, Router


class Kernel(HttpKernel):
    middleware = {"auth": Authenticate}


def test_api_route_unauthenticated_is_401_json(auth_app):
    def routes():
        from flask_artisan import App

        Route.get("/login", lambda: "form").name("login")
        with RouteGroup(App.make(Router), prefix="/api", json=True):
            Route.get("/me", lambda: Auth.user()).middleware("auth:web,api")

    app = auth_app(routes, kernel=Kernel)
    app.test_client().get("/api/me").assert_status(401).assert_json({"message": "Unauthenticated."})

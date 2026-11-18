from app.http.kernel import Kernel
from flask_artisan import RouteServiceProvider as BaseRouteServiceProvider


class RouteServiceProvider(BaseRouteServiceProvider):
    # Charge routes/web.py (groupe "web") et routes/api.py (préfixe /api, groupe "api").
    kernel = Kernel

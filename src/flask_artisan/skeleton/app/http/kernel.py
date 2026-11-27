from flask_artisan import HttpKernel, ValidateSignature, VerifyCsrfToken
from flask_artisan.auth import Authenticate, EnsureEmailIsVerified
from flask_artisan.rate_limiting import ThrottleRequests


class Kernel(HttpKernel):
    # Exécutés sur toutes les routes déclarées avec Route.
    global_middleware = []

    # Alias utilisables dans les routes : Route.get(...).middleware("auth") ou "auth:api"
    middleware = {
        "auth": Authenticate,
        "throttle": ThrottleRequests,  # "throttle:60,1" : 60 requêtes par minute
        "signed": ValidateSignature,  # URL produite par signed_url(...), sinon 403
        "verified": EnsureEmailIsVerified,  # e-mail vérifié (User avec MustVerifyEmail)
    }

    # Appliqués automatiquement à routes/web.py et routes/api.py.
    groups = {
        "web": [VerifyCsrfToken],  # champ csrf_field() ou en-tête X-CSRF-TOKEN
        "api": ["throttle:60,1"],
    }

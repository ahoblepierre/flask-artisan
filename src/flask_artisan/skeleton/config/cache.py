from flask_artisan import env
from flask_artisan.cache import default_prefix

config = {
    # array (mémoire, tests), file (dossier storage/cache) ou redis.
    "default": env("CACHE_STORE", "file"),
    "stores": {
        "array": {"driver": "array"},
        "file": {"driver": "file", "path": "storage/cache"},
        "redis": {
            "driver": "redis",  # pip install "flask-artisan[redis]"
            "url": env("REDIS_URL", "redis://127.0.0.1:6379/0"),
        },
    },
    # Store des compteurs de throttle et RateLimiter (défaut : le store par défaut).
    # "limiter": "redis",
    # Préfixe des clés : plusieurs applications peuvent partager un Redis.
    "prefix": env("CACHE_PREFIX", default_prefix(env("APP_NAME"))),
}

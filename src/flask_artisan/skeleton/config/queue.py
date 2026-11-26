from flask_artisan import env

config = {
    # sync (exécution immédiate) ou redis (worker : flask queue:work).
    "default": env("QUEUE_CONNECTION", "sync"),
    "connections": {
        "sync": {"driver": "sync"},
        "redis": {
            "driver": "rq",  # pip install "flask-artisan[rq]"
            "url": env("REDIS_URL", "redis://127.0.0.1:6379/0"),
            "queue": "default",  # file utilisée quand le job n'en précise pas
        },
    },
}

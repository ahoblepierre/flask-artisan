from flask_artisan import env

config = {
    # smtp, log (écrit dans les logs) ou array (gardé en mémoire).
    "default": env("MAIL_MAILER", "log"),
    "mailers": {
        "smtp": {
            "transport": "smtp",
            "host": env("MAIL_HOST", "127.0.0.1"),
            "port": env("MAIL_PORT", 2525),
            "username": env("MAIL_USERNAME"),
            "password": env("MAIL_PASSWORD"),
            "encryption": env("MAIL_ENCRYPTION"),  # tls, ssl ou vide
            "timeout": 10,
        },
        "log": {"transport": "log"},
        "array": {"transport": "array"},
    },
    "from": {
        "address": env("MAIL_FROM_ADDRESS", "hello@example.com"),
        "name": env("MAIL_FROM_NAME", env("APP_NAME", "Flask-Artisan")),
    },
}

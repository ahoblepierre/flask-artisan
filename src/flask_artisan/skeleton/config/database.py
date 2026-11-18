from flask_artisan import env

config = {
    # sqlite, mysql, mariadb ou pgsql. Pilotes : pip install "flask-artisan[mysql]" ou [pgsql].
    "default": env("DB_CONNECTION", "sqlite"),
    "connections": {
        "sqlite": {
            "driver": "sqlite",
            "url": env("DB_URL"),
            "database": env("DB_DATABASE", "database/database.sqlite"),
        },
        "mysql": {
            "driver": "mysql",
            "url": env("DB_URL"),
            "host": env("DB_HOST", "127.0.0.1"),
            "port": env("DB_PORT", "3306"),
            "database": env("DB_DATABASE", "forge"),
            "username": env("DB_USERNAME", "root"),
            "password": env("DB_PASSWORD", ""),
        },
        "mariadb": {
            "driver": "mariadb",
            "url": env("DB_URL"),
            "host": env("DB_HOST", "127.0.0.1"),
            "port": env("DB_PORT", "3306"),
            "database": env("DB_DATABASE", "forge"),
            "username": env("DB_USERNAME", "root"),
            "password": env("DB_PASSWORD", ""),
        },
        "pgsql": {
            "driver": "pgsql",
            "url": env("DB_URL"),
            "host": env("DB_HOST", "127.0.0.1"),
            "port": env("DB_PORT", "5432"),
            "database": env("DB_DATABASE", "forge"),
            "username": env("DB_USERNAME", "postgres"),
            "password": env("DB_PASSWORD", ""),
        },
    },
}

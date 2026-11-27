from flask_artisan import env

config = {
    # Disque de Storage.put(...), Storage.get(...)… : local, public ou s3.
    "default": env("FILESYSTEM_DISK", "local"),
    "disks": {
        # Fichiers privés : jamais servis par une URL.
        "local": {"driver": "local", "root": "storage/app/private"},
        # Servis par la route /storage/<chemin> (en production : nginx, voir la doc).
        "public": {
            "driver": "local",
            "root": "storage/app/public",
            "url": "/storage",
            "serve": True,
        },
        "s3": {
            "driver": "s3",  # pip install "flask-artisan[s3]"
            "bucket": env("AWS_BUCKET"),
            "region": env("AWS_DEFAULT_REGION", "us-east-1"),
            # Vides : identifiants de l'environnement ou rôle IAM (chaîne de boto3).
            "key": env("AWS_ACCESS_KEY_ID"),
            "secret": env("AWS_SECRET_ACCESS_KEY"),
            "endpoint": env("AWS_ENDPOINT"),  # MinIO, Cloudflare R2… sinon AWS
            "url": env("AWS_URL"),  # CDN devant le bucket, sinon l'URL du bucket
            "root": "",  # préfixe des clés dans le bucket
        },
    },
}

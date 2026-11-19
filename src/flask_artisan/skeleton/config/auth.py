from app.models.user import User

config = {
    # Guard utilisé par Auth.user(), Auth.attempt()… et par le middleware "auth" sans paramètre.
    "defaults": {"guard": "web"},
    "guards": {
        # Session Flask signée avec APP_KEY : routes/web.py.
        "web": {"driver": "session"},
        # En-tête "Authorization: Bearer <token>" (user.create_token) : middleware "auth:api".
        "api": {"driver": "token"},
    },
    "model": User,
}

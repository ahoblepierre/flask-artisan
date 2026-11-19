from sqlalchemy.orm import validates
from werkzeug.security import check_password_hash, generate_password_hash

from flask_artisan.auth.tokens import PersonalAccessToken, issue_token

# Préfixes des hash Werkzeug : une valeur déjà hachée n'est pas re-hachée.
HASH_PREFIXES = ("scrypt:", "pbkdf2:")


class AuthenticationError(Exception):
    pass


class Authenticatable:
    """Mixin d'utilisateur : `password` est haché à chaque affectation (pas à la relecture)."""

    @validates("password")
    def _hash_password(self, key, value):
        if value is None or value.startswith(HASH_PREFIXES):
            return value
        return generate_password_hash(value)

    def check_password(self, plain: str) -> bool:
        return self.password is not None and check_password_hash(self.password, plain)


class HasApiTokens:
    """Mixin d'utilisateur : tokens d'API stockés en base (`personal_access_tokens`)."""

    def create_token(self, name: str) -> str:
        """Renvoie le token en clair `"<id>|<secret>"` : c'est la seule fois où il est visible."""
        return issue_token(self.id, name)

    def tokens(self):
        return PersonalAccessToken.where("user_id", self.id)

    def current_access_token(self):
        """Le token qui a authentifié la requête courante (guard token), sinon None."""
        return getattr(self, "_access_token", None)

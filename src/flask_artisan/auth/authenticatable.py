from sqlalchemy.orm import validates
from werkzeug.security import check_password_hash, generate_password_hash

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

import re

from sqlalchemy import delete
from sqlalchemy.orm import validates
from werkzeug.security import check_password_hash, generate_password_hash

from flask_artisan.auth.tokens import PersonalAccessToken, issue_token
from flask_artisan.database.model import _db

# Hash Werkzeug complet (méthode$sel$hex) : une valeur déjà hachée n'est pas re-hachée.
WERKZEUG_HASH = re.compile(r"(scrypt|pbkdf2):[^$]+\$[^$]+\$[0-9a-f]+")


class AuthenticationError(Exception):
    pass


class Authenticatable:
    """Mixin d'utilisateur : `password` est haché à chaque affectation (pas à la relecture)."""

    @validates("password")
    def _hash_password(self, key, value):
        if value is None or WERKZEUG_HASH.fullmatch(value):
            return value
        return generate_password_hash(value)

    def check_password(self, plain: str) -> bool:
        return self.password is not None and check_password_hash(self.password, plain)

    def send_password_reset_notification(self, token: str) -> None:
        """Envoie le lien de réinitialisation ; à redéfinir pour changer de mail."""
        if not callable(getattr(self, "notify", None)):
            raise TypeError(
                f"{type(self).__name__} doit hériter de Notifiable pour recevoir le lien "
                "de réinitialisation."
            )
        from flask_artisan.auth.notifications import ResetPassword

        self.notify(ResetPassword(token))


class HasApiTokens:
    """Mixin d'utilisateur : tokens d'API stockés en base (`personal_access_tokens`)."""

    def create_token(self, name: str) -> str:
        """Renvoie le token en clair `"<id>|<secret>"` : c'est la seule fois où il est visible."""
        return issue_token(self.id, name)

    def _hard_delete(self) -> None:
        # Sinon, sous SQLite, un nouvel utilisateur qui reprend cet id hériterait des tokens.
        _db().session.execute(
            delete(PersonalAccessToken).where(PersonalAccessToken.user_id == self.id)
        )
        super()._hard_delete()

    def tokens(self):
        return PersonalAccessToken.where("user_id", self.id)

    def current_access_token(self):
        """Le token qui a authentifié la requête courante (guard token), sinon None."""
        return getattr(self, "_access_token", None)

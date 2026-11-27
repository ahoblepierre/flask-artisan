from datetime import datetime, timezone

from flask import current_app, redirect, url_for
from sqlalchemy import DateTime
from sqlalchemy.orm import Mapped, mapped_column
from werkzeug.routing import BuildError

from flask_artisan.auth.manager import AuthManager
from flask_artisan.middleware import Middleware, expects_json

UNVERIFIED = ({"message": "Your email address is not verified."}, 403)


class MustVerifyEmail:
    """Mixin d'utilisateur : `email_verified_at`, lien de vérification par mail."""

    email_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None, sort_order=99
    )

    def __init_subclass__(cls, **kw):
        from flask_artisan.database import Model

        mro = cls.__mro__
        if Model in mro and mro.index(Model) < mro.index(MustVerifyEmail):
            # Sinon les méthodes de Model passeraient avant celles du mixin.
            raise TypeError(
                f"{cls.__name__} : placez MustVerifyEmail avant Model "
                f"(class {cls.__name__}(MustVerifyEmail, ..., Model))."
            )
        super().__init_subclass__(**kw)

    def has_verified_email(self) -> bool:
        return self.email_verified_at is not None

    def mark_email_as_verified(self) -> None:
        self.email_verified_at = datetime.now(timezone.utc)
        self.save()

    def send_email_verification_notification(self) -> None:
        """Envoie le lien signé ; à redéfinir pour changer de mail."""
        if not callable(getattr(self, "notify", None)):
            raise TypeError(
                f"{type(self).__name__} doit hériter de Notifiable pour recevoir le lien "
                "de vérification."
            )
        from flask_artisan.auth.notifications import VerifyEmail

        self.notify(VerifyEmail())


class EnsureEmailIsVerified(Middleware):
    """`verified` : l'utilisateur connecté doit avoir vérifié son e-mail (s'il le doit)."""

    def handle(self, request, next):
        user = current_app.make(AuthManager).guard().user()
        if user is not None and (
            not isinstance(user, MustVerifyEmail) or user.has_verified_email()
        ):
            return next(request)
        if request.environ.get("flask_artisan.route_json", False) or expects_json(request):
            return UNVERIFIED
        try:
            return redirect(url_for("verification.notice"))
        except BuildError:  # projet sans auth:install
            return UNVERIFIED

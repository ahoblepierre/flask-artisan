import inspect

from sqlalchemy import delete

from flask_artisan.database.model import _db
from flask_artisan.notifications.base import Notification
from flask_artisan.notifications.models import DatabaseNotification
from flask_artisan.queue.serialization import class_path

RESERVED = ("notify", "notifications", "unread_notifications", "route_notification_for")


class Notifiable:
    """Mixin de modèle : `user.notify(...)`, `user.notifications`, `user.unread_notifications`."""

    def __init_subclass__(cls, **kw):
        from flask_artisan.database import Model

        mro = cls.__mro__
        if Model in mro and mro.index(Model) < mro.index(Notifiable):
            # Sinon Model._hard_delete passe en premier : notifications orphelines.
            raise TypeError(
                f"{cls.__name__} : placez Notifiable avant Model "
                f"(class {cls.__name__}(Notifiable, Model))."
            )
        # Une colonne (annotée, ou une valeur non appelable) du même nom ; redéfinir la méthode reste permis.
        columns = set(inspect.get_annotations(cls)) | {
            name
            for name, value in vars(cls).items()
            if not callable(value) and not isinstance(value, property)
        }
        clash = [name for name in RESERVED if name in columns]
        if clash and Model in mro:
            raise TypeError(
                f"{cls.__name__}.{clash[0]} masquerait la méthode de Notifiable : renommez-le."
            )
        super().__init_subclass__(**kw)

    def notify(self, notification: Notification) -> None:
        Notification.send([self], notification)

    @property
    def notifications(self):
        """Les notifications du canal database, des plus récentes aux plus anciennes."""
        return (
            DatabaseNotification.where("notifiable_type", class_path(type(self)))
            .where("notifiable_id", self.id)
            .latest()
            .order_by("id", "desc")  # même created_at (MySQL : à la seconde) : id UUIDv7, croissant
        )

    @property
    def unread_notifications(self):
        return self.notifications.where_null("read_at")

    def route_notification_for(self, channel: str):
        method = getattr(self, f"route_notification_for_{channel}", None)
        if callable(method):
            return method()
        if channel == "mail":
            return getattr(self, "email", None)
        return None

    def _hard_delete(self) -> None:
        # Sinon, sous SQLite, un nouveau modèle qui reprend cet id hériterait des notifications.
        _db().session.execute(
            delete(DatabaseNotification).where(
                DatabaseNotification.notifiable_type == class_path(type(self)),
                DatabaseNotification.notifiable_id == self.id,
            )
        )
        super()._hard_delete()


class AnonymousNotifiable:
    """Destinataire sans compte : `Notification.route("mail", "a@x.org").notify(...)`."""

    def __init__(self):
        self.routes: dict = {}

    def route(self, channel: str, value) -> "AnonymousNotifiable":
        self.routes[channel] = value
        return self

    def route_notification_for(self, channel: str):
        return self.routes.get(channel)

    def notify(self, notification: Notification) -> None:
        Notification.send([self], notification)

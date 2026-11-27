from sqlalchemy import delete

from flask_artisan.database.model import _db
from flask_artisan.notifications.base import Notification
from flask_artisan.notifications.models import DatabaseNotification
from flask_artisan.queue.serialization import class_path


class Notifiable:
    """Mixin de modèle : `user.notify(...)`, `user.notifications`, `user.unread_notifications`."""

    def notify(self, notification: Notification) -> None:
        Notification.send([self], notification)

    @property
    def notifications(self):
        """Les notifications du canal database, des plus récentes aux plus anciennes."""
        return (
            DatabaseNotification.where("notifiable_type", class_path(type(self)))
            .where("notifiable_id", self.id)
            .latest()
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

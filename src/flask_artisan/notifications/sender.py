import json

from flask_artisan.notifications.models import DatabaseNotification
from flask_artisan.notifications.notifiable import AnonymousNotifiable
from flask_artisan.queue.serialization import class_path

CHANNELS = ("mail", "database")


class NotificationSender:
    """Le service `"notifications"` : envoie chaque notification sur les canaux de `via()`."""

    def __init__(self, app):
        self._app = app

    def send(self, notifiables, notification) -> None:
        if not isinstance(notifiables, (list, tuple)):
            notifiables = [notifiables]
        first = None
        # Un destinataire ou un canal en échec n'empêche pas les autres ; la 1re erreur remonte.
        for notifiable in notifiables:
            try:
                self.send_now(notifiable, notification)
            except Exception as exc:  # noqa: BLE001 (relevée après les autres envois)
                first = first or exc
        if first is not None:
            raise first

    def channels(self, notifiable, notification) -> list[str]:
        channels = list(notification.via(notifiable))
        for channel in channels:
            if channel not in CHANNELS:
                raise ValueError(
                    f"Canal de notification inconnu : {channel!r} (connus : {', '.join(CHANNELS)})."
                )
        return channels

    def send_now(self, notifiable, notification, channels=None) -> None:
        if channels is None:
            channels = self.channels(notifiable, notification)
        first = None
        for channel in channels:
            try:
                getattr(self, f"_send_{channel}")(notifiable, notification)
            except Exception as exc:  # noqa: BLE001 (relevée après les autres canaux)
                first = first or exc
        if first is not None:
            raise first

    @staticmethod
    def _payload(notifiable, notification, channel: str):
        method = getattr(notification, f"to_{channel}", None)
        if not callable(method):
            raise NotImplementedError(
                f"{type(notification).__name__} doit définir to_{channel}(notifiable) "
                f"(canal {channel!r} dans via())."
            )
        return method(notifiable)

    def _send_mail(self, notifiable, notification) -> None:
        raise NotImplementedError("Canal mail : tâche 2.")

    def _send_database(self, notifiable, notification) -> None:
        if isinstance(notifiable, AnonymousNotifiable):
            raise ValueError(  # noqa: TRY004 (erreur d'usage, pas de type)
                "Canal database impossible pour une notification à la demande "
                "(Notification.route) : aucun destinataire à enregistrer."
            )
        data = self._payload(notifiable, notification, "database")
        try:
            json.dumps(data)
        except (TypeError, ValueError) as exc:
            raise TypeError(
                f"{type(notification).__name__}.to_database() doit renvoyer du JSON : {exc}"
            ) from None
        DatabaseNotification.create(
            type=class_path(type(notification)),
            notifiable_type=class_path(type(notifiable)),
            notifiable_id=notifiable.id,
            data=data,
        )

import json
import logging

from flask_artisan.notifications.base import Notification
from flask_artisan.notifications.models import DatabaseNotification
from flask_artisan.notifications.notifiable import AnonymousNotifiable
from flask_artisan.queue import Job, ShouldQueue
from flask_artisan.queue.serialization import class_path, import_class

CHANNELS = ("mail", "database")

logger = logging.getLogger(__name__)


class NotificationSender:
    """Le service `"notifications"` : envoie chaque notification sur les canaux de `via()`."""

    def __init__(self, app):
        self._app = app

    def send(self, notifiables, notification) -> None:
        if not isinstance(notifiables, (list, tuple)):
            notifiables = [notifiables]
        first = None
        queued = isinstance(notification, ShouldQueue)
        # Un destinataire ou un canal en échec n'empêche pas les autres ; la 1re erreur remonte.
        # En file aussi : le pilote sync exécute le job dans push() et propagerait l'erreur.
        for notifiable in notifiables:
            try:
                if not queued:
                    self.send_now(notifiable, notification)
                    continue
                for channel in self.channels(notifiable, notification):
                    try:
                        job = SendQueuedNotification.wrap(notification, notifiable, channel)
                        self._app.make("queue").push(job)
                    except Exception as exc:  # noqa: BLE001 (relevée après les autres envois)
                        first = first or exc
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
        route = notifiable.route_notification_for("mail")
        if not route:
            logger.warning(
                "%s : aucun destinataire mail pour %r, canal mail ignoré.",
                type(notification).__name__,
                notifiable,
            )
            return
        mailable = self._payload(notifiable, notification, "mail")
        # Toujours synchrone ici : une notification en file l'est déjà par son propre job.
        self._app.make("mail").to(route).send(mailable)

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


class SendQueuedNotification(Job):
    """Job du framework : une notification `ShouldQueue`, pour un destinataire et un canal."""

    @classmethod
    def wrap(cls, notification, notifiable, channel: str) -> "SendQueuedNotification":
        job = cls()
        job.notification_class = class_path(type(notification))
        job.notification_data = {
            k: v for k, v in vars(notification).items() if not k.startswith("_")
        }
        # Un modèle voyage par identifiant (sérialisation de la file) ; à la demande : ses routes.
        if isinstance(notifiable, AnonymousNotifiable):
            job.notifiable = {"routes": dict(notifiable.routes)}
        else:
            job.notifiable = notifiable
        job.channel = channel
        for setting in ("tries", "backoff", "timeout"):
            if hasattr(notification, setting):
                setattr(job, setting, getattr(notification, setting))
        job.on_queue(getattr(notification, "queue", None))
        return job

    def handle(self) -> None:
        from flask_artisan.helpers import app

        if self.channel not in CHANNELS:
            raise TypeError(f"Canal invalide dans une notification en file : {self.channel!r}.")
        cls = import_class(self.notification_class, Notification)
        notification = cls.__new__(cls)
        for key, value in (self.notification_data or {}).items():
            if not isinstance(key, str) or key.startswith("_"):
                raise TypeError(f"Attribut invalide dans une notification en file : {key!r}.")
            setattr(notification, key, value)
        notifiable = self.notifiable
        if isinstance(notifiable, dict):
            notifiable = AnonymousNotifiable()
            notifiable.routes = dict(self.notifiable.get("routes") or {})
        # Par son nom : le service partagé (mode fake compris), pas une nouvelle instance.
        app().make("notifications").send_now(notifiable, notification, [self.channel])

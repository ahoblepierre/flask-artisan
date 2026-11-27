def _sender():
    from flask_artisan.application import Application

    return Application.get_instance().make("notifications")


class Notification:
    """Une notification : `via()` choisit les canaux, `to_mail()`/`to_database()` les remplissent.

    Pas de façade séparée : `Notification.send(...)`, `.route(...)`, `.fake()` sont des
    méthodes de classe (une façade du même nom se heurterait à cette classe à l'import).
    """

    def via(self, notifiable) -> list[str]:
        raise NotImplementedError(
            f"{type(self).__name__}.via(notifiable) doit renvoyer la liste des canaux."
        )

    @classmethod
    def send(cls, notifiables, notification: "Notification") -> None:
        _sender().send(notifiables, notification)

    @classmethod
    def route(cls, channel: str, value):
        from flask_artisan.notifications.notifiable import AnonymousNotifiable

        return AnonymousNotifiable().route(channel, value)

    @classmethod
    def fake(cls):
        return _sender().fake()

    @classmethod
    def restore(cls) -> None:
        _sender().restore()

"""Notifications façon Laravel : `user.notify(InvoicePaid(invoice))`, canaux mail et database.

L'import de ce paquet enregistre la table `notifications` (modèle DatabaseNotification) :
un projet qui n'utilise pas les notifications ne l'importe pas, et n'a pas la table.
"""

from flask_artisan.notifications.base import Notification
from flask_artisan.notifications.models import DatabaseNotification
from flask_artisan.notifications.notifiable import AnonymousNotifiable, Notifiable

__all__ = ["AnonymousNotifiable", "DatabaseNotification", "Notifiable", "Notification"]

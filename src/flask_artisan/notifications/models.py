import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Index, String

from flask_artisan.database import Mapped, Model, column


class DatabaseNotification(Model):
    """Une notification du canal `database`, destinataire polymorphe (comme Laravel)."""

    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_notifiable", "notifiable_type", "notifiable_id"),)

    id: Mapped[str] = column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    # Chemins `module.Classe` ; pas de clé étrangère : le destinataire peut être tout modèle.
    type: Mapped[str]
    notifiable_type: Mapped[str]
    notifiable_id: Mapped[int]
    data: Mapped[dict] = column(JSON)
    read_at: Mapped[datetime | None]

    fillable = ("type", "notifiable_type", "notifiable_id", "data")

    def mark_as_read(self) -> "DatabaseNotification":
        if self.read_at is None:
            self.read_at = datetime.now(timezone.utc)
            self.save()
        return self

    def mark_as_unread(self) -> "DatabaseNotification":
        if self.read_at is not None:
            self.read_at = None
            self.save()
        return self

    def read(self) -> bool:
        return self.read_at is not None

    def unread(self) -> bool:
        return self.read_at is None

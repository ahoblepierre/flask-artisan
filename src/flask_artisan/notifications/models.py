import os
import threading
import time
import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Index, String

from flask_artisan.database import Mapped, Model, column

_clock = threading.Lock()
_last = [0, 0]  # (milliseconde, séquence) du dernier id


def uuid7() -> str:
    """UUID version 7 (RFC 9562) : croissant dans le temps, et dans un même processus."""
    with _clock:
        ms = time.time_ns() // 1_000_000
        if ms <= _last[0]:
            ms, seq = _last[0], _last[1] + 1
            if seq > 0xFFF:
                ms, seq = ms + 1, 0
        else:
            seq = int.from_bytes(os.urandom(2), "big") & 0x7FF
        _last[:] = [ms, seq]
    rand = int.from_bytes(os.urandom(8), "big") & ((1 << 62) - 1)
    return str(uuid.UUID(int=(ms << 80) | (0x7 << 76) | (seq << 64) | (0b10 << 62) | rand))


class DatabaseNotification(Model):
    """Une notification du canal `database`, destinataire polymorphe (comme Laravel)."""

    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_notifiable", "notifiable_type", "notifiable_id"),)

    id: Mapped[str] = column(String(36), primary_key=True, default=uuid7)
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

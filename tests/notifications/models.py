from flask_artisan.database import Mapped, Model
from flask_artisan.notifications import Notifiable


class NUser(Notifiable, Model):
    name: Mapped[str]
    email: Mapped[str | None]

    fillable = ["name", "email"]


class NTeam(Notifiable, Model):
    name: Mapped[str]

    fillable = ["name"]

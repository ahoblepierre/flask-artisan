from flask_artisan.auth import Authenticatable, HasApiTokens
from flask_artisan.database import Mapped, Model, SoftDeletes
from flask_artisan.notifications import Notifiable


class AMember(Authenticatable, HasApiTokens, Model):
    email: Mapped[str | None]
    password: Mapped[str | None]
    hidden = ["password"]


class AMemberSD(Authenticatable, HasApiTokens, SoftDeletes, Model):
    email: Mapped[str | None]
    password: Mapped[str | None]


class PwUser(Authenticatable, Notifiable, Model):
    email: Mapped[str | None]
    password: Mapped[str | None]
    fillable = ["email", "password"]

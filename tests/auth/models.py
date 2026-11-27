from flask_artisan.auth import Authenticatable, HasApiTokens, MustVerifyEmail
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


class PwTokenUser(Authenticatable, HasApiTokens, Notifiable, Model):
    email: Mapped[str | None]
    password: Mapped[str | None]
    fillable = ["email", "password"]


class VeUser(MustVerifyEmail, Authenticatable, Notifiable, Model):
    email: Mapped[str | None]
    password: Mapped[str | None]
    fillable = ["email", "password"]


class VePlain(Authenticatable, Model):
    email: Mapped[str | None]
    password: Mapped[str | None]
    fillable = ["email", "password"]

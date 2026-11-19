from flask_artisan.auth import Authenticatable, HasApiTokens
from flask_artisan.database import Mapped, Model, SoftDeletes


class AMember(Authenticatable, HasApiTokens, Model):
    email: Mapped[str | None]
    password: Mapped[str | None]
    hidden = ["password"]


class AMemberSD(Authenticatable, HasApiTokens, SoftDeletes, Model):
    email: Mapped[str | None]
    password: Mapped[str | None]

from flask_artisan.auth import Authenticatable, HasApiTokens
from flask_artisan.database import Mapped, Model, column


class User(Authenticatable, HasApiTokens, Model):
    name: Mapped[str]
    email: Mapped[str] = column(unique=True)
    # Haché automatiquement à l'affectation ; vérifier avec user.check_password("...").
    password: Mapped[str]

    # Seules ces clés sont acceptées par User.create(...) / user.update(...).
    fillable = ["name", "email", "password"]
    # Jamais sérialisées en JSON.
    hidden = ["password"]

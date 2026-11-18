from flask_artisan.database import Mapped, Model, column


class User(Model):
    name: Mapped[str]
    email: Mapped[str] = column(unique=True)
    password: Mapped[str]

    # Seules ces clés sont acceptées par User.create(...) / user.update(...).
    fillable = ["name", "email", "password"]
    # Jamais sérialisées en JSON.
    hidden = ["password"]

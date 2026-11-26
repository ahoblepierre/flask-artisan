from flask_artisan.database import Mapped, Model


class CPost(Model):
    title: Mapped[str]
    fillable = ("title",)

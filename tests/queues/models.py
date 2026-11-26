from flask_artisan.database import Mapped, Model


class QPodcast(Model):
    title: Mapped[str]
    fillable = ("title",)

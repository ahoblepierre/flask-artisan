from flask.json.provider import DefaultJSONProvider

from flask_artisan.database.model import Model


class ModelJSONProvider(DefaultJSONProvider):
    """Le JSON de Flask, qui sait aussi sérialiser les modèles (`to_dict()`)."""

    @staticmethod
    def default(o):
        if isinstance(o, Model):
            return o.to_dict()
        return DefaultJSONProvider.default(o)

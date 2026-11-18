# Flask-Artisan

**Les conventions de Laravel, mais c'est du Flask.**

Flask-Artisan donne une structure prête à l'emploi aux applications Flask : conteneur de services,
service providers, configuration par fichiers, façades et helpers. L'application reste un vrai
objet `Flask` : `flask run`, les extensions Flask et leur documentation fonctionnent tels quels.

> Projet en cours de développement (v0.1 en préparation), pas encore publié sur PyPI.

## Démarrer un projet

```bash
pip install "flask-artisan @ git+https://github.com/ahoblepierre/flask-artisan"
flask-artisan new blog
cd blog
pip install -r requirements.txt
flask run
```

Le projet généré :

```
blog/
├── app/providers/app_service_provider.py
├── bootstrap/app.py      # crée l'Application
├── config/app.py         # nom, environnement, debug, clé, providers
├── config/flask.py       # clés copiées dans app.config (extensions Flask)
├── tests/
├── wsgi.py               # détecté par `flask run`
└── .env                  # APP_KEY générée automatiquement
```

## Conteneur de services

```python
from flask_artisan import app

app().bind(Mailer, SmtpMailer)                        # nouvelle instance à chaque make
app().singleton(Cache, lambda app: RedisCache("..."))  # une seule instance
app().make(ReportService)  # dépendances du constructeur injectées d'après leurs annotations
```

## Service providers

```python
from flask_artisan import ServiceProvider


class MailServiceProvider(ServiceProvider):
    def register(self):
        self.app.singleton(Mailer, SmtpMailer)

    def boot(self):
        mail_extension.init_app(self.app)  # n'importe quelle extension Flask
```

Ajoutez la classe à `providers` dans `config/app.py`.

## Configuration

```python
# config/app.py
from flask_artisan import env

config = {"name": env("APP_NAME", "Blog"), "debug": env("APP_DEBUG", False)}
```

```python
from flask_artisan import config

config("app.name")
config("app.timezone", "UTC")  # valeur par défaut
```

## Façades

```python
from flask_artisan import Config, Facade

Config.get("app.name")


class Mail(Facade):
    accessor = Mailer  # n'importe quelle clé du conteneur


Mail.send(...)
```

## Feuille de route v0.1

1. ✅ Socle : package, Application, conteneur, providers, config, façades
2. Routage et middlewares (`routes/web.py`, controllers en classes)
3. ORM façon Eloquent sur SQLAlchemy, migrations
4. Authentification (façade `Auth`, guards session et token)
5. Commandes `flask make:*`, `flask migrate`, `flask route:list`

## Contribuer

Voir [CONTRIBUTING.md](CONTRIBUTING.md).

## Licence

MIT

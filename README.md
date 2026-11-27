# Flask-Artisan

**Les conventions de Laravel, mais c'est du Flask.**

Flask-Artisan donne une structure prête à l'emploi aux applications Flask : conteneur de services,
service providers, configuration par fichiers, façades et helpers. L'application reste un vrai
objet `Flask` : `flask run`, les extensions Flask et leur documentation fonctionnent tels quels.

> Version 0.10 (alpha) : l'API peut encore changer avant la 1.0. Voir le [changelog](https://github.com/ahoblepierre/flask-artisan/blob/main/CHANGELOG.md).

**Documentation : https://ahoblepierre.github.io/flask-artisan/**

## Démarrer un projet

Prérequis : Python 3.10 ou plus.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install flask-artisan
flask-artisan new blog
cd blog
pip install -r requirements.txt
flask run
```

## Un aperçu

```python
# routes/api.py
from flask_artisan import Route
from app.http.controllers.user_controller import UserController

Route.get("/users", UserController.index).name("users.index")

with Route.prefix("/admin").name("admin.").middleware("auth"):
    Route.post("/users", UserController.store)
```

## Ce que couvre la documentation

- [Conteneur de services](https://ahoblepierre.github.io/flask-artisan/conteneur/), [service providers](https://ahoblepierre.github.io/flask-artisan/service-providers/), [configuration](https://ahoblepierre.github.io/flask-artisan/configuration/), [façades](https://ahoblepierre.github.io/flask-artisan/facades/)
- [Routage, controllers et middlewares](https://ahoblepierre.github.io/flask-artisan/routage/)
- [Vues et formulaires](https://ahoblepierre.github.io/flask-artisan/vues/) (erreurs et `old()` après redirection, CSRF, page de connexion)
- [Validation](https://ahoblepierre.github.io/flask-artisan/validation/) (Form Requests, réponses 422)
- [Authentification](https://ahoblepierre.github.io/flask-artisan/authentification/) (guards session et token)
- [Limitation de débit et verrous](https://ahoblepierre.github.io/flask-artisan/limitation-de-debit/)
- [Tests HTTP](https://ahoblepierre.github.io/flask-artisan/tests-http/) (assertions chaînables, `acting_as`)
- [Base de données](https://ahoblepierre.github.io/flask-artisan/base-de-donnees/) (modèles façon Eloquent, migrations)
- [Cache](https://ahoblepierre.github.io/flask-artisan/cache/) (stores `file`, `redis`, `array`)
- [Stockage de fichiers](https://ahoblepierre.github.io/flask-artisan/stockage/) (façade `Storage`, disques local et S3, uploads)
- [Événements](https://ahoblepierre.github.io/flask-artisan/evenements/), [mail](https://ahoblepierre.github.io/flask-artisan/mail/), [notifications](https://ahoblepierre.github.io/flask-artisan/notifications/), [queues](https://ahoblepierre.github.io/flask-artisan/queues/)
- [Tâches planifiées](https://ahoblepierre.github.io/flask-artisan/planification/) (`flask schedule:run`, fréquences, verrous)
- [Console](https://ahoblepierre.github.io/flask-artisan/console/) (`flask make:*`, commandes du projet)

## Contribuer

Voir [CONTRIBUTING.md](https://github.com/ahoblepierre/flask-artisan/blob/main/CONTRIBUTING.md).

## Licence

MIT

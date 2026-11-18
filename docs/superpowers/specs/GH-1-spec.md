# GH-1 — Socle : package framework, Application, conteneur, providers, config, façades

Ticket : https://github.com/ahoblepierre/flask-artisan/issues/1
Statut : brouillon, en attente d'approbation

## Intention

Flask-Artisan est un framework open source qui apporte les conventions de Laravel à Flask, **Flask restant le moteur**. Le différenciateur face à Masonite (« Laravel en Python » mais sans Flask) : toute l'écosystème Flask (extensions, `flask run`, doc, hébergeurs) fonctionne tel quel.

Ce chantier pose le socle sur lequel se brancheront les chantiers suivants de la v0.1 (routage, ORM, auth, CLI) :

- un **package pip `flask-artisan`** (le framework), séparé d'un **squelette de projet** généré par `artisan new` ;
- une classe `Application` qui **est** un Flask ;
- un conteneur de services, des service providers, une config à la Laravel, des façades et quelques helpers.

Public visé : un développeur Python (souvent venant de Laravel) qui veut démarrer un projet Flask structuré en une commande, et des contributeurs externes qui doivent pouvoir lire et tester le code facilement.

## Objectifs

1. Installer le package puis `artisan new blog && cd blog && flask run` donne une application qui répond. **Pas de publication PyPI dans ce chantier** (décision de Pierre : publication à la fin de la v0.1) ; l'objectif est vérifié avec un wheel construit localement, et le `requirements.txt` du squelette pointe vers `flask-artisan @ git+https://github.com/ahoblepierre/flask-artisan` jusqu'à la publication.
2. Un développeur Laravel reconnaît immédiatement : `app.bind/singleton/make`, `ServiceProvider.register/boot`, `config("app.name")`, `env("APP_DEBUG")`, façades `App` et `Config`.
3. Toute extension Flask s'installe comme d'habitude (`ext.init_app(app)`), typiquement dans un provider.
4. Package testé (pytest) et CI GitHub Actions dès ce chantier.

## Non-objectifs (chantiers suivants)

Routage à la Laravel et controllers en classes (2), ORM et migrations (3), auth (4), commandes `make:*`, `serve`, `migrate` (5). Validation, events, mail, cache, queues : après v0.1.

Pas non plus dans ce chantier : bindings à portée de requête, cache des façades, `Facade.fake()`, alias du conteneur, `app.call()` (injection dans les fonctions — arrive avec le chantier 2 qui en a besoin).

## Anti-objectifs

- Casser la compatibilité Flask (un `Application` qui ne serait pas un vrai `Flask`).
- Ajouter une dépendance externe au cœur pour quelque chose que la bibliothèque standard fait.
- Une API « inspirée » mais différente de Laravel sans raison : quand Laravel a un nom, on le reprend.

## Approches considérées

| | Approche | Verdict |
|---|---|---|
| **A** | `Application` hérite de `Flask` (et du conteneur), conteneur maison | **Choisie** par Pierre : garde la compatibilité totale Flask, API calquée sur Laravel, conteneur ~150 lignes facile à tester. |
| B | Même structure, conteneur = bibliothèque existante (dependency-injector, punq) | Écartée : API non-Laravel à envelopper quand même, dépendance externe au cœur. |
| C | `Application` contient un Flask (composition) | Écartée : `flask run` et les extensions ne marchent plus tels quels, ce qui détruit le différenciateur. |

## Conception

### Organisation du repo

```
flask-artisan/
├── pyproject.toml            # package "flask-artisan", entry point `artisan`
├── src/flask_artisan/
│   ├── __init__.py           # exporte Application, ServiceProvider, Facade, app, config, env, base_path
│   ├── container.py          # Container, BindingResolutionError
│   ├── application.py        # Application(Flask, Container)
│   ├── providers.py          # ServiceProvider
│   ├── config.py             # Repository (config/*.py, notation pointée)
│   ├── env.py                # env() + chargement .env
│   ├── helpers.py            # app(), config(), base_path()
│   ├── facades.py            # Facade, App, Config
│   ├── cli.py                # `artisan new`
│   └── skeleton/             # squelette copié par `artisan new` (données du package)
├── tests/
├── docs/
└── .github/workflows/ci.yml
```

L'ébauche actuelle (`app/`, `app.py`, `setup.py`, `requirements.txt`, `migrations/`, `instance/`, `build/`, `dist/`, `*.egg-info`, `__pycache__`, `.DS_Store`) est **supprimée** ; ses fonctionnalités (auth, modèles, commandes) seront refaites proprement dans les chantiers 2 à 5. L'historique git les conserve. `.gitignore` est complété en conséquence. *(Décision de Claude, validée avec « on réorganise tout ».)*

### Conteneur (`Container`)

API (noms Laravel) :

- `bind(abstract, concrete=None)` — nouvelle instance à chaque `make`.
- `singleton(abstract, concrete=None)` — une seule instance, créée au premier `make`.
- `instance(abstract, obj)` — enregistre un objet déjà construit.
- `make(abstract, **params)` — résout.
- `bound(abstract) -> bool`.

Règles :

- `abstract` est une classe ou une chaîne (`"config"`, `"app"`).
- `concrete` est une classe, ou un callable `lambda app: ...` qui reçoit le conteneur. `None` = `abstract` lui-même (doit être une classe).
- **Autowiring** : une classe non enregistrée est construite en résolvant les paramètres de son `__init__` via leurs annotations de type (`typing.get_type_hints`). Un paramètre sans annotation de classe résoluble utilise sa valeur par défaut ; sinon `BindingResolutionError` avec le nom de la classe et du paramètre. Les `**params` passés à `make` sont prioritaires.
- Détection des dépendances circulaires (pile de résolution) → `BindingResolutionError` lisible, pas de `RecursionError`.
- Création des singletons protégée par un `threading.RLock` (le serveur Flask est multithreadé).

### Application

```python
class Application(Flask, Container):
    def __init__(self, base_path: str | Path): ...
```

Au constructeur, dans cet ordre :

1. `Flask.__init__(import_name=<nom du dossier>, root_path=base_path)`.
2. Charge `base_path/.env` (python-dotenv, sans écraser les variables déjà présentes dans l'environnement).
3. Charge la config (`config/*.py`) dans un `Repository`.
4. **Pont vers Flask** : `SECRET_KEY = config("app.key")`, `DEBUG = config("app.debug")`, puis chaque clé du fichier `config/flask.py` est copiée telle quelle dans `app.config` (c'est là qu'on met `SQLALCHEMY_DATABASE_URI`, etc., pour les extensions).
5. S'enregistre dans le conteneur sous `"app"` et `Application` ; le `Repository` sous `"config"` et `Repository`.
6. Se déclare instance courante (`Application.get_instance()`, utilisée par façades et helpers).
7. Enregistre chaque provider de `config("app.providers")` (appel de `register()`), puis les boote tous (appel de `boot()`).

**Mode debug sous `flask run`** : la CLI Flask écrase `app.debug` avec `FLASK_DEBUG` après chargement de l'app, donc le pont `DEBUG` ne suffit pas. Le `.env` généré contient `FLASK_DEBUG=${APP_DEBUG}` (interpolation de python-dotenv, que la CLI Flask charge avant l'app) : `APP_DEBUG` reste la seule valeur à changer. Le pont `DEBUG` couvre les serveurs WSGI (gunicorn…). Un test vérifie le chemin réel via le `FlaskGroup`/`ScriptInfo` de Flask, pas seulement `Application(...)`. *(Décision de Claude.)*

Si `app.key` est vide, le constructeur lève une erreur explicite (« APP_KEY manquant dans .env »). `artisan new` la génère, donc ça n'arrive qu'en cas d'oubli.

Autres méthodes : `register(provider_class)` (si l'app est déjà bootée, boote aussi ce provider), `boot()` (idempotent), `base_path(path="")`, `config_path(path="")`, `app_path(path="")`, `environment()` → `config("app.env")`.

### Service providers

```python
class ServiceProvider:
    def __init__(self, app: Application): self.app = app
    def register(self): ...   # uniquement des bindings
    def boot(self): ...       # tout le reste (init_app d'extensions, etc.)
```

Même règle qu'en Laravel : `register` ne doit pas résoudre de services, `boot` peut.

### Configuration

- Chaque fichier `config/<nom>.py` définit un dict `config = {...}`. Clé de premier niveau = nom du fichier.
- `Repository.get("app.name", default=None)`, `.set(key, value)`, `.has(key)`, `.all()`, notation pointée sur les dicts imbriqués.
- Fichiers chargés avec `importlib` à partir de leur chemin (pas d'import par nom de module, pour éviter les conflits avec d'autres packages `config`).

### env()

`env(key, default=None)` lit `os.environ` avec les conversions de Laravel : `"true"/"(true)"` → `True`, `"false"/"(false)"` → `False`, `"null"/"(null)"` → `None`, `"empty"/"(empty)"` → `""`, guillemets entourants retirés. Insensible à la casse pour ces mots-clés.

### Façades

```python
class Facade(metaclass=FacadeMeta):
    accessor: str | type   # clé dans le conteneur

class Config(Facade): accessor = "config"
class App(Facade):    accessor = "app"

Config.get("app.name")   # → Application.get_instance().make("config").get("app.name")
```

Le métaclasse redirige tout accès d'attribut vers l'objet résolu. Pas de cache : chaque appel passe par `make` (un singleton = une recherche dans un dict), ce qui évite les instances périmées entre tests. L'utilisateur crée ses façades de la même manière.

### Helpers

`app(abstract=None, **params)` (sans argument : l'application ; sinon `make`), `config(key=None, default=None)` (sans argument : le `Repository`), `env(...)`, `base_path(path="")`. Erreur claire si aucune application n'a été créée.

### Squelette et `artisan new`

Squelette généré :

```
blog/
├── app/providers/app_service_provider.py   # AppServiceProvider vide commenté
├── bootstrap/app.py      # app = Application(Path(__file__).resolve().parent.parent)
├── config/app.py         # name, env, debug, key, providers
├── config/flask.py       # clés passées telles quelles à app.config
├── tests/test_app.py     # l'app démarre
├── wsgi.py               # from bootstrap.app import app  (détecté par `flask run`)
├── .env.example  .env  .gitignore  requirements.txt (flask-artisan, via git jusqu'à la publication PyPI)
```

En attendant le routage du chantier 2, `AppServiceProvider.boot()` déclare une route `/` de démonstration avec le `@app.route` Flask standard (renvoie le nom de l'app) — ce qui montre aussi que Flask « nu » marche.

`artisan new <nom>` (click, déjà dépendance de Flask) :

- refuse si le dossier existe et n'est pas vide ;
- copie `skeleton/` ;
- crée `.env` à partir de `.env.example` avec `APP_KEY` = `secrets.token_hex(32)` et `APP_NAME` = `<nom>` ;
- affiche les prochaines étapes (`cd`, `flask run`).

### Dépendances et outillage

- Python ≥ 3.10. Dépendances : `flask>=3`, `python-dotenv`. Rien d'autre dans le cœur (JWT, Talisman, WTF, Login, SQLAlchemy reviendront dans leurs chantiers respectifs).
- `pyproject.toml` (setuptools), version `0.1.0.dev0`, entry point `artisan = flask_artisan.cli:main`, `skeleton/` inclus comme données du package.
- Dev : `pytest`, `ruff` (lint + format) en extra `dev`.
- CI GitHub Actions : ruff + pytest sur Python 3.10 à 3.13.

### Tests attendus

- Conteneur : bind / singleton / instance, autowiring en chaîne, valeur par défaut, `**params` prioritaires, erreur sur paramètre non résoluble, erreur sur dépendance circulaire, singleton unique sous accès concurrents.
- Config : chargement des fichiers, notation pointée, défaut, `set`.
- `env()` : chaque conversion.
- Application : est une instance de `Flask` ; pont `SECRET_KEY`/`DEBUG`/`config/flask.py` ; ordre register-puis-boot ; provider enregistré après boot est booté ; erreur si `APP_KEY` absent.
- Façades et helpers : résolution, erreur sans application.
- `artisan new` : génère le projet dans `tmp_path`, `.env` contient une clé, refus sur dossier non vide ; le projet généré démarre et `GET /` répond 200 (via le client de test Flask).

### Documentation

README réécrit : pitch (« Laravel, mais c'est du Flask »), installation, `artisan new`, conteneur/providers/config/façades en exemples courts, état de la feuille de route. `CONTRIBUTING.md` court : installation dev, lancer tests et ruff, conventions issues/branches/PR du `CLAUDE.md`.

## Laissé au builder

Découpage interne des modules au-delà de ce qui est listé, messages d'erreur exacts, contenu des commentaires du squelette, détails du workflow CI.

## Livraison

Branche `feat/1-socle`, plan `docs/superpowers/plans/GH-1-plan.md`, PR `… (#1)` avec `Closes #1`.

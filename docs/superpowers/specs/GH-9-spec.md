# GH-9 — CLI : générateurs `flask make:*`, commandes du projet, `flask route:list`

Ticket : https://github.com/ahoblepierre/flask-artisan/issues/9
Statut : en attente d'approbation

## Intention

Dernier chantier de la v0.1. Un développeur Laravel tape `php artisan make:controller` sans y penser ; ici, il doit retrouver le même réflexe dans `flask` :

```bash
flask make:controller PhotoController --resource
flask make:command SendEmails
flask app:send-emails 42        # sa propre commande, découverte toute seule
flask route:list
```

Les générateurs écrivent le fichier au bon endroit, avec le bon squelette. Les commandes du projet sont de simples commandes Click, découvertes dans `app/console/commands/`.

## Objectifs

1. `flask make:controller`, `make:model`, `make:middleware`, `make:provider`, `make:command` créent un fichier prêt à l'emploi dans le dossier de convention.
2. Un fichier Python dans `app/console/commands/` qui définit une commande Click devient une commande `flask`, sans rien déclarer ailleurs. Elle s'exécute dans le contexte de l'application (modèles, `config`, façades utilisables).
3. `flask route:list` montre, pour chaque route déclarée avec `Route`, les méthodes, l'URI, le nom, l'action et les middlewares résolus.
4. Les commandes sont disponibles dans tout projet Flask-Artisan, sans provider à déclarer.

## Non-objectifs (hors périmètre)

- Personnalisation des modèles de fichiers (`stub:publish`).
- Filtres de `route:list` (`--path`, `--name`, `--method`).
- `make:test`, `make:request`, `make:seeder`, `make:factory` (pas de validation ni de seeders en v0.1).
- `make:model -m` : nos migrations sont générées depuis les colonnes du modèle, une migration lancée sur un modèle vide n'aurait rien d'utile.
- Commandes en classes avec signature texte façon Laravel (approche B écartée).
- Édition automatique de `config/app.py` ou du kernel.

## Anti-objectifs

- Écraser un fichier existant sans `--force`.
- Réécrire automatiquement du code Python du projet (config, kernel).
- Masquer une erreur dans une commande du projet : un fichier de `app/console/commands/` qui ne s'importe pas doit faire échouer `flask` avec un message qui nomme le fichier.

## Approches considérées

Pour les commandes du projet :

- **A. Commandes Click** (retenue). Format natif de Flask, rien à maintenir. `@click.command("app:send-emails")` + `@click.argument(...)`.
- **B. Classes façon Laravel** (`signature = "app:send-emails {user} {--queue}"`, `handle()`). Familier pour un dev Laravel, mais demande un parseur de signature qui fera toujours moins que Click.

Pour le branchement : dans `Application` (retenu, toujours disponible) plutôt qu'un `ConsoleServiceProvider` à déclarer (un oubli de plus possible) ou un provider par chantier comme pour les migrations (dispersé).

## Décisions

### Branchement

- `Application` ajoute à `app.cli` les commandes du framework (`make:*`, `route:list`) dans son constructeur.
- La découverte des commandes du projet ne tourne **que pour le CLI** : `app.cli` est un groupe Click (sous-classe d'`AppGroup`) qui, à la première demande de liste ou de commande (`list_commands`, `get_command`), importe les fichiers `app/console/commands/*.py` (hors `__init__.py`, ordre alphabétique) et ajoute chaque objet `click.Command` défini au niveau du module. Choix : un fichier cassé dans `app/console/commands/` ne doit pas empêcher l'app web (gunicorn, `flask run`, client de test) de démarrer, ni être importé dans chaque worker.
- Les commandes ainsi ajoutées s'exécutent dans un app context (comme celles déclarées avec `@app.cli.command`).
- Dossier absent : rien à faire. Erreur d'import : `flask` échoue avec un message qui nomme le fichier (l'exception d'origine est chaînée).
- Deux commandes de même nom : la dernière importée gagne ; pas de détection en v0.1.

### Noms et chemins

- Le nom donné est en CamelCase (`UserController`, `EnsureJson`). Il peut contenir des `/` pour un sous-dossier : `Admin/UserController`.
- Le fichier est le nom en snake_case : `UserController` → `user_controller.py`, `HTTPClient` → `http_client.py` (même règle que `_snake` des modèles).
- Un sous-dossier est créé avec un `__init__.py` vide à chaque niveau.
- `make:model` et `make:command` **refusent** les sous-dossiers (erreur claire) : le chargement des modèles (`import_models`) et la découverte des commandes ne lisent que le premier niveau de leur dossier, un fichier plus profond ne serait jamais vu. Les controllers, middlewares et providers sont importés explicitement par le code du projet : les sous-dossiers y sont permis.
- Un nom invalide (vide, qui n'est pas un identifiant Python après découpe) → erreur Click claire.
- Fichier déjà présent → erreur `Le fichier … existe déjà (--force pour l'écraser).` ; avec `--force`, il est réécrit.
- Chaque générateur affiche le chemin créé, relatif à la racine du projet.

### Générateurs

| Commande | Dossier | Contenu |
|---|---|---|
| `make:controller Nom` | `app/http/controllers/` | classe vide avec une méthode `index` d'exemple |
| `make:controller Nom --resource` | idem | les 7 méthodes de `Route.resource` : `index`, `create`, `store`, `show(id)`, `edit(id)`, `update(id)`, `destroy(id)` |
| `make:model Nom` | `app/models/` | `class Nom(Model)` avec `fillable = []` et un commentaire d'exemple de colonne ; affiche ensuite « ajoutez vos colonnes, puis `flask make:migration "create <table>"` » (table = nom de table du modèle) |
| `make:middleware Nom` | `app/http/middleware/` | `class Nom(Middleware)` avec `handle(self, request, next)` ; affiche la ligne d'alias à ajouter au kernel |
| `make:provider Nom` | `app/providers/` | `class Nom(ServiceProvider)` avec `register` et `boot` ; affiche la ligne à ajouter à `providers` dans `config/app.py` |
| `make:command Nom [--command app:nom]` | `app/console/commands/` | fonction Click ; nom de commande par défaut `app:<nom-en-kebab>` (`SendEmails` → `app:send-emails`) |

- Les modèles de fichiers sont des fichiers texte du package, dans `src/flask_artisan/stubs/`, remplis avec `string.Template`. Ils sont ajoutés à `package-data`.
- Un fichier généré passe `ruff check` et `ruff format --check` avec la config du projet.

### `flask route:list`

- Le `Router` garde la liste des routes qu'il a poussées dans Flask (au `flush`), avec leur endpoint et leur pile de middlewares résolue.
- Tableau en texte, une ligne par route, triée par URI puis par méthode :

```
Méthodes   URI             Nom          Action                       Middlewares
GET        /               home         HomeController@index
POST       /api/login      api.login    AuthController@login
GET        /api/user       api.user     AuthController@user          Authenticate:api
```

- Méthodes : celles déclarées (sans `HEAD`/`OPTIONS` ajoutés par Flask), jointes par `|`.
- Action : `Classe@méthode` pour un controller, nom de la fonction sinon.
- Middlewares : noms de classe, avec les paramètres après `:`, joints par `, `.
- Les routes ajoutées directement avec Flask (`@app.route`, blueprints, `static`) ne sont pas listées (`flask routes` de Flask les montre).
- Aucune route : message `Aucune route déclarée.`

### Squelette

- `app/console/__init__.py`, `app/console/commands/__init__.py` (vides).
- Pas de commande d'exemple livrée (un fichier d'exemple apparaîtrait dans `flask --help` de chaque projet).

### Documentation

- README : section « Console » (générateurs, commandes du projet, `route:list`). Feuille de route : point 5 coché.
- CLAUDE.md : branchement des commandes et découverte dans `Application`, `Router` qui garde ses routes.

## Pièges connus

- **App context.** Une commande ajoutée par `app.cli.add_command` n'a pas d'app context automatiquement : il faut l'envelopper (`flask.cli.with_appcontext`) ou passer par `AppGroup`.
- **Import du paquet `app`.** La découverte importe `app.console.commands.<fichier>` : la racine du projet doit être dans `sys.path` (comme pour `import_models`).
- **Tests.** Deux apps de test dans un même processus partagent `sys.modules` : utiliser `project_modules` pour isoler le paquet `app` d'un projet de test.

## Laissé au constructeur

- Module(s) du package : `flask_artisan/console.py` ou un sous-paquet.
- Mise en forme exacte du tableau de `route:list` (largeurs de colonnes).
- Contenu exact des modèles de fichiers, dans le respect du tableau ci-dessus et des conventions du squelette.

## Livraison

- Tests pytest : chaque générateur (chemin, contenu importable, `--force`, sous-dossier, sous-dossier refusé pour model/command, nom invalide, `--resource`, `--command`), découverte des commandes du projet (exécution dans l'app context, erreur d'import nommant le fichier, dossier absent, un fichier cassé n'empêche pas l'app web de démarrer), `route:list` (action controller et fonction, middlewares avec paramètres, groupes, aucune route).
- Test de bout en bout du projet généré : `make:controller --resource`, `make:command` puis exécution de la commande générée, `route:list` qui montre les routes du squelette ; les fichiers générés passent ruff.
- README et CLAUDE.md à jour.
- PR `feat/9-cli`, titre avec `(#9)`, corps avec `Closes #9`. CI verte sur 3.10 à 3.13.

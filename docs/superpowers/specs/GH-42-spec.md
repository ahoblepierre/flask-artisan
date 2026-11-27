# GH-42 : tâches planifiées

Ticket : https://github.com/ahoblepierre/flask-artisan/issues/42

## Pourquoi

Les tâches récurrentes d'un projet (un rapport chaque jour à 8 h, un nettoyage toutes les 5 minutes) demandent aujourd'hui une ligne cron par tâche. Ces lignes vivent sur le serveur, hors du code, et rien n'empêche deux exécutions de se chevaucher. Laravel déclare ces tâches en code, dans le projet, et n'a besoin que d'une ligne cron qui lance le planificateur chaque minute. C'est un des outils de Laravel les plus utilisés, et il s'appuie sur les verrous livrés en 0.7 (#36).

## Objectifs (approche A, choisie par Pierre)

- Les tâches se déclarent dans `routes/console.py` avec la façade `Schedule` :
  - `Schedule.command("emails:send --force")` lance une commande `flask` ;
  - `Schedule.job(RapportJob(...))` envoie un job dans la queue ;
  - `Schedule.call(fn)` appelle une fonction.
- Les fréquences courantes existent, plus une expression cron libre.
- `without_overlapping()` et `on_one_server()` s'appuient sur `Cache.lock`.
- Trois commandes : `flask schedule:run`, `flask schedule:work` et `flask schedule:list`.
- Une clé de config `app.timezone` est ajoutée.
- Une aide de test indique les tâches dues à une heure donnée.
- Une page de doc « Tâches planifiées » est ajoutée.

## Non-objectifs

- Exécution en arrière-plan (`run_in_background`), hooks `before` et `after`, sortie envoyée par mail ou dans un fichier, ping d'URL.
- Fréquences de moins d'une minute, mode maintenance, `environments(...)`, conditions `when` et `skip`.
- Commande `schedule:test`.

## Anti-objectifs

- L'app web ne doit jamais charger `routes/console.py`. Seules les commandes `schedule:*` le chargent, comme les commandes du projet. Un fichier cassé ne doit donc pas bloquer l'app web.
- L'échec d'une tâche ne doit pas empêcher les autres tâches dues de s'exécuter.
- Une tâche ne doit jamais s'exécuter deux fois dans la même minute pour une même exécution de `schedule:run`. Le cas du changement d'heure est traité plus bas.

## Approches envisagées

- **A. Le cœur de Laravel** : retenue par Pierre.
- **B. Le minimum** (`call` + `cron` + `schedule:run`) : écartée, car elle n'offre aucune protection contre les doubles exécutions.
- **Analyse des expressions cron : par nous, sans dépendance** (choix du rédacteur). Le format à 5 champs est petit. `croniter`, la dépendance la plus courante, a changé de mainteneur en 2025, et on n'a besoin que de tester si une minute correspond, pas de parcourir les dates.

## Décisions

### API

Module `src/flask_artisan/scheduling.py` :
- classe `Schedule` : le registre des tâches. `Application` crée l'instance et l'enregistre dans le conteneur (`"schedule"`), comme le `Dispatcher` ;
- classe `Event` : une tâche ;
- façade `Schedule` dans `facades.py`, exportée par `flask_artisan`.

Le registre expose :
- `command(name: str) -> Event` : `name` est découpé avec `shlex.split` ;
- `job(job: Job, queue: str | None = None, connection: str | None = None) -> Event` : comme Laravel, `queue` est la **file** (appliquée par `job.on_queue(queue)`) et `connection` la connexion de `queue.connections` (`Queue.connection(name)`, nom inconnu → `ValueError` à l'exécution comme aujourd'hui) ;
- `call(fn, *args, **kwargs) -> Event` ;
- `events() -> list[Event]` ;
- `due_events(now: datetime) -> list[Event]`, qui exige un `datetime` avec fuseau, sinon `ValueError`. C'est l'aide de test.

Chaque méthode de fréquence de `Event` renvoie l'`Event` lui-même, pour enchaîner les appels :

| Méthode | Expression |
|---------|-----------|
| `cron(expr)` | `expr` telle quelle (validée) |
| `every_minute()` | `* * * * *` |
| `every_two_minutes()`, `every_five_minutes()`, `every_ten_minutes()`, `every_fifteen_minutes()`, `every_thirty_minutes()` | `*/n * * * *` |
| `hourly()` | `0 * * * *` |
| `hourly_at(minute)` | `m * * * *` |
| `daily()` | `0 0 * * *` |
| `daily_at("HH:MM")` | `M H * * *` |
| `weekly()` | `0 0 * * 0` |
| `weekly_on(day, "HH:MM"="00:00")` | `M H * * day` (0 = dimanche … 6 = samedi) |
| `monthly()` | `0 0 1 * *` |
| `monthly_on(day=1, "HH:MM"="00:00")` | `M H day * *` |
| `weekdays()` | remplace le champ jour de semaine par `1-5` |
| `weekends()` | remplace le champ jour de semaine par `0,6` |

Autres méthodes de `Event` :
- `timezone(name)` : un nom IANA, validé par `zoneinfo.ZoneInfo`. Un nom inconnu lève `ValueError`.
- `name(text)` : le libellé affiché par `schedule:list` et utilisé dans les clés de verrou. Par défaut, c'est la commande, le chemin de la classe du job ou le nom qualifié de la fonction.
- `without_overlapping(minutes=1440)`.
- `on_one_server()`.

Une tâche `call` sur une lambda ou une fonction locale (nom qualifié contenant `<lambda>` ou `<locals>`) qui reçoit `without_overlapping()` ou `on_one_server()` sans `name()` préalable lève `ValueError` (Laravel lève une `LogicException`) : sinon deux lambdas partageraient le même verrou. `name()` doit donc être appelé avant ces deux méthodes.

Les arguments invalides lèvent `ValueError` au moment de la déclaration, avec un message qui nomme la méthode. Exemples : `daily_at("25:00")`, `weekly_on(7)`, `hourly_at(60)`, une expression cron mal formée.

### Expressions cron

- Cinq champs : minute (0-59), heure (0-23), jour du mois (1-31), mois (1-12), jour de semaine (0-7, où 0 et 7 désignent dimanche).
- Chaque champ accepte `*`, `n`, `a-b`, `*/n`, `a-b/n` et les listes séparées par des virgules. Les noms (`mon`, `jan`) et les macros (`@daily`) ne sont pas acceptés.
- Sémantique du planificateur de Laravel (le cron classique traite aussi `*/n` comme libre) : si le jour du mois **et** le jour de semaine sont tous deux restreints, la tâche est due quand l'un **ou** l'autre correspond.
- Une tâche est due quand l'heure courante, tronquée à la minute et convertie dans son fuseau (celui de la tâche, sinon `app.timezone`), correspond à l'expression.

### Fuseau horaire

- `config/app.py` du squelette : `"timezone": env("APP_TIMEZONE", "UTC")`. Sans cette clé, la valeur est `UTC`.
- Le nom est validé au chargement du planning. Une valeur inconnue lève `ValueError` en nommant `APP_TIMEZONE`.
- Changement d'heure : comme le planificateur de Laravel, on compare l'heure locale. Une heure qui n'existe pas (passage à l'heure d'été) est sautée. Une heure qui existe deux fois (passage à l'heure d'hiver) peut lancer la tâche deux fois. C'est documenté.
- Windows n'a pas de base de fuseaux horaires : on ajoute la dépendance `tzdata; sys_platform == "win32"`.

### Exécution

`schedule:run` :
1. Charge `routes/console.py`.
2. Calcule la minute courante une seule fois, au démarrage.
3. Exécute les tâches dues **l'une après l'autre**, dans l'ordre de déclaration.

Pour chaque tâche :
- **commande** : lancée dans le même processus, avec `app.cli.main(args, prog_name="flask", standalone_mode=False)`. Une commande inconnue est une erreur de cette tâche. Un code de sortie différent de 0 compte comme un échec.
- **job** : envoyé avec la queue (`Queue.push`, ou `Queue.connection(connection).push`), dans la file `queue` si elle est précisée. Le planificateur n'attend pas la fin du job. C'est la manière recommandée pour un travail long.
- **fonction** : appelée avec `app.call(fn, *args, **kwargs)`, donc avec l'injection du conteneur.

Affichage et code de sortie :
- Le planificateur affiche une ligne avant chaque tâche (`Exécution : <name>`), puis `OK` ou l'erreur.
- Une exception est affichée avec sa trace sur stderr, et le planificateur passe à la tâche suivante.
- Le code de sortie est 1 si une tâche a échoué, 0 sinon.
- Si aucune tâche n'est due, il affiche `Aucune tâche planifiée à exécuter.`

### Verrous

- Ils passent par le store de cache par défaut (`Cache.lock`).
- Identifiant d'une tâche : `sha1(expression + fuseau + name)`.
- **`without_overlapping(minutes)`** :
  - le planificateur prend le verrou `schedule:<id>` avant de lancer la tâche ;
  - il le libère après la tâche, même en cas d'échec ;
  - s'il ne peut pas prendre le verrou, la tâche est sautée et le planificateur affiche `Sautée (déjà en cours) : <name>` ;
  - la durée `minutes` est le TTL de sécurité, au cas où le processus meurt.
- **`on_one_server()`** :
  - le planificateur prend le verrou `schedule:<id>:<minute UTC AAAAMMJJHHMM>` avec un TTL de 3600 s, et ne le libère jamais ;
  - le serveur qui le prend exécute la tâche, et les autres la sautent ;
  - cela n'a de sens qu'avec un store partagé (`redis`), et la doc le dit.
- Pour un job, le verrou de `without_overlapping` couvre l'envoi dans la queue, pas l'exécution par le worker. C'est documenté : pour un job, la protection se fait côté job (hors périmètre).

### `schedule:work`

- C'est une boucle dans le processus. Elle charge le planning une seule fois.
- À chaque début de minute, elle exécute la même logique que `schedule:run` pour cette minute.
- Elle s'arrête sur Ctrl+C (sortie propre, code 0).
- Si une tâche dure plus d'une minute, les minutes manquées ne sont **pas** rattrapées. C'est documenté : pour un travail long, utiliser `job`.
- Elle est destinée au développement, ou à un conteneur sans cron.

### `schedule:list`

Un tableau avec trois colonnes :
- `Expression` ;
- `Prochaine exécution`, dans le fuseau de la tâche, calculée en avançant minute par minute, avec au plus 366 jours ;
- `Tâche` (le `name`).

Sans tâche, il affiche `Aucune tâche planifiée.`

### Chargement de `routes/console.py`

- Le fichier est chargé avec le même mécanisme que `Router.load` (chargement depuis le chemin du fichier). Une erreur dans le fichier devient une `click.ClickException` qui nomme le fichier.
- Si le fichier n'existe pas, le planning est vide.
- Le registre est vidé avant chaque chargement : charger deux fois ne duplique pas les tâches.

### Squelette

- `routes/console.py` contient un exemple commenté de chaque type de tâche.
- `config/app.py` contient `timezone`, et `.env.example` contient `APP_TIMEZONE=UTC`.

### Documentation

- Nouvelle page `docs/planification.md`, intitulée « Tâches planifiées » dans la rubrique « Tâches de fond » de la navigation. Elle couvre :
  - la ligne cron à installer : `* * * * * cd /chemin/du/projet && .venv/bin/flask schedule:run >> /dev/null 2>&1` ;
  - les trois types de tâches ;
  - le tableau des fréquences ;
  - le fuseau et le changement d'heure ;
  - les verrous et le store qu'ils demandent ;
  - `schedule:work` et `schedule:list` ;
  - comment tester.
- Une ligne dans la liste du README, une puce dans CLAUDE.md et une entrée dans le CHANGELOG.

## Vérification

- Tests unitaires de l'analyse cron :
  - chaque forme de champ ;
  - la règle du « ou » entre jour du mois et jour de semaine ;
  - le 7 qui vaut dimanche ;
  - les erreurs.
- Tests de chaque fréquence via `due_events`, sur des dates fixes avec fuseau, dont un passage à l'heure d'été en `Europe/Paris`.
- Tests de `schedule:run` avec `CliRunner` : les trois types de tâches, l'échec isolé avec le code 1, et le message quand rien n'est dû.
- Tests des verrous avec le store `array` : une tâche dont le verrou est déjà pris est sautée, et `on_one_server` n'exécute qu'une fois pour deux exécutions de la même minute.
- Un test du projet généré, en sous-processus : `flask schedule:list` fonctionne sur le squelette.
- `mkdocs build --strict`, la suite pytest et ruff passent.

## Choix du rédacteur (relecture builder)

- Commande en échec : un `SystemExit` ou `click.exceptions.Exit` non nul, ou une `ClickException`, comptent comme échec.
- `schedule:work` pousse un contexte d'application neuf à chaque minute (comme `worker.run` par job) pour retirer la session de base de données ; il attend le début de la minute suivante avant la première exécution.
- Le fuseau de l'identifiant de verrou est le fuseau effectif (celui de la tâche, sinon `app.timezone`) ; `app.timezone` est validé aussi par `due_events`.
- `schedule:list` affiche `—` sans exécution dans les 366 jours (ex. `0 0 31 2 *`) ; le calcul saute heures et jours qui ne correspondent pas.
- Avec les deux verrous, `on_one_server` est pris avant `without_overlapping`, tous deux par `Lock.get()` (sans attente).
- La classe `Event` de `scheduling.py` n'est pas exportée par `flask_artisan` (la façade `Event` des événements existe déjà).
- Les tests de `schedule:run` passent par un vrai `routes/console.py` dans un projet temporaire.

## Laissé au rédacteur du plan

- Le découpage interne de `scheduling.py` (analyse cron, `Event`, `Schedule`, commandes Click).
- Comment injecter l'horloge dans les tests de `schedule:run` (fixture ou paramètre caché).

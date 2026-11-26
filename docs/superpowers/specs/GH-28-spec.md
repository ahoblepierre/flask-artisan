# GH-28 — Queues : jobs sur RQ, `queue:work`, échecs, `Mail.queue`, écouteurs `ShouldQueue`

Ticket : https://github.com/ahoblepierre/flask-artisan/issues/28
Statut : en attente d'approbation (relecture constructeur faite)

## Intention

Sortir d'une requête le travail long ou fragile (envoi de mail, traitement de fichier, appel à une API tierce) pour qu'il s'exécute en arrière-plan, avec nouvelles tentatives en cas d'échec. Un développeur Laravel s'attend à écrire :

```python
# app/jobs/process_podcast.py
from flask_artisan.queue import Job


class ProcessPodcast(Job):
    tries = 3
    backoff = [10, 60]                     # secondes avant la 2e, puis la 3e tentative

    def __init__(self, podcast: Podcast):
        self.podcast = podcast             # un modèle voyage par son identifiant

    def handle(self, transcoder: Transcoder):   # dépendances injectées par le conteneur
        transcoder.run(self.podcast)

    def failed(self, exc: Exception):      # après la dernière tentative
        ...


ProcessPodcast.dispatch(podcast)
dispatch(ProcessPodcast(podcast).on_queue("audio").delay(60))
Mail.to(user).queue(Welcome(user))
```

puis lancer `flask queue:work`, et dans ses tests `Queue.fake()` puis `fake.assert_pushed(ProcessPodcast)`.

**Décision de Pierre** : ne pas réécrire de moteur de file. L'API de Laravel enveloppe **RQ** (Redis), comme Flask-Artisan enveloppe SQLAlchemy et Alembic. RQ fournit le stockage, le worker, les tentatives espacées, la coupure des jobs trop longs, le registre des échecs et les jobs différés. Ni Celery ni RQ ne sont utilisés aujourd'hui dans l'entreprise ; RQ est retenu pour sa simplicité et sa proximité avec le modèle « un job, une méthode ».

## Objectifs

1. Une classe `Job` : `handle()` avec injection, `failed()`, réglages `queue`, `tries`, `backoff`, `timeout`.
2. Envoi : `Job.dispatch(...)`, `Job.dispatch_sync(...)`, helper `dispatch(job)`, façade `Queue` (`Queue.push(job)`), options `on_queue(...)` et `delay(...)`.
3. Sérialisation à la Laravel : les modèles voyagent par identifiant et sont rechargés à l'exécution.
4. Pilotes `sync` (exécution immédiate, sans dépendance) et `rq` (Redis), choisis par `config/queue.py` et `.env`.
5. `flask queue:work` et les commandes des jobs en échec (`queue:failed`, `queue:retry`, `queue:forget`, `queue:flush`).
6. `Queue.fake()` pour les tests.
7. `Mail.to(...).queue(mailable)` et `Mail.to(...).later(delay, mailable)`.
8. Écouteurs d'événements mis en file d'attente (`ShouldQueue`).
9. `flask make:job`.
10. Une section README complète, base de la documentation publique.

## Non-objectifs (hors périmètre)

- Celery, file en base de données, SQS : un pilote pourra s'ajouter plus tard derrière la même interface.
- Tâches planifiées (`schedule:run`, cron), chaînes et batches de jobs, jobs uniques, middlewares de jobs, limitation de débit.
- Tableau de bord (Horizon) : `rq-dashboard` reste utilisable tel quel.
- `deleteWhenMissingModels`, événements de cycle de vie des jobs.
- Worker sous Windows natif (WSL conseillé).

## Anti-objectifs

- Désérialiser du `pickle` lu dans Redis : JSON seulement.
- Exécuter autre chose qu'un job : seules des sous-classes de `Job` (et les enveloppes du framework) s'exécutent.
- Rendre `flask-artisan` dépendant de Redis : sans `[rq]`, tout fonctionne avec `sync`.
- Avaler une exception de job : elle est journalisée, compte comme une tentative, et finit dans le registre des échecs.
- Garder une session SQLAlchemy sale d'un job au suivant dans le worker.

## Approches considérées

1. **Envelopper RQ.** **Retenue** (choix de Pierre). Le moteur, la partie la plus risquée, est éprouvé ; on écrit l'API de Laravel, la sérialisation, l'intégration au conteneur, au mail et aux événements. Coût : Redis obligatoire pour une vraie file, dépendance optionnelle à suivre, worker hors Windows.
2. **Notre propre file** (table `jobs` en base). Écartée : réinventer la prise de job concurrente, les délais d'exécution, les tentatives et les jobs différés.
3. **Envelopper Celery.** Écartée pour l'instant : plus puissant (RabbitMQ, SQS) mais lourd à configurer et plus éloigné du modèle de Laravel. L'interface de pilote laisse la porte ouverte.

## Décisions

### Dépendance

- Extra `rq = ["rq>=3,<4"]` dans `pyproject.toml` (RQ 3 demande Python ≥ 3.10, comme le projet). `fakeredis[lua]` et `rq` entrent dans l'extra `dev` pour la suite de tests.
- `flask_artisan.queue` n'importe `rq` et `redis` qu'à l'utilisation du pilote `rq`. Pilote `rq` sans RQ installé → erreur claire : « pip install "flask-artisan[rq]" ».

### `Job`

- Classe de base dans `flask_artisan.queue`. Attributs de classe :
  - `queue = "default"` ;
  - `tries = 1` (nombre total d'essais) ;
  - `backoff = 0` : secondes avant chaque nouvel essai, entier ou liste (passé à `rq.Retry(interval=…)`) ;
  - `timeout = 60` : secondes avant que RQ coupe le job.
- `handle()` est appelé par `app.call`, donc ses paramètres annotés sont injectés par le conteneur.
- `failed(exc)` (facultatif) est appelé **une fois**, après le dernier essai en échec, dans le worker.
- Options d'envoi, sur l'instance, qui renvoient l'instance : `on_queue(name)`, `delay(seconds | timedelta)`.
- `Job.dispatch(*args, **kwargs)` = `dispatch(cls(*args, **kwargs))` ; `Job.dispatch_sync(...)` exécute tout de suite dans le processus courant, quel que soit le pilote.
- `dispatch(job)` (helper exporté par `flask_artisan`) et `Queue.push(job)` envoient sur la connexion par défaut ; `Queue.connection(name).push(job)` sur une autre. Valeur renvoyée : l'identifiant du job RQ (`str`), `None` pour `sync`.
- Une classe de job doit être importable par son chemin (`module.Classe`, pas de classe locale) : sinon `TypeError` dès l'envoi, qui la nomme. Vérifié aussi en `sync`, pour que l'erreur apparaisse en développement.

### Sérialisation

Un job est stocké comme un dictionnaire JSON : `{"class": "app.jobs.process_podcast.ProcessPodcast", "data": {...}, "queue": ..., "tries": ...}`. `data` = les attributs publics de l'instance (`vars` sans `_`), chacun converti récursivement :

- `str`, `int`, `float`, `bool`, `None` : tels quels ;
- `list`, `tuple` (→ liste), `dict` à clés `str` : récursif ;
- un modèle `Model` : `{"__model__": "module.Classe", "id": <clé primaire>}`, rechargé par `find_or_fail` à l'exécution (un modèle supprimé entre-temps fait échouer le job avec `ModelNotFound`) ; un modèle non enregistré (sans id) → `TypeError` à l'envoi ;
- `datetime`, `date` : marqueur + ISO 8601 ; `Decimal` : marqueur + chaîne ;
- toute autre valeur → `TypeError` à l'envoi, qui nomme la classe du job et l'attribut.

À l'exécution, l'objet est reconstruit **sans appeler `__init__`** (`cls.__new__(cls)` puis attributs restaurés), comme Laravel. Le même mécanisme sert aux mailables et aux événements mis en file.

Côté RQ : sérialiseur JSON de RQ (`rq.serializers.JSONSerializer`), jamais `pickle`. La fonction mise en file est une fonction fixe du framework (`flask_artisan.queue.run`), qui reçoit le dictionnaire, importe la classe, **vérifie que c'est une sous-classe de `Job`** avant toute instanciation, puis exécute.

### Pilotes et configuration

`config/queue.py` (squelette) :

```python
config = {
    # sync (exécution immédiate) ou redis (worker : flask queue:work).
    "default": env("QUEUE_CONNECTION", "sync"),
    "connections": {
        "sync": {"driver": "sync"},
        "redis": {
            "driver": "rq",
            "url": env("REDIS_URL", "redis://127.0.0.1:6379/0"),
            "queue": "default",          # file utilisée quand le job n'en précise pas
        },
    },
}
```

- Sans `config/queue.py` : connexion `sync`. Un projet existant fonctionne sans changement.
- Config relue à chaque envoi (comme le mail).
- **`sync`** : reconstruit le job à partir de sa forme sérialisée puis l'exécute tout de suite (les erreurs de sérialisation et de rechargement apparaissent donc dès le développement) ; une exception remonte à l'appelant ; `tries`, `backoff` et `delay` sont ignorés ; `failed()` est appelé avant que l'exception remonte.
- **`rq`** : `Queue(nom, connection=Redis.from_url(url), serializer=JSONSerializer)` ; `enqueue` avec `job_timeout=timeout`, `retry=Retry(max=tries - 1, interval=backoff)` si `tries > 1`, `enqueue_in` si `delay`. Le `queue` du job, ou celui d'`on_queue`, prime sur celui de la connexion.
- Une connexion ou un pilote inconnu → `ValueError` qui le nomme.
- `.env.example` : `QUEUE_CONNECTION=sync`, `REDIS_URL` commenté.

### Exécution dans le worker

- `flask queue:work [connexion] [--queue a,b] [--burst]` : lance un worker RQ **dans le processus de l'application** (`SimpleWorker`, comme `queue:work` de Laravel, qui exécute ses jobs dans un seul processus PHP), avec le planificateur (`with_scheduler=True`) pour les jobs différés et les nouvelles tentatives espacées. Raison : l'app est déjà chargée et les jobs s'exécutent avec elle, sans la recréer. Choix du rédacteur : le planificateur de RQ tourne, lui, dans un processus enfant créé par `fork` (y compris sous macOS) ; il ne fait que des opérations Redis, ce qui est sans risque, et on garde le comportement standard de RQ. `--queue` vaut par défaut la file de la connexion.
- Chaque job s'exécute dans un contexte d'application ; à la fin (succès ou échec), la session de base est annulée si besoin puis retirée (`DB.session.remove()` quand le provider de base de données est chargé).
- Sous RQ, `failed(exc)` est appelé quand il ne reste plus d'essai (`retries_left` épuisé) ; une exception dans `failed` est journalisée sans masquer celle du job.

### Jobs en échec

Toutes s'appuient sur le `FailedJobRegistry` de RQ, pour la connexion par défaut ou celle donnée par `--connection` :

- `flask queue:failed` : id, classe du job, file, date d'échec, dernière ligne de l'exception ;
- `flask queue:retry <id>…` ou `flask queue:retry all` : remet en file avec **tous** ses essais (`retries_left` remis à `tries - 1` avant le `requeue`, comme Laravel ; choix du rédacteur) ;
- `flask queue:forget <id>` : supprime un job en échec ;
- `flask queue:flush` : les supprime tous.

Avec le pilote `sync`, ces commandes répondent qu'il n'y a pas de file à inspecter (code de sortie 0).

### `Queue.fake()`

Même modèle qu'`Event.fake()` et `Mail.fake()` : un mode du gestionnaire de files.

- Pendant le fake, tout envoi (sauf `dispatch_sync`) est **sérialisé** (les erreurs de sérialisation restent levées), enregistré, et ni exécuté ni envoyé à Redis.
- `QueueFake` : `restore()`, `with`, `pushed(cls)`, `assert_pushed(cls, callback=None)`, `assert_pushed_times(cls, n)`, `assert_not_pushed(cls, callback=None)`, `assert_nothing_pushed()`, `assert_pushed_on(queue, cls)`. Le callback reçoit l'instance du job (celle passée à `dispatch`, avec `queue_name` et `delay_seconds` lisibles). `isinstance` : les sous-classes comptent.
- Les jobs internes (mail, écouteur) sont aussi enregistrés : `assert_pushed(SendQueuedMailable)` et `assert_pushed(CallQueuedListener)` marchent, mais on vérifie plutôt `Mail.fake()` / un fake d'événements.

### Mail en file d'attente

- `PendingMail.queue(mailable)` et `PendingMail.later(delay, mailable)` ; `Mail.queue(...)` sans `to` n'existe pas (comme `send`).
- Ils envoient un job du framework `SendQueuedMailable` qui contient la classe du mailable, ses attributs publics sérialisés, l'enveloppe et le nom du mailer ; son `handle` reconstruit le mailable et appelle l'envoi normal. Les destinataires sont validés à l'appel de `queue`, pas dans le worker.
- `queue` (attribut de classe facultatif du mailable) choisit la file.
- Sous `Mail.fake()`, `queue`/`later` sont enregistrés à part : `MailFake.assert_queued(cls, callback=None)`, `assert_not_queued(cls, callback=None)`, `queued(cls)`, et `assert_nothing_queued()` ; `assert_sent` ne compte pas les mails mis en file (comme Laravel).

### Écouteurs `ShouldQueue`

- Classe marqueur `ShouldQueue` dans `flask_artisan.queue`. Un écouteur en classe qui en hérite n'est pas appelé directement : le `Dispatcher` envoie un job `CallQueuedListener` (classe de l'écouteur, méthode, événement sérialisé) ; le worker reconstruit l'événement, construit l'écouteur par `app.make` et appelle sa méthode.
- Les attributs `queue`, `tries`, `backoff`, `timeout` de l'écouteur sont repris, comme sur un job.
- La valeur renvoyée par `dispatch` contient `None` pour un écouteur mis en file ; `False` ne peut pas arrêter la propagation depuis un écouteur en file.
- Un écouteur en tuple `(Classe, "méthode")` dont la classe hérite de `ShouldQueue` est mis en file lui aussi, avec sa méthode (choix du rédacteur). Une fonction ne peut pas être `ShouldQueue` (rien à marquer).

### Générateur

- `flask make:job ProcessPodcast` → `app/jobs/process_podcast.py` (classe `Job` avec `handle`, `__init__` commenté), sous-dossiers acceptés. Affiche l'exemple `ProcessPodcast.dispatch(...)`.
- Squelette : `app/jobs/__init__.py`, `config/queue.py`, bloc dans `.env.example`.

### Exports

- `flask_artisan` : façade `Queue`, helper `dispatch`.
- `flask_artisan.queue` : `Job`, `ShouldQueue`, `QueueFake`, `QueueManager`.

### Documentation

- README : section « Queues » complète : pourquoi une file, installation (`pip install "flask-artisan[rq]"`, Redis local avec Docker), configuration, écrire un job (réglages, injection, `failed`), sérialisation et ses limites (modèle rechargé, valeurs acceptées), envoyer (`dispatch`, `on_queue`, `delay`, `dispatch_sync`, connexions), lancer le worker en production (superviseur, redémarrage après déploiement car le code est chargé une fois), jobs en échec, mails en file, écouteurs `ShouldQueue`, tester (`Queue.fake()`, assertions, `sync`), `make:job`.
- « Console », « Après la v0.1 » ; CLAUDE.md ; CHANGELOG.

## Pièges connus

- **Contexte et session dans le worker** : un seul processus exécute tous les jobs ; sans `remove()` de la session, les objets d'un job fuient dans le suivant.
- **Code chargé une fois** : après un déploiement, le worker doit être redémarré (à documenter).
- **Classes locales** : les tests utilisent des jobs définis au niveau module.
- **Modèle de menace : Redis est une infrastructure de confiance** (choix du rédacteur, comme RQ, Celery et Laravel, qui désérialise du PHP lu dans Redis). Le worker RQ importe et appelle la fonction nommée dans le job **avant** notre code : quiconque peut écrire dans Redis peut donc faire exécuter du code, quoi qu'on fasse dans `run`. Le JSON (pas de `pickle`) et les vérifications de sous-classes (`Job`, `Mailable`, `ShouldQueue`, `Model`, aucun nom de méthode commençant par `_`) sont une défense en profondeur et une protection contre les données corrompues, pas une frontière de sécurité. Le README le dit et demande un Redis protégé (mot de passe, réseau privé, `rediss://`). Restreindre le worker lui-même (`job_class` RQ personnalisé) reste possible plus tard.
- **Sérialiseur partout** : RQ utilise `pickle` par défaut ; chaque `Queue`, registre, `fetch_job` et worker reçoit `JSONSerializer`. Les outils externes aussi (`rq-dashboard`, CLI `rq` : option `--serializer rq.serializers.JSONSerializer`), à documenter.
- **`backoff` plus court que `tries - 1`** : RQ répète la **première** valeur ; Laravel la dernière. La liste est complétée avec sa dernière valeur avant d'être passée à `Retry`.
- **`failed()` sous RQ** : le callback `on_failure` de RQ est appelé à **chaque** essai en échec ; `failed()` n'est appelé que lorsque `retries_left` vaut 0 ou `None`. Une exception levée par `failed()` est rattrapée et journalisée, sinon RQ l'enregistrerait à la place de celle du job.
- **Pas de réseau dans la suite** : le pilote `rq` se teste avec `fakeredis[lua]` (le planificateur utilise des scripts Lua) et un `SimpleWorker` en mode `burst`.
- **Tests du conteneur** : aucun nouvel attribut sur `Application` ; le gestionnaire vit dans le conteneur (`"queue"`, `QueueManager`).
- **Événement émis pendant une transaction** : le job peut partir avant le `commit` et ne pas trouver le modèle. Documenté (comme Laravel sans `afterCommit`), pas traité.

## Laissé au constructeur

- Structure interne du `QueueManager`, des pilotes et de `run`.
- Format exact des marqueurs de sérialisation (`datetime`, `Decimal`, modèle) dans le respect des points ci-dessus.
- Mise en forme de `queue:failed` et texte exact des messages.

## Livraison

- Tests pytest :
  - sérialisation : chaque type accepté, modèle rechargé, modèle supprimé (`ModelNotFound`), modèle sans id et valeur non prise en charge (`TypeError` nommant l'attribut), classe locale refusée, reconstruction sans `__init__`, chemin non-`Job` refusé à l'exécution ;
  - `sync` : exécution immédiate, injection dans `handle`, exception qui remonte, `failed` appelé ;
  - `rq` (fakeredis + `SimpleWorker` burst) : exécution, file choisie, `delay` (job planifié), tentatives (`tries`, `backoff`), `failed` appelé une seule fois après le dernier essai, timeout transmis, sérialiseur JSON (aucun pickle), session retirée après chaque job ;
  - commandes `queue:failed`, `retry`, `forget`, `flush`, et leur réponse avec `sync` ; `queue:work --burst` ;
  - fake : chaque assertion, `assert_pushed_on`, sous-classes, erreur de sérialisation levée sous fake, `restore`, `with` ;
  - mail : `queue`, `later`, envoi réel par le worker, assertions `queued` du `MailFake` ;
  - écouteurs `ShouldQueue` : job envoyé, écouteur exécuté par le worker avec l'événement reconstruit ;
  - `make:job` ; pilote `rq` sans RQ installé (message d'installation) ;
  - projet généré : `make:job`, `dispatch` en `sync`, test du projet avec `Queue.fake()`.
- README, CLAUDE.md, CHANGELOG.
- PR `feat/28-queues`, commits et titre avec `(#28)`, corps avec `Closes #28`.

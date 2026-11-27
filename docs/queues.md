# Queues

Certaines tâches n'ont rien à faire dans une requête HTTP : envoyer un mail, traiter une vidéo, appeler une API lente. Une **file d'attente** les met de côté ; un processus à part, le **worker**, les exécute en arrière-plan et les réessaie en cas d'échec. La requête répond tout de suite.

Flask-Artisan ne réinvente pas le moteur : il pose l'API de Laravel sur [RQ](https://python-rq.org) (Redis), qui gère le stockage, le worker, les nouvelles tentatives, la coupure des jobs trop longs, les jobs différés et le registre des échecs.

## Installer

Le pilote `sync` (défaut) exécute les jobs tout de suite, sans rien installer : pratique en développement et dans les tests. Pour une vraie file, il faut RQ et un serveur Redis :

```bash
pip install "flask-artisan[rq]"
docker run -d -p 6379:6379 redis:7     # un Redis local pour le développement
```

```ini
# .env
QUEUE_CONNECTION=redis
REDIS_URL=redis://127.0.0.1:6379/0
```

Les connexions sont déclarées dans `config/queue.py` (`sync` et `redis` dans le squelette) ; la configuration est relue à chaque envoi. Un projet sans ce fichier utilise `sync`.

**Sécurité.** Le worker exécute ce qu'il lit dans Redis : quiconque peut écrire dans votre Redis peut lui faire exécuter du code (c'est vrai de RQ, Celery ou Laravel). Traitez Redis comme une base de données : mot de passe, réseau privé, connexion chiffrée (`rediss://`) s'il passe par Internet. Flask-Artisan stocke les jobs en JSON (jamais en `pickle`) et n'exécute que des classes de job, mais ce sont des garde-fous, pas une barrière.

## Écrire un job

```bash
flask make:job ProcessPodcast        # app/jobs/process_podcast.py
```

```python
# app/jobs/process_podcast.py
from flask_artisan.queue import Job

from app.models.podcast import Podcast
from app.services.transcoder import Transcoder


class ProcessPodcast(Job):
    queue = "audio"          # file (défaut : celle de la connexion, "default")
    tries = 3                # nombre total d'essais (défaut : 1)
    backoff = [10, 60]       # secondes avant le 2e, puis le 3e essai (défaut : 0)
    timeout = 120            # secondes avant que le worker coupe le job (défaut : 60)

    def __init__(self, podcast: Podcast):
        self.podcast = podcast

    def handle(self, transcoder: Transcoder):     # dépendances injectées par le conteneur
        transcoder.run(self.podcast)

    def failed(self, exc: Exception):             # facultatif : après le dernier essai raté
        self.podcast.update(status="failed")
```

- `backoff` peut être un nombre (le même délai à chaque fois) ou une liste ; si la liste est plus courte que le nombre d'essais, sa dernière valeur est répétée.
- `failed(exc)` est appelé **une fois**, quand il ne reste plus d'essai. Une erreur levée dans `failed` est journalisée sans masquer celle du job.

**Ce qui voyage dans la file.** Les attributs publics du job (ceux qui ne commencent pas par `_`) sont enregistrés en JSON. Sont acceptés : les valeurs JSON (`str`, nombres, `bool`, `None`, listes, dicts à clés `str`), les `datetime`, `date`, `Decimal`, et les **modèles**, qui voyagent par leur identifiant et sont **rechargés depuis la base** au moment de l'exécution : le job travaille sur des données à jour. Tout le reste (un fichier ouvert, un client HTTP…) lève `TypeError` dès l'envoi, en nommant l'attribut. Un modèle doit être enregistré (avoir un `id`) ; s'il a été supprimé avant l'exécution, le job échoue avec `ModelNotFound`.

Le job est reconstruit **sans appeler `__init__`** : ne mettez dans `__init__` que des affectations. Les classes de jobs doivent être définies au niveau d'un module (pas dans une fonction).

## Envoyer un job

```python
from flask_artisan import Queue, dispatch

ProcessPodcast.dispatch(podcast)                          # crée le job et le met en file
dispatch(ProcessPodcast(podcast).on_queue("urgent"))      # sur une autre file
dispatch(ProcessPodcast(podcast).delay(60))               # dans 60 secondes (ou un timedelta)
Queue.connection("redis").push(ProcessPodcast(podcast))   # sur une connexion précise
ProcessPodcast.dispatch_sync(podcast)                     # tout de suite, quel que soit le pilote
```

`dispatch` renvoie l'identifiant du job RQ (ou `None` avec `sync`). Avec `sync`, le job s'exécute immédiatement, après un aller-retour par la sérialisation (les erreurs de sérialisation apparaissent donc dès le développement) ; son exception remonte à l'appelant après l'appel de `failed`, et `tries`, `backoff` et `delay` sont ignorés.

**Transactions.** Un job envoyé pendant une transaction peut être exécuté avant le `commit` : le worker ne trouverait pas encore le modèle. Envoyez-le après la transaction.

## Lancer le worker

```bash
flask queue:work                      # connexion par défaut, file de la connexion
flask queue:work redis --queue urgent,default   # plusieurs files, par ordre de priorité
flask queue:work --burst              # s'arrête quand les files sont vides
```

**Le worker n'écoute que les files qu'on lui donne** : sans `--queue`, seulement celle de la connexion (`default`). Un job, un mail ou un écouteur envoyé sur une autre file (`queue = "audio"`) attend tant qu'aucun worker n'écoute cette file : listez-les toutes, par ordre de priorité (`--queue audio,listeners,mails,default`), ou lancez un worker par file.

Le worker exécute les jobs **dans le processus de l'application** (comme `php artisan queue:work`), chacun avec sa propre session de base de données. Il gère aussi les jobs différés et les essais espacés.

**En production**, faites-le tourner sous un superviseur qui le relance s'il s'arrête, et **redémarrez-le après chaque déploiement** : il charge le code une seule fois. Avec systemd :

```ini
# /etc/systemd/system/monsite-worker.service
[Service]
WorkingDirectory=/srv/monsite
ExecStart=/srv/monsite/.venv/bin/flask queue:work --queue audio,listeners,mails,default
Restart=always

[Install]
WantedBy=multi-user.target
```

Le worker RQ ne tourne pas sous Windows natif : utilisez WSL ou Docker.

## Jobs en échec

Un job qui a épuisé ses essais va dans le registre des échecs de RQ :

```bash
flask queue:failed                # id, classe, file, date, dernière ligne de l'erreur
flask queue:retry <id> [<id>…]    # le remet en file, avec tous ses essais
flask queue:retry all
flask queue:forget <id>           # le supprime
flask queue:flush                 # les supprime tous
```

Ces commandes couvrent toutes les files de la connexion et acceptent `--connection <nom>`. Les outils de RQ (`rq info`, [rq-dashboard](https://github.com/Parallels/rq-dashboard)) marchent aussi, à condition de leur indiquer le sérialiseur JSON : `--serializer rq.serializers.JSONSerializer`.

## Mails et écouteurs en file d'attente

```python
Mail.to(user).queue(Welcome(user))         # le worker enverra le mail
Mail.to(user).later(600, Reminder(user))   # dans 10 minutes
```

Les destinataires sont vérifiés tout de suite ; le mailable voyage comme un job (ses modèles par identifiant). Un attribut `queue = "mails"` sur la classe du mailable choisit la file.

Un écouteur d'événement qui hérite de `ShouldQueue` n'est pas appelé pendant `Event.dispatch` : il est mis en file, et le worker l'exécute avec l'événement reconstruit.

```python
from flask_artisan.queue import ShouldQueue


class SendShipmentNotification(ShouldQueue):
    queue = "listeners"      # facultatif, comme tries, backoff, timeout
    tries = 3

    def handle(self, event: OrderShipped):
        Mail.to(event.order.user).send(OrderShippedMail(event.order))
```

Il se déclare comme les autres écouteurs (dans `listen`, en classe ou en tuple `(Classe, "méthode")`). L'événement doit être une classe de l'application et être sérialisable (mêmes règles qu'un job) ; `Event.dispatch` renvoie `None` pour cet écouteur, qui ne peut pas arrêter la propagation.

## Tester

`Queue.fake()` enregistre les jobs poussés **sans les exécuter** (ils sont tout de même sérialisés : une erreur de sérialisation reste levée). Utilisé comme bloc `with`, il se restaure à la sortie :

```python
from wsgi import app

from flask_artisan import Queue
from app.jobs.process_podcast import ProcessPodcast


def test_upload_queues_processing():
    with Queue.fake() as fake:
        app.test_client().post("/api/podcasts", json={"title": "Épisode 1"})

    fake.assert_pushed(ProcessPodcast)
    fake.assert_pushed(ProcessPodcast, lambda job: job.podcast.title == "Épisode 1")
    fake.assert_pushed_on("audio", ProcessPodcast)
```

| Méthode | Vérifie que… |
|---|---|
| `assert_pushed(Classe, callback=None)` | le job a été poussé au moins une fois (et que `callback(job)` est vrai pour l'un d'eux) |
| `assert_pushed_times(Classe, n)` | le job a été poussé exactement `n` fois |
| `assert_not_pushed(Classe, callback=None)` | le job n'a pas été poussé (ou aucun ne satisfait `callback`) |
| `assert_nothing_pushed()` | aucun job n'a été poussé |
| `assert_pushed_on(file, Classe)` | le job a été poussé sur cette file |
| `pushed(Classe)` | (pas une assertion) la liste des jobs poussés |

Le callback reçoit l'instance passée à `dispatch` ; `job.queue_name` et `job.delay_seconds` y donnent la file et le délai demandés. `dispatch_sync` n'est pas intercepté. Pour tester ce que fait un job, appelez simplement `ProcessPodcast.dispatch_sync(...)` ou laissez le pilote `sync`.

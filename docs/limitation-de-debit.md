# Limitation de débit et verrous

La limitation de débit refuse les requêtes au-delà d'un nombre donné par fenêtre de temps : contre le test de mots de passe en boucle, ou pour protéger une API. Les verrous garantissent qu'un seul processus fait un travail à la fois. Les deux reposent sur le [cache](cache.md).

## Le middleware `throttle`

```python
Route.post("/login", AuthController.login).middleware("throttle:5,1")   # 5 requêtes par minute

with Route.middleware("throttle:60,1"):
    Route.get("/photos", PhotoController.index)
```

`throttle:<max>,<minutes>` laisse passer `max` requêtes par fenêtre de `minutes` minutes. Le squelette déclare l'alias dans `app/http/kernel.py`, limite le groupe `api` à `throttle:60,1` et `/api/login` à `throttle:5,1`.

Chaque réponse acceptée porte `X-RateLimit-Limit` et `X-RateLimit-Remaining`. Au-delà, la route n'est pas exécutée et le client reçoit :

```
HTTP/1.1 429 TOO MANY REQUESTS
Retry-After: 42
X-RateLimit-Limit: 5
X-RateLimit-Remaining: 0
X-RateLimit-Reset: 1764150000

{"message": "Too Many Attempts."}
```

`Retry-After` donne les secondes à attendre, `X-RateLimit-Reset` l'horodatage Unix de réouverture. Une requête refusée ne compte pas : la fenêtre se rouvre à l'heure annoncée. Même une rafale de requêtes simultanées ne dépasse pas la limite : chacune compte avant de passer, et celles en trop sont refusées.

**Qui est compté.** Par défaut, l'adresse IP du client. Si un middleware `auth` a déjà identifié l'utilisateur **avant** `throttle`, c'est l'utilisateur qui est compté (par guard : l'utilisateur 1 du guard `api` et l'admin 1 d'un guard `admin` ont chacun leur compteur), quelle que soit son IP :

```python
with Route.middleware("auth:api", "throttle:60,1"):   # auth d'abord : limite par utilisateur
    Route.get("/user", AuthController.user)
```

`throttle` n'authentifie jamais lui-même (ni lecture de session, ni requête SQL). Les middlewares d'un groupe passent avant ceux de la route : le `throttle:60,1` du groupe `api` compte donc par IP.

**Compteurs partagés.** Le compteur est lié à la limite et à la personne, pas à la route : toutes les routes en `throttle:60,1` partagent le même compteur pour un client (comme Laravel), alors que `throttle:5,1` en a un autre. Quand deux limites s'appliquent (le groupe `api` et le login), chacune compte, et les en-têtes `X-RateLimit-*` sont ceux de la plus proche de la route.

Des paramètres qui ne sont pas des entiers positifs (`throttle:abc`) lèvent `ValueError` à la première requête.

## Derrière un proxy

Derrière nginx ou un load balancer, Flask voit l'IP du proxy : tous les clients partageraient un seul compteur. Indiquez le nombre de proxys devant l'application dans `.env` :

```env
TRUSTED_PROXIES=1
```

L'IP du client et le schéma (`https`) sont alors lus dans `X-Forwarded-For` et `X-Forwarded-Proto`, posés par le proxy (`ProxyFix` de Werkzeug). L'hôte et le port ne sont pas lus dans `X-Forwarded-Host` / `X-Forwarded-Port` : un proxy qui ne les pose pas laisserait le client choisir l'hôte des URL absolues (liens des mails) ; le proxy doit transmettre l'en-tête `Host`, ou fixez `SERVER_NAME` dans `config/flask.py`. Laissez `0` (défaut) sans proxy : sinon un client pourrait choisir son IP avec un faux `X-Forwarded-For`.

## `RateLimiter`

Pour compter soi-même, par exemple les échecs de connexion par adresse e-mail :

```python
from flask_artisan import Auth, RateLimiter


class AuthController:
    def login(self, request: LoginRequest):
        data = request.validated()
        key = f"login:{data['email'].lower()}"
        if RateLimiter.too_many_attempts(key, 5):
            seconds = RateLimiter.available_in(key)
            return {"message": f"Trop de tentatives, réessayez dans {seconds} s."}, 429
        user = Auth.validate(email=data["email"], password=data["password"])
        if user is None:
            RateLimiter.hit(key, 300)        # fenêtre de 5 minutes
            return {"message": "Invalid credentials."}, 401
        RateLimiter.clear(key)
        return {"token": user.create_token("api")}
```

| Méthode | Effet |
|---|---|
| `hit(key, decay_seconds=60)` | compte une tentative et renvoie le total ; la fenêtre démarre à la première |
| `attempts(key)` | tentatives de la fenêtre en cours |
| `too_many_attempts(key, max_attempts)` | `True` si `max_attempts` est atteint et que la fenêtre n'est pas finie |
| `remaining(key, max_attempts)` | tentatives restantes |
| `available_in(key)` | secondes avant la réouverture (0 si ouverte) |
| `clear(key)` | remet à zéro |
| `attempt(key, max_attempts, callback, decay_seconds=60)` | `False` si trop de tentatives, sinon compte puis renvoie `callback()` (`True` s'il renvoie `None`) |

Les compteurs vont dans le store par défaut, ou dans celui de `cache.limiter` (`config/cache.py`) :

```python
config = {
    "default": env("CACHE_STORE", "file"),
    "limiter": "redis",       # compteurs dans Redis, le reste du cache ailleurs
    ...
}
```

## Verrous

```python
from flask_artisan import Cache

lock = Cache.lock("rapport:mensuel", 120)     # expire seul au bout de 120 s
if lock.get():
    try:
        generer_rapport()
    finally:
        lock.release()
```

| Forme | Effet |
|---|---|
| `Cache.lock(name, seconds=0, owner=None)` | un verrou ; `seconds=0` : sans expiration ; nom et `owner` sont des chaînes non vides (`TypeError` / `ValueError` sinon, comme une durée négative) |
| `lock.get()` | prend le verrou s'il est libre ; `True` / `False` |
| `lock.get(callback)` | si le verrou est libre : le prend, appelle `callback()`, le libère (même en cas d'exception) et renvoie son résultat ; sinon `False` |
| `lock.block(seconds)` / `lock.block(seconds, callback)` | comme `get`, mais attend jusqu'à `seconds` secondes (essai toutes les 250 ms), puis lève `LockTimeoutError` |
| `with Cache.lock(name, seconds):` | prend le verrou, le libère en sortie ; lève `LockTimeoutError` tout de suite s'il est pris |
| `lock.release()` | libère, **seulement si on en est le propriétaire** ; `True` / `False` |
| `lock.force_release()` | libère sans condition |
| `lock.owner` | jeton du propriétaire (aléatoire si non fourni) |
| `Cache.restore_lock(name, owner)` | le verrou d'un autre processus, pour le libérer |

```python
from flask_artisan.cache import LockTimeoutError

try:
    Cache.lock("stock:42", 10).block(5, lambda: decrementer_stock(42))
except LockTimeoutError:
    return {"message": "Réessayez."}, 409
```

Donnez toujours une durée à un verrou pris dans une requête : si le processus meurt avant `release()`, le verrou expire seul. Un processus lent dont le verrou a expiré, puis a été repris par un autre, ne peut pas libérer le verrou du second : `release()` renvoie `False`.

Pour libérer depuis un autre processus (verrou pris dans une requête, travail fini par un job), transmettez le propriétaire :

```python
lock = Cache.lock("import:clients", 600)
if lock.get():
    ImportClients.dispatch(owner=lock.owner)

# dans le job
Cache.restore_lock("import:clients", self.owner).release()
```

## Quel store choisir

| Store | Compteurs et verrous |
|---|---|
| `redis` | sûrs entre processus et entre serveurs (`SET NX`, `INCRBY`, script Lua pour `release`) |
| `file` (défaut) | sûrs entre processus d'**une même machine** (verrou `flock` sur `storage/cache/.lock`, ouvert en lecture seule : un cron sous un autre utilisateur n'a pas besoin d'y écrire) ; pas sous Windows, où ils restent approximatifs |
| `array` | propres à chaque processus : chaque worker gunicorn a ses propres compteurs |

Avec plusieurs serveurs, utilisez `redis` (`CACHE_STORE=redis`, ou seulement `"limiter": "redis"` pour les compteurs).

Avec le store `file`, chaque adresse IP vue laisse deux fichiers de compteur dans `storage/cache`, jusqu'à `flask cache:prune`, planifiée toutes les heures dans un projet généré (voir [Purger les entrées expirées](cache.md#purger-les-entrees-expirees)).

## Tester

Avec le store `file`, les compteurs restent sur le disque d'un lancement de tests à l'autre : le 6ᵉ login en une minute répondrait 429. Utilisez `CACHE_STORE=array` en test et videz le cache entre deux tests (voir [Cache, Tester](cache.md#tester)), et remettez vos propres compteurs à zéro avec `RateLimiter.clear(key)`. Les compteurs de `throttle` ont une clé interne (un hash) : pour eux, videz le cache (`Cache.flush()`).

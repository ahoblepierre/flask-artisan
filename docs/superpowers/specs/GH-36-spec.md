# GH-36 — Limitation de débit (`throttle`), `RateLimiter` et verrous (`Cache.lock`)

Ticket : https://github.com/ahoblepierre/flask-artisan/issues/36
Statut : en attente d'approbation (relecture constructeur faite)

## Intention

La route `/api/login` du squelette accepte aujourd'hui un nombre illimité de tentatives : n'importe qui peut tester des mots de passe en boucle. Laravel la protège d'office avec le middleware `throttle`. Un développeur Laravel s'attend à écrire :

```python
# routes/api.py
Route.post("/login", AuthController.login).middleware("throttle:5,1")   # 5 requêtes par minute

# dans un controller
from flask_artisan import RateLimiter

key = f"login:{email}"
if RateLimiter.too_many_attempts(key, 5):
    return {"message": f"Réessayez dans {RateLimiter.available_in(key)} s."}, 429
RateLimiter.hit(key, 60)

# un seul processus à la fois
from flask_artisan import Cache

with Cache.lock("rapport:mensuel", 120):
    generer_rapport()
```

Le tout repose sur le cache (#32) : les compteurs et les verrous sont des clés du cache.

**Décisions de Pierre** (reco validée) : middleware `throttle`, `RateLimiter`, `Cache.lock`, `/api/login` protégée par défaut ; **option A** pour le store `file` : il devient atomique entre processus d'une même machine grâce à `fcntl.flock` (comme le `FileStore` de Laravel), approximatif sous Windows (documenté).

## Objectifs

1. Middleware `throttle:<max>,<minutes>` (alias du kernel) : au-delà, réponse 429 avec `Retry-After` ; en-têtes `X-RateLimit-Limit` / `X-RateLimit-Remaining` sur chaque réponse.
2. `RateLimiter` (service `"limiter"`, façade `RateLimiter`) : `hit`, `attempts`, `too_many_attempts`, `remaining`, `available_in`, `clear`, `attempt`.
3. `Cache.lock(name, seconds)` : `get`, `block`, `release`, `force_release`, `owner`, gestionnaire de contexte ; `Cache.restore_lock(name, owner)`. Seul le propriétaire libère.
4. Store `file` : `add`, `increment`, `pull` et la libération d'un verrou atomiques entre processus (POSIX).
5. Option `app.trusted_proxies` : l'IP du client est lue derrière un proxy.
6. Squelette : alias `throttle`, groupe `api` à `throttle:60,1`, `/api/login` à `throttle:5,1`.
7. Une section README complète, base de la documentation publique.

## Non-objectifs (hors périmètre)

- Limiteurs nommés (`RateLimiter.for("api", ...)` puis `throttle:api`).
- Jobs uniques (`ShouldBeUnique`) et middleware de job `WithoutOverlapping` : ils s'appuieront sur `Cache.lock`.
- Atomicité du store `file` sous Windows (pas de `fcntl`).
- Limite par utilisateur sur le store `array` partagée entre processus (il est par processus, par nature).
- Middleware `TrustProxies` configurable par liste d'adresses : un nombre de proxys suffit (`ProxyFix`).

## Anti-objectifs

- Un utilisateur bloqué pour toujours : un compteur sans TTL (clé expirée entre `add` et `increment`) ne doit jamais survivre.
- Un verrou libéré par quelqu'un d'autre que son propriétaire (un processus lent dont le verrou a expiré et a été repris ne doit pas libérer celui du suivant).
- Derrière un proxy, tout le monde bloqué ensemble parce que tous partagent l'IP du proxy, sans moyen de le régler.
- Une IP falsifiée par `X-Forwarded-For` quand l'application n'est **pas** derrière un proxy : `trusted_proxies` vaut 0 par défaut.

## Approches considérées (store `file`)

1. **A — `fcntl.flock` sur un fichier verrou du dossier de cache.** **Retenue.** Atomique entre processus d'une même machine, verrou rendu par le système si un processus meurt. Approximatif sous Windows.
2. **B — Ne rien changer, documenter « Redis pour plusieurs workers ».** Écartée : le réglage par défaut resterait perméable.
3. **C — `Cache.lock` refusé sur `file`.** Écartée : un projet neuf n'aurait pas de verrou sans Redis.

## Décisions

### Verrous (`cache.py`)

- `Store.lock(name, seconds=0, owner=None) -> Lock` ; `Store.restore_lock(name, owner) -> Lock`. Ajoutés à `PUBLIC` (donc `Cache.lock(...)` vise le store par défaut).
- Clé du verrou : `prefix + "lock:" + name` (passe par `_key`, donc `name` doit être une chaîne non vide).
- `owner` : chaîne aléatoire (`secrets.token_hex(16)`) si absent.
- `seconds` : 0 = pas d'expiration (comme Laravel) ; sinon entier de secondes (`_seconds`, donc `timedelta` accepté).
- `Lock.get(callback=None)` : acquiert par `_add(k, owner, seconds)`. Sans callback, renvoie `True`/`False`. Avec callback, renvoie `False` si non acquis, sinon le résultat du callback, et libère dans un `finally`.
- `Lock.block(seconds, callback=None)` : réessaie toutes les 250 ms jusqu'à `seconds` ; au-delà, lève `LockTimeoutError`. Avec callback : même comportement que `get` (libère après). Sans callback : `True`.
- `Lock.release() -> bool` : supprime seulement si la valeur stockée est encore l'`owner` (nouvelle primitive de pilote `_delete_if(k, text) -> bool`, atomique).
- `Lock.force_release()` : `_delete(k)` sans condition.
- `Lock.owner` : attribut en lecture.
- `with Cache.lock(name, seconds):` : `__enter__` fait `get()` et lève `LockTimeoutError` si le verrou est pris (pas d'attente : pour attendre, `block`) ; `__exit__` fait `release()`.
- `LockTimeoutError(Exception)` exportée par `flask_artisan.cache`.

### Primitives de pilote

- `_delete_if(k, text) -> bool` : nouvelle, sur les trois pilotes.
  - `array` : sous un `threading.Lock` du store.
  - `file` : sous le verrou de dossier.
  - `redis` : script Lua (`if GET == ARGV[1] then DEL`), via `register_script`. `fakeredis[lua]` est déjà dans l'extra `dev`.
- `array` : `_add`, `_increment`, `_pull`, `_delete_if` sous un `threading.Lock` (le store vit dans un processus servi par plusieurs threads).
- `file` : `_add`, `_increment`, `_pull`, `_delete_if` sous `fcntl.flock(LOCK_EX)` d'un fichier `.lock` du dossier de cache (créé à la demande). Un seul verrou par dossier : simple, et les sections tenues sont courtes. Sans `fcntl` (Windows) : pas de verrou, commentaire `shortcut:` et phrase dans le README. `get`/`put` ne prennent pas le verrou (`os.replace` est déjà atomique). `.lock` ne correspond pas à `CACHE_FILE` : `flush` ne le supprime pas.
- Les commentaires `shortcut:` actuels sur `FileStore._add` / `_increment` disparaissent.

### `RateLimiter` (`rate_limiting.py`)

- `RateLimiter(app)`, créé dans `Application.__init__` à côté du `CacheManager` (`"limiter"`, `RateLimiter`) ; façade `RateLimiter` (accesseur `"limiter"`).
- Store : `config("cache.limiter")` s'il est défini, sinon le store par défaut ; relu à chaque appel.
- Deux clés par limite : `key` (compteur) et `key + ":timer"` (horodatage Unix entier de fin de fenêtre).
- `hit(key, decay_seconds=60) -> int` (algorithme de Laravel, qui évite le compteur éternel) :
  ```
  store.add(key + ":timer", now + decay, decay)
  added = store.add(key, 0, decay)
  hits = store.increment(key)
  if not added and hits == 1:   # la clé a expiré entre add et increment
      store.put(key, 1, decay)
  return hits
  ```
- `attempts(key) -> int` : `store.get(key, 0)`.
- `too_many_attempts(key, max_attempts) -> bool` : si `attempts >= max_attempts` et que le timer existe → `True` ; si le timer a disparu, `clear(key)` et `False`.
- `remaining(key, max_attempts) -> int` : `max(0, max_attempts - attempts)`.
- `available_in(key) -> int` : `max(0, timer - now)` (0 sans timer).
- `clear(key)` : supprime compteur et timer.
- `attempt(key, max_attempts, callback, decay_seconds=60)` : `False` si trop de tentatives, sinon `hit` puis résultat du callback (`True` si le callback renvoie `None`, comme Laravel).
- `now` = `int(time.time())` (les tests remplacent `time.time`).

### Middleware `ThrottleRequests` (`rate_limiting.py`)

- `handle(request, next, max_attempts="60", decay_minutes="1")` : paramètres convertis en `int` ; valeur non entière ou ≤ 0 → `ValueError` nommant `throttle` (erreur du développeur).
- Identité : l'identifiant d'un utilisateur **déjà résolu** dans cette requête par un guard (un middleware `auth` placé avant) ; sinon `request.remote_addr`. *Choix du rédacteur :* `throttle` ne déclenche jamais l'authentification lui-même. Appeler `Auth.user()` lirait la session (et ajouterait `Vary: Cookie`) puis ferait une requête SQL à chaque appel d'API. Il ne lit que l'état d'auth de la requête (`request.environ["flask_artisan.auth"]`), sans résoudre.
- Ordre des middlewares : les groupes passent avant ceux de la route (`routing.py`), et il n'y a pas de liste de priorité comme chez Laravel (hors périmètre). Le `throttle` du groupe `api` limite donc par IP. Pour limiter par utilisateur, on le place après l'auth : `Route.middleware("auth:api", "throttle:60,1")`. Le README le documente.
- Clé : `"throttle:" + sha1(f"{max}|{decay}|{identité}")`. Deux limites différentes (groupe `api` à 60/min, login à 5/min) ont chacune leur compteur ; des routes avec la même limite partagent le leur (comme Laravel, où la limite vaut pour l'utilisateur, pas pour la route).
- Ordre : vérifier `too_many_attempts` **avant** `hit` ; une requête refusée ne compte pas dans **son** compteur. Elle compte, en revanche, dans celui d'un `throttle` extérieur qui l'a laissée passer : c'est le modèle en oignon, comme chez Laravel.
- Refus : `({"message": "Too Many Attempts."}, 429)` avec `Retry-After` (= `available_in`), `X-RateLimit-Limit`, `X-RateLimit-Remaining: 0`, `X-RateLimit-Reset` (horodatage Unix). JSON comme `Unauthenticated.` (pas de page HTML : chantier vues #19).
- Accepté : la réponse de `next` reçoit `X-RateLimit-Limit` et `X-RateLimit-Remaining`, **sauf si elle les porte déjà**. *Choix du rédacteur :* le `throttle` le plus proche de la route (le plus strict en pratique, ex. `5,1` sur le login sous le `60,1` du groupe) décide des en-têtes ; un 429 dit toujours `Remaining: 0`. `next` renvoie déjà un `Response` (le routeur passe tout par `make_response`).

### Proxy

- `config("app.trusted_proxies", 0)` lu dans `Application.__init__` : si > 0, `self.wsgi_app = ProxyFix(self.wsgi_app, x_for=n, x_proto=n, x_host=n, x_port=n)`. Valeur non entière → `ValueError` au démarrage, qui nomme `TRUSTED_PROXIES`.
- Squelette : `"trusted_proxies": int(env("TRUSTED_PROXIES", 0))` dans `config/app.py`, ligne commentée dans `.env.example`.

### Squelette

- `app/http/kernel.py` : alias `"throttle": ThrottleRequests` ; groupe `"api": ["throttle:60,1"]`.
- `routes/api.py` : `Route.post("/login", ...).middleware("throttle:5,1")`.
- `config/cache.py` : `"limiter": None` commenté (« store des compteurs, défaut : le store par défaut »).

### Exports

- `flask_artisan` : façade `RateLimiter`.
- `flask_artisan.rate_limiting` : `RateLimiter`, `ThrottleRequests`.
- `flask_artisan.cache` : `Lock`, `LockTimeoutError`.

### Documentation

- README : section « Limitation de débit et verrous » (middleware, en-têtes, identité, `RateLimiter`, `Cache.lock`, proxy, store `file` et Windows, tests avec `CACHE_STORE=array`), ligne de feuille de route, liste des commandes inchangée.
- CLAUDE.md : puce d'architecture ; CHANGELOG : section « Non publié ».

## Pièges connus

- **Tests d'une application** : avec le store `file`, les compteurs survivent d'un lancement de tests à l'autre (une minute). Le README conseille `CACHE_STORE=array` en test.
- **`hit` sur une clé non entière** (un développeur qui a mis une chaîne dans la clé) : `increment` lève déjà `ValueError`, on la laisse passer.
- **Horloge** : comme pour le cache, les tests remplacent `time.time` ; `block` doit dormir avec `time.sleep` (remplaçable dans les tests).
- **Propriétaire du verrou** : il est stocké encodé en JSON, comme toute valeur, pour que la lecture tolérante ne prenne pas un verrou pour une valeur illisible et ne le supprime pas. `seconds=0` devient « sans TTL » (`None`).
- **Multi-processus** : un test du store `file` lance plusieurs processus (`multiprocessing`, contexte `spawn` ou `fork`) qui incrémentent la même clé et vérifie le total exact.

## Laissé au constructeur

- Structure interne de `Lock` (classe unique, primitives appelées sur le store).
- Texte des messages d'erreur (en français, comme le reste du framework), sauf `Too Many Attempts.`.
- Nom exact de la méthode qui tient le verrou de dossier du store `file`.

## Livraison

- Tests pytest :
  - verrous, sur les trois pilotes (paramétrés) : `get` libre / pris, expiration (horloge), `release` par le propriétaire, refus pour un autre `owner`, `force_release`, `restore_lock`, `block` qui attend puis réussit, `block` qui lève `LockTimeoutError`, callback (résultat, libération même sur exception), `with` ;
  - store `file` : total exact d'`increment` concurrents en plusieurs processus ; `flush` laisse `.lock` ;
  - `RateLimiter` : `hit`, `attempts`, `too_many_attempts` (sous / à la limite / timer expiré), `remaining`, `available_in`, `clear`, `attempt`, compteur jamais éternel (clé expirée entre `add` et `increment`), store `cache.limiter` ;
  - middleware : 429 après `max`, en-têtes, fenêtre qui se rouvre, identité par utilisateur puis par IP, deux limites indépendantes, paramètres invalides, requête refusée non comptée ;
  - `trusted_proxies` : IP de `X-Forwarded-For` lue avec 1, ignorée avec 0 ;
  - squelette : 6ᵉ `POST /api/login` en une minute → 429, dans `tests/test_cli.py` (projet neuf à chaque test, donc `storage/cache` vide). *Choix du rédacteur :* pas de test de login dans `skeleton/tests/`, pour que les compteurs du store `file` ne fassent pas échouer un second lancement des tests du projet dans la minute. Le flux `AUTH_FLOW` existant fait exactement 5 logins : il reste sous la limite, et un commentaire le signale.
- README, CLAUDE.md, CHANGELOG.
- Branche `feat/36-throttle-locks`, commits et titre de PR avec `(#36)`, PR avec `Closes #36`.

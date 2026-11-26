# GH-32 — Cache : `Cache.get` / `put` / `remember`, pilotes `array`, `file`, `redis`

Ticket : https://github.com/ahoblepierre/flask-artisan/issues/32
Statut : en attente d'approbation (relecture constructeur faite)

## Intention

Garder de côté le résultat d'un calcul coûteux (statistiques, réponse d'une API tierce, page de résultats) et compter des choses (tentatives, vues) sans repasser par la base à chaque requête. Un développeur Laravel s'attend à écrire :

```python
from flask_artisan import Cache

stats = Cache.remember("stats:dashboard", 600, lambda: compute_stats())   # 10 minutes
Cache.put("weather:paris", forecast, timedelta(hours=1))
Cache.get("weather:paris", default=None)
Cache.increment("visits")
Cache.forget("stats:dashboard")
Cache.store("redis").get("...")
```

Le pilote se choisit dans `.env` (`CACHE_STORE=redis`) sans toucher au code.

**Décisions de Pierre** (reco validée) : pilotes maison `array`, `file`, `redis` sans `cachelib` ; valeurs en JSON, modèles par identifiant (même sérialisation que les queues) ; `remember`, `increment`, `pull` ; verrous plus tard.

Pourquoi pas `cachelib` (équivalent de RQ pour le cache, maintenu par Pallets) : ses versions ≥ 0.15 exigent Python 3.11 (le projet supporte 3.10) et il stocke en `pickle`. Contrairement à une file d'attente, le moteur d'un cache est simple, et Redis fournit nativement l'atomicité (`SET NX`, `INCRBY`).

## Objectifs

1. Un `CacheManager` toujours présent dans le conteneur (`"cache"`, façade `Cache`) ; ses méthodes visent le store par défaut, `Cache.store(name)` un autre.
2. API d'un store : `get`, `put`, `add`, `forever`, `remember`, `remember_forever`, `has`, `missing`, `pull`, `forget`, `increment`, `decrement`, `flush`.
3. Trois pilotes : `array` (mémoire du processus), `file` (dossier du projet), `redis`.
4. Valeurs en JSON, avec la sérialisation des queues (modèles par identifiant, `datetime`, `date`, `Decimal`).
5. `flask cache:clear [store]`.
6. Une section README complète, base de la documentation publique.

## Non-objectifs (hors périmètre)

- Verrous atomiques (`Cache.lock`), jobs uniques, limitation de débit (`throttle`) : chantier ultérieur, qui s'appuiera sur ce cache.
- Tags, `many` / `put_many`, `flexible` (stale-while-revalidate).
- Décorateur de vues (`@cache.cached`), cache HTTP.
- Pilotes memcached, database, DynamoDB ; pilote `null`.
- Helper `cache()` ; `Cache.fake()` (Laravel n'en a pas : les tests utilisent le pilote `array`).
- `cachelib` et Flask-Caching.

## Anti-objectifs

- `pickle` : rien n'est désérialisé en `pickle`, ni depuis Redis ni depuis un fichier.
- Un `flush` qui vide toute la base Redis (et donc les files RQ qui partagent le même Redis) : seules les clés du préfixe du cache sont supprimées.
- Une valeur non sérialisable acceptée puis perdue : `TypeError` dès `put`, qui nomme la clé.
- Un fichier de cache à moitié écrit lu par une autre requête.

## Approches considérées

1. **Pilotes maison sur la bibliothèque standard et redis-py.** **Retenue.** Peu de code, JSON, Python 3.10, atomicité native de Redis.
2. **Envelopper `cachelib`.** Écartée : Python 3.11 pour les versions récentes (3.10 tomberait sur 0.13, de 2024), `pickle`, et il faudrait quand même écrire `remember`, `pull`, le préfixe et la sérialisation des modèles.
3. **Flask-Caching.** Écartée : API de décorateurs, différente de Laravel, et repose sur `cachelib`.

## Décisions

### Clés, TTL, valeurs

- Une clé est une chaîne non vide ; sinon `TypeError` / `ValueError`.
- TTL : secondes (`int` / `float`, arrondi au-dessus) ou `timedelta` ; `None` = pour toujours. Un TTL ≤ 0 dans `put` supprime la clé (comme Laravel) ; dans `add` et `remember`, il ne stocke rien.
- Valeur : passée par `dump` / `load` de `flask_artisan.queue.serialization` puis `json`. Un **modèle** est stocké par son identifiant et **rechargé depuis la base** à la lecture : c'est une donnée à jour, mais une requête par modèle. Le README le dit et conseille de mettre en cache `to_dict()` (ou des données calculées) quand on veut éviter la base. Valeur non prise en charge → `TypeError` qui nomme la clé.
- `None` ne se distingue pas d'une clé absente : `put(k, None)` (et `forever`) **supprime** la clé, comme un TTL ≤ 0 (choix du rédacteur : sinon Redis garderait `"null"`, que `SET NX` et `INCRBY` verraient comme présent, et les trois pilotes divergeraient). `get(k)` renvoie alors le `default`, `has(k)` vaut `False`, `add(k, v)` stocke.
- **Valeur illisible à la lecture** (choix du rédacteur) : un modèle supprimé depuis (`ModelNotFound`), une classe déplacée ou une donnée corrompue (`TypeError`, JSON invalide) comptent comme **absents** : la clé est supprimée, un avertissement est journalisé, et `remember` recalcule. Jamais de 404 venu du cache. `has(k)` sur une valeur modèle fait donc une requête.

### API d'un store

| Méthode | Comportement |
|---|---|
| `get(key, default=None)` | valeur, ou `default` (appelé s'il est appelable) |
| `put(key, value, ttl=None)` | stocke ; renvoie `True` |
| `add(key, value, ttl=None)` | stocke seulement si absente ; renvoie `True` si stockée (atomique avec `redis`) |
| `forever(key, value)` | `put` sans expiration |
| `remember(key, ttl, callback)` | valeur en cache, sinon `callback()` stocké puis renvoyé ; un `None` renvoyé n'est pas stocké |
| `remember_forever(key, callback)` | idem sans expiration |
| `has(key)` / `missing(key)` | présence d'une valeur non `None` |
| `pull(key, default=None)` | lit puis supprime |
| `forget(key)` | supprime ; renvoie `True` si la clé existait |
| `increment(key, by=1)` / `decrement(key, by=1)` | entier ; clé absente = 0 ; garde l'expiration existante ; valeur non entière → `ValueError` ; atomique avec `redis` |
| `flush()` | vide le store (préfixe seulement pour `redis`) |

`remember` n'est pas atomique (deux requêtes simultanées peuvent calculer toutes les deux) : comme Laravel sans verrou, documenté.

### `CacheManager`

- Créé par `Application.__init__` à côté du `QueueManager` (`"cache"` et `CacheManager`) ; façade `Cache`, exportée par `flask_artisan`.
- Ses méthodes (`get`, `put`, … `flush`) délèguent au store par défaut ; `store(name=None)` renvoie un store. Nom inconnu → `ValueError` qui le nomme ; pilote inconnu → `ValueError`.
- Config relue à chaque appel de `store()` ; les stores `array` sont gardés par le manager (un par nom), pour conserver leurs valeurs ; les autres sont reconstruits (légers : le client Redis est mis en cache par URL).

### Pilotes

- **`array`** : dictionnaire du processus `{clé: (expire_à | None, valeur JSON)}`, horloge `time.time()`. Perdu au redémarrage, non partagé entre processus ou workers.
- **`file`** : un fichier JSON par clé dans `path` (défaut `storage/cache` du projet, relatif à la base du projet), nommé par le SHA-256 de la clé préfixée, contenu `{"expires": float | null, "value": ...}`. Écriture atomique (fichier temporaire dans le même dossier + `os.replace`). Un fichier expiré est supprimé à la lecture ; un fichier illisible ou corrompu compte comme absent (et est supprimé). Dossier créé à la première écriture. `increment` n'est pas atomique entre processus (verrou de fichier hors périmètre) : documenté. `flush` supprime les fichiers du dossier.
- **`redis`** : redis-py, `url` (défaut `REDIS_URL`), clés `prefix + clé`, valeurs JSON (un entier est stocké tel quel, donc `INCRBY` fonctionne) ; TTL par `SET … PX`, `add` par `SET NX PX`, `increment` par `INCRBY` (garde le TTL), `forget` par `DEL`, `pull` par `GET` + `DEL` dans une transaction `MULTI` (choix du rédacteur : `GETDEL` exigerait Redis ≥ 6.2, aucune version minimale n'est imposée) ; `flush` par `SCAN MATCH prefix*` + `DEL` par lots. Sans redis-py installé → `RuntimeError` : `pip install "flask-artisan[redis]"`. Le client est mis en cache par URL (un pool par processus).

### Configuration

`config/cache.py` (squelette) :

```python
config = {
    # array (mémoire, tests), file (dossier storage/cache) ou redis.
    "default": env("CACHE_STORE", "file"),
    "stores": {
        "array": {"driver": "array"},
        "file": {"driver": "file", "path": "storage/cache"},
        "redis": {"driver": "redis", "url": env("REDIS_URL", "redis://127.0.0.1:6379/0")},
    },
    # Préfixe des clés : plusieurs applications peuvent partager un Redis.
    "prefix": env("CACHE_PREFIX", "<app>_cache:"),   # <app> = APP_NAME en minuscules, sans espaces
}
```

- Sans `config/cache.py` : store `file` dans `storage/cache`, préfixe dérivé du nom de l'app.
- `.env.example` : `CACHE_STORE=file`, `CACHE_PREFIX` commenté.
- Extra `redis = ["redis>=5"]` dans `pyproject.toml` (l'extra `rq` l'apporte déjà).
- Squelette : `.gitignore` gagne `storage/`.

### Commande

- `flask cache:clear [STORE]` : `flush()` du store (défaut : le store par défaut) et affiche ce qui a été vidé.

### Tests d'une application

- Pas de `Cache.fake()` : on utilise le pilote `array` (`CACHE_STORE=array`, ou `Cache.store("array")`). Les tests du squelette partagent une app : le README conseille `Cache.flush()` dans une fixture.

### Exports

- `flask_artisan` : façade `Cache`.
- `flask_artisan.cache` : `CacheManager`, `ArrayStore`, `FileStore`, `RedisStore`.

### Documentation

- README : section « Cache » : configurer (trois pilotes, préfixe, Redis partagé avec les queues), chaque méthode avec un exemple, TTL, ce qui peut être mis en cache (JSON, modèles rechargés et leur coût, `to_dict()`), `remember` non atomique, `increment` non atomique avec `file`, tester avec `array`, `flask cache:clear`.
- « Console », « Après la v0.1 » ; CLAUDE.md ; CHANGELOG.

## Pièges connus

- **Le module standard.** Comme pour `tests/queues/`, un dossier de tests ne doit pas s'appeler comme un module standard ; `tests/cache/` ne masque rien (pas de module `cache` dans la bibliothèque standard), à vérifier.
- **Tests du conteneur** : rien de nouveau sur `Application`, le manager vit dans le conteneur.
- **Pas de réseau** : `redis` se teste avec `fakeredis` (déjà dans l'extra `dev`).
- **Horloge** : les tests d'expiration remplacent `time.time` lui-même (fakeredis le suit aussi), pas une référence gardée par le module du cache, plutôt que de dormir.

## Laissé au constructeur

- Structure interne (classe de base commune pour la sérialisation et `remember`/`pull`/`missing`, pilotes qui ne font que le stockage brut).
- Calcul exact du préfixe par défaut (dans le respect de « minuscules, sans espaces »).
- Texte des messages.

## Livraison

- Tests pytest, communs aux trois pilotes (paramétrés) quand le comportement est le même :
  - `get`/`put`/`default` appelable, TTL en secondes et `timedelta`, expiration (horloge remplacée), TTL ≤ 0, `forever`, `add` (présente / absente / expirée), `remember` (calcul une fois, `None` non stocké), `remember_forever`, `has`/`missing`, `pull`, `forget`, `increment`/`decrement` (absente, existante, TTL conservé, valeur non entière), `flush` ;
  - valeurs : JSON, `datetime`, `Decimal`, modèle rechargé, modèle supprimé depuis (absent, clé supprimée, `remember` recalcule), valeur non prise en charge (`TypeError` nommant la clé), clé invalide, `put(k, None)` qui supprime ;
  - `file` : fichier corrompu = absent, écriture atomique (aucun fichier temporaire restant), dossier créé ;
  - `redis` : préfixe, `flush` ne touche pas une clé hors préfixe (ex. une clé `rq:`), `add` et `increment` natifs, message sans redis-py ;
  - manager : store par défaut, `store(name)`, store et pilote inconnus, défauts sans `config/cache.py`, store `array` conservé ;
  - `cache:clear` ;
  - projet généré : `config/cache.py`, `.gitignore` avec `storage/`, `Cache.remember` en `file` qui écrit dans `storage/cache`.
- README, CLAUDE.md, CHANGELOG.
- PR `feat/32-cache`, commits et titre avec `(#32)`, corps avec `Closes #32`.

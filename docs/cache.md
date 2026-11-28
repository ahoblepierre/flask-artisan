# Cache

Le cache garde de côté le résultat d'un calcul coûteux (statistiques, réponse d'une API tierce, page de résultats) pour ne pas le refaire à chaque requête, et sert à compter des choses (tentatives, vues).

```python
from datetime import timedelta

from flask_artisan import Cache

stats = Cache.remember("stats:dashboard", 600, lambda: compute_stats())   # calculé au plus une fois toutes les 10 minutes
Cache.put("weather:paris", forecast, timedelta(hours=1))
Cache.get("weather:paris")                       # None si absent ou expiré
Cache.increment("visits")
Cache.forget("stats:dashboard")
```

## Configurer

Le store se choisit avec `CACHE_STORE` dans `.env` :

| Store | Où vont les valeurs | Usage |
|---|---|---|
| `file` (défaut) | un fichier par clé dans `storage/cache/` du projet | une seule machine, sans Redis |
| `redis` | le serveur Redis de `REDIS_URL` | production, plusieurs processus ou serveurs |
| `array` | la mémoire du processus, perdue au redémarrage | tests |

`redis` demande redis-py : `pip install "flask-artisan[redis]"` (déjà présent avec `[rq]`). Le cache peut partager le Redis des [queues](queues.md) : ses clés portent un préfixe (`CACHE_PREFIX`, par défaut le nom de l'application suivi de `_cache:`), et `Cache.flush()` ne supprime que les clés de ce préfixe, jamais les files d'attente. Aucune version minimale de Redis n'est exigée.

Les stores sont déclarés dans `config/cache.py` (le squelette ajoute `storage/` au `.gitignore`). La configuration est relue à chaque appel ; un projet sans ce fichier utilise `file`, et son store `redis` lit `REDIS_URL`. Les fichiers du store `file` sont créés en mode `0644`, lisibles par une commande planifiée qui tournerait sous un autre utilisateur que le serveur web ; `flask cache:clear` n'efface que ces fichiers, jamais un autre fichier du dossier.

`Cache.get(...)` et les autres méthodes visent le store par défaut ; `Cache.store("redis")` en désigne un autre :

```python
Cache.store("redis").put("k", "v", 60)
```

## Méthodes

| Méthode | Effet |
|---|---|
| `get(key, default=None)` | la valeur, ou `default` (appelé s'il s'agit d'une fonction) |
| `put(key, value, ttl=None)` | stocke ; `ttl` en secondes ou `timedelta`, `None` = sans expiration |
| `add(key, value, ttl=None)` | stocke seulement si la clé est absente ; renvoie `True` si stockée (atomique, voir [Quel store choisir](limitation-de-debit.md#quel-store-choisir)) |
| `forever(key, value)` | `put` sans expiration |
| `remember(key, ttl, callback)` | la valeur en cache, sinon `callback()` stocké puis renvoyé |
| `remember_forever(key, callback)` | idem, sans expiration |
| `has(key)` / `missing(key)` | la clé a-t-elle une valeur ? |
| `pull(key, default=None)` | lit puis supprime |
| `forget(key)` | supprime ; renvoie `True` si la clé existait |
| `increment(key, by=1)` / `decrement(key, by=1)` | ajoute à un entier et renvoie le résultat ; une clé absente vaut 0 ; l'expiration est conservée |
| `flush()` | vide le store |
| `prune()` | supprime les entrées expirées et renvoie leur nombre (voir [Purger les entrées expirées](#purger-les-entrees-expirees)) |

- `None` équivaut à « absent » : `put(key, None)` supprime la clé, et un `remember` dont le callback renvoie `None` ne stocke rien (il sera rappelé la fois suivante). Un `ttl` de 0 ou négatif supprime aussi la clé.
- Un `ttl` fractionnaire est arrondi à la seconde supérieure.
- `remember` n'est pas atomique : deux requêtes simultanées sur une clé absente peuvent calculer toutes les deux (comme Laravel sans verrou).
- `add`, `increment` et `pull` sont atomiques entre processus avec `redis`, et avec `file` sur une même machine (hors Windows) ; pour plusieurs serveurs, utilisez `redis`.
- Verrous : voir [Verrous](limitation-de-debit.md#verrous).

## Ce qu'on peut mettre en cache

Les valeurs sont enregistrées en JSON (jamais en `pickle`) : `str`, nombres, `bool`, listes, dicts à clés `str`, ainsi que `datetime`, `date` et `Decimal`. Toute autre valeur lève `TypeError` dès `put`, en nommant la clé.

Un **modèle** est stocké par son identifiant et **relu en base à chaque lecture** : la donnée est à jour, mais le cache n'épargne pas la requête. Pour éviter la base, mettez en cache des données calculées ou `to_dict()` :

```python
user_card = Cache.remember(f"user:{user.id}:card", 300, lambda: user.to_dict())
```

Une valeur devenue illisible (modèle supprimé depuis, classe déplacée, fichier corrompu) compte comme **absente** : la clé est supprimée, un avertissement est journalisé, et `remember` recalcule. Le cache ne lève jamais de 404.

## Tester

Utilisez le store `array` dans les tests (`CACHE_STORE=array`, ou `Cache.store("array")`). Les tests du projet généré partagent une application : videz le cache entre deux tests.

```python
import pytest

from flask_artisan import Cache


@pytest.fixture(autouse=True)
def empty_cache():
    yield
    Cache.flush()
```

## Vider le cache

```bash
flask cache:clear            # le store par défaut
flask cache:clear redis      # un store précis
```

## Purger les entrées expirées

Les stores `file` et `array` ne suppriment une entrée expirée que lorsqu'on relit sa clé. Une clé jamais relue reste donc stockée : c'est le cas des compteurs de [`throttle`](limitation-de-debit.md), deux fichiers par adresse IP. `flask cache:prune` les supprime :

```bash
flask cache:prune            # le store par défaut, et celui des compteurs (cache.limiter) s'il est différent
flask cache:prune file       # un store précis
```

Les entrées encore valides et celles sans expiration restent. Seul le store `file` en a vraiment besoin : Redis supprime lui-même les clés expirées (la commande y renvoie 0), et le store `array` disparaît avec le processus. `Cache.prune()` fait la même chose depuis le code, pour le store par défaut.

Un projet généré planifie déjà la commande toutes les heures dans `routes/console.py` (voir [Tâches planifiées](planification.md)). Dans un projet créé avant la 0.10.1, ajoutez cette ligne, puis installez la ligne cron du planificateur :

```python
Schedule.command("cache:prune").hourly()
```

En production, préférez Redis pour les compteurs (`"limiter": "redis"` dans `config/cache.py`) : ils expirent sans aucune purge.

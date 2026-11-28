# GH-64 : purge des entrées expirées du cache (`flask cache:prune`)

Ticket : https://github.com/ahoblepierre/flask-artisan/issues/64

## Pourquoi

L'audit de sécurité du 27/11/2026 a confirmé ce défaut (sévérité faible) et l'a reproduit trois fois.

`FileStore` (`src/flask_artisan/cache.py`) ne supprime un fichier expiré qu'à la relecture de la même clé. Il n'existe aucune autre purge. Or `ThrottleRequests` crée deux clés par adresse IP anonyme (`throttle:<sha1>` et `throttle:<sha1>:timer`). Le squelette utilise `CACHE_STORE=file`, avec `throttle` sur le groupe `api` et sur les routes de connexion.

Concrètement, chaque adresse vue laisse deux fichiers pour toujours : 30 adresses donnent 60 fichiers, et il en reste toujours 62 une heure plus tard. Un client qui contrôle beaucoup d'adresses (IPv6, ou `TRUSTED_PROXIES` mal réglé) fait grossir `storage/cache` sans borne. Quand le disque ou les inodes sont épuisés, toutes les routes limitées, connexion comprise, répondent 500. Le seul recours aujourd'hui est `cache:clear`, qui efface aussi les compteurs et les verrous encore valides.

`ArrayStore` a la même expiration paresseuse, dans la mémoire du processus.

## Objectif

Les entrées expirées sont récupérées. La taille du store est alors bornée par les entrées encore valides, et non par toutes les clés jamais écrites.

## Design retenu (option A, choisie par Pierre)

- **`Store.prune() -> int`** : méthode publique qui supprime les entrées expirées et renvoie leur nombre. Elle rejoint `PUBLIC`, donc `Cache.prune()` vise le store par défaut.
  - `FileStore` : elle parcourt les fichiers du dossier dont le nom correspond à `CACHE_FILE` (le même filtre que `_flush` : jamais `.lock`, `.gitignore` ni `.tmp-…`). Elle supprime ceux qui sont expirés ou illisibles. Les entrées sans expiration et les entrées encore valides restent. Un dossier absent renvoie 0.
    - **Verrou par fichier, jamais sur tout le parcours** (mon choix, signalé par la relecture) : la liste et la première lecture se font sans verrou. Pour chaque fichier expiré ou illisible, on prend `_locked()` le temps de le relire et de le supprimer avec `_unlink_if_same`. Un fichier réécrit entre-temps par `os.replace` (nouvel inode, ou entrée redevenue valide) est épargné. Les requêtes limitées ne sont bloquées que le temps d'une suppression, jamais pendant tout le parcours d'un dossier énorme, ce qui avait fait écarter l'option B.
  - `ArrayStore` : sous `_mutex`, elle retire les entrées expirées du dictionnaire.
  - `RedisStore` : renvoie 0, car Redis applique déjà le TTL.
- **Commande `flask cache:prune [store]`** : même traitement des erreurs que `cache:clear`. Elle affiche une ligne par store purgé, « N entrée(s) expirée(s) supprimée(s) du store <nom>. », et s'enregistre à côté de `cache_clear` dans `console.py`.
  - **Sans argument** (choix de Pierre, option A) : elle purge le store par défaut, puis le store des compteurs `cache.limiter` s'il est réglé et différent. Elle couvre ainsi les compteurs de `throttle` même quand un projet les met dans un store à part. La résolution du nom suit `RateLimiter._store()`.
  - **Avec un argument** : elle ne purge que le store nommé.
- **Squelette** : `routes/console.py` active `Schedule.command("cache:prune").hourly()`, avec un commentaire sur son rôle. C'est la première tâche active du fichier.
- **Docs** :
  - `docs/cache.md` : nouvelle section « Purger les entrées expirées » avec `flask cache:prune`, la ligne à ajouter dans `routes/console.py` d'un projet existant, et Redis recommandé pour `cache.limiter` en production ;
  - `docs/console.md` : la commande dans la liste ;
  - `docs/limitation-de-debit.md` : une phrase sur la purge, dans « Quel store choisir » ;
  - `docs/planification.md` : une ligne qui signale que le squelette planifie déjà `cache:prune` toutes les heures.
- **CHANGELOG** : entrée « Sécurité » (le défaut corrigé) et entrée « Ajouté » (`Cache.prune()`, `flask cache:prune`), dans la section non publiée.

## Approches écartées

- Pour la commande sans argument : purger tous les stores configurés (touche des stores jamais créés, comme un `redis` déclaré mais pas utilisé), ou seulement le store par défaut (laisse le défaut ouvert quand `cache.limiter` est réglé).
- **B. Purge déclenchée au hasard pendant les écritures** (loterie à la Laravel). Elle parcourt tout le dossier sous le verrou global et bloque toutes les requêtes limitées de la machine, justement quand le dossier est gros.
- **C. A et B à la fois** : le risque de B demeure.

## Tests

- **`FileStore.prune`** :
  - une entrée expirée est supprimée ;
  - une entrée valide et une entrée sans expiration restent ;
  - un fichier illisible est supprimé ;
  - `.lock`, `.gitignore` et un `.tmp-…` restent ;
  - la valeur renvoyée est le nombre de fichiers supprimés ;
  - un dossier absent renvoie 0.

  On simule le temps en remplaçant `time.time`, comme dans `tests/cache/`.
- **Contrat commun** (`tests/cache/test_store_contract.py`) : après `prune()`, une clé valide se lit toujours et une clé expirée est absente, pour les trois pilotes.
- **`ArrayStore.prune`** : le dictionnaire ne contient plus l'entrée expirée.
- **`RedisStore.prune`** : renvoie 0.
- **La commande** :
  - store par défaut et store nommé ;
  - sans argument, avec `cache.limiter` réglé sur un autre store `file` : les deux stores sont purgés, avec une ligne chacun ;
  - `cache.limiter` égal au store par défaut : une seule purge ;
  - store inconnu → erreur Click ;
  - message avec le nombre.
- **Scénario de l'audit** : 30 adresses passent par `throttle`, puis on avance le temps au-delà de la fenêtre et on lance `prune()`. Il ne reste aucun fichier de compteur.
- **`tests/test_cli.py`, projet généré** :
  - `schedule:list` affiche maintenant `cache:prune` ;
  - `schedule:run` doit réussir à n'importe quelle minute. Comme la tâche tourne à la minute 0, le test ne vérifie plus le message « Aucune tâche planifiée à exécuter. », seulement le code de sortie 0.

## Hors périmètre

- Les autres notes de durcissement du cache de l'audit : fichiers en 0644, `_read` qui supprime sur n'importe quelle `OSError`, `decrement` qui recrée une clé sans TTL, `flock` bloquant.
- Une purge automatique sans planificateur.

## Laissé au développeur

- Le libellé exact des messages et des commentaires.
- La factorisation éventuelle entre `cache_clear` et `cache_prune` (résolution du store, erreurs).

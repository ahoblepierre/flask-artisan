# GH-73 : ne pas supprimer un fichier de cache sur une erreur de lecture

Ticket : https://github.com/ahoblepierre/flask-artisan/issues/73

## Pourquoi

Relevé par la relecture de #64 ; c'était une note de durcissement de l'audit du 27/11/2026.

`FileStore._load` (`src/flask_artisan/cache.py`) classe toute `OSError` de lecture (hors fichier absent) comme `_CORRUPT`. Le fichier est alors supprimé :

- par `_read`, pour la clé lue : `get`, `add`, `increment`, `pull`, `forget`, et donc la prise d'un verrou ;
- par `prune`, pour tous les fichiers du dossier, depuis #64.

Or une `PermissionError` (fichier en 0600 d'une ancienne version, écrit sous un autre utilisateur) ou une erreur `EIO` n'est pas une corruption. Conséquence : `cache:prune` efface des verrous tenus et des entrées `forever`, et un `add` peut prendre un verrou détenu par un autre processus.

## Objectif

Seul un **contenu** invalide (JSON illisible, format inattendu) compte comme corrompu et entraîne la suppression. Un fichier que l'on ne peut pas lire n'est jamais supprimé.

## Design retenu (option B, choisie par Pierre)

- `_load` ne range plus `OSError` dans `_CORRUPT` : l'erreur remonte (`FileNotFoundError` vaut toujours « absente »).
- **Lectures par clé** (`get`, `add`, `increment`, `pull`, `forget`, verrous) : l'`OSError` remonte à l'appelant. On ne prend jamais un verrou qu'on n'a pas pu lire.
- **`prune`** : un fichier illisible, à la première lecture comme à la relecture sous verrou, est laissé en place. Un avertissement est journalisé (logger `flask_artisan.cache`, avec le nom du fichier), et la purge continue. Un seul fichier illisible ne doit pas bloquer la purge, sinon on retrouverait #64.

## Approche écartée

- **A. L'erreur remonte partout, `prune` compris.** Un seul fichier illisible ferait échouer chaque `cache:prune` : le dossier grossirait de nouveau sans borne.

## Tests

Les fichiers sont rendus illisibles par `chmod 000`. Les tests sont sautés si le fichier reste lisible (root, Windows).

- `get` d'une clé dont le fichier est illisible lève `PermissionError`, et le fichier reste.
- `add` sur ce fichier lève l'erreur, sans écraser le fichier.
- `prune` laisse le fichier illisible, supprime les autres fichiers expirés, et journalise un avertissement avec le nom du fichier.
- Les tests existants passent : le JSON invalide est toujours supprimé, par `get` comme par `prune`.

## Livraison

- `src/flask_artisan/cache.py`.
- Doc `docs/cache.md` : la phrase sur les valeurs illisibles précise qu'un fichier qu'on ne peut pas lire n'est pas supprimé.
- CHANGELOG : une entrée « Sécurité » dans `[Non publié]`.

## Hors périmètre

Les autres notes de durcissement du cache : droits des fichiers, `decrement` sans TTL, `flock` bloquant.

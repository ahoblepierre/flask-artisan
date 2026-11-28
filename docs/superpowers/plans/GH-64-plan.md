# GH-64 Purge des entrées expirées du cache — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal :** les entrées expirées du cache sont récupérées. On ajoute `Store.prune()` (et `Cache.prune()`), puis la commande `flask cache:prune`, planifiée toutes les heures dans le squelette.

**Architecture :**
- `Store.prune() -> int` est implémentée par chaque pilote : `FileStore` purge le dossier en ne verrouillant qu'un fichier à la fois, `ArrayStore` purge son dictionnaire sous son mutex, `RedisStore` renvoie 0.
- La commande `cache:prune` vit dans `cache.py`, à côté de `cache:clear`. Sans argument, elle purge le store par défaut puis `cache.limiter` s'il est différent.
- Le squelette active la tâche dans `routes/console.py`.

**Tech Stack :** Python 3.10+, Click, pytest (horloge `clock` de `tests/cache/conftest.py`, `fakeredis`).

**Spec :** `docs/superpowers/specs/GH-64-spec.md`

## Global Constraints

- `FileStore.prune` ne prend jamais `_locked()` pour tout le parcours : un verrou par fichier supprimé seulement. Il ne lit jamais par `_get` sous le verrou (flock non réentrant) : il lit par `_read(..., clean=False)` ou en ouvrant le fichier lui-même.
- `FileStore.prune` ne touche qu'aux fichiers dont le nom correspond à `CACHE_FILE`.
- Une entrée sans expiration (`expires` à `None`) n'est jamais purgée.
- `prune` rejoint le tuple `PUBLIC` de `cache.py`.
- Commande sans argument : store par défaut (`cache.default`, défaut `file`), puis `cache.limiter` s'il est réglé et différent. Avec un argument : ce store seulement. Une ligne de sortie par store : `"{n} entrée(s) expirée(s) supprimée(s) du store {nom}."`
- Erreurs de la commande traitées comme dans `cache_clear` (`ClickException` pour `ValueError`/`RuntimeError`/`OSError` et pour les erreurs du module `redis`).
- Commits et PR contiennent `(#64)`. La PR contient `Closes #64`. Code, commentaires et docs en français.

## Review Focus

- Course entre `prune` et une écriture : un fichier remplacé par `os.replace` après la première lecture (nouvel inode, entrée redevenue valide) ne doit pas être supprimé.
- Fichiers étrangers dans le dossier (`.lock`, `.gitignore`, `.tmp-…`, un sous-dossier dont le nom ressemble à un hash) : intacts, sans erreur.
- Dossier du store absent : `prune()` renvoie 0 sans créer le dossier.
- `cache.limiter` qui désigne un store inconnu : la commande échoue proprement (code non nul, message), comme `cache:clear nope`.
- `schedule:run` du projet généré lancé pile à la minute 0 : la tâche s'exécute et le test reste vert.

---

### Task 1: `Store.prune()` for the three drivers

**Files :**
- Modify : `src/flask_artisan/cache.py` (`PUBLIC`, `Store`, `ArrayStore`, `FileStore`, `RedisStore`)
- Modify : `tests/cache/test_file_store.py`
- Modify : `tests/cache/test_store_contract.py`

**Interfaces :**
- Consomme : rien.
- Produit : `Store.prune(self) -> int` (publique, dans `PUBLIC`, donc `Cache.prune()`). Elle délègue à `_prune(self) -> int` de chaque pilote ; `Store._prune` lève `NotImplementedError` comme les autres primitives.

- [ ] **Step 1 : écrire les tests qui échouent**

Dans `tests/cache/test_store_contract.py` (paramétré sur les trois pilotes par la fixture `store`) :

```python
def test_prune_keeps_live_entries(store, clock):
    store.put("short", 1, 10)
    store.put("long", 2, 100)
    store.forever("always", 3)
    clock.advance(11)
    store.prune()
    assert store.missing("short")
    assert store.get("long") == 2 and store.get("always") == 3


def test_prune_returns_an_int(store):
    assert store.prune() == 0
```

Dans `tests/cache/test_file_store.py` :

```python
def test_prune_removes_expired_and_unreadable_files(tmp_path, clock):
    store = FileStore("p:", tmp_path)
    store.put("old", 1, 10)
    store.put("live", 1, 100)
    store.forever("always", 1)
    corrupt = tmp_path / ("0" * 64)
    corrupt.write_text("{pas du json")
    clock.advance(11)
    assert store.prune() == 2
    assert len(files(tmp_path)) == 2
    assert store.get("live") == 1 and store.get("always") == 1


def test_prune_leaves_foreign_files(tmp_path):
    store = FileStore("p:", tmp_path)
    store.put("k", 1)
    for name in (".gitignore", ".tmp-abc"):
        (tmp_path / name).write_text("x")
    (tmp_path / ("a" * 64)).mkdir()
    assert store.prune() == 0
    assert {".gitignore", ".tmp-abc", "a" * 64} <= set(files(tmp_path))


def test_prune_missing_directory(tmp_path):
    store = FileStore("p:", tmp_path / "absent")
    assert store.prune() == 0
    assert not (tmp_path / "absent").exists()


def test_prune_spares_a_file_rewritten_meanwhile(tmp_path, clock, monkeypatch):
    store = FileStore("p:", tmp_path)
    store.put("k", "old", 10)
    clock.advance(11)
    real_locked = store._locked

    def rewrite_then_lock():
        store.put("k", "new", 100)  # os.replace entre la lecture et le verrou
        return real_locked()

    monkeypatch.setattr(store, "_locked", rewrite_then_lock)
    assert store.prune() == 0
    monkeypatch.undo()
    assert store.get("k") == "new"


def test_prune_reclaims_throttle_counters(tmp_path, clock):
    # Scénario de l'audit : deux clés par client anonyme, jamais relues.
    store = FileStore("p:", tmp_path)
    for i in range(30):
        store.add(f"throttle:{i}:timer", 1, 60)
        store.add(f"throttle:{i}", 0, 60)
    assert len(files(tmp_path)) == 60
    clock.advance(61)
    assert store.prune() == 60
    assert files(tmp_path) == []
```

Note : `files()` exclut déjà `.lock`. Le test « rewritten meanwhile » suppose que `FileStore.prune` prend `self._locked()` pour chaque suppression, après sa première lecture.

- [ ] **Step 2 : lancer les tests et vérifier qu'ils échouent**

Commande : `.venv/bin/pytest tests/cache/test_store_contract.py tests/cache/test_file_store.py -q -k prune`
Attendu : échecs `AttributeError: 'FileStore' object has no attribute 'prune'` (et pareil pour les autres pilotes).

- [ ] **Step 3 : implémenter dans `src/flask_artisan/cache.py`**

- `PUBLIC` : ajouter `"prune"`.
- `Store` : `_prune(self) -> int` qui lève `NotImplementedError` (dans la section des primitives), et `prune(self) -> int` qui renvoie `self._prune()`, à côté de `flush`.
- `ArrayStore._prune` : sous `self._mutex`, retirer chaque clé dont l'expiration est passée (réutiliser `_alive` ou la même comparaison), et renvoyer le nombre retiré.
- `RedisStore._prune` : renvoyer 0, avec un commentaire d'une ligne (TTL natif).
- `FileStore._prune` :
  - si `self.directory` n'est pas un dossier, renvoyer 0 ;
  - pour chaque `path` de `iterdir()` dont le nom correspond à `CACHE_FILE` et qui est un fichier, faire une première lecture sans verrou (ouvrir, `fstat` pour l'inode, `json.loads`, prendre `expires`). Le fichier est « à supprimer » s'il est illisible ou si `expires` n'est pas `None` et `<= time.time()` ;
  - pour un fichier à supprimer, sous `with self._locked():`, relire de la même façon. S'il est toujours à supprimer, appeler `self._unlink_if_same(path, inode_relu)` et compter. Un `FileNotFoundError` à l'une ou l'autre lecture fait passer au fichier suivant ;
  - factoriser la lecture « inode + verdict » dans une petite fonction privée si elle sert deux fois ;
  - un commentaire d'une ligne explique le verrou par fichier : le parcours d'un gros dossier ne doit pas bloquer les requêtes limitées.

- [ ] **Step 4 : lancer les tests et vérifier qu'ils passent**

Commande : `.venv/bin/pytest tests/cache -q`
Attendu : tout `tests/cache` passe, y compris les nouveaux tests sur les trois pilotes.

- [ ] **Step 5 : commit**

```bash
git add src/flask_artisan/cache.py tests/cache/test_store_contract.py tests/cache/test_file_store.py docs/superpowers/specs/GH-64-spec.md docs/superpowers/plans/GH-64-plan.md
git commit -m "feat: Cache.prune(), purge des entrées expirées (#64)"
```

### Task 2: `flask cache:prune` command

**Files :**
- Modify : `src/flask_artisan/cache.py` (nouvelle commande `cache_prune`, à côté de `cache_clear`)
- Modify : `src/flask_artisan/console.py` (import et enregistrement à côté de `cache_clear`)
- Modify : `tests/cache/test_command.py`

**Interfaces :**
- Consomme : `Store.prune() -> int` (Task 1).
- Produit : la commande Click `cache:prune` avec l'argument optionnel `store_name`.

- [ ] **Step 1 : écrire les tests qui échouent** dans `tests/cache/test_command.py`

```python
def test_prune_default_store(cache_app, tmp_path, clock):
    configure(cache_app, tmp_path, default="file")
    store = cache_app.make("cache").store()
    store.put("old", 1, 10)
    store.put("live", 1, 100)
    clock.advance(11)
    result = cli(cache_app, "cache:prune")
    assert result.exit_code == 0, result.output
    assert "1 entrée(s) expirée(s) supprimée(s) du store file." in result.output
    assert store.get("live") == 1


def test_prune_named_store(cache_app, tmp_path, clock):
    configure(cache_app, tmp_path, default="file")
    cache_app.make("cache").store("array").put("old", 1, 10)
    clock.advance(11)
    result = cli(cache_app, "cache:prune", "array")
    assert result.exit_code == 0, result.output
    assert "du store array." in result.output and "du store file." not in result.output


def test_prune_also_limiter_store(cache_app, tmp_path, clock):
    configure(cache_app, tmp_path, default="array")
    config = cache_app.make("config")
    config.set("cache.limiter", "file")
    cache_app.make("cache").store("file").put("throttle", 1, 10)
    clock.advance(11)
    result = cli(cache_app, "cache:prune")
    assert result.exit_code == 0, result.output
    assert "du store array." in result.output
    assert "1 entrée(s) expirée(s) supprimée(s) du store file." in result.output


def test_prune_limiter_same_as_default_runs_once(cache_app, tmp_path):
    configure(cache_app, tmp_path, default="file")
    cache_app.make("config").set("cache.limiter", "file")
    result = cli(cache_app, "cache:prune")
    assert result.output.count("du store file.") == 1


def test_prune_unknown_store(cache_app, tmp_path):
    configure(cache_app, tmp_path)
    result = cli(cache_app, "cache:prune", "nope")
    assert result.exit_code != 0 and "nope" in result.output


def test_prune_unknown_limiter_store(cache_app, tmp_path):
    configure(cache_app, tmp_path)
    cache_app.make("config").set("cache.limiter", "nope")
    result = cli(cache_app, "cache:prune")
    assert result.exit_code != 0 and "nope" in result.output
```

- [ ] **Step 2 : lancer les tests et vérifier qu'ils échouent**

Commande : `.venv/bin/pytest tests/cache/test_command.py -q -k prune`
Attendu : échecs (code de sortie 2, commande inconnue).

- [ ] **Step 3 : implémenter**

- `cache_prune(store_name)` dans `cache.py`, décorée comme `cache_clear` (`@click.command("cache:prune")`, `@click.argument("store_name", required=False)`, `@with_appcontext`) :
  - sans argument, la liste des noms vaut `[défaut]`, plus `cache.limiter` s'il est réglé et différent du défaut ;
  - pour chaque nom, appeler `manager.store(name).prune()` et afficher la ligne prévue par les contraintes globales ;
  - les erreurs sont traitées comme dans `cache_clear`. Factoriser ce traitement entre les deux commandes si c'est simple, par exemple avec un petit gestionnaire de contexte.
- `console.py` : importer `cache_prune` et l'ajouter juste après `cache_clear` dans la liste des commandes enregistrées.

- [ ] **Step 4 : lancer les tests et vérifier qu'ils passent**

Commande : `.venv/bin/pytest tests/cache -q`
Attendu : tout passe.

- [ ] **Step 5 : commit**

```bash
git add src/flask_artisan/cache.py src/flask_artisan/console.py tests/cache/test_command.py
git commit -m "feat: commande flask cache:prune (#64)"
```

### Task 3: Skeleton schedule, docs and CHANGELOG

**Files :**
- Modify : `src/flask_artisan/skeleton/routes/console.py`
- Modify : `tests/test_cli.py` (`test_generated_project_schedule`)
- Modify : `docs/cache.md`, `docs/console.md`, `docs/limitation-de-debit.md`, `docs/planification.md`
- Modify : `CHANGELOG.md` (section `[Non publié]`)

**Interfaces :**
- Consomme : la commande `cache:prune` (Task 2).
- Produit : rien.

- [ ] **Step 1 : adapter le test qui échoue** dans `tests/test_cli.py`, `test_generated_project_schedule`

Remplacer l'assertion `"Aucune tâche planifiée." in result.stdout` (sur `schedule:list`) par `"cache:prune" in result.stdout`. Supprimer l'assertion sur le message « Aucune tâche planifiée à exécuter. » : le test ne vérifie plus que le code de sortie 0 de `schedule:run`, car à la minute 0 la tâche horaire s'exécute.

- [ ] **Step 2 : lancer le test et vérifier qu'il échoue**

Commande : `.venv/bin/pytest tests/test_cli.py -q -k generated_project_schedule`
Attendu : échec, car `cache:prune` n'est pas dans la sortie de `schedule:list`.

- [ ] **Step 3 : squelette**

Dans `src/flask_artisan/skeleton/routes/console.py`, avant les exemples commentés, ajouter une ligne active : `Schedule.command("cache:prune").hourly()`, précédée d'un commentaire (« supprime les entrées expirées du cache, dont les compteurs de limitation laissés par chaque adresse IP »). Retirer le `# noqa: F401` de l'import, devenu utile.

- [ ] **Step 4 : lancer le test et vérifier qu'il passe**

Commande : `.venv/bin/pytest tests/test_cli.py -q -k generated_project_schedule`
Attendu : passe.

- [ ] **Step 5 : docs et CHANGELOG**

- `docs/cache.md` : après « Vider le cache », ajouter une section « Purger les entrées expirées » qui couvre :
  - `flask cache:prune` (avec et sans store) ;
  - ce que la commande purge sans argument (store par défaut, plus `cache.limiter`) ;
  - le fait que seul le store `file` en a vraiment besoin ;
  - la ligne `Schedule.command("cache:prune").hourly()` déjà présente dans un projet généré depuis cette version, à ajouter dans `routes/console.py` d'un projet existant ;
  - Redis recommandé pour `cache.limiter` en production.

  Ajouter aussi `Cache.prune()` au tableau ou à la liste des méthodes, si la page en a une.
- `docs/console.md` : la ligne `flask cache:prune` sous `flask cache:clear`.
- `docs/limitation-de-debit.md`, « Quel store choisir » : une phrase sur les compteurs du store `file`, qui restent sur le disque jusqu'à `cache:prune` (lien vers la section de `cache.md`).
- `docs/planification.md` : une phrase qui signale que le squelette planifie déjà `cache:prune` toutes les heures.
- `CHANGELOG.md`, section `[Non publié]` :
  - sous `### Ajouté` (à créer avant `### Sécurité`) : « `Cache.prune()` et la commande `flask cache:prune` : suppression des entrées expirées ; sans argument, le store par défaut et celui des compteurs (`cache.limiter`) (#64). » ;
  - sous `### Modifié` (à créer) : « Squelette : `routes/console.py` planifie `cache:prune` toutes les heures (#64). » ;
  - sous `### Sécurité` : « Le store `file` gardait pour toujours les compteurs de limitation de chaque adresse IP : `cache:prune` les supprime une fois expirés (#64). »

- [ ] **Step 6 : suite complète, lint et doc**

Commandes :
- `.venv/bin/pytest -q`
- `.venv/bin/ruff check . && .venv/bin/ruff format --check .`
- `.venv/bin/mkdocs build --strict`

Attendu : tout passe, et les ancres citées dans les liens existent.

- [ ] **Step 7 : commit**

```bash
git add src/flask_artisan/skeleton/routes/console.py tests/test_cli.py docs/cache.md docs/console.md docs/limitation-de-debit.md docs/planification.md CHANGELOG.md
git commit -m "feat: cache:prune planifiée dans le squelette, docs (#64)"
```

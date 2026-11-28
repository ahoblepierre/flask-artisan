# GH-73 Fichier de cache illisible jamais supprimé — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal :** une `OSError` à la lecture d'un fichier du store `file` ne le supprime plus. Elle remonte pour les lectures par clé ; `prune` passe le fichier avec un avertissement.

**Architecture :** `FileStore._load` ne classe plus `OSError` comme `_CORRUPT` et la laisse remonter. `FileStore._prune` intercepte `OSError` fichier par fichier.

**Tech Stack :** Python 3.10+, pytest (`clock`, `caplog`).

**Spec :** `docs/superpowers/specs/GH-73-spec.md`

## Global Constraints

- `FileNotFoundError` vaut toujours « absente » (`None, None`).
- Un JSON invalide ou un format inattendu reste `_CORRUPT`, donc supprimé (tests existants inchangés).
- `prune` ne s'arrête jamais sur un fichier illisible : avertissement sur le logger `flask_artisan.cache`, avec `path.name`.
- Commit et PR contiennent `(#73)`. La PR contient `Closes #73`. Code, commentaires et docs en français.

## Review Focus

- Fichier qui devient illisible entre la première lecture de `prune` et la relecture sous verrou : pas d'exception, pas de suppression.
- `IsADirectoryError` sur une clé dont le chemin est un dossier : l'erreur remonte, comme une autre `OSError`.
- Verrou (`Cache.lock(...).get()`) sur un fichier illisible : erreur, jamais une prise du verrou.
- Le `flock` est relâché quand une `OSError` remonte sous `_locked()` (gestionnaire de contexte).

---

### Task 1: Keep unreadable cache files

**Files :**
- Modify : `src/flask_artisan/cache.py` (`FileStore._load`, `FileStore._prune`)
- Modify : `tests/cache/test_file_store.py`
- Modify : `docs/cache.md`, `CHANGELOG.md`

**Interfaces :** aucune nouvelle. `_load(path)` peut maintenant lever `OSError`.

- [ ] **Step 1 : écrire les tests qui échouent** dans `tests/cache/test_file_store.py`

Un helper `unreadable(path)` fait `chmod 000`, puis `pytest.skip` si `os.access(path, os.R_OK)` reste vrai. Une fixture ou un `finally` remet les droits pour que `tmp_path` puisse être nettoyé.

- `test_unreadable_file_raises_and_is_kept` : `store.put("k", 1)`, fichier rendu illisible ; `pytest.raises(PermissionError)` sur `store.get("k")`, et le fichier existe toujours.
- `test_add_on_unreadable_file_raises` : même préparation ; `store.add("k", 2)` lève `PermissionError`, et le fichier existe toujours.
- `test_prune_skips_unreadable_file` : avec `clock` et `caplog`, `put("a", 1, 10)` (rendu illisible) et `put("b", 1, 10)` ; `clock.advance(11)` ; `prune() == 1`. Le fichier de `a` reste, celui de `b` est supprimé, et le nom du fichier de `a` figure dans `caplog.text`.

- [ ] **Step 2 : vérifier qu'ils échouent**

Commande : `.venv/bin/pytest tests/cache/test_file_store.py -q -k unreadable`
Attendu : 3 échecs (aucune exception levée, ou fichier supprimé).

- [ ] **Step 3 : implémenter**

- `_load` : retirer `OSError` du `except` de corruption. Mettre à jour la docstring : une erreur de lecture remonte.
- `_prune` : envelopper le traitement d'un fichier (première lecture, plus le bloc sous verrou) dans `try/except OSError` ; sur erreur, `logger.warning("Cache : %s illisible, laissé en place (%s).", path.name, exc)` puis passer au fichier suivant.

- [ ] **Step 4 : vérifier qu'ils passent**

Commande : `.venv/bin/pytest tests/cache -q`
Attendu : tout passe.

- [ ] **Step 5 : doc et CHANGELOG**

- `docs/cache.md`, phrase « Une valeur devenue illisible… » : ajouter qu'un fichier que le serveur ne peut pas lire (droits, disque) n'est jamais supprimé, et que l'erreur remonte.
- `CHANGELOG.md`, `[Non publié]`, `### Sécurité` (à créer) : « Store `file` : une erreur de lecture (droits, disque) ne supprime plus le fichier : `cache:prune` le laisse en place avec un avertissement, et une lecture par clé lève l'erreur au lieu de prendre un verrou tenu (#73). »

- [ ] **Step 6 : suite, lint, doc**

Commandes : `.venv/bin/pytest -q` ; `.venv/bin/ruff check . && .venv/bin/ruff format --check .` ; `.venv/bin/mkdocs build --strict`
Attendu : tout passe.

- [ ] **Step 7 : commit**

```bash
git add src/flask_artisan/cache.py tests/cache/test_file_store.py docs/cache.md CHANGELOG.md docs/superpowers/specs/GH-73-spec.md docs/superpowers/plans/GH-73-plan.md
git commit -m "fix: ne pas supprimer un fichier de cache illisible (#73)"
```

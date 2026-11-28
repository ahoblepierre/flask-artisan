# GH-63 URLs signées : `?` interdit dans le chemin décodé — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal :** un message signé correspond à un seul couple (chemin, requête). Un lien réécrit avec `%3F` dans le chemin est refusé, et `signed_url` refuse de signer un chemin dont la forme décodée contient `?`.

**Architecture :** deux contrôles dans `src/flask_artisan/signing.py`. `has_valid_signature` renvoie `False` si `req.path` contient `?`. `signed_url` lève `ValueError` si le chemin décodé produit par `_canonical` contient `?`. Le message signé ne change pas, donc les liens déjà émis restent valides.

**Tech Stack :** Flask 3.1 / Werkzeug, pytest.

**Spec :** `docs/superpowers/specs/GH-63-spec.md`

## Global Constraints

- Ne pas modifier le format du message signé : `<chemin décodé sans script_root>?<requête brute>`.
- Les tests existants de `tests/test_signing.py` passent sans modification.
- Commit et PR contiennent `(#63)`. La PR contient `Closes #63`.
- Code, commentaires et docs en français, comme le reste du dépôt.

## Review Focus

- `?` encodé en minuscules (`%3f`) dans le chemin : Werkzeug le décode aussi, il doit être refusé.
- Lien réécrit vers une route `path:` (une valeur qui contient des `/` puis `%3F`) : refusé.
- Valeur de route contenant `?` avec `_external=True` : `ValueError`, pas une URL absolue invalide.
- Valeur de route légitime avec `%`, espace, `é` ou `@` : toujours signée et acceptée (test existant `test_encoded_path_params_are_accepted`).
- Application montée sous un `SCRIPT_NAME` : toujours acceptée (test existant `test_app_under_script_root`).

---

### Task 1: Reject `?` in the decoded signed path

**Files :**
- Modify : `src/flask_artisan/signing.py` (`_canonical` ou `signed_url`, et `has_valid_signature`)
- Modify : `tests/test_signing.py`
- Modify : `docs/authentification.md` (section « URLs signées »)
- Modify : `CHANGELOG.md` (section `[Non publié]`)

**Interfaces :**
- Consomme : rien.
- Produit : `signed_url(endpoint, expires=None, **values) -> str` lève `ValueError` (message qui contient le nom de l'endpoint) quand le chemin décodé contient `?`. `has_valid_signature(req) -> bool` renvoie `False` quand `req.path` contient `?`.

- [ ] **Step 1 : écrire les tests qui échouent** dans `tests/test_signing.py`

```python
def _moved_query(url):
    # /files/report?expires=T&signature=S  ->  /files/report%3Fexpires=T?signature=S
    path, query = url.split("?", 1)
    rest, signature = query.rsplit("&", 1)
    return f"{path}%3F{rest}?{signature}"


@pytest.fixture
def named_app(routed_app):
    return routed_app(
        lambda: Route.get("/s/<name>", lambda name: name).name("s").middleware(ValidateSignature)
    )


def test_query_moved_into_path_is_forbidden(named_app, monkeypatch):
    client = named_app.test_client()
    with named_app.test_request_context():
        url = signed_url("s", expires=60, name="report")
    assert client.get(_moved_query(url)).status_code == 403
    monkeypatch.setattr(signing, "_now", lambda: signing.time.time() + 3600)
    assert client.get(_moved_query(url)).status_code == 403


def test_lowercase_encoded_question_mark_is_forbidden(named_app):
    with named_app.test_request_context():
        url = signed_url("s", expires=60, name="report")
    assert named_app.test_client().get(_moved_query(url).replace("%3F", "%3f")).status_code == 403


@pytest.mark.parametrize("external", [False, True])
def test_value_with_question_mark_cannot_be_signed(named_app, external):
    with named_app.test_request_context(), pytest.raises(ValueError, match="'s'"):
        signed_url("s", name="a?b", _external=external)
```

- [ ] **Step 2 : lancer les tests et vérifier qu'ils échouent**

Commande : `.venv/bin/pytest tests/test_signing.py -q`
Attendu : `test_query_moved_into_path_is_forbidden` échoue (200 au lieu de 403), `test_lowercase_encoded_question_mark_is_forbidden` aussi, et `test_value_with_question_mark_cannot_be_signed` échoue (`DID NOT RAISE`). Les 8 tests existants passent.

- [ ] **Step 3 : implémenter dans `src/flask_artisan/signing.py`**

- Dans `has_valid_signature`, avant de calculer le HMAC : `if "?" in req.path: return False`, avec un commentaire d'une ligne (le `?` décodé imiterait le séparateur de la requête signée).
- Côté signature, le chemin décodé (la partie de `_canonical` avant la requête) qui contient `?` lève `ValueError(f"signed_url('{endpoint}') : une valeur de route contient « ? », impossible à signer sans ambiguïté.")`. Le contrôle doit avoir lieu avant tout retour, donc aussi pour `_external=True`.

- [ ] **Step 4 : lancer les tests et vérifier qu'ils passent**

Commande : `.venv/bin/pytest tests/test_signing.py -q`
Attendu : 12 tests passent (8 existants + 4 nouveaux en comptant les deux cas paramétrés).

- [ ] **Step 5 : doc et CHANGELOG**

- `docs/authentification.md`, section « URLs signées », après le paragraphe sur la signature, ajouter : « Une valeur de route qui contient `?` ne peut pas être signée : `signed_url` lève `ValueError`. »
- `CHANGELOG.md`, sous `## [Non publié]`, ajouter :

```markdown
### Sécurité

- URLs signées : un lien dont la requête était déplacée dans le chemin (`%3F`) restait valide après expiration ; il est désormais refusé, et `signed_url` refuse une valeur de route contenant `?` (#63).
```

- [ ] **Step 6 : suite complète, lint et doc**

Commandes :
- `.venv/bin/pytest -q`
- `.venv/bin/ruff check . && .venv/bin/ruff format --check .`
- `.venv/bin/mkdocs build --strict`

Attendu : toute la suite passe, ruff ne signale rien, mkdocs construit sans erreur.

- [ ] **Step 7 : commit**

```bash
git add src/flask_artisan/signing.py tests/test_signing.py docs/authentification.md CHANGELOG.md docs/superpowers/specs/GH-63-spec.md docs/superpowers/plans/GH-63-plan.md
git commit -m "fix: URLs signées, refuser « ? » dans le chemin décodé (#63)"
```

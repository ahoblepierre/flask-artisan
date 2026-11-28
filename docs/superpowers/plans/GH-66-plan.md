# GH-66 `age_flash` garde une lecture de session antérieure — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal :** quand du code lit la session avant les `before_request`, la réponse garde `Vary: Cookie`. Une requête qui ne lit pas la session n'en reçoit toujours pas.

**Architecture :** `age_flash` (`src/flask_artisan/views.py`) lit le drapeau `accessed` de l'objet session sous-jacent avant de le toucher, puis le restaure au lieu de le forcer à `False`. Il retrouve l'objet par le contexte de requête : `_session` en Flask 3.1, `session` en Flask 3.0. Si ni l'un ni l'autre n'existe, il ne remet rien à zéro, ce qui échoue du côté sûr.

**Tech Stack :** Flask 3.0 / 3.1, pytest.

**Spec :** `docs/superpowers/specs/GH-66-spec.md`

## Global Constraints

- Ne jamais lire le drapeau à travers le proxy `flask.session` ni la propriété `RequestContext.session` de Flask 3.1 : les deux le mettent à `True`.
- Si l'objet sous-jacent est introuvable, ne pas toucher à `accessed`.
- Les tests existants de `tests/test_views.py` et `tests/test_html_errors.py` passent sans modification.
- Commit et PR contiennent `(#66)`. La PR contient `Closes #66`.
- Code, commentaires et docs en français.

## Review Focus

- Requête qui ne lit pas la session (`/json`) : toujours sans `Vary: Cookie` (`test_no_vary_cookie_when_nothing_flashed`).
- Lecture de session dans un `request_started` ou un convertisseur d'URL, pas seulement dans un `url_value_preprocessor` : même mécanisme, la réponse doit porter `Vary: Cookie`.
- Données flashées présentes : `age_flash` les retire (session modifiée), `Vary: Cookie` présent comme avant.
- Flask 3.0 (plancher de `pyproject`) : `RequestContext.session` est un attribut simple. Le code ne doit pas lever d'erreur ; la CI installe 3.1, donc ce cas se vérifie à la lecture du code.
- Repli si l'attribut privé disparaît : `accessed` n'est pas remis à zéro (pas d'exception).

---

### Task 1: Preserve a prior session read in `age_flash`

**Files :**
- Modify : `src/flask_artisan/views.py` (`age_flash`)
- Modify : `tests/test_views.py`
- Modify : `CHANGELOG.md` (section `[Non publié]`, sous-section `### Sécurité` existante)

**Interfaces :**
- Consomme : rien.
- Produit : `age_flash() -> None`, même contrat qu'avant. Seule la valeur finale de `accessed` change quand rien n'a été flashé.

- [ ] **Step 1 : écrire le test qui échoue** à la fin de `tests/test_views.py`

```python
def test_session_read_before_before_request_keeps_vary_cookie(client):
    app = client.application

    @app.url_value_preprocessor
    def read_session(endpoint, values):
        from flask import g, session

        g.uid = session.get("uid")

    with client.session_transaction() as session:
        session["uid"] = "alice"
    assert "Cookie" in client.get("/json").headers.get("Vary", "")
```

Le handler `/json` ne relit pas la session, donc seule la lecture du préprocesseur dépend de la session.

- [ ] **Step 2 : lancer le test et vérifier qu'il échoue**

Commande : `.venv/bin/pytest tests/test_views.py -q -k keeps_vary`
Attendu : échec, car `Vary` ne contient pas `Cookie`.

- [ ] **Step 3 : implémenter `age_flash` dans `src/flask_artisan/views.py`**

- Une fonction privée `_session_accessed() -> bool | None` renvoie le drapeau sans le modifier. Elle prend le contexte de requête (`flask.globals.request_ctx._get_current_object()`), puis l'objet session par `vars(ctx).get("_session")` (Flask 3.1) ou `vars(ctx).get("session")` (Flask 3.0), et renvoie `None` si aucun n'existe. `vars()` évite de déclencher la propriété de Flask 3.1.
- Dans `age_flash`, appeler `_session_accessed()` en premier. Dans la branche « rien de flashé », si la valeur n'est pas `None`, faire `store.accessed = valeur` au lieu de `False`.
- Remplacer le commentaire actuel (« rien n'avait lu la session avant nous ») par un commentaire qui explique pourquoi on restaure l'état d'avant, et pourquoi on passe par un attribut privé.

- [ ] **Step 4 : lancer les tests et vérifier qu'ils passent**

Commande : `.venv/bin/pytest tests/test_views.py tests/test_html_errors.py -q`
Attendu : tous passent, y compris le nouveau test et `test_no_vary_cookie_when_nothing_flashed`.

- [ ] **Step 5 : CHANGELOG**

Sous la sous-section `### Sécurité` de `[Non publié]`, ajouter : « Une lecture de la session avant les `before_request` (`url_value_preprocessor`, convertisseur d'URL, `request_started`) garde désormais `Vary: Cookie` sur la réponse : un cache partagé ne la sert plus à un autre utilisateur (#66). »

- [ ] **Step 6 : suite complète, lint et doc**

Commandes :
- `.venv/bin/pytest -q`
- `.venv/bin/ruff check . && .venv/bin/ruff format --check .`
- `.venv/bin/mkdocs build --strict`

Attendu : tout passe.

- [ ] **Step 7 : commit**

```bash
git add src/flask_artisan/views.py tests/test_views.py CHANGELOG.md docs/superpowers/specs/GH-66-spec.md docs/superpowers/plans/GH-66-plan.md
git commit -m "fix: age_flash garde une lecture de session antérieure, Vary: Cookie (#66)"
```

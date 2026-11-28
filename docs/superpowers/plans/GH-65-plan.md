# GH-65 Ne pas flasher le jeton de réinitialisation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal :** après un échec de validation d'un formulaire HTML, le champ `token` (jeton de réinitialisation) n'est plus recopié dans la session.

**Architecture :** ajouter `"token"` à la constante `DONT_FLASH` de `src/flask_artisan/routing.py`. `_redirect_back` l'applique déjà à chaque saisie flashée.

**Tech Stack :** Flask 3.1, pytest.

**Spec :** `docs/superpowers/specs/GH-65-spec.md`

## Global Constraints

- `DONT_FLASH = {"password", "password_confirmation", "current_password", "_token", "token"}`.
- Les tests existants de `tests/test_html_errors.py` passent sans modification.
- Commit et PR contiennent `(#65)`. La PR contient `Closes #65`.
- Code, commentaires et docs en français.

## Review Focus

- Formulaire avec `token` en query string (`request.args`) plutôt qu'en corps : `_redirect_back` fusionne `args` et `form`, donc `token` doit être exclu dans les deux cas.
- Le kit `auth:install` ne lit jamais `old('token')` : vérifier `stubs/auth/resources/views/auth/*.html.stub`.
- Un champ dont le nom contient `token` sans être `token` (par exemple `device_token`) reste flashé : le filtre compare des noms exacts, comme avant.

---

### Task 1: Exclude `token` from flashed old input

**Files :**
- Modify : `src/flask_artisan/routing.py:20` (`DONT_FLASH`)
- Modify : `tests/test_html_errors.py`
- Modify : `docs/vues.md` (liste « ne sont jamais gardés »)
- Modify : `CHANGELOG.md` (section `[Non publié]`, sous-section `### Sécurité` existante)

**Interfaces :**
- Consomme : rien.
- Produit : `DONT_FLASH` contient `"token"`.

- [ ] **Step 1 : écrire le test qui échoue** à la fin de `tests/test_html_errors.py`

```python
def test_reset_token_is_never_flashed(app):
    client = app.test_client()
    data = {"email": "x", "token": "secret-reset-token", "password": "s"}
    client.post("/form?token=from-query", data=data, headers=REFERER)
    old = flashed(client)["_flash_old"]
    assert old == {"email": "x"}
```

- [ ] **Step 2 : lancer le test et vérifier qu'il échoue**

Commande : `.venv/bin/pytest tests/test_html_errors.py -q -k reset_token`
Attendu : échec, car `old` contient `token`.

- [ ] **Step 3 : implémenter**

Dans `src/flask_artisan/routing.py`, `DONT_FLASH` devient `{"password", "password_confirmation", "current_password", "_token", "token"}`. Le commentaire au-dessus mentionne le jeton de réinitialisation : le cookie de session Flask est signé, pas chiffré.

- [ ] **Step 4 : lancer les tests et vérifier qu'ils passent**

Commande : `.venv/bin/pytest tests/test_html_errors.py -q`
Attendu : tous les tests passent, y compris le nouveau.

- [ ] **Step 5 : doc et CHANGELOG**

- `docs/vues.md` : la puce « les champs `password`, `password_confirmation` et `current_password` ne sont jamais gardés » cite aussi `_token` (jeton CSRF) et `token` (jeton de réinitialisation du mot de passe).
- `CHANGELOG.md`, sous la sous-section `### Sécurité` existante de `[Non publié]`, ajouter : « Le champ `token` (jeton de réinitialisation du mot de passe) n'est plus recopié dans le cookie de session après un échec de validation (#65). »

- [ ] **Step 6 : suite complète, lint et doc**

Commandes :
- `.venv/bin/pytest -q`
- `.venv/bin/ruff check . && .venv/bin/ruff format --check .`
- `.venv/bin/mkdocs build --strict`

Attendu : tout passe.

- [ ] **Step 7 : commit**

```bash
git add src/flask_artisan/routing.py tests/test_html_errors.py docs/vues.md CHANGELOG.md docs/superpowers/specs/GH-65-spec.md docs/superpowers/plans/GH-65-plan.md
git commit -m "fix: ne pas flasher le jeton de réinitialisation (#65)"
```

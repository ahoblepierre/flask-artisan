# Mineurs de validation : plan d'implémentation

> **Pour les agents :** sous-skill requise : superpowers:executing-plans. Les étapes utilisent des cases à cocher (`- [ ]`).

**Objectif :** les trois corrections de la spec, chacune en TDD.

**Spec :** [docs/superpowers/specs/GH-53-spec.md](../specs/GH-53-spec.md)

## Contraintes globales
- Le conteneur ne change pas. `routing.py` importe déjà `validation`.
- Commits et PR : `(#53)`.

## Points à surveiller
1. **`integer`/`numeric` sur des entrées limites** (`"-0"`, `"1e3"`, `"1E-3"`, `".5"`, `"5."`, `"+1"`, `"１２"` en pleine chasse) : comportement fixé par les tests de la tâche 1.
2. **Annotation en chaîne** (`from __future__ import annotations`) sur le handler : la détection passe par `typing.get_type_hints` et ne doit pas planter si les annotations sont illisibles. Couvert par `test_form_request_default_with_string_annotations` (tâche 3).

---

### Task 1: ASCII digits for integer and numeric

**Fichiers :** modifier `src/flask_artisan/validation.py`, tests dans `tests/validation/test_rules.py`.

- [ ] **Étape 1 : écrire les tests.**
  - `test_integer_ascii_only` : `"123"` et `"-4"` passent ; `"١٢٣"`, `"１２"`, `" 12"` et `"+1"` échouent.
  - `test_numeric_ascii_only` : `"1.5"`, `"-0"`, `"1e3"`, `"1E-3"`, `"5"` et `2.5` passent ; `"١٢٣"`, `" 12 "`, `"1_000"`, `".5"`, `"5."`, `"nan"` et `"inf"` échouent.
- [ ] **Étape 2 : RED.** Lancer `.venv/bin/pytest tests/validation/test_rules.py -q -k ascii`. Attendu : ÉCHEC.
- [ ] **Étape 3 : implémenter** les regex de la spec, compilées une fois au niveau du module avec `re.ASCII`. Garder `math.isfinite(float(value))` pour `numeric` (`"1e999"`).
- [ ] **Étape 4 : GREEN.** Lancer `.venv/bin/pytest tests/validation -q`. Attendu : tout passe.
- [ ] **Étape 5 : commit** `fix: integer et numeric en chiffres ASCII seulement (#53)`.

### Task 2: regex compiled at construction

**Fichiers :** modifier `src/flask_artisan/validation.py` (`_check_params`), tests dans `tests/validation/test_validator.py`.

- [ ] **Étape 1 : écrire le test.** `test_invalid_regex_at_construction` : `Validator({}, {"code": "regex:[a-"})` lève `ValueError`, avec `regex` et `code`, sans aucune valeur à valider.
- [ ] **Étape 2 : RED.** Attendu : ÉCHEC (DID NOT RAISE).
- [ ] **Étape 3 : implémenter.** `re.compile(params[0])` dans `_check_params`, et `re.error` est converti en `ValueError`.
- [ ] **Étape 4 : GREEN.** Lancer `.venv/bin/pytest tests/validation -q`.
- [ ] **Étape 5 : commit** `fix: regex invalide détectée à la construction du Validator (#53)`.

### Task 3: FormRequest with a default value refused

**Fichiers :** modifier `src/flask_artisan/routing.py` (`flush`, avant `add_url_rule`), tests dans `tests/validation/test_form_request.py`. Modifier aussi `docs/validation.md` et `CHANGELOG.md`.

- [ ] **Étape 1 : écrire les tests.**
  - `test_form_request_default_refused` : une fonction `def store(request: StoreRequest = None)` passée à `Route.post`, puis `routed_app(...)`, lève `RouteError`, avec `request` et `valeur par défaut`. Même test avec une méthode de controller.
  - `test_form_request_default_with_string_annotations` : un handler dont l'annotation est une chaîne illisible (`"Inconnu"`) n'empêche pas l'enregistrement de la route.
- [ ] **Étape 2 : RED.** Attendu : ÉCHEC (DID NOT RAISE).
- [ ] **Étape 3 : implémenter.** Une fonction `_check_form_request_defaults(route)` :
  - elle passe par `typing.get_type_hints` (qui renvoie `{}` en cas d'erreur) ;
  - elle parcourt les paramètres d'`inspect.signature` ;
  - elle lève `RouteError` si l'annotation est une classe sous-classe de `FormRequest` et que le paramètre a une valeur par défaut.
- [ ] **Étape 4 : écrire la doc et le CHANGELOG** de la spec.
- [ ] **Étape 5 : vérification complète.** Lancer `.venv/bin/pytest -q`, `.venv/bin/ruff check .`, `.venv/bin/ruff format --check .` et `.venv/bin/mkdocs build --strict`. Attendu : tout passe.
- [ ] **Étape 6 : commit** `fix: FormRequest avec valeur par défaut refusée à l'enregistrement de la route (#53)`.

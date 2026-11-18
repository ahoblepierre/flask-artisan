# Contribuer à Flask-Artisan

## Installation

```bash
git clone https://github.com/ahoblepierre/flask-artisan
cd flask-artisan
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
```

## Tests et style

```bash
.venv/bin/pytest                                       # toute la suite
.venv/bin/pytest tests/test_container.py::test_bound   # un seul test
.venv/bin/ruff check . && .venv/bin/ruff format .      # la CI vérifie les deux
```

## Conventions

- Chaque changement part d'une **issue GitHub**.
- Branche : `feat/<n°>-slug` ou `fix/<n°>-slug`.
- Les commits et le titre de la PR contiennent `(#<n°>)` ; la PR contient `Closes #<n°>`.
- Les fonctionnalités importantes ont une spec (`docs/superpowers/specs/GH-<n°>-spec.md`)
  et un plan (`docs/superpowers/plans/GH-<n°>-plan.md`).
- Quand Laravel a un nom pour un concept, on le reprend.

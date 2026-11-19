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

## Publier une version

La publication passe par GitHub Actions ([publish.yml](.github/workflows/publish.yml)) avec le Trusted Publishing de PyPI : aucun token n'est stocké.

1. Sur une branche avec son issue : mettre à jour `__version__` dans `src/flask_artisan/__init__.py` et ajouter la section de la version dans `CHANGELOG.md`. Merger la PR.
2. Essai à blanc : onglet **Actions → Publish → Run workflow** sur `main`. Le package part sur [TestPyPI](https://test.pypi.org/project/flask-artisan/). Vérifier la page, puis l'installation :
   ```bash
   pip install -i https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ flask-artisan==<version>
   ```
3. Publication : `git tag v<version> && git push origin v<version>`. Le workflow vérifie que le tag correspond à la version, puis attend l'approbation dans l'environnement `pypi` (onglet Actions → **Review deployments**).

Un numéro de version publié ne peut jamais être republié, même après suppression : en cas d'erreur, publier la version suivante.

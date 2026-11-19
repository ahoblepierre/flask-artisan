# Publication PyPI 0.1.0 — plan d'implémentation

**But :** flask-artisan 0.1.0 publiable sur PyPI par GitHub Actions (Trusted Publishing).
**Spec :** [docs/superpowers/specs/GH-11-spec.md](../specs/GH-11-spec.md)

## Contraintes globales

- Aucun secret dans le dépôt ni dans les workflows (OIDC uniquement).
- Publication PyPI seulement sur un tag `v*` dont la version correspond au package.
- Commits : `… (#11)`.

### Task 1: version et métadonnées

- [ ] Tests (RED) dans `tests/test_package.py` : `flask_artisan.__version__ == "0.1.0"` et `importlib.metadata.version("flask-artisan") == flask_artisan.__version__` ; dans `tests/test_cli.py`, le `requirements.txt` généré contient `flask-artisan>=0.1,<0.2`.
- [ ] `__version__ = "0.1.0"` ; `pyproject.toml` : `dynamic = ["version"]` + `[tool.setuptools.dynamic] version = { attr = "flask_artisan.__version__" }`, description, classifiers, URLs, mots-clés ; squelette `requirements.txt`. Réinstaller (`pip install -e ".[dev]"`) puis GREEN.
- [ ] Commit `chore: version 0.1.0 et métadonnées du package (#11)`.

### Task 2: workflow de publication

- [ ] `.github/workflows/publish.yml` comme décrit dans la spec.
- [ ] Vérifier en local l'équivalent du job `build` : `python -m build`, `twine check --strict dist/*`, test de fumée du wheel dans un venv neuf.
- [ ] Commit `ci: publication PyPI et TestPyPI par Trusted Publishing (#11)`.

### Task 3: documentation

- [ ] `CHANGELOG.md` (0.1.0), README (installation PyPI, liens absolus), CONTRIBUTING (« Publier une version »), CLAUDE.md.
- [ ] Commit `docs: changelog 0.1.0, installation depuis PyPI, procédure de publication (#11)`.

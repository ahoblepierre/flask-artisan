# GH-11 — Publication de flask-artisan 0.1.0 sur PyPI

Ticket : https://github.com/ahoblepierre/flask-artisan/issues/11
Statut : approuvé (design court validé dans la conversation)

## Intention

Rendre le framework installable avec `pip install flask-artisan`, en 0.1.0, avec une publication reproductible à chaque version.

## Approches

- **A. GitHub Actions + Trusted Publishing** (retenue) : un tag `v*` publie sur PyPI après approbation (environnement `pypi`) ; un lancement manuel publie sur TestPyPI (environnement `testpypi`). Aucun token stocké.
- B. `twine upload` à la main avec un token : écartée (dépend d'une machine, secret à protéger).

## Décisions

- Version **0.1.0**, source unique : `flask_artisan.__version__`, lue par setuptools (`dynamic = ["version"]`).
- Métadonnées : description à jour (conteneur, routage, ORM, auth, CLI), classifiers Python 3.10–3.13, `Development Status :: 3 - Alpha`, URLs (dépôt, issues, changelog), mots-clés.
- `CHANGELOG.md` (format Keep a Changelog) avec la 0.1.0.
- README : installation par `pip install flask-artisan`, mention « pas encore publié » retirée, liens relatifs remplacés par des URL GitHub (page PyPI).
- Squelette : `requirements.txt` → `flask-artisan>=0.1,<0.2`.
- Workflow `.github/workflows/publish.yml` :
  - job `build` : `python -m build`, `twine check --strict`, sur un tag : version du package = tag sans `v` ; test de fumée (wheel installé dans un venv neuf, `flask-artisan new`, `flask route:list` dans le projet généré) ; artefact `dist`.
  - job `testpypi` (seulement `workflow_dispatch`) et job `pypi` (seulement tags `v*`), `permissions: id-token: write`, `pypa/gh-action-pypi-publish`.
- CONTRIBUTING : section « Publier une version ».

## Hors périmètre

Nouvelles fonctionnalités ; suppression des anciens projets PyPI de Pierre.

## Livraison

Tests : version cohérente (`__version__` = métadonnées installées = 0.1.0), `requirements.txt` du squelette. PR `feat/11-release` avec `Closes #11`, CI verte, puis essai TestPyPI, tag `v0.1.0`, publication.

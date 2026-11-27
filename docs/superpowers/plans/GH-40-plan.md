# Site de documentation : plan d'implémentation

> **Pour les agents :** sous-skill requise : superpowers:subagent-driven-development (recommandé) ou superpowers:executing-plans pour exécuter ce plan tâche par tâche. Les étapes utilisent des cases à cocher (`- [ ]`).

**Objectif :** découper le README en pages MkDocs Material dans `docs/` et publier le site sur GitHub Pages à chaque push sur `main`.

**Architecture :**
- `mkdocs.yml` à la racine lit `docs/` et en exclut `superpowers/`.
- Un workflow `docs.yml` lance `mkdocs build --strict` sur chaque PR et chaque push, puis déploie sur `main` avec `actions/deploy-pages`.
- Le README est réduit à une page d'accueil courte dont tous les liens sont absolus.

**Stack :** MkDocs ≥ 1.6, mkdocs-material 9.x, GitHub Actions (`upload-pages-artifact`, `deploy-pages`).

**Spec :** [docs/superpowers/specs/GH-40-spec.md](../specs/GH-40-spec.md)

## Contraintes globales

- Le texte est repris tel quel. On ne change que les niveaux de titre (`###` → `##` dans une page) et les liens.
- `exclude_docs: superpowers/` : aucune spec ni aucun plan dans `site/`.
- Extra `docs = ["mkdocs>=1.6,<2", "mkdocs-material>=9.5,<10"]`, absent de `dev`.
- `site_url: https://ahoblepierre.github.io/flask-artisan/`
- Liens du README : uniquement des URL absolues (`https://ahoblepierre.github.io/flask-artisan/...` ou `https://github.com/ahoblepierre/flask-artisan/blob/main/...`).
- Le lien « Cache, Tester » de la page Limitation de débit devient `cache.md#tester`.
- Commits et PR : `(#40)`. L'activation de Pages n'est **pas** une tâche du plan : elle se fait juste avant le merge (voir la spec).

## Points à surveiller

1. **Ancres des titres accentués :** l'ancre de « Événements » ou de « Façades » générée par MkDocs (`toc`, slugify par défaut) diffère de celle de GitHub. Tout lien vers une ancre doit passer `--strict`, et `validation.anchors: warn` le garantit.
2. **Doublons de titres dans une page :** « Tester » et « Générateur » apparaissent dans plusieurs pages. Une fois découpés, chacun devient `#tester` dans sa page, et le lien vers la mauvaise page passerait `--strict`. La tâche 2 vérifie à la main le seul lien de ce type (`cache.md#tester`).
3. **Blocs de code modifiés pendant le copier-coller :** le script de contrôle de la tâche 2 compare chaque bloc, octet pour octet.
4. **Rendu PyPI :** les liens relatifs du README court seraient cassés sur PyPI. La tâche 3 vérifie avec `twine check --strict` et un `grep`.
5. **Workflow de déploiement lancé sur une PR :** le job `deploy` doit porter `if: github.event_name == 'push'`. Sinon, une PR venant d'un fork échoue faute de permissions.

---

### Tâche 1 : socle MkDocs

**Fichiers :**
- Créer : `mkdocs.yml`, `docs/index.md` (provisoire : titre et accroche)
- Modifier : `pyproject.toml` (extra `docs`), `.gitignore` (`site/`)

**Interfaces :**
- Produit : `mkdocs.yml` avec un `nav` complet, qui pointe déjà vers les 15 pages de la spec. La tâche 2 crée ces pages.

- [ ] **Étape 1 : écrire `mkdocs.yml`** avec le `nav` complet de la spec et les réglages de la section « `mkdocs.yml` » de la spec :
  - `validation` : `nav.omitted_files`, `links.not_found`, `links.anchors` et `links.unrecognized_links` à `warn` ;
  - palettes Material avec bascule : `scheme: default` et `scheme: slate`, chacune avec son `toggle`.
- [ ] **Étape 2 : ajouter l'extra `docs`** et `site/` au `.gitignore`, puis lancer `.venv/bin/pip install -e ".[docs]"`.
- [ ] **Étape 3 : RED.** Lancer `.venv/bin/mkdocs build --strict`.
  Attendu : ÉCHEC, avec des avertissements sur les pages du `nav` qui n'existent pas encore (`conteneur.md`…), et aucune mention de `superpowers/`.
- [ ] **Étape 4 : commit**
  ```bash
  git add mkdocs.yml docs/index.md pyproject.toml .gitignore
  git commit -m "docs: socle MkDocs Material (#40)"
  ```

### Tâche 2 : découpage du README en pages

**Fichiers :**
- Créer : les 14 pages de la spec (`docs/conteneur.md` … `docs/console.md`).
- Modifier : `docs/index.md` (contenu complet : accroche, version, « Démarrer un projet », « Feuille de route »).
- Script jetable, hors du repo : `<scratchpad>/check_split.py`.

**Interfaces :**
- Consomme : le `nav` de la tâche 1 (noms de fichiers).
- Produit : les pages lues par la tâche 3, qui en tire les liens absolus du README court.

- [ ] **Étape 1 : écrire `check_split.py`.** Le script lit le README d'origine (`git show main:README.md`) et tous les `docs/*.md` hors de `superpowers/`. Il vérifie :
  - que chaque titre `##` ou `###` du README, hors « Contribuer » et « Licence », apparaît comme titre (`#` à `###`) dans une page ;
  - que chaque bloc de code délimité par trois accents graves (contenu exact) apparaît dans une page.

  Il affiche ce qui manque et sort avec le code 1 s'il manque quelque chose.
- [ ] **Étape 2 : RED.** Lancer `python3 <scratchpad>/check_split.py`.
  Attendu : code 1, presque tous les titres et blocs manquent.
- [ ] **Étape 3 : créer les pages.**
  - Chaque page commence par `# <titre de la section>`, et ses `###` deviennent des `##`.
  - Les liens `](#cache)` et `](#queues)` deviennent `](cache.md)` et `](queues.md)`.
  - `](#tester-1)` devient `](cache.md#tester)`.
  - `](#verrous)` et `](#quel-store-choisir)` gardent leur ancre si la cible est dans la même page.
  - Les liens CHANGELOG et CONTRIBUTING restent en URL absolue.
- [ ] **Étape 4 : GREEN.**
  - Lancer `python3 <scratchpad>/check_split.py`. Attendu : code 0.
  - Lancer `.venv/bin/mkdocs build --strict`. Attendu : `Documentation built`, sans aucun `WARNING`.
  - Lancer `find site -path '*superpowers*'`. Attendu : aucune sortie.
- [ ] **Étape 5 : vérifier à la main le point à surveiller n° 2.** Ouvrir `docs/limitation-de-debit.md` : le lien du « Tester » du cache vise `cache.md#tester`.
- [ ] **Étape 6 : commit** `docs: pages du site depuis le README (#40)`.

### Tâche 3 : README court et lien Documentation

**Fichiers :**
- Modifier : `README.md`, `pyproject.toml` (`Documentation = "https://ahoblepierre.github.io/flask-artisan/"` dans `[project.urls]`).

**Interfaces :**
- Consomme : les noms de pages de la tâche 2, pour construire les URL `https://ahoblepierre.github.io/flask-artisan/<page>/`, avec des URL de répertoire, comme le fait MkDocs par défaut.

- [ ] **Étape 1 : RED.** Lancer `grep -c '' README.md`.
  Attendu : 1176. Le README est encore long, et il n'y a pas de lien Documentation.
- [ ] **Étape 2 : réécrire `README.md`.** Il contient, dans cet ordre :
  - le titre, l'accroche et la ligne de version ;
  - les commandes de « Démarrer un projet » (sans l'arborescence) ;
  - un exemple de route de quelques lignes, repris de la page Routage ;
  - `**Documentation : https://ahoblepierre.github.io/flask-artisan/**` ;
  - la liste des sujets, une ligne par page avec son lien absolu ;
  - « Contribuer » et « Licence ».
- [ ] **Étape 3 : GREEN.**
  - Lancer `grep -nE '\]\((#|[^h])' README.md`. Attendu : aucune sortie, donc aucun lien relatif ni ancre locale.
  - Lancer `rm -rf dist && .venv/bin/python -m build && .venv/bin/twine check --strict dist/*`. Attendu : `PASSED` deux fois. Si `build` ou `twine` manque, l'installer dans le venv.
- [ ] **Étape 4 : commit** `docs: README court, lien vers le site (#40)`.

### Tâche 4 : workflow de déploiement et docs du repo

**Fichiers :**
- Créer : `.github/workflows/docs.yml`.
- Modifier : `CLAUDE.md`, `CONTRIBUTING.md`, `CHANGELOG.md`.

- [ ] **Étape 1 : écrire `docs.yml`.**
  - Déclencheurs : `on: push: branches: [main]` et `pull_request`.
  - Job `build` :
    - étapes : `checkout`, `setup-python` 3.12, `pip install -e ".[docs]"`, `mkdocs build --strict` ;
    - puis `actions/upload-pages-artifact@v3` (`path: site`), avec `if: github.event_name == 'push'`.
  - Job `deploy` :
    - `needs: build`, `if: github.event_name == 'push'` ;
    - `permissions: pages: write, id-token: write` ;
    - `environment: { name: github-pages, url: ${{ steps.deployment.outputs.page_url }} }` ;
    - `actions/deploy-pages@v4` (`id: deployment`).
  - `concurrency: { group: pages, cancel-in-progress: false }`.
- [ ] **Étape 2 : vérifier la syntaxe.** Lancer `.venv/bin/python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/docs.yml'))"`.
  Attendu : aucune erreur. PyYAML est installé avec MkDocs.
- [ ] **Étape 3 : mettre à jour les docs du repo.**
  - `CLAUDE.md` : la doc publique vit dans `docs/*.md` (site MkDocs, hors `docs/superpowers/`), et la commande `.venv/bin/mkdocs serve` s'ajoute aux commandes.
  - `CONTRIBUTING.md` : prévisualiser avec `pip install -e ".[docs]" && mkdocs serve`, et une fonctionnalité met à jour sa page.
  - `CHANGELOG.md`, sous `[Non publié]` : « Site de documentation (MkDocs Material, GitHub Pages), README raccourci (#40) ».
- [ ] **Étape 4 : vérification complète.** Lancer, dans cet ordre :
  - `.venv/bin/pytest -q` ;
  - `.venv/bin/ruff check .` ;
  - `.venv/bin/ruff format --check .` ;
  - `.venv/bin/mkdocs build --strict`.

  Attendu : tout passe.
- [ ] **Étape 5 : commit** `ci: déploiement du site sur GitHub Pages (#40)`.

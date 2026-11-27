# GH-40 : site de documentation

Ticket : https://github.com/ahoblepierre/flask-artisan/issues/40

## Pourquoi

Toute la documentation vit dans le README : 1 176 lignes, 17 sections. Pierre veut une documentation complète pour que les gens adoptent le framework. Une page unique de cette taille n'a ni recherche, ni navigation, ni lien stable vers une section, et PyPI (`readme = "README.md"`) affiche les 1 176 lignes.

## Objectifs

- Le contenu du README est découpé en pages Markdown dans `docs/`, qui deviennent la **seule source** de la documentation (approche A, choisie par Pierre).
- Le site est construit par **MkDocs** avec le thème **Material**. Il offre la recherche en français, une navigation par sections, le mode clair et sombre, et un bouton copier sur les blocs de code.
- Le site est publié sur GitHub Pages à l'adresse `https://ahoblepierre.github.io/flask-artisan/`. Chaque push sur `main` le redéploie.
- Le README devient court et donne le lien vers le site.
- `pyproject.toml` gagne `Documentation = "https://ahoblepierre.github.io/flask-artisan/"` dans `[project.urls]`.

## Non-objectifs

- Documentation versionnée par release (mike), traduction anglaise, référence d'API générée depuis les docstrings, nom de domaine, logo.
- Réécriture du contenu : on découpe et on corrige les liens, sans changer le texte.

## Anti-objectifs

- Les specs et plans internes (`docs/superpowers/`) ne doivent jamais apparaître sur le site.
- Pas de contenu en double entre le README et le site : le README ne garde que la présentation et le démarrage.
- Un lien interne cassé ne doit pas passer : le build échoue.

## Approches envisagées

- **A. Pages dans `docs/`, README court** : retenue par Pierre. Une seule copie du texte, et PyPI affiche une page lisible.
- **B. README source, découpé en pages par un script au build** : écartée. PyPI garde 1 176 lignes, les titres deviennent des contraintes, et il faut maintenir un script.
- Outil : MkDocs Material (choix du rédacteur). Il est en Python comme le projet et ne demande aucun code. Sphinx est plus lourd pour un contenu déjà en Markdown.

## Décisions

### Pages

Une page par section `##` du README. Le texte est repris tel quel ; les titres `###` restent des `##` dans leur page.

| Page | Section du README |
|------|-------------------|
| `docs/index.md` | titre, accroche, ligne de version, « Démarrer un projet », « Feuille de route » |
| `docs/conteneur.md` | Conteneur de services |
| `docs/service-providers.md` | Service providers |
| `docs/configuration.md` | Configuration |
| `docs/facades.md` | Façades |
| `docs/routage.md` | Routage (controllers, middlewares) |
| `docs/validation.md` | Validation |
| `docs/authentification.md` | Authentification |
| `docs/base-de-donnees.md` | Base de données |
| `docs/evenements.md` | Événements |
| `docs/mail.md` | Mail |
| `docs/queues.md` | Queues |
| `docs/cache.md` | Cache |
| `docs/limitation-de-debit.md` | Limitation de débit et verrous |
| `docs/console.md` | Console |

Navigation (`nav` de `mkdocs.yml`) :

- Accueil
- Les bases : Conteneur, Service providers, Configuration, Façades
- HTTP : Routage, Validation, Authentification, Limitation de débit et verrous
- Données : Base de données, Cache
- Tâches de fond : Événements, Mail, Queues
- Console

« Contribuer » et « Licence » restent dans le README seulement.

### Liens

- Les ancres du README qui pointent vers une autre section deviennent des liens relatifs vers la page cible (`cache.md`, `queues.md#…`). Celles qui restent dans la même page gardent leur ancre. Attention aux doublons numérotés du README : `#tester` est celui des Queues, `#tester-1` celui du Cache, `#tester-2` celui de la limitation de débit. Le lien « Cache, Tester » de la page Limitation de débit devient donc `cache.md#tester` (choix du rédacteur : `--strict` ne verrait pas un lien vers le mauvais « Tester » qui existe).
- Les liens vers des fichiers du repo (CHANGELOG, CONTRIBUTING) restent en URL GitHub absolues.

### `mkdocs.yml` (à la racine)

- `site_name: Flask-Artisan`, `site_url`, `repo_url: https://github.com/ahoblepierre/flask-artisan`.
- `exclude_docs: superpowers/` (les specs et plans restent dans `docs/` mais hors du site).
- `theme`: `material`, `language: fr`, palettes clair et sombre avec bascule, `features: [navigation.sections, content.code.copy, search.highlight]`.
- `plugins: [search]` avec `lang: fr`.
- `markdown_extensions`: `admonition`, `pymdownx.highlight`, `pymdownx.superfences`, `toc` avec `permalink: true` (ancres visibles et copiables).
- `validation` : liens absents, ancres inconnues et liens non reconnus en `warn`, pour que `--strict` les transforme en erreurs.

### Dépendances

Extra `docs = ["mkdocs>=1.6,<2", "mkdocs-material>=9.5,<10"]` (mkdocs 1.6 pour `validation.anchors`, choix du rédacteur) dans `pyproject.toml`. Il n'entre ni dans `dev` ni dans le package installé.

### Workflow `.github/workflows/docs.yml`

- Déclencheurs : `push` sur `main` et `pull_request`.
- Job `build` : `pip install -e ".[docs]"`, puis `mkdocs build --strict`. Sur une PR, le job s'arrête là : un lien cassé fait échouer la PR.
- Sur `main` seulement : `actions/upload-pages-artifact` (dossier `site/`), puis un job `deploy` avec `actions/deploy-pages`, l'environnement `github-pages` et les permissions `pages: write` et `id-token: write`.
- `site/` est ajouté au `.gitignore`.

### Activation de GitHub Pages

C'est un réglage du repo (source : « GitHub Actions »). Pierre a donné son accord (option b) : on l'active **juste avant le merge**, une fois la CI de la PR verte, avec `gh api -X POST repos/ahoblepierre/flask-artisan/pages -f build_type=workflow`. Le push du merge déploie alors directement le site, et `main` reste vert. Activer Pages sans site publié n'expose rien. Si la PR est abandonnée, on désactive Pages avec `gh api -X DELETE repos/ahoblepierre/flask-artisan/pages`.

### README court

Le README garde le titre, l'accroche, la ligne de version, les commandes de « Démarrer un projet » (sans l'arborescence), un exemple de route de quelques lignes, un lien bien visible vers le site, la liste des sujets couverts (une ligne chacun, avec un lien absolu vers la page), puis « Contribuer » et « Licence ». Tous les liens sont absolus, puisque PyPI ne résout pas les liens relatifs.

### Fichiers à mettre à jour

- `CLAUDE.md` : la documentation vit dans `docs/*.md`, avec la commande `mkdocs serve`.
- `CONTRIBUTING.md` : comment prévisualiser la doc (`pip install -e ".[docs]" && mkdocs serve`), et la règle qu'une fonctionnalité met à jour sa page.
- `CHANGELOG.md` : une entrée sous `[Non publié]`.

## Vérification

- `mkdocs build --strict` passe en local et en CI.
- Une vérification compare les deux versions : chaque titre `##` ou `###` du README d'origine se retrouve dans une page, et chaque bloc de code du README d'origine se retrouve, identique, dans une page. C'est un script jetable, lancé une fois et cité dans la PR, pas un test pytest.
- `site/` ne contient aucun fichier issu de `superpowers/`.
- `python -m build` puis `twine check --strict` sur le README court.
- La suite pytest et ruff restent au vert.

## Laissé au rédacteur du plan

- Le texte exact de l'exemple du README court.
- Les couleurs du thème (on garde les défauts de Material si rien ne s'impose).

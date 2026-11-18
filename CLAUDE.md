# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Le projet

Flask-Artisan : un framework open source qui apporte les conventions de Laravel à Flask. **Flask reste le moteur** (décision actée) : on ajoute une couche (conteneur, service providers, façades, routage à la Laravel, ORM façon Eloquent sur SQLAlchemy, auth, CLI « artisan ») sans casser la compatibilité avec l'écosystème Flask. Le différenciateur face à Masonite est justement d'être du Flask.

Le code actuel est une ébauche à refondre, pas une base à préserver.

## Feuille de route (v0.1 publique = chantiers 1 à 5)

Chaque chantier a sa propre spec et son propre plan, dans cet ordre :

1. **Socle** : package pip `flask-artisan` (framework) séparé d'un squelette de projet généré par `artisan new <projet>` ; `Application` qui enveloppe Flask, conteneur, service providers, config `config/*.py` + `.env`, façades.
2. **Routage & middlewares** : `routes/web.py` / `routes/api.py`, controllers en classes, groupes/préfixes, middlewares nommés via un kernel.
3. **ORM** : modèles façon Eloquent sur SQLAlchemy 2 (timestamps, soft delete, relations), migrations Alembic via le CLI.
4. **Auth** : façade `Auth`, guards session et token, hash automatique, middleware `auth`.
5. **CLI** : `make:*`, `serve`, `migrate`, `route:list`.

Après v0.1 : validation (Form Requests), helpers, events, mail, cache, queues.

## Tickets, branches, specs

Ce repo est public et n'utilise **pas** le Jira de l'entreprise (remplace la règle Jira globale). Les tickets sont des **GitHub Issues** sur `ahoblepierre/flask-artisan` (créer avec `gh issue create`).

- Branche : `feat/<n°>-slug` ou `fix/<n°>-slug`
- Spec / plan : `docs/superpowers/specs/GH-<n°>-spec.md`, `docs/superpowers/plans/GH-<n°>-plan.md`
- Commit et titre de PR contiennent `(#<n°>)` ; la PR ferme l'issue (`Closes #<n°>`).

## Commandes (état actuel)

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
flask run                        # app.py -> app.create_app()
flask db migrate -m "..." && flask db upgrade
flask make:controller Nom | make:model Nom | make:middleware Nom | make:cm Nom
```

Aucun test ni linter n'existe encore.

## Architecture actuelle (à refondre)

- `app.py` charge `.env` puis appelle `create_app()` ([app/__init__.py](app/__init__.py)), qui initialise JWT, CSRF, Talisman, la config (`FLASK_ENV` → `app/config/*`), SQLAlchemy/Migrate/LoginManager, lance `db.create_all()`, puis enregistre blueprints et commandes.
- Les extensions sont des singletons dans [app/extensions.py](app/extensions.py).
- Les controllers sont des blueprints enregistrés à la main dans [app/controllers/__init__.py](app/controllers/__init__.py) ; les commandes `make:*` ([app/commands.py](app/commands.py)) réécrivent ce fichier par manipulation de texte.
- Les modèles doivent être importés dans [app/models/__init__.py](app/models/__init__.py) pour être créés.

## Pièges connus de l'ébauche

- Mots de passe stockés en clair alors que `Auth.attempt` utilise `check_password_hash` : la connexion ne peut pas fonctionner.
- Les routes `show`/`destroy` (et le template `make:controller`) attendent un `id` absent de l'URL → 500.
- `make:cm` génère `Nom_bp` mais importe `nom_bp` → l'app ne démarre plus.
- L'entry point `lara-flask=app.commands:cli` de `setup.py` pointe vers une fonction inexistante.
- `build/`, `dist/`, `*.egg-info`, `__pycache__`, `.DS_Store` et `instance/dev.db` sont commités par erreur.

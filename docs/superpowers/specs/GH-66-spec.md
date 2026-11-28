# GH-66 : `age_flash` ne doit pas effacer une lecture de session antérieure (`Vary: Cookie`)

Ticket : https://github.com/ahoblepierre/flask-artisan/issues/66

## Pourquoi

Audit de sécurité du 27/11/2026, piste classée « à valider ». Le défaut est dans le code ; son exploitation dépend du déploiement.

`age_flash` (`src/flask_artisan/views.py`) est le premier `before_request` de l'application. Quand rien n'a été flashé, il met `session.accessed = False`, pour qu'une réponse qui ne lit pas la session n'ait pas `Vary: Cookie` (optimisation introduite dans #19). Il suppose que rien n'a lu la session avant lui.

Or Flask exécute avant les `before_request` les gestionnaires `request_started`, les convertisseurs d'URL et les `url_value_preprocessor`. Si du code projet y lit la session et que le handler ne la relit pas, la réponse dépend de la session mais sort sans `Vary: Cookie`. Flask seul aurait posé cet en-tête. Derrière un cache partagé qui met ces GET en cache, la réponse d'un utilisateur pourrait alors être servie à un autre.

## Objectif

`age_flash` ne change l'état `accessed` que pour annuler sa propre lecture. Une lecture antérieure garde `Vary: Cookie`.

## Design retenu (option A, choisie par Pierre)

- Avant de toucher la session, `age_flash` lit le drapeau `accessed` de l'objet session sous-jacent, sans passer par le proxy `flask.session`. Depuis Flask 3.1, la propriété `RequestContext.session` met elle-même `accessed = True` à chaque lecture.
  - Flask 3.1 : l'objet est dans `RequestContext._session` (attribut privé).
  - Flask 3.0 : `RequestContext.session` est un simple attribut, dont la lecture ne marque rien.
- Quand rien n'a été flashé, `age_flash` remet `accessed` à la valeur lue au départ, au lieu de `False`.
- Si l'attribut est introuvable (Flask a changé ses internes), `age_flash` ne remet rien à zéro. Le seul effet est un `Vary: Cookie` en trop, ce qui reste sûr, et le test existant `test_no_vary_cookie_when_nothing_flashed` le signalerait en CI.
- Un commentaire explique la dépendance à l'attribut privé.

## Approche écartée

- **B. Supprimer l'optimisation** (ne plus toucher `accessed`) : c'est le plus simple, mais toutes les réponses, API comprise, recevraient `Vary: Cookie`, ce que #19 voulait éviter.

## Tests

- Un `url_value_preprocessor` qui lit `session["uid"]`, avec un handler qui ne relit pas la session : la réponse porte `Vary: Cookie`.
- Une requête qui ne lit pas la session n'a toujours pas `Vary: Cookie` (test existant, inchangé).
- Les données flashées vieillissent toujours (tests existants de `tests/test_views.py` et `tests/test_html_errors.py`, inchangés).

## Livraison

- `src/flask_artisan/views.py` (`age_flash`).
- CHANGELOG : une entrée « Sécurité » dans la section non publiée.
- La doc n'est pas touchée : le comportement documenté ne change pas.

## Hors périmètre

- `Vary: Accept` sur `expects_json` et `Cache-Control: private` sur les réponses authentifiées (notes de durcissement de l'audit).
- L'issue #64.

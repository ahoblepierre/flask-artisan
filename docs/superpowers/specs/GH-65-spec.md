# GH-65 : ne pas flasher le jeton de réinitialisation (`DONT_FLASH`)

Ticket : https://github.com/ahoblepierre/flask-artisan/issues/65

## Pourquoi

Audit de sécurité du 27/11/2026, note de durcissement.

Quand un formulaire HTML échoue en validation, `_redirect_back` (`src/flask_artisan/routing.py`) recopie la saisie dans la session (`_flash_old`) pour que `old()` la réaffiche. `DONT_FLASH` exclut `password`, `password_confirmation`, `current_password` et `_token`, mais pas `token`.

Le formulaire « nouveau mot de passe » du kit `auth:install` envoie justement le jeton de réinitialisation dans un champ `token`. Après un échec (mot de passe trop court, confirmation différente, jeton invalide), ce jeton en clair est donc écrit dans le cookie de session Flask, qui est signé mais pas chiffré. Laravel peut se contenter de son `dontFlash` parce que son cookie de session est chiffré.

## Objectif

Le jeton de réinitialisation n'est jamais copié dans la session par le flash de validation.

## Design retenu

- `DONT_FLASH` devient `{"password", "password_confirmation", "current_password", "_token", "token"}`.
- Rien d'autre ne change dans le kit. La vue `auth/reset_password.html` reçoit `token` depuis l'URL (`NewPasswordController.create`) et n'utilise jamais `old('token')`. Après un échec, la redirection revient sur `/reset-password/<token>`, qui réaffiche le jeton.

## Approches écartées

- **Un attribut `dont_flash` par `FormRequest`.** Personne ne l'a demandé, et la liste globale couvre le seul cas connu. On l'ajoutera quand un projet en aura besoin (choix de Pierre).

## Tests

- Après un échec de validation d'un formulaire HTML qui contient `token`, `email` et `password`, `_flash_old` contient `email`, mais ni `token` ni `password`.
- Les tests existants du flash restent inchangés.

## Livraison

- `src/flask_artisan/routing.py` : la constante.
- `docs/vues.md` : la liste des champs jamais gardés cite aussi `token` (et `_token`).
- CHANGELOG : une entrée « Sécurité » dans la section non publiée.

## Hors périmètre

Les issues #64 et #66.

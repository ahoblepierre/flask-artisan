# GH-63 : URLs signées, contournement de l'expiration par `%3F` dans le chemin

Ticket : https://github.com/ahoblepierre/flask-artisan/issues/63

## Pourquoi

L'audit de sécurité du 27/11/2026 a confirmé un défaut (sévérité faible) dans les URLs signées. Le message signé vaut `<chemin décodé>?<requête>` (`src/flask_artisan/signing.py`, `_canonical` à la signature, `has_valid_signature` à la vérification). Comme `%3F` se décode en `?`, deux URL différentes produisent le même message :

- l'URL signée : `/files/report?expires=1060&signature=S` ;
- l'URL réécrite : `/files/report%3Fexpires=1060?signature=S`.

La forme réécrite n'a plus de paramètre `expires`, donc un lien expiré redevient valide sans limite de temps. Elle permet aussi de retirer les paramètres signés de la requête.

Pour que l'attaque marche, il faut :
- un lien signé déjà émis ;
- une route dont le dernier convertisseur accepte `?` et `=` ;
- un handler qui tolère la valeur suffixée.

La vérification d'e-mail du kit n'est pas touchée.

## Objectif

Un message signé correspond à un seul couple (chemin, requête). Un `expires` signé est toujours présent au moment de la vérification.

## Approche retenue (option A, choisie par Pierre)

Le chemin décodé ne peut pas contenir `?`. Le premier `?` du message sépare alors sans ambiguïté le chemin de la requête.

- **Vérification :** `has_valid_signature` renvoie `False` (donc 403) si `req.path` contient `?`, avant même de calculer le HMAC.
- **Signature :** `signed_url` lève `ValueError` si le chemin décodé contient `?`, c'est-à-dire si une valeur de route en contient un. C'est une erreur du développeur, signalée tout de suite au lieu de produire un lien que la vérification refuserait. Le message d'erreur nomme l'endpoint.
- **Le message signé ne change pas :** les liens déjà envoyés (vérification d'e-mail, téléchargements temporaires) restent valides après la mise à jour.

## Approches écartées

- **B. Préfixer la longueur du chemin dans le message.** Toutes les valeurs restent permises, mais toutes les signatures changent : chaque lien déjà envoyé devient invalide à la mise à jour.
- **Signer le chemin encodé.** Le chemin décodé a été choisi dans #59 pour qu'un proxy qui ré-encode ne casse pas le lien.

## Tests

- Le lien réécrit en `%3F` est refusé (403), avant et après l'expiration du lien d'origine.
- `signed_url` lève `ValueError` pour une valeur de route contenant `?`, en relatif comme avec `_external=True`.
- Les valeurs encodées déjà acceptées (`a b`, `é`, `x@y`), le préfixe `SCRIPT_NAME` et l'expiration continuent de fonctionner : les tests existants passent sans modification.

## Livraison

- Correction dans `src/flask_artisan/signing.py`.
- Une ligne dans `docs/authentification.md` (section des URLs signées) : une valeur de route contenant `?` ne peut pas être signée.
- Entrée « Sécurité » dans le CHANGELOG, section non publiée.

## Hors périmètre

- Une clé dérivée par usage pour les URL signées (note de durcissement de l'audit).
- Les issues #64, #65 et #66.

## Laissé au développeur

- Le libellé exact du message de `ValueError`.
- L'emplacement du contrôle : dans `_canonical` ou dans `signed_url`.

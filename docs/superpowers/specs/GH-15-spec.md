# GH-15 — Validation : `FormRequest`, `Validator` et règles façon Laravel (API JSON)

Ticket : https://github.com/ahoblepierre/flask-artisan/issues/15
Statut : en attente d'approbation (relecture constructeur faite)

## Intention

Premier chantier après la v0.1. Aujourd'hui, chaque controller vérifie ses entrées à la main (`AuthController.login` teste `isinstance(data, dict)` puis lit des `data.get(...)`). Un développeur Laravel s'attend à écrire :

```python
class StorePostRequest(FormRequest):
    def rules(self):
        return {"title": "required|string|max:255", "email": "required|email|unique:users,email"}


class PostController:
    def store(self, request: StorePostRequest):
        return Post.create(**request.validated()), 201
```

et à ne jamais entrer dans `store` si les données sont mauvaises : le framework répond seul 422 avec les erreurs par champ.

## Objectifs

1. Une sous-classe de `FormRequest` annotée dans un paramètre de controller est construite, autorisée puis validée **avant** l'appel du controller.
2. Échec de validation → réponse `422` JSON au format Laravel. `authorize()` faux → `403` JSON.
3. Le même moteur est utilisable seul : `Validator(data, rules, messages)` et `validate(data, rules, messages)`.
4. Règles en chaîne façon Laravel, dont `unique` et `exists` sur la base du projet.
5. `flask make:request Nom` génère une `FormRequest`.

## Non-objectifs (hors périmètre)

- Formulaires HTML : redirection vers la page précédente, erreurs en session, `old()`, helpers Jinja. Une requête non JSON reçoit aussi le 422 JSON.
- Champs imbriqués et jokers (`items.*.name`, `user.email`).
- Fichiers (`file`, `image`, `mimes`).
- Conversion des valeurs : `validated()` rend les valeurs telles que reçues (`"42"` reste une chaîne), comme Laravel.
- Règles objets ou closures, `after()` / validation conditionnelle avancée (`required_if`, `required_unless`…), `attributes()` pour renommer les champs, traduction des messages.
- Arrêt au premier échec (`bail`).

## Anti-objectifs

- Appeler le controller avec des données non validées.
- Rendre dans `validated()` un champ sans règle (protection contre l'assignation de masse : `Post.create(**request.validated())` doit être sûr).
- Masquer une erreur du développeur (règle inconnue, paramètre manquant, table inconnue) en erreur de validation : c'est une exception Python, donc un 500.
- Ajouter une dépendance.

## Approches considérées

- **A. `FormRequest` injectée et validée par le conteneur, plus un `Validator` autonome** (retenue). Familier pour un dev Laravel ; l'injection par annotation existe déjà (`Container.call`).
- **B. Helper seul dans le controller** (`validate(request.get_json(), {...})`). Plus petit, mais règles mêlées aux controllers. Fourni de toute façon par A (même moteur).
- **C. Modèles pydantic.** Dépendance lourde, ne ressemble pas à Laravel. Écartée.

## Décisions

### Données validées

- Source : les paramètres de l'URL (`request.args`) fusionnés avec le corps ; le corps gagne en cas de conflit.
- Corps : le JSON s'il est un objet ; sinon le formulaire (`request.form`) ; un JSON qui n'est pas un objet (liste, nombre, invalide) compte comme corps vide.
- Pour `args` et `form`, une clé répétée garde sa première valeur (pas de listes en v1).

### `FormRequest`

- Module : `flask_artisan.validation` (exporte `FormRequest`, `Validator`, `ValidationError`, `validate`).
- Méthodes à surcharger : `rules() -> dict` (obligatoire), `authorize() -> bool` (défaut `True`), `messages() -> dict` (défaut `{}`).
- API : `validated() -> dict`, `all() -> dict` (toutes les données sources), `input(key, default=None)`.
- Construite par le conteneur quand un paramètre de controller est annoté par sa classe. À la construction : `authorize()` puis validation. `authorize()` faux → `AuthorizationError` (403, `{"message": "This action is unauthorized."}`).
- Utilisable dans `rules()` / `authorize()` : `Auth.user()`, les paramètres de route (`request.view_args`). Pour une mise à jour, le développeur écrit lui-même `f"unique:users,email,{request.view_args['id']}"` (comme en PHP) : le framework ne remplace aucun `{…}` (choix du constructeur de la spec).
- Hors requête Flask (construction directe dans un script) : erreur claire, pas de validation silencieuse sur des données vides.

### `Validator` et `validate`

- `Validator(data: Mapping, rules: dict, messages: dict | None = None)` ; méthodes `fails()`, `passes()`, `errors() -> dict[str, list[str]]`, `validated() -> dict` (lève `ValidationError` si échec).
- `validate(data, rules, messages=None) -> dict` : raccourci qui lève `ValidationError` ou rend `validated()`.
- Une règle s'écrit en chaîne `"required|max:255"` ou en liste `["required", "regex:^a|b$"]` (la liste permet un `|` dans un paramètre).
- Paramètres séparés par des virgules après `:`.

### Erreur de validation

- `ValidationError` est une `HTTPException` de Werkzeug (code 422) qui produit elle-même sa réponse JSON : aucun gestionnaire d'erreur à enregistrer, elle traverse les middlewares comme un `abort`. Elle expose `.errors`.
- Corps : `{"message": <premier message>[ + " (and N more error(s))"], "errors": {champ: [messages…]}}`. Exemple : `"The email field is required. (and 2 more errors)"`, `"(and 1 more error)"` au singulier (format Laravel).
- Ordre : champs dans l'ordre de `rules()`, messages dans l'ordre des règles.

### Sémantique des règles

- Un champ est **absent** s'il n'est pas dans les données. Il est **vide** s'il vaut `None`, une chaîne vide ou ne contenant que des espaces, ou une liste/dict vide.
- Champ absent, ou chaîne vide / liste / dict vide : seules les règles de présence s'appliquent (`required`, `required_with`) ; les autres sont ignorées.
- Valeur `None` présente : avec `nullable`, toutes les règles hors présence sont ignorées. **Sans `nullable`, chacune d'elles échoue** (type, format, taille, `in`, `same`, `confirmed`, `regex`, `unique`, `exists`…), comme Laravel où `null` échoue presque tout. Ainsi `{"email": None}` n'atteint jamais `validated()` avec `email|unique:users,email` (choix du constructeur de la spec).
- `sometimes` : si le champ est absent, aucune règle ne s'applique (y compris `required`).
- `validated()` : les champs qui ont une règle **et** sont présents dans les données ; jamais les champs `*_confirmation` sans règle propre.
- Taille (`min`, `max`, `between`) : valeur numérique si le champ a `numeric` ou `integer`, nombre d'éléments pour une liste ou un dict, longueur sinon.

| Règle | Réussit si |
|---|---|
| `required` | présent et non vide |
| `required_with:a,b` | `required` dès qu'un des champs cités est présent et non vide |
| `nullable` | (marqueur) `None` accepté |
| `sometimes` | (marqueur) voir plus haut |
| `string` | `str` |
| `integer` | `int` (pas `bool`) ou chaîne d'entier (`"42"`, `"-3"`) |
| `numeric` | `int`/`float` (pas `bool`) ou chaîne convertible par `float`, hors `nan`/`inf` |
| `boolean` | `True`, `False`, `0`, `1`, `"0"`, `"1"`, `"true"`, `"false"` |
| `array` | `list` ou `dict` |
| `email` | chaîne avec un seul `@`, partie locale et domaine non vides, un point dans le domaine, sans espace |
| `url` | `http`/`https` avec un hôte (`urllib.parse`) |
| `date` | chaîne lue par `datetime.fromisoformat` |
| `min:n` / `max:n` / `between:a,b` | taille ≥ n / ≤ n / dans [a, b] |
| `in:a,b` / `not_in:a,b` | `str(valeur)` dans / hors de la liste |
| `confirmed` | `<champ>_confirmation` présent et égal |
| `same:autre` | égal au champ `autre` |
| `regex:motif` | `re.search` trouve le motif dans la chaîne |
| `unique:table,colonne[,id_ignoré[,colonne_id]]` | aucune ligne de `table` avec `colonne = valeur` (sauf `colonne_id = id_ignoré`, `colonne_id` par défaut `id`) |
| `exists:table,colonne` | au moins une ligne de `table` avec `colonne = valeur` |

- `colonne` omise dans `unique`/`exists` : le nom du champ.
- `unique`/`exists` passent par la session ORM du `DatabaseManager` (`DB.session`, donc la même transaction que le reste de la requête : les lignes non validées sont vues), requête Core paramétrée ; table et colonne sont des identifiants validés (`[A-Za-z_][A-Za-z0-9_]*`) puis cités. Les lignes soft-deleted comptent (comme Laravel).
- Règle inconnue ou paramètre manquant (`max` sans nombre) → `ValueError` qui nomme la règle et le champ.

### Messages

- Par défaut en anglais, ceux de Laravel, avec `:attribute` = nom du champ où `_` devient une espace (`first_name` → `first name`). Exemples : `The :attribute field is required.`, `The :attribute field must be a valid email address.`, `The :attribute field must not be greater than :max characters.` (variantes `numeric`/`array`/`string` pour les règles de taille, comme Laravel), `The :attribute has already been taken.` (`unique`), `The selected :attribute is invalid.` (`exists`, `in`).
- `messages()` / argument `messages` : clés `"champ.règle"` (prioritaire) ou `"règle"` ; mêmes remplacements (`:attribute`, `:min`, `:max`, `:other`, `:values`).

### Générateur

- `flask make:request StorePostRequest` → `app/http/requests/store_post_request.py`, sous-dossiers permis (comme `make:controller`), `rules()` qui rend un dict vide d'exemple commenté. Mêmes règles que les autres générateurs (`--force`, noms invalides, ruff).

### Squelette

- `app/http/requests/__init__.py` et `app/http/requests/login_request.py` (`email: required|string|email`, `password: required|string`, `device_name: sometimes|string|max:255`).
- `AuthController.login(self, request: LoginRequest)` lit `request.validated()` ; le garde `isinstance(data, dict)` disparaît.
- Changement visible : un login sans `email` ou avec `password` non chaîne reçoit désormais **422** (avant : 401). Identifiants faux → toujours 401.

### Documentation

- README : section « Validation » (FormRequest, règles disponibles, format d'erreur, `validate()`), `make:request` dans « Console », feuille de route : validation cochée.
- CLAUDE.md : sous-paquet ou module validation, `ValidationError` qui est une `HTTPException`, validation déclenchée à la construction par le conteneur.
- CHANGELOG : section « Non publié ».

## Pièges connus

- **Construction par le conteneur.** `Container.make` autowire le `__init__` : la validation doit se déclencher à la construction sans paramètre obligatoire, ou via un crochet du conteneur. Une `FormRequest` liée explicitement (`app.bind`) doit aussi être validée.
- **Paramètre nommé `request`.** Il masque `flask.request` dans la méthode, comme `$request` dans Laravel : les exemples l'acceptent.
- **`bool` est un `int`** en Python : `integer`/`numeric` doivent l'exclure, `boolean` doit l'accepter.
- **Tables de test.** Les modèles et `Model.metadata` sont globaux au processus : préfixer les modèles de test (`VUser`…).
- **Middlewares.** `ValidationError` naît dans la vue, après les middlewares : un middleware qui inspecte la réponse voit le 422.

## Laissé au constructeur

- Module unique `validation.py` ou sous-paquet ; découpage règles / messages.
- Mécanisme exact du déclenchement à la construction (`__init__` ou crochet de résolution dans le conteneur), dans le respect des pièges ci-dessus.
- Expression exacte des messages non cités, en reprenant ceux de Laravel.

## Livraison

- Tests pytest : chaque règle (succès, échec, champ absent, vide, `None` avec et sans `nullable`), `sometimes`, `required_with`, taille selon le type, `confirmed`, règle en liste avec `|`, règle inconnue, messages par défaut et personnalisés, format `message` (singulier/pluriel), `validated()` limité aux champs avec règle ; `unique` (avec ignore) et `exists` sur SQLite ; `FormRequest` injectée (succès, 422, 403, controller non appelé, paramètres de route dans `rules()`), source JSON / form / query, JSON non objet ; `make:request`.
- Test de bout en bout du projet généré : `/api/login` sans champ → 422 au format attendu, bons identifiants → token.
- README, CLAUDE.md, CHANGELOG à jour.
- PR `feat/15-validation`, titre avec `(#15)`, corps avec `Closes #15`. CI verte sur 3.10 à 3.13.

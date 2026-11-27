# Validation

Une `FormRequest` déclare ses règles ; annotée dans un controller, elle est construite, autorisée puis validée **avant** l'appel de la méthode :

```python
# app/http/requests/store_post_request.py   (flask make:request StorePostRequest)
from flask_artisan.validation import FormRequest


class StorePostRequest(FormRequest):
    def authorize(self):          # False → 403 {"message": "This action is unauthorized."}
        return True

    def rules(self):
        return {
            "title": "required|string|max:255",
            "email": "required|email|unique:users,email",
            "tags": ["sometimes", "array"],          # forme liste : utile si un paramètre contient « | »
        }

    def messages(self):           # optionnel : "champ.règle" ou "règle"
        return {"email.unique": "Cet email est déjà utilisé."}


class PostController:
    def store(self, request: StorePostRequest):
        return Post.create(**request.validated()), 201   # seulement les champs avec une règle
```

Le paramètre annoté par la `FormRequest` ne doit pas avoir de valeur par défaut (`request: StorePostRequest = None`) : le conteneur prendrait la valeur par défaut et la validation serait sautée, donc la route est refusée (`RouteError`) à l'enregistrement. Seule exception : une FormRequest liée explicitement dans le conteneur (`app.bind(...)`) et annotée par sa classe seule (pas `| None`), que le conteneur construit avant le défaut.

Données lues : paramètres de l'URL fusionnés avec le corps (JSON objet, sinon formulaire). En cas d'échec, réponse **422** :

```json
{"message": "The title field is required. (and 1 more error)",
 "errors": {"title": ["The title field is required."], "email": ["The email field must be a valid email address."]}}
```

Sur une requête de formulaire HTML (hors routes d'API), l'échec redirige vers la page précédente avec `errors` et `old()` : voir [Vues et formulaires](vues.md#erreurs-de-validation-json-ou-redirection).

Hors controller : `validate(data, rules)` rend les données validées ou lève `ValidationError` (qui devient la même réponse 422 si elle sort d'une vue) ; `Validator(data, rules).fails()` / `.errors()` pour décider soi-même.

| Règles | |
|---|---|
| Présence | `required`, `required_with:a,b`, `nullable`, `sometimes` |
| Types | `string`, `integer`, `numeric`, `boolean`, `array`, `email`, `url`, `date` |
| Fichiers | `file`, `image`, `mimes:jpg,pdf` : voir [Stockage de fichiers](stockage.md#enregistrer-un-fichier-envoye) |
| Taille | `min:n`, `max:n`, `between:a,b` (valeur si `numeric`/`integer`, éléments pour une liste, kilo-octets pour un fichier, longueur sinon) |
| Valeurs | `in:a,b`, `not_in:a,b`, `confirmed`, `same:champ`, `regex:motif` |
| Base | `unique:table[,colonne[,id_ignoré[,colonne_id]]]`, `exists:table[,colonne]` |

Une `FormRequest` lit aussi les fichiers envoyés (`request.files`, le premier par champ) ; un champ fichier sans fichier choisi compte comme vide.

Un champ absent ou vide n'est soumis qu'aux règles de présence ; `None` échoue toutes les autres règles sauf avec `nullable`. Pour ignorer la ligne courante lors d'une mise à jour : `f"unique:users,email,{request.view_args['id']}"`. Les valeurs ne sont pas converties (`"42"` reste une chaîne). `integer` et `numeric` n'acceptent que des chiffres ASCII, sans espaces ni `_` (`"١٢٣"`, `" 12 "` et `"1_000"` sont refusés) ; `numeric` accepte `-1.5` et `1e3`, pas `.5` ni `5.`. Un motif `regex` invalide lève `ValueError` dès la construction du `Validator`.

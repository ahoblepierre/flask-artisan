# Vues et formulaires

Les pages HTML sont des templates Jinja dans `resources/views/`. Un controller les rend avec `render_template` de Flask. Le framework ajoute ce qu'il faut pour les formulaires :

- le retour sur le formulaire après une erreur de validation, avec les erreurs et les saisies ;
- la protection CSRF ;
- les messages flash.

## Templates et layout

L'héritage de Jinja joue le rôle des layouts de Blade :

```html
{# resources/views/layouts/app.html #}
<!doctype html>
<html lang="fr">
<body>
    {% for message in get_flashed_messages() %}<p>{{ message }}</p>{% endfor %}
    {% block content %}{% endblock %}
</body>
</html>
```

```html
{# resources/views/posts/create.html #}
{% extends "layouts/app.html" %}

{% block content %}
<form method="post" action="{{ url_for('posts.store') }}">
    {{ csrf_field() }}
    <input name="title" value="{{ old('title') }}">
    {% if errors.has('title') %}<p>{{ errors.first('title') }}</p>{% endif %}
    <button>Publier</button>
</form>
{% endblock %}
```

```python
from flask import flash, redirect, render_template, url_for


class PostController:
    def create(self):
        return render_template("posts/create.html")

    def store(self, request: StorePostRequest):
        Post.create(**request.validated())
        flash("Article publié.")
        return redirect(url_for("posts.index"))
```

Les templates sont cherchés dans `resources/views/`, puis dans `templates/` (le dossier de Flask).

## Erreurs de validation : JSON ou redirection

Quand une [validation](validation.md) échoue (`FormRequest`, `validate()` ou une `ValidationError` levée dans le controller) :

| Requête | Réponse |
|---------|---------|
| route de `routes/api.py` | toujours le **422 JSON** |
| requête qui attend du JSON (`Content-Type` JSON, ou un en-tête `Accept` qui préfère le JSON) | **422 JSON** |
| les autres (un formulaire HTML) | **redirection 302** vers la page précédente, avec les erreurs et les saisies gardées pour la requête suivante |

La « page précédente » est l'en-tête `Referer`, s'il pointe vers le même site. Sinon, la redirection va vers `/`, ce qui exclut toute redirection vers un site extérieur.

Un refus d'autorisation (`authorize()` qui renvoie `False`) suit la même règle : 403 JSON pour une API, page 403 HTML pour un formulaire.

Pour renvoyer une erreur qui ne vient pas d'une règle (des identifiants refusés, par exemple), levez vous-même une `ValidationError` :

```python
from flask_artisan.validation import ValidationError

raise ValidationError({"email": ["Ces identifiants ne correspondent à aucun compte."]})
```

## `errors` et `old()`

Dans tous les templates :

| Nom | Rôle |
|-----|------|
| `errors.has("email")` | le champ a une erreur |
| `errors.first("email")` | le premier message du champ, sinon `""` |
| `errors.get("email")` | la liste des messages du champ |
| `errors.all()` | tous les messages |
| `errors.any()` | au moins une erreur (`{% if errors %}` marche aussi) |
| `old("email", default="")` | la valeur saisie avant l'erreur |

Les erreurs et les saisies ne vivent que pour la requête qui suit la redirection. Pour les garder, la session étant un cookie signé :

- les champs `password`, `password_confirmation` et `current_password` ne sont jamais gardés ;
- une saisie de plus de 1 000 caractères ne l'est pas non plus, et `old()` rend alors la valeur par défaut. Au-delà d'environ 4 Ko, le navigateur ignorerait le cookie : l'utilisateur perdrait sa session en même temps que ses saisies ;
- pour un champ à valeurs multiples, seule la première valeur est gardée.

Côté Python, `from flask_artisan.views import ErrorBag, errors, old`.

## Protection CSRF

Le middleware `VerifyCsrfToken` est dans le groupe `web` du kernel du squelette : toutes les routes de `routes/web.py` sont protégées.

- `GET`, `HEAD` et `OPTIONS` passent sans contrôle.
- Les autres méthodes doivent envoyer le jeton de la session, de l'une de ces deux façons :
  - le champ `_token`, ajouté par `{{ csrf_field() }}` ;
  - l'en-tête `X-CSRF-TOKEN`, pour un appel JavaScript, avec la valeur de `{{ csrf_token() }}`.
- Un jeton absent ou faux renvoie **419**. La réponse est une page « Page expirée », ou `{"message": "CSRF token mismatch."}` si la requête attend du JSON.

```html
<meta name="csrf-token" content="{{ csrf_token() }}">
<script>
fetch("/posts", {method: "POST", headers: {"X-CSRF-TOKEN": document.querySelector('meta[name="csrf-token"]').content}});
</script>
```

Le jeton change à chaque connexion et à chaque déconnexion, parce que `Auth.login` et `Auth.logout` vident la session. Les routes de `routes/api.py` ne sont pas protégées par CSRF : elles s'authentifient par token, pas par cookie. Le squelette pose aussi `SESSION_COOKIE_SAMESITE = "Lax"` dans `config/flask.py`.

Pendant les tests (`app.testing = True`, posé par le `tests/conftest.py` du squelette), le contrôle est sauté, comme dans Laravel.

## Messages flash

Ce sont ceux de Flask : `flash("Enregistré.")` dans le controller, puis `get_flashed_messages()` dans le template (le layout du squelette les affiche).

## La page de connexion du squelette

Le projet généré contient un parcours complet avec le guard session :

| Route | Rôle |
|-------|------|
| `GET /login` (`login`) | le formulaire, `resources/views/auth/login.html` |
| `POST /login` | `SessionController.store` : `Auth.attempt`, puis redirection vers `/dashboard`, ou retour au formulaire avec l'erreur |
| `POST /logout` (`logout`) | déconnexion, retour à `/` |
| `GET /dashboard` (`dashboard`) | page protégée par `auth` |

Le middleware `auth` renvoie un invité vers la route `login`. `POST /login` a `throttle:5,1`, comme `/api/login`. La clé du throttle ne contient pas la route : une même adresse IP a donc 5 essais par minute pour les deux pages réunies.

Les tests du parcours sont dans `tests/test_web_auth.py`, et les [assertions de test HTTP](tests-http.md) sont décrites sur leur page.

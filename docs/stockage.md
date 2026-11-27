# Stockage de fichiers

La façade `Storage` lit et écrit des fichiers sur des **disques** déclarés dans `config/filesystems.py`. Le même code tourne sur le disque local en développement et sur S3 en production :

```python
from flask_artisan import Storage

Storage.put("rapports/novembre.csv", contenu)        # disque par défaut (FILESYSTEM_DISK)
Storage.disk("public").put("logo.png", octets)
Storage.disk("s3").get("factures/42.pdf")             # bytes
```

## Disques

| Disque | Pilote | Usage |
|--------|--------|-------|
| `local` | `local`, `storage/app/private` | fichiers privés, jamais servis par une URL |
| `public` | `local`, `storage/app/public` | fichiers servis par `/storage/<chemin>` |
| `s3` | `s3` | un bucket S3 ou compatible (MinIO, Cloudflare R2) |

`FILESYSTEM_DISK` dans `.env` choisit le disque par défaut (`local`). Sans `config/filesystems.py`, `local` et `public` existent avec ces valeurs. Les dossiers sont créés à la première écriture, et `storage/` est déjà ignoré par git.

### S3

```bash
pip install "flask-artisan[s3]"
```

```bash
AWS_BUCKET=mon-bucket
AWS_DEFAULT_REGION=eu-west-3
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
# AWS_ENDPOINT=https://<compte>.r2.cloudflarestorage.com   # MinIO, R2… ; vide pour AWS
# AWS_URL=https://cdn.example.com                          # CDN devant le bucket
```

Sans clé ni secret, `boto3` utilise sa propre chaîne d'identifiants (variables d'environnement, rôle IAM). La clé `root` de la config préfixe toutes les clés du bucket.

Droits IAM nécessaires : `s3:GetObject`, `s3:PutObject`, `s3:DeleteObject` et `s3:ListBucket`. Sans `ListBucket`, S3 répond 403 au lieu de 404 pour un fichier absent, et `exists()`, `missing()` et `delete()` lèvent une erreur au lieu de renvoyer `False`.

## API

Les chemins sont relatifs à la racine du disque, avec `/` comme séparateur.

| Méthode | Rôle |
|---------|------|
| `put(path, contenu)` | écrit des `bytes`, une `str` (UTF-8) ou un fichier binaire ouvert ; crée les dossiers ; renvoie `path` |
| `get(path)` | le contenu en `bytes` ; `FileNotFoundError` si absent |
| `exists(path)`, `missing(path)` | booléens |
| `delete(*paths)` | `True` si tous existaient ; un fichier absent n'est pas une erreur |
| `size(path)` | taille en octets |
| `files(dossier="")` | les fichiers du dossier (non récursif, sans les fichiers cachés), triés |
| `url(path)` | URL publique (disque avec `url`, ou S3) |
| `path(path)` | chemin absolu (disques `local` seulement) |
| `put_file(dossier, fichier)` | enregistre un fichier envoyé sous un nom aléatoire ; renvoie le chemin |
| `put_file_as(dossier, fichier, nom)` | idem, sous le nom donné |
| `download(path, nom=None)` | réponse Flask qui télécharge le fichier (pièce jointe) |

Un chemin absolu, `..`, `\`, `:` (lettre de lecteur), un nom de périphérique Windows (`CON`, `NUL`…), un segment vide ou le caractère NUL lèvent `ValueError`. Un lien symbolique qui mène hors de la racine aussi : aucune méthode ne sort du disque. Un dossier n'est pas un fichier : `get` et `size` lèvent `FileNotFoundError`, `delete` renvoie `False`.

`get` charge le fichier entier en mémoire. Pour de très gros fichiers, utilisez `path()` sur un disque local, ou le client `boto3` directement.

## Enregistrer un fichier envoyé

```html
<form method="post" enctype="multipart/form-data">
    {{ csrf_field() }}
    <input type="file" name="avatar">
    {% if errors.has('avatar') %}<p>{{ errors.first('avatar') }}</p>{% endif %}
    <button>Envoyer</button>
</form>
```

```python
from flask import redirect, url_for

from flask_artisan import Auth, Storage
from flask_artisan.validation import FormRequest


class AvatarRequest(FormRequest):
    def rules(self):
        return {"avatar": "required|image|max:2048"}   # 2 Mo


class ProfileController:
    def update(self, request: AvatarRequest):
        path = Storage.disk("public").put_file("avatars", request.validated()["avatar"])
        Auth.user().update(avatar=path)
        return redirect(url_for("dashboard"))
```

```html
<img src="{{ avatar_url }}">   {# Storage.disk("public").url(user.avatar), passé par le controller #}
```

`put_file` ne reprend jamais le nom envoyé : il génère 40 caractères hexadécimaux aléatoires, puis ajoute l'extension du nom envoyé, nettoyée et en minuscules (`avatars/3f9c….png`). Pour un nom choisi, utilisez `put_file_as("avatars", fichier, f"{user.id}.png")`.

Un champ avec plusieurs fichiers (`<input multiple>`) ne donne que le premier à la `FormRequest`. Pour tous les avoir, utilisez `request.files.getlist("photos")` de Flask.

Les règles de [validation](validation.md) des fichiers :

| Règle | Vérifie |
|-------|---------|
| `file` | un fichier a été envoyé |
| `image` | extension `jpg`, `jpeg`, `png`, `gif`, `bmp`, `webp` ou `avif`, et type MIME `image/…` (jamais SVG) |
| `mimes:jpg,pdf` | l'extension est dans la liste |
| `max:2048`, `min:…`, `between:…` | la taille, en **kilo-octets** |

`image` et `mimes` se fient au nom et au type envoyés par le navigateur, sans analyser le contenu. Ne traitez donc jamais un fichier envoyé comme sûr : la protection décrite plus bas est ce qui empêche un fichier piégé de s'exécuter.

## Le disque public

Le disque `public` est servi par la route `GET /storage/<chemin>` (nom `storage.public`, visible dans `flask route:list`). La route lit le disque à chaque requête : `Storage.fake("public")` est donc servi aussi.

Un fichier envoyé par un utilisateur ne doit jamais s'exécuter comme une page du site (XSS stocké). Pour ça, la route :

- pose toujours `X-Content-Type-Options: nosniff` ;
- répond 404 pour un fichier caché (un segment qui commence par `.`, comme `.env` ou une écriture en cours) ;
- sert « en ligne » seulement les images PNG, JPEG, GIF, WebP, AVIF et BMP, le PDF, le texte brut, l'audio et la vidéo ;
- sert tout le reste (HTML, SVG, JavaScript, fichier sans extension) en pièce jointe : le navigateur le télécharge au lieu de l'afficher.

Sur S3, `put` pose les mêmes protections dans les métadonnées de l'objet (`ContentType` et `ContentDisposition: attachment` hors de cette liste), puisque le bucket ou le CDN sert le fichier sans passer par l'app.

Si le projet déclare lui-même une route sur la même URL (`/storage/<path:…>`), c'est la sienne qui répond : la route du framework est ajoutée après celles des providers.

Pour qu'un disque `local` soit servi, sa config doit avoir `"serve": True` et une `url` relative (`"/storage"`). Avec `"serve": False`, il n'y a pas de route.

### En production : nginx

La route Flask suffit, mais nginx sert les fichiers plus vite :

```nginx
# Pièce jointe par défaut ; en ligne seulement pour la même liste que la route.
map $uri $storage_disposition {
    default attachment;
    ~*\.(png|jpe?g|gif|webp|avif|bmp|pdf|txt|mp3|m4a|ogg|oga|wav|mp4|webm|ogv|mov)$ "";
}

server {
    location ~ /storage/(.*/)?\. { return 404; }   # fichiers cachés, comme la route

    location /storage/ {
        alias /chemin/du/projet/storage/app/public/;
        add_header X-Content-Type-Options nosniff always;
        add_header Content-Disposition $storage_disposition always;   # vide : en-tête non envoyé
    }
}
```

Gardez une liste blanche, comme ici : une liste d'extensions interdites oublie toujours un type qui exécute du script (`.xhtml`, `.mht`…). Les fichiers sont écrits avec les droits `0644`, lisibles par l'utilisateur de nginx.

## Tester

`Storage.fake()` remplace un disque par un dossier temporaire, supprimé par `Storage.restore()` ou à la sortie du `with` :

```python
import io

from flask_artisan import Storage


def test_avatar_upload(client, user):
    with Storage.fake("public") as disk:
        client.acting_as(user).post(
            "/profile", data={"avatar": (io.BytesIO(b"..."), "moi.png", "image/png")}
        ).assert_redirect("/dashboard")
        assert disk.files("avatars")
        disk.assert_missing("avatars/moi.png")   # nom aléatoire, jamais le nom envoyé
```

Le disque fake garde l'URL du vrai disque, et les vrais dossiers du projet ne sont jamais touchés. `assert_exists(path)` et `assert_missing(path)` existent sur tous les disques.

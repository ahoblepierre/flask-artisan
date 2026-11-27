# GH-49 : stockage de fichiers (façade `Storage`, disques, uploads)

Ticket : https://github.com/ahoblepierre/flask-artisan/issues/49

## Pourquoi

Les formulaires HTML sont livrés (#19), mais rien n'aide à enregistrer un fichier envoyé, ni à le servir, ni à passer d'un disque local en développement à S3 en production. Chaque projet écrit ses `open()`, ses chemins et sa protection contre les `../`. Laravel règle tout ça avec `Storage` (des disques configurés, la même API partout) et `$request->file('avatar')->store('avatars')`. En production, les conteneurs perdent leur disque à chaque déploiement, d'où S3.

## Objectifs (approche A, choisie par Pierre)

- La façade `Storage` vise le disque par défaut, et `Storage.disk("public")` vise un disque nommé. Les disques sont déclarés dans `config/filesystems.py`.
- Trois pilotes : `local`, `s3` (extra `[s3]`, `boto3`) et le disque de test de `Storage.fake()`.
- Enregistrement d'un fichier de formulaire sous un nom aléatoire (`put_file`) ou choisi (`put_file_as`).
- Le disque `public` est servi par une route `/storage/<chemin>`.
- Règles de validation pour les fichiers : `file`, `image`, `mimes:…`, et `max`/`min`/`size` en kilo-octets.
- Commande : aucune. Le dossier est créé à la première écriture.
- Doc : une page « Stockage de fichiers ».

## Non-objectifs

- Visibilité par fichier (`public`/`private` sur S3), URL temporaires signées (`temporary_url`), `copy`, `move`, `append`, `prepend`, métadonnées (`last_modified`, `mime_type`).
- Pilotes FTP, SFTP, Google Cloud, Azure.
- Streaming de gros fichiers : `get` charge tout en mémoire, et `put` accepte `bytes`, `str` ou un objet fichier binaire.
- `storage:link` (lien symbolique), car la route le remplace.
- Plusieurs fichiers dans un même champ (`<input multiple>`) : `FormRequest` garde le premier, comme `to_dict()` (choix du rédacteur, à la suite de la relecture). `request.files.getlist(...)` reste disponible à la main.
- Analyse du contenu des fichiers (python-magic) : `image` et `mimes` se fient à l'extension et au type MIME envoyés, voir les anti-objectifs.

## Anti-objectifs

- **Aucun chemin ne sort de la racine du disque.** Un chemin absolu, `..`, `\`, le caractère NUL ou un segment vide sont refusés (`ValueError`) par toutes les méthodes, sur tous les pilotes.
- **Un fichier envoyé par un utilisateur et servi par `/storage/...` ne doit jamais s'exécuter comme une page du site** (XSS stocké par un `.html` ou un `.svg`). Voir « Route du disque public ».
- Un projet sans l'extra `[s3]` n'importe jamais `boto3`. L'erreur ne survient qu'à l'usage d'un disque `s3`, avec la commande d'installation.
- `Storage.fake()` n'écrit jamais dans les vrais dossiers du projet.

## Approches envisagées

- **A. `local` et `public`, avec S3 en extra** : retenue par Pierre.
- **B. `local` et `public` seulement** : écartée, car l'interface n'aurait jamais été éprouvée sur un stockage distant.
- **Servir le disque public par une route Flask plutôt que par un lien symbolique** (choix du rédacteur) : ça marche sous Windows et sans configuration du serveur. En production, nginx peut servir `storage/app/public` directement, et la doc le montre.
- **`moto` pour tester S3** (choix du rédacteur) : il simule l'API S3 en mémoire, sans réseau, dans la CI.
- **Validation des fichiers incluse** (choix du rédacteur) : sans `image|max:2048`, le parcours d'upload n'est pas utilisable tel quel. Le coût reste petit, car `_size` sait déjà mesurer selon le type.

## Décisions

### Module et service

- Le code vit dans `src/flask_artisan/filesystem.py`.
- `Application` crée le `FilesystemManager` à côté du `CacheManager` et l'enregistre comme `"filesystem"`, avec la façade `Storage`.
- Comme pour le cache, la config est relue à chaque appel de `disk()`.

### Config (`config/filesystems.py` du squelette, et mêmes valeurs par défaut sans le fichier)

```python
config = {
    "default": env("FILESYSTEM_DISK", "local"),
    "disks": {
        "local": {"driver": "local", "root": "storage/app/private"},
        "public": {"driver": "local", "root": "storage/app/public", "url": "/storage", "serve": True},
        "s3": {
            "driver": "s3",  # pip install "flask-artisan[s3]"
            "bucket": env("AWS_BUCKET"),
            "region": env("AWS_DEFAULT_REGION", "us-east-1"),
            "key": env("AWS_ACCESS_KEY_ID"),
            "secret": env("AWS_SECRET_ACCESS_KEY"),
            "endpoint": env("AWS_ENDPOINT"),  # MinIO, R2… sinon AWS
            "url": env("AWS_URL"),  # CDN devant le bucket, sinon l'URL du bucket
            "root": "",  # préfixe des clés dans le bucket
        },
    },
}
```

- Un `root` relatif est résolu depuis la racine du projet.
- `.env.example` reçoit `FILESYSTEM_DISK=local` et les clés `AWS_*`, vides.
- Si `key` et `secret` sont vides, `boto3` utilise sa propre chaîne d'identifiants (variables d'environnement, rôle IAM).

### API d'un disque

Elle est commune aux pilotes et porte sur des chemins relatifs, avec `/` comme séparateur :

| Méthode | Comportement |
|---------|--------------|
| `put(path, contents) -> str` | écrit `bytes`, `str` (UTF-8) ou un objet fichier binaire ; crée les dossiers ; renvoie `path` |
| `get(path) -> bytes` | `FileNotFoundError` si le fichier est absent |
| `exists(path)`, `missing(path)` | booléens |
| `delete(*paths) -> bool` | `True` si tous existaient ; un fichier absent n'est pas une erreur |
| `size(path) -> int` | en octets |
| `files(directory="") -> list[str]` | chemins relatifs à la racine, triés, non récursif |
| `url(path) -> str` | voir plus bas ; `RuntimeError` si le disque n'a ni `url` ni pilote S3 |
| `path(path) -> Path` | chemin absolu, pour les disques `local` seulement ; `RuntimeError` sur S3 |
| `put_file(directory, file) -> str` | nom aléatoire `secrets.token_hex(20)` + l'extension du nom envoyé (`secure_filename`, en minuscules, vide si aucune) ; renvoie `directory/nom` |
| `put_file_as(directory, file, name) -> str` | `name` est validé comme un seul segment de chemin |
| `download(path, name=None)` | réponse Flask en pièce jointe (`send_file` d'un `BytesIO`, `download_name=name or basename`) |
| `assert_exists(path)`, `assert_missing(path)` | `AssertionError` lisible, pour les tests |

- `file` est un `werkzeug.datastructures.FileStorage`, c'est-à-dire `request.files["avatar"]`.
- La validation des chemins (anti-objectifs) se trouve dans une fonction unique, `_clean(path) -> str`, appelée par chaque méthode. `directory=""` est permis pour `put_file` et pour `files`.

### URL

- **Disque `local` avec `url`** : `url.rstrip("/") + "/" + quote(path)`.
- **S3** :
  - si `url` est donné : `url + "/" + clé` ;
  - si `endpoint` est donné : `endpoint/bucket/clé` ;
  - sinon : `https://{bucket}.s3.{region}.amazonaws.com/{clé}`.

  La `clé` est `root/path`, sans `/` de tête. L'URL n'est pas signée : le bucket ou le CDN doit être public pour ces fichiers.

### Route du disque public

- Pour chaque disque `local` qui a `serve: True` et un `url` relatif, `Application.boot()` déclare la route `GET <url>/<path:path>` (nom `storage.<disque>`) **par le `Router`**, dans sa fenêtre de collecte et avant les `boot()` des providers. La route apparaît donc dans `route:list`, sans middleware (choix du rédacteur, à la suite de la relecture).
- La vue résout `Storage.disk(nom)` **à chaque requête** et sert depuis sa racine. Un `Storage.fake("public")` est donc servi par `/storage/...`, ce qui permet de tester « upload puis affichage » sans toucher aux vrais dossiers (choix du rédacteur, à la suite de la relecture).
  - La route sert le fichier avec `send_from_directory(root, path)`, qui renvoie 404 sur `..` ou sur un fichier absent.
  - Elle n'est ajoutée qu'une fois, et seulement si la config la demande. Un projet existant sans `config/filesystems.py` reçoit les valeurs par défaut, et donc la route `/storage/`.
- **Contre le XSS stocké** (anti-objectif) :
  - chaque réponse porte `X-Content-Type-Options: nosniff` ;
  - un fichier est servi « en ligne » seulement si son type est dans une liste sûre : `image/png`, `image/jpeg`, `image/gif`, `image/webp`, `image/avif`, `application/pdf`, `text/plain`, `audio/*` et `video/*` ;
  - tout autre type, y compris `image/svg+xml` et `text/html`, est servi en `Content-Disposition: attachment`.

### En-têtes des objets S3 (choix du rédacteur, à la suite de la relecture)

Les fichiers S3 sont servis directement par le bucket ou le CDN, sans passer par la route. `put` pose donc lui-même les en-têtes, avec la même liste sûre que la route :

- `ContentType` est deviné depuis l'extension (`mimetypes.guess_type`), sinon `application/octet-stream` ;
- un type hors de la liste sûre reçoit en plus `ContentDisposition: attachment`.

Un `.html` ou un `.svg` envoyé ne s'exécute donc pas sur le domaine du CDN. La liste sûre est une constante unique (`INLINE_TYPES`), partagée par la route et par S3. Les tests moto vérifient ces métadonnées.

### `Storage.fake(name=None)`

- C'est un mode du gestionnaire, comme `Mail.fake()`. Il remplace le disque `name` (le défaut sinon) par un disque `local` dans un dossier `tempfile.mkdtemp(prefix="flask-artisan-")`, et renvoie ce disque.
- Un deuxième `fake` du même disque repart d'un dossier vide.
- `Storage.restore()` (et la sortie du `with`, puisque le disque renvoyé est un gestionnaire de contexte) quitte le mode fake pour tous les disques et supprime les dossiers temporaires.
- Le disque fake garde le `url` du vrai disque, ce qui permet de tester `Storage.url(...)`.

### Validation des fichiers (`validation.py`)

- **`FormRequest`** lit aussi `request.files`. Un champ fichier vide (aucun fichier choisi, `filename == ""`) compte comme absent pour `required`.
- **Règles :**
  - `file` : un `FileStorage` avec un nom non vide ;
  - `image` : un `file` dont l'extension est `jpg`, `jpeg`, `png`, `gif`, `bmp`, `webp` ou `avif`, **et** dont le `mimetype` envoyé commence par `image/` (pas `svg`, comme Laravel 11) ;
  - `mimes:jpg,png` : l'extension du nom envoyé, en minuscules, est dans la liste (`jpeg` vaut `jpg` et inversement).
- **Taille :** pour un `FileStorage`, `_size` renvoie sa taille en kilo-octets (`ceil(octets / 1024)`, mesurée en se plaçant à la fin du flux, puis en revenant à la position de départ). `max:2048` vaut donc 2 Mo.
- **Messages :** une variante `"file"` est ajoutée pour `min`, `max`, `size` et `between` (« must not be greater than :max kilobytes »), plus les messages `file`, `image` et `mimes`, dans la langue des messages existants (anglais, comme Laravel).
- `validated()` renvoie le `FileStorage` tel quel.
- Côté sérialisation, un `FileStorage` n'est jamais flashé dans `old()` : `_redirect_back` ne lit que `args` et `form`, donc rien ne change.

### Squelette

- `config/filesystems.py` et `.env.example` (voir plus haut).
- La ligne `storage/` de `.gitignore` existe déjà et couvre `storage/app/`.
- Aucun controller d'exemple. Une ligne commentée dans `routes/web.py` montre un upload.

### Tests

- **Contrat commun :** les mêmes tests de l'API tournent sur les trois pilotes, comme pour le cache (`tests/storage/`) :
  - `local` dans `tmp_path` ;
  - `s3` avec `moto` (`mock_aws`, bucket créé dans la fixture) ;
  - le disque de `Storage.fake()`.
- **Extras :** `dev` reçoit `boto3` et `moto[s3]>=5`, et un nouvel extra `s3 = ["boto3>=1.34"]` est ajouté.
- **Tests dédiés :**
  - les chemins refusés (`../x`, `/etc/passwd`, `a\\b`, `a//b`, `"a\x00"`) sur chaque pilote ;
  - la route publique : 200 et `nosniff` sur un `.png`, `attachment` sur un `.html` et un `.svg`, 404 sur `../`.

### Doc

- **Nouvelle page `docs/stockage.md`, « Stockage de fichiers »,** ajoutée au nav dans la section « Données », après Cache. Elle couvre :
  - les disques et la config, et S3 (y compris MinIO et R2 par `endpoint`) ;
  - l'API ;
  - l'upload avec validation ;
  - le disque public et la route, avec la protection `attachment` ;
  - le bloc nginx `location /storage/ { alias …/storage/app/public/; add_header X-Content-Type-Options nosniff; }`, avec l'avertissement que nginx ne pose pas l'`attachment` de lui-même ;
  - `Storage.fake()`.
- `validation.md` reçoit les nouvelles règles.
- Mises à jour aussi : le README (une ligne), CLAUDE.md (une puce) et le CHANGELOG.

## Laissé au constructeur

- La structure interne des pilotes (classe de base, méthodes privées).
- Le texte des messages d'erreur du framework.
- La forme exacte des fixtures de contrat.

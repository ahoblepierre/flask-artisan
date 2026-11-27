# Stockage de fichiers : plan d'implémentation

> **Pour les agents :** sous-skill requise : superpowers:subagent-driven-development (recommandé) ou superpowers:executing-plans pour exécuter ce plan tâche par tâche. Les étapes utilisent des cases à cocher (`- [ ]`).

**Objectif :** une façade `Storage` avec des disques `local` et `s3` et un mode `fake`, une route qui sert le disque public sans XSS stocké, et des règles de validation pour les fichiers envoyés.

**Architecture :**
- Le module `filesystem.py` contient `_clean`, `Disk` (API commune et assertions), `LocalDisk`, `S3Disk` (import de `boto3` à l'usage) et `FilesystemManager` (service `"filesystem"`, façade `Storage`, config relue à chaque `disk()`, mode `fake`).
- `Application.boot()` déclare les routes des disques servis par le `Router`.
- La validation reçoit `request.files` et trois règles.

**Stack :** Werkzeug (`FileStorage`, `secure_filename`), Flask (`send_from_directory`, `send_file`), boto3, moto 5 (`mock_aws`).

**Spec :** [docs/superpowers/specs/GH-49-spec.md](../specs/GH-49-spec.md)

## Contraintes globales

- `INLINE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp", "image/avif", "application/pdf", "text/plain"}`, plus tout type `audio/*` ou `video/*`. Cette constante est utilisée par la route et par S3.
- Chemins refusés par `_clean` : chemin absolu, `..`, `\`, `\x00`, segment vide (`a//b`), et chemin vide, sauf là où `directory=""` est permis.
- `boto3` n'est importé que dans `S3Disk`. Sans lui, un `RuntimeError` dit `pip install "flask-artisan[s3]"`.
- Défauts sans `config/filesystems.py` : `local` → `storage/app/private`, `public` → `storage/app/public` (avec `url: "/storage"` et `serve: True`), et `default` vaut `local`.
- Extras : `s3 = ["boto3>=1.34"]` ; `dev` reçoit `boto3>=1.34` et `moto[s3]>=5`.
- Commits et PR : `(#49)`.

## Points à surveiller

1. **Traversée de chemin** par chaque méthode, sur chaque pilote, et par la route. Couvert par `test_rejected_paths` (tâche 1, contrat) et `test_route_rejects_traversal` (tâche 3).
2. **Fichier HTML ou SVG envoyé puis servi** : il part en `attachment` sur la route et sur S3. Couvert par `test_route_attachment_for_unsafe_types` (tâche 3) et `test_s3_unsafe_type_is_attachment` (tâche 2).
3. **Nom envoyé hostile pour `put_file`** (`../../x.php`, `évil.PNG`, sans extension) : le nom est toujours aléatoire, avec une extension sûre en minuscules. Couvert par `test_put_file_names` (tâche 1).
4. **Champ fichier vide** (aucun fichier choisi) avec `required|file` : erreur `required`, pas une exception. Couvert par `test_empty_file_input_is_missing` (tâche 4).
5. **Le fake ne touche jamais les vrais dossiers**, y compris par la route. Couvert par `test_fake_is_isolated` (tâche 1) et `test_route_serves_fake` (tâche 3).

---

### Task 1: Disk API, local driver, manager, fake

**Fichiers :**
- Créer : `src/flask_artisan/filesystem.py`, `tests/storage/__init__.py`, `tests/storage/conftest.py`, `tests/storage/test_disk_contract.py` et `tests/storage/test_manager.py`.
- Modifier :
  - `src/flask_artisan/application.py` : créer le manager à côté du `CacheManager`, et l'enregistrer sous `"filesystem"` et `FilesystemManager` ;
  - `src/flask_artisan/facades.py` : `class Storage(Facade): accessor = "filesystem"` ;
  - `src/flask_artisan/__init__.py` : exporter `Storage`.

**Interfaces :**
- Produit, dans `filesystem.py` :
  - `_clean(path: str, allow_empty: bool = False) -> str` ;
  - `class Disk` avec `put`, `get`, `exists`, `missing`, `delete`, `size`, `files`, `url`, `path`, `put_file`, `put_file_as`, `download`, `assert_exists` et `assert_missing`, avec les signatures et le comportement de la spec ;
  - `class LocalDisk(Disk)`, `__init__(self, root: Path, url: str | None = None)` ;
  - `class FilesystemManager`, avec `disk(name=None) -> Disk`, `fake(name=None) -> LocalDisk`, `restore()` et un `__getattr__` qui relaie les méthodes publiques de `Disk` vers le disque par défaut ;
  - la constante `INLINE_TYPES`.
- Le disque renvoyé par `fake()` est un gestionnaire de contexte : `__exit__` appelle `manager.restore()`.

- [ ] **Étape 1 : écrire les tests.**
  - La fixture `disk`, dans `conftest.py`, est paramétrée `["local", "fake"]`. La tâche 2 ajoute `"s3"`.
    - `local` : `LocalDisk(tmp_path / "d", url="/files")`.
    - `fake` : une app de `make_project`, puis `app.make("filesystem").fake("public")`, qui garde l'url `/storage`.
  - Les tests de contrat :
    - `test_put_get` : `put("a/b.txt", "hé")` renvoie `"a/b.txt"` et `get` donne `"hé".encode()` ; `put` d'un `io.BytesIO(b"x")` marche aussi ;
    - `test_exists_missing_delete` : `delete("a.txt", "absent.txt")` vaut `False`, `delete("a.txt")` sur un fichier présent vaut `True`, puis `missing` ;
    - `test_get_missing_raises` : `FileNotFoundError` ;
    - `test_size_and_files` : `files("a")` vaut `["a/1.txt", "a/2.txt"]` (trié, sans le sous-dossier `a/sub/x`) ; `files()` à la racine ;
    - `test_url` : se termine par `/a%20b.png` pour `"a b.png"` ;
    - `test_rejected_paths` : paramétré sur `["../x", "/etc/passwd", "a\\b", "a//b", "a\x00", ""]`, `put`, `get`, `exists` et `delete` lèvent `ValueError` ;
    - `test_put_file_names` : avec des `FileStorage(stream=BytesIO(b"x"), filename=...)` sur `"../../x.php"`, `"évil.PNG"`, `"noext"` et `""`, le résultat correspond à `r"^up/[0-9a-f]{40}(\.php|\.png|)$"`, et le fichier existe ;
    - `test_put_file_as` : `put_file_as("up", f, "avatar.png") == "up/avatar.png"` ; le nom `"a/b.png"` lève `ValueError` ;
    - `test_download` : dans un `test_request_context`, `download("a.txt", "facture.txt")` a `Content-Disposition` avec `attachment` et `facture.txt` ;
    - `test_assertions` : `assert_exists` et `assert_missing`, et leur `AssertionError`.
  - Dans `test_manager.py` :
    - `test_default_disk_relay` : `Storage.put` écrit sur le disque par défaut, dont la racine `root` est surchargée vers `tmp_path` par `config.set` ;
    - `test_unknown_disk` : `ValueError` ;
    - `test_local_path_only` : `path()` renvoie un chemin absolu sous la racine ;
    - `test_fake_is_isolated` : après `Storage.fake()` puis `put`, le dossier `storage/app/private` du projet n'existe pas, et `restore()` supprime le dossier temporaire ;
    - `test_fake_twice_starts_empty` ;
    - `test_fake_context_manager` : `with Storage.fake("public") as d:`, puis le disque redevient réel après le bloc ;
    - `test_defaults_without_config` : sans `config/filesystems.py`, `disk("public").url("x")` vaut `"/storage/x"`.
- [ ] **Étape 2 : RED.** Lancer `.venv/bin/pytest tests/storage -q`.
  Attendu : ÉCHEC à l'import de `flask_artisan.filesystem`.
- [ ] **Étape 3 : implémenter.**
  - Le `put` de `LocalDisk` écrit dans un fichier temporaire du même dossier, puis fait `os.replace` (écriture atomique, comme `FileStore`).
  - `_size` de `FileStorage` n'est pas concerné ici.
- [ ] **Étape 4 : GREEN.** Lancer `.venv/bin/pytest tests/storage tests/test_application.py tests/test_facades.py -q`.
  Attendu : tout passe.
- [ ] **Étape 5 : commit** `feat: façade Storage, disque local et Storage.fake (#49)`.

### Task 2: S3 driver

**Fichiers :**
- Modifier : `src/flask_artisan/filesystem.py`, `pyproject.toml` (extras), `tests/storage/conftest.py` (paramètre `"s3"`).
- Créer : `tests/storage/test_s3.py`.

**Interfaces :**
- Consomme : `Disk`, `_clean` et `INLINE_TYPES` de la tâche 1.
- Produit : `class S3Disk(Disk)`, `__init__(self, bucket, region, key=None, secret=None, endpoint=None, url=None, root="")`. Le client `boto3` est créé à l'usage. `FilesystemManager.disk()` construit un `S3Disk` pour `driver: "s3"`.

- [ ] **Étape 1 : écrire les tests.**
  - La fixture `disk` ajoute `"s3"` : sous `mock_aws()`, créer le bucket `"b"` et construire `S3Disk("b", "us-east-1", root="app")`. Tous les tests de contrat tournent dessus. `files()` passe par `list_objects_v2` avec `Delimiter="/"`.
  - Dans `test_s3.py` :
    - `test_s3_keys_under_root` : `put("x.txt", "1")` crée la clé `app/x.txt` ;
    - `test_s3_url_variants` : sans option, `https://b.s3.us-east-1.amazonaws.com/app/x.png` ; avec `endpoint="http://minio:9000"`, `http://minio:9000/b/app/x.png` ; avec `url="https://cdn.example"`, `https://cdn.example/app/x.png` ;
    - `test_s3_safe_type_inline` : `head_object` d'un `a.png` donne le `ContentType` `image/png`, sans `ContentDisposition` ;
    - `test_s3_unsafe_type_is_attachment` : `a.html` et `a.svg` ont un `ContentDisposition` qui commence par `attachment` ;
    - `test_s3_path_unsupported` : `RuntimeError` ;
    - `test_missing_boto3_message` : avec `monkeypatch.setitem(sys.modules, "boto3", None)`, le premier usage lève `RuntimeError` avec `flask-artisan[s3]`.
- [ ] **Étape 2 : RED.** Lancer `.venv/bin/pytest tests/storage -q`.
  Attendu : les tests `s3` ÉCHOUENT (`S3Disk` n'existe pas).
- [ ] **Étape 3 : implémenter `S3Disk`.**
  - `get` d'une clé absente lève `FileNotFoundError` (en interceptant `ClientError` avec le code `NoSuchKey` ou `404`).
  - `exists` passe par `head_object`.
  - `delete` passe par `delete_objects`, après un `head_object` par clé pour calculer le booléen.
- [ ] **Étape 4 : GREEN.** Lancer `.venv/bin/pytest tests/storage -q`.
  Attendu : tout passe.
- [ ] **Étape 5 : commit** `feat: disque S3 (extra [s3]) (#49)`.

### Task 3: public disk route

**Fichiers :**
- Modifier : `src/flask_artisan/application.py` (`boot`), `src/flask_artisan/filesystem.py` (la vue `serve(disk_name, path)`).
- Créer : `tests/storage/test_route.py`.

**Interfaces :**
- Consomme : `FilesystemManager.disk` et `INLINE_TYPES`.
- Produit : les routes nommées `storage.<disque>`. Dans `Application.boot()`, à l'intérieur du `collecting()`, avant les `boot()` des providers, elles sont déclarées par `Router.get(f"{url}/<path:path>", partial-like view)`. La vue reçoit `path` et doit avoir un `__name__` pour l'endpoint automatique, mais le nom est posé explicitement.

- [ ] **Étape 1 : écrire les tests.** On utilise une app de `make_project` dont le disque `public` a sa racine sous `tmp_path`.
  - `test_route_serves_safe_inline` : `GET /storage/a.png` répond 200, avec `X-Content-Type-Options: nosniff` et sans `attachment` ;
  - `test_route_attachment_for_unsafe_types` : `.html`, `.svg` et `.js` sont servis avec un `Content-Disposition` en `attachment` et avec `nosniff` ;
  - `test_route_rejects_traversal` : `/storage/../config/app.py` et `/storage/%2e%2e/x` répondent 404 ; un fichier absent aussi ;
  - `test_route_serves_fake` : `Storage.fake("public").put("x.txt", "f")`, puis `GET /storage/x.txt` renvoie `f` ;
  - `test_route_in_route_list` : `storage.public` est dans `Router.registered` ;
  - `test_no_route_without_serve` : avec `serve: False`, `/storage/x` répond 404 et la route est absente.
- [ ] **Étape 2 : RED.** Lancer `.venv/bin/pytest tests/storage/test_route.py -q`.
  Attendu : ÉCHEC (404 partout).
- [ ] **Étape 3 : implémenter.**
  - Les disques sont lus dans `config("filesystems.disks", DEFAULT_DISKS)`. Seuls les disques `driver == "local"` avec `serve` et un `url` qui commence par `/` sont servis.
  - La vue fait `send_from_directory(disk.root, path)`. Elle prend le type par `mimetypes.guess_type`, pose `nosniff`, et pose `Content-Disposition: attachment` si le type n'est pas dans la liste sûre.
- [ ] **Étape 4 : GREEN.** Lancer `.venv/bin/pytest tests/storage tests/test_route_list.py tests/test_routing.py -q`.
  Attendu : tout passe. Si un test existant de `route:list` compte les routes, il faut l'adapter en ledgerisant un ruling.
- [ ] **Étape 5 : commit** `feat: route du disque public, types non sûrs en pièce jointe (#49)`.

### Task 4: file validation

**Fichiers :**
- Modifier : `src/flask_artisan/validation.py`
- Créer : `tests/validation/test_files.py`

**Interfaces :**
- Produit :
  - les règles `file`, `image` et `mimes` dans `RULES` ;
  - `mimes` avec au moins un paramètre, dans la table des paramètres ;
  - `_size` qui renvoie des kilo-octets pour un `FileStorage` ;
  - la variante `"file"` des messages `min`, `max`, `size` et `between` ;
  - `FormRequest` qui fusionne `request.files.to_dict()` dans ses données.

- [ ] **Étape 1 : écrire les tests.** On utilise `validate()` avec des `FileStorage` construits à la main.
  - `test_file_rule` : passe pour un fichier nommé ; échoue pour une chaîne ;
  - `test_image_rule` : `a.PNG` en `image/png` passe ; `a.svg` en `image/svg+xml` échoue ; `a.png` en `text/html` échoue ;
  - `test_mimes_rule` : `mimes:jpg,pdf` accepte `a.jpeg` et `b.PDF`, et refuse `c.png` ;
  - `test_max_kilobytes` : un fichier de 2 049 Ko échoue à `max:2048`, avec un message qui contient « kilobytes », et 2 048 Ko passe ; la position du flux est conservée (`stream.tell()` inchangé) ;
  - `test_empty_file_input_is_missing` : un `FileStorage(filename="")` avec `required|file` donne l'erreur `required` ;
  - `test_form_request_reads_files` : une route avec une `FormRequest` (`{"avatar": "required|image|max:10"}`) et un `client.post(data={"avatar": (BytesIO(b"x"), "a.png", "image/png")})` ; le controller reçoit un `FileStorage` dans `validated()`.
- [ ] **Étape 2 : RED.** Lancer `.venv/bin/pytest tests/validation/test_files.py -q`.
  Attendu : ÉCHEC (règles inconnues).
- [ ] **Étape 3 : implémenter.**
  - `_empty` traite un `FileStorage` sans `filename` comme vide.
  - `image` et `mimes` lisent l'extension avec `rsplit(".", 1)` sur le nom envoyé, en minuscules.
- [ ] **Étape 4 : GREEN.** Lancer `.venv/bin/pytest tests/validation tests/test_html_errors.py -q`.
  Attendu : tout passe.
- [ ] **Étape 5 : commit** `feat: règles de validation file, image, mimes et tailles en Ko (#49)`.

### Task 5: skeleton, docs

**Fichiers :**
- Créer : `src/flask_artisan/skeleton/config/filesystems.py`, `docs/stockage.md`.
- Modifier :
  - le squelette : `.env.example` (`FILESYSTEM_DISK=local` et les `AWS_*` vides) et `routes/web.py` (exemple d'upload en commentaire) ;
  - le site : `mkdocs.yml` (`- Stockage de fichiers: stockage.md` après Cache) et `docs/validation.md` (les règles `file`, `image` et `mimes`) ;
  - le repo : `README.md`, `CLAUDE.md` et `CHANGELOG.md`.
  - `tests/test_cli.py` : ajouter `test_generated_project_storage`. Dans un projet généré, ce test lance un script qui fait `Storage.disk("public").put("x.txt", "hi")`, puis `app.test_client().get("/storage/x.txt")`, et vérifie le statut 200, le corps `hi` et la présence de `nosniff`.

- [ ] **Étape 1 : RED.** Lancer `.venv/bin/pytest tests/test_cli.py::test_generated_project_storage -q`.
  Attendu : ÉCHEC tant que le test n'existe pas. On écrit le test, puis on le relance.
  Attendu : il passe déjà grâce aux valeurs par défaut. Le vérifier ensuite avec `config/filesystems.py` présent.
- [ ] **Étape 2 : écrire `config/filesystems.py` et `.env.example`** comme le dit la spec, puis relancer le test. Attendu : il passe.
- [ ] **Étape 3 : écrire la doc** comme le dit la spec, section « Doc », avec le bloc nginx.
- [ ] **Étape 4 : vérification complète.** Lancer `.venv/bin/pytest -q`, `.venv/bin/ruff check .`, `.venv/bin/ruff format --check .` et `.venv/bin/mkdocs build --strict`.
  Attendu : tout passe.
- [ ] **Étape 5 : commit** `feat: config filesystems du squelette, page Stockage de fichiers (#49)`.

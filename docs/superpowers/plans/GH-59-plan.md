# Kit de démarrage `flask auth:install` : plan d'implémentation

> **Pour les agents :** sous-skill requise : superpowers:subagent-driven-development (recommandé) ou superpowers:executing-plans pour exécuter ce plan tâche par tâche. Les étapes utilisent des cases à cocher (`- [ ]`).

**Objectif :** des briques d'auth dans le framework (URLs signées, réinitialisation du mot de passe, `MustVerifyEmail`, deux notifications), et une commande `flask auth:install` qui copie dans le projet les parcours inscription, mot de passe oublié et vérification de l'e-mail.

**Architecture :**
- `flask_artisan/signing.py` : `signed_url`, `has_valid_signature`, middleware `ValidateSignature`.
- `flask_artisan/auth/` :
  - `verification.py` : `MustVerifyEmail` et `EnsureEmailIsVerified`, exportés par `flask_artisan.auth` ;
  - `passwords.py` : `PasswordResetToken` et `Password`. **Jamais importé** par `flask_artisan.auth`, son import enregistre la table ;
  - `notifications.py` : `ResetPassword` et `VerifyEmail`, importé à l'usage seulement.
- Les templates de ces mails sont dans `flask_artisan/resources/views/flask_artisan/emails/`, chargés en dernier par le `ChoiceLoader`.
- `RouteServiceProvider` charge `routes/auth.py` s'il existe.
- `auth:install` copie l'arbre `flask_artisan/stubs/auth/`. Chaque fichier y porte le suffixe `.stub`, retiré à la copie, pour que ni pytest, ni ruff, ni setuptools ne les prennent pour du code du repo.

**Stack :** `hmac` et `hashlib` (bibliothèque standard), `Model`, `Notification` et `Mailable`, `Authenticate`, `expects_json`, `ThrottleRequests`, `click`.

**Spec :** [docs/superpowers/specs/GH-59-spec.md](../specs/GH-59-spec.md)

## Contraintes globales

- `Application(...)` n'importe jamais `flask_artisan.auth.passwords` ni `flask_artisan.auth.notifications`. `import flask_artisan.auth` non plus : après lui, aucun des deux n'est dans `sys.modules`.
- **Table `password_reset_tokens`** :
  - `email` en clé primaire (texte) ;
  - `token` en `String(64)`, le sha256 hex du jeton en clair ;
  - `created_at` (date avec fuseau) ;
  - pas d'`id`, pas d'`updated_at` (`timestamps = False`).
- **Statuts de `Password`** (attributs de classe) :
  - `RESET_LINK_SENT = "passwords.sent"` ;
  - `RESET_THROTTLED = "passwords.throttled"` ;
  - `INVALID_USER = "passwords.user"` ;
  - `INVALID_TOKEN = "passwords.token"` ;
  - `PASSWORD_RESET = "passwords.reset"`.
- **Config relue à chaque appel**, avec ces valeurs par défaut si la clé manque :
  - `auth.passwords.expire` = 60 minutes ;
  - `auth.passwords.throttle` = 60 secondes ;
  - `auth.verification.expire` = 60 minutes.
- **Noms de routes fixes**, que le framework utilise : `password.reset` (paramètres `token` et `email`), `verification.verify` (`id` et `hash`), `verification.notice`.
- **`hash` de vérification** : `hashlib.sha1(email.encode()).hexdigest()`.
- **Signature** : HMAC-SHA256 hex, clé `current_app.config["SECRET_KEY"]`, message `<chemin>?<requête sans signature>` (ou `<chemin>` seul s'il n'y a pas de requête). Paramètres de requête : `expires` (timestamp UNIX entier) et `signature`, toujours en dernier.
- **Réponse JSON** de `verified` : `{"message": "Your email address is not verified."}`, code 403. Pour `signed` : `{"message": "Invalid signature."}`, code 403.
- Les modèles de test portent des noms uniques dans la suite : préfixes `Pw` (mot de passe) et `Ve` (vérification).
- Commits et PR : `(#59)`.

## Points à surveiller

1. **SQLite rend des dates sans fuseau.** Un jeton de 59 minutes doit être accepté et un jeton de 61 minutes refusé, après relecture en base (session expirée). Tests `test_reset_accepts_fresh_token_after_reload` et `test_reset_rejects_expired_token` (tâche 3).
2. **URL signée trafiquée** : un paramètre modifié, `expires` changé, une seconde `signature` ajoutée, ou une signature retirée sont tous refusés. Test `test_tampered_urls_are_rejected` (tâche 1).
3. **Un `User` sans `Notifiable`** : `send_reset_link` lève un `TypeError` qui nomme `Notifiable`, pas un `AttributeError`. Test `test_reset_link_requires_notifiable` (tâche 2).
4. **`auth:install` avec un seul fichier en conflit** : aucun fichier n'est écrit, et le code de sortie est 1. Test `test_auth_install_conflict_writes_nothing` (tâche 6).
5. **Le lien de vérification d'un autre utilisateur**, ou celui d'un e-mail changé depuis, ouvert en étant connecté : 403, rien n'est marqué. Tests `test_verify_link_of_other_user_is_forbidden` et `test_verify_link_after_email_change_is_forbidden` dans les tests installés (tâche 6).

---

### Task 1: signed URLs

**Files:**
- Create: `src/flask_artisan/signing.py`
- Modify: `src/flask_artisan/__init__.py` (exports `signed_url`, `ValidateSignature`)
- Modify: `src/flask_artisan/skeleton/app/http/kernel.py` (alias `"signed": ValidateSignature`)
- Test: `tests/test_signing.py`

**Interfaces :**
- Produit :
  - `signed_url(endpoint: str, expires: int | None = None, **values) -> str`. `expires` est en secondes à partir de maintenant, et `_external=True` est transmis à `url_for` ;
  - `has_valid_signature(request) -> bool` ;
  - `class ValidateSignature(Middleware)`, dont `handle(request, next)` renvoie 403 JSON si la signature est invalide.
- L'heure passe par `signing._now() -> float` (par défaut `time.time`), que les tests remplacent.

- [ ] **Step 1 : écrire les tests qui échouent.** App de test : `make_project` avec une route `GET /files/<int:id>` nommée `files.show`, protégée par `ValidateSignature` et qui renvoie `"ok"`.
  - `test_signed_url_is_accepted` : `client.get(signed_url("files.show", id=3))` donne 200 et `"ok"`.
  - `test_signed_url_with_expiry` : avec `expires=60`, l'URL contient `expires=` et donne 200. Avec `_now` avancé de 61 s, elle donne 403 et `{"message": "Invalid signature."}`.
  - `test_tampered_urls_are_rejected` : 403 pour chacun de ces cas :
    - `id` remplacé (`/files/4?...` avec la même signature) ;
    - `expires` augmenté ;
    - `&signature=x` ajouté ;
    - la signature retirée ;
    - un paramètre `&a=1` ajouté ;
    - `expires=abc`.
  - `test_external_signed_url` : `signed_url("files.show", id=3, _external=True)` commence par `http://localhost/` et `client.get` du même chemin donne 200.
  - `test_signature_depends_on_app_key` : une URL signée par une app avec `APP_KEY` différente donne 403.
- [ ] **Step 2 : lancer les tests.** `.venv/bin/pytest tests/test_signing.py -q`. Attendu : ÉCHEC, `ModuleNotFoundError: flask_artisan.signing`.
- [ ] **Step 3 : implémenter `signing.py`.**
  - On construit le chemin relatif par `url_for(endpoint, **values, expires=…)`, on le signe, puis on ajoute `signature` en dernier.
  - Pour `_external`, on préfixe `request.host_url` sans le `/` final, ou on refait `url_for(..., _external=True)` avec la signature, à condition que le test d'aller-retour passe.
  - La vérification relit `request.query_string` brut, découpé sur `&`. Elle exige **exactement un** élément `signature=` et le **dernier**, puis compare avec `hmac.compare_digest`.
  - Ajouter l'alias `signed` au `Kernel` du squelette.
- [ ] **Step 4 : relancer les tests.** `.venv/bin/pytest tests/test_signing.py -q`. Attendu : SUCCÈS.
- [ ] **Step 5 : commit.** `git commit -m "feat: URLs signées et middleware signed (#59)"`

### Task 2: mail templates and auth notifications

**Files:**
- Create: `src/flask_artisan/auth/notifications.py`
- Create: `src/flask_artisan/resources/views/flask_artisan/emails/reset_password.html`, `reset_password.txt`, `verify_email.html`, `verify_email.txt`
- Modify: `src/flask_artisan/application.py` (troisième `FileSystemLoader`, en dernier)
- Modify: `src/flask_artisan/auth/authenticatable.py` (`Authenticatable.send_password_reset_notification`)
- Modify: `pyproject.toml` (`package-data` : `"resources/views/flask_artisan/emails/*"`)
- Test: `tests/auth/test_auth_notifications.py`

**Interfaces :**
- Consomme : `signed_url` (tâche 1).
- Produit :
  - `class ResetPassword(Notification)`, avec `__init__(self, token: str)`, l'attribut `token`, `via → ["mail"]` et `to_mail(notifiable) -> Mailable` ;
  - `class VerifyEmail(Notification)`, avec `via → ["mail"]` et `to_mail(notifiable) -> Mailable` ;
  - `reset_url(notifiable, token) -> str` = `url_for("password.reset", token=token, email=notifiable.email, _external=True)` ;
  - `verification_url(notifiable) -> str` = `signed_url("verification.verify", expires=<auth.verification.expire>*60, id=notifiable.id, hash=sha1(email), _external=True)` ;
  - `Authenticatable.send_password_reset_notification(self, token: str) -> None`, qui importe `ResetPassword` à l'appel et lève `TypeError("<Classe> doit hériter de Notifiable pour recevoir le lien de réinitialisation.")` si `self` n'a pas `notify`.
- Mails :
  - sujets exacts : `"Réinitialisation du mot de passe"` et `"Vérifiez votre adresse e-mail"` ;
  - contexte des templates : `url` et `expire` (en minutes) ;
  - `view` = `flask_artisan/emails/<nom>.html`, `text` = `flask_artisan/emails/<nom>.txt`.

- [ ] **Step 1 : écrire les tests qui échouent** (app de `tests/auth/conftest.py`, avec des routes `password.reset` et `verification.verify` déclarées pour le test, et le modèle `PwUser(Authenticatable, Notifiable, Model)` ajouté à `tests/auth/models.py`).
  - `test_reset_password_mail` : avec `Mail.fake()`, `user.notify(ResetPassword("abc"))` envoie un mail à `user.email`, avec le sujet ci-dessus, et le texte contient `http://localhost/reset-password/abc?email=`.
  - `test_verify_email_mail_has_signed_link` : le texte contient une URL qui, ouverte par le client de test, passe `ValidateSignature`.
  - `test_project_can_override_template` : `resources/views/flask_artisan/emails/reset_password.txt` du projet remplace celui du package.
  - `test_reset_link_requires_notifiable` : sur `AMember` (sans `Notifiable`), `send_password_reset_notification("x")` lève un `TypeError` dont le message contient `Notifiable`.
  - `test_auth_import_does_not_load_notifications` : en sous-processus, `import flask_artisan.auth` laisse absents `flask_artisan.auth.notifications` et `flask_artisan.auth.passwords` de `sys.modules`.
- [ ] **Step 2 : lancer les tests.** `.venv/bin/pytest tests/auth/test_auth_notifications.py -q`. Attendu : ÉCHEC (module absent).
- [ ] **Step 3 : implémenter** les notifications, les templates (en français, sur le modèle des mails existants), le chargeur et `package-data`.
- [ ] **Step 4 : relancer les tests.** `.venv/bin/pytest tests/auth -q`. Attendu : SUCCÈS.
- [ ] **Step 5 : commit.** `git commit -m "feat: notifications ResetPassword et VerifyEmail (#59)"`

### Task 3: password broker

**Files:**
- Create: `src/flask_artisan/auth/passwords.py`
- Test: `tests/auth/test_passwords.py`

**Interfaces :**
- Consomme : `send_password_reset_notification` (tâche 2).
- Produit :
  - `class PasswordResetToken(Model)`, avec les colonnes des contraintes globales ;
  - `class Password`, avec les cinq statuts, `send_reset_link(email: str) -> str` et `reset(email: str, token: str, password: str) -> str`. Ce sont des méthodes de classe, qui résolvent l'app par `Application.get_instance()`. L'heure passe par `passwords._now() -> datetime` (UTC avec fuseau), que les tests remplacent.
- `reset`, en cas de succès :
  1. `user.password = password` ;
  2. si le modèle utilise `HasApiTokens`, supprime ses `PersonalAccessToken`, par la même requête `delete` que `HasApiTokens._hard_delete` ;
  3. supprime la ligne de jeton ;
  4. `user.save()`, qui valide le tout.
- La comparaison des dates rend aware une date naïve relue de SQLite (`replace(tzinfo=timezone.utc)`).

- [ ] **Step 1 : écrire les tests qui échouent** (`Notification.fake()`, `PwUser` défini en tâche 2, et un `PwTokenUser(Authenticatable, HasApiTokens, Notifiable, Model)`).
  - `test_send_reset_link_stores_hashed_token` : le statut vaut `RESET_LINK_SENT`, et la ligne en base contient `sha256(token)`, jamais le jeton en clair (on récupère le jeton par l'assertion du fake).
  - `test_unknown_email` : statut `INVALID_USER`, rien d'envoyé, aucune ligne.
  - `test_throttled_within_60_seconds` : deux envois à 30 s d'intervalle donnent `RESET_THROTTLED` la seconde fois, et un seul mail. À 61 s, le second passe et remplace le jeton (une seule ligne).
  - `test_reset_changes_password_and_consumes_token` : `PASSWORD_RESET`, `check_password` du nouveau mot de passe, ligne supprimée. Un second `reset` avec le même jeton donne `INVALID_TOKEN`.
  - `test_reset_rejects_wrong_token` : `INVALID_TOKEN`, mot de passe inchangé.
  - `test_reset_accepts_fresh_token_after_reload` : jeton créé, `DB.session.expire_all()`, `_now` + 59 min : `PASSWORD_RESET`.
  - `test_reset_rejects_expired_token` : idem à + 61 min : `INVALID_TOKEN`.
  - `test_reset_revokes_api_tokens` : un `PwTokenUser` avec 2 jetons d'API n'en a plus aucun après le `reset`.
  - `test_config_overrides_expiry` : `auth.passwords.expire` = 5, `_now` + 6 min : `INVALID_TOKEN`.
- [ ] **Step 2 : lancer les tests.** `.venv/bin/pytest tests/auth/test_passwords.py -q`. Attendu : ÉCHEC (module absent).
- [ ] **Step 3 : implémenter `passwords.py`.**
- [ ] **Step 4 : relancer les tests.** `.venv/bin/pytest tests/auth -q`. Attendu : SUCCÈS.
- [ ] **Step 5 : commit.** `git commit -m "feat: réinitialisation du mot de passe (Password, password_reset_tokens) (#59)"`

### Task 4: email verification

**Files:**
- Create: `src/flask_artisan/auth/verification.py`
- Modify: `src/flask_artisan/auth/__init__.py` (exports `MustVerifyEmail`, `EnsureEmailIsVerified`)
- Modify: `src/flask_artisan/skeleton/app/http/kernel.py` (alias `"verified": EnsureEmailIsVerified`)
- Modify: `src/flask_artisan/skeleton/config/auth.py` (clés `passwords` et `verification`, avec un commentaire)
- Test: `tests/auth/test_verification.py`

**Interfaces :**
- Consomme : `VerifyEmail` (tâche 2), importé dans `send_email_verification_notification` au moment de l'appel.
- Produit :
  - mixin `MustVerifyEmail`, qui porte `email_verified_at: Mapped[datetime | None]`, déclaré comme `SoftDeletes.deleted_at` ;
  - ses méthodes `has_verified_email() -> bool`, `mark_email_as_verified() -> None` et `send_email_verification_notification() -> None` ;
  - `__init_subclass__` lève `TypeError("<C> : placez MustVerifyEmail avant Model …")` si `Model` le précède dans le MRO ;
  - `class EnsureEmailIsVerified(Middleware)`, dont `handle(request, next)` suit la spec. L'utilisateur vient de `current_app.make(AuthManager).user()`. Si la route `verification.notice` est absente, la réponse est le 403 JSON.

- [ ] **Step 1 : écrire les tests qui échouent** (`VeUser(MustVerifyEmail, Authenticatable, Notifiable, Model)` et `VePlain(Authenticatable, Model)`. Routes de test : `GET /secret`, protégée par `auth` puis `EnsureEmailIsVerified`, `verification.notice` et `/api/secret` en JSON).
  - `test_column_and_methods` : `email_verified_at` est `None`, `has_verified_email()` vaut False, puis True après `mark_email_as_verified()` et relecture.
  - `test_model_before_mixin_is_refused` : `class X(Model, MustVerifyEmail)` lève un `TypeError`.
  - `test_unverified_user_is_redirected_to_notice` : 302 vers `/verify-email`.
  - `test_unverified_user_gets_json_on_api` : 403 et le message JSON.
  - `test_verified_user_passes` : 200.
  - `test_model_without_mixin_passes` : un `VePlain` connecté obtient 200.
  - `test_email_verified_at_not_mass_assignable` : `VeUser.create(..., email_verified_at=…)` n'affecte pas la colonne, ou lève `MassAssignmentError`, comme le fait `fillable` aujourd'hui.
  - `test_send_verification_notification` : avec `Notification.fake()`, `VerifyEmail` est envoyé à l'utilisateur.
- [ ] **Step 2 : lancer les tests.** `.venv/bin/pytest tests/auth/test_verification.py -q`. Attendu : ÉCHEC (import).
- [ ] **Step 3 : implémenter** le module, les exports, les alias du `Kernel` et `config/auth.py`.
- [ ] **Step 4 : relancer les tests.** `.venv/bin/pytest tests/auth tests/test_cli.py::test_generated_project_tests_pass -q`. Attendu : SUCCÈS.
- [ ] **Step 5 : commit.** `git commit -m "feat: MustVerifyEmail et middleware verified (#59)"`

### Task 5: load routes/auth.py

**Files:**
- Modify: `src/flask_artisan/route_provider.py`
- Test: `tests/test_route_provider.py`

**Interfaces :**
- Produit : `RouteServiceProvider.boot()` charge `base_path("routes/auth.py")`, avec `middleware=self._group("web")` et sans préfixe, après `web.py`. Il le fait seulement si le fichier existe.

- [ ] **Step 1 : écrire les tests qui échouent.**
  - `test_auth_routes_file_is_loaded_with_web_group` : un `routes/auth.py` qui déclare `GET /hello` nommée `hello` répond 200, et la route a le groupe `web` (`Router.registered` contient `VerifyCsrfToken`).
  - `test_missing_auth_routes_file_is_fine` : sans le fichier, l'app démarre.
- [ ] **Step 2 : lancer les tests.** `.venv/bin/pytest tests/test_route_provider.py -q`. Attendu : le premier test ÉCHOUE (404).
- [ ] **Step 3 : implémenter** (vérifier ce que `router.load` fait d'un fichier absent, et garder le même comportement).
- [ ] **Step 4 : relancer les tests.** `.venv/bin/pytest tests/test_route_provider.py -q`. Attendu : SUCCÈS.
- [ ] **Step 5 : commit.** `git commit -m "feat: routes/auth.py chargé dans le groupe web (#59)"`

### Task 6: flask auth:install

**Files:**
- Create: `src/flask_artisan/stubs/auth/…`. C'est l'arbre de la table « `flask auth:install` » de la spec. Chaque fichier y porte le suffixe `.stub`, par exemple `stubs/auth/routes/auth.py.stub`.
- Modify: `src/flask_artisan/console.py` (commande `auth_install`, ajoutée à la liste des commandes)
- Modify: `pyproject.toml` (`package-data` : `"stubs/auth/**/*"`)
- Test: `tests/test_console.py`, `tests/test_cli.py`

**Interfaces :**
- Consomme : tout ce qui précède. Les fichiers installés importent :
  - `from flask_artisan.auth import MustVerifyEmail` ;
  - `from flask_artisan.auth.passwords import Password` ;
  - `from flask_artisan.signing import ValidateSignature` ;
  - `from flask_artisan.auth.notifications import ResetPassword, VerifyEmail` (dans les tests installés).
- Produit : `@click.command("auth:install") @with_appcontext def auth_install()`.
  - Elle calcule la liste des cibles (chemin du stub sans `.stub`, par rapport à `base_path()`).
  - Si au moins une cible existe, elle n'écrit rien, affiche `Fichiers déjà présents, rien n'a été installé :` suivi de la liste, et lève `click.exceptions.Exit(1)`.
  - Sinon, elle écrit tout (dossiers créés), affiche `Créé : <chemin>` par fichier, puis les cinq étapes manuelles de la spec, numérotées.
- Les routes, controllers, FormRequests et vues sont conformes aux tables de la spec. Les controllers suivent le style de `SessionController` (`flash`, `redirect(url_for(...))`, `ValidationError` pour renvoyer en arrière).
  - `RegisteredUserController.store` crée par `User.create(name=…, email=…, password=…)`, jamais avec tout `validated()`.
  - `PasswordResetLinkController.store` flashe `"Si un compte existe pour cette adresse, un lien de réinitialisation vient d'être envoyé."` pour `RESET_LINK_SENT`, `INVALID_USER` et `RESET_THROTTLED`.
  - `NewPasswordController.store` : en cas de succès, flash `"Mot de passe réinitialisé : vous pouvez vous connecter."`, puis redirection vers `login`. Sinon, `ValidationError({"email": ["Ce lien de réinitialisation est invalide ou a expiré."]})`.
  - `EmailVerificationController.verify` répond `abort(403)` si `id != Auth.id()` ou si le `hash` ne correspond pas (`hmac.compare_digest`). Il marque l'e-mail vérifié s'il ne l'était pas, flashe `"Adresse e-mail vérifiée."` et redirige vers `dashboard`.
- Tests installés (`tests/test_auth_flows.py.stub`) :
  - un marqueur `needs_verification = pytest.mark.skipif(not issubclass(User, MustVerifyEmail), reason="Ajoutez MustVerifyEmail à User (étape 1 de flask auth:install).")` ;
  - `test_register_creates_user_and_logs_in`, `test_register_validates_input` ;
  - `test_forgot_password_sends_link`, `test_forgot_password_same_message_for_unknown_email` ;
  - `test_reset_password_with_emailed_token`, `test_reset_password_rejects_bad_token` ;
  - avec `@needs_verification` : `test_register_sends_verification`, `test_verify_link_marks_email_verified`, `test_verify_link_of_other_user_is_forbidden`, `test_verify_link_after_email_change_is_forbidden`, `test_tampered_verify_link_is_forbidden`, `test_resend_verification`.

- [ ] **Step 1 : écrire les tests qui échouent.**
  - Dans `tests/test_console.py` :
    - `test_auth_install_creates_files` : tous les fichiers de la table de la spec existent, sans suffixe `.stub`, et la sortie contient `MustVerifyEmail` et `flask make:migration`.
    - `test_auth_install_conflict_writes_nothing` : si `resources/views/auth/register.html` existe déjà, le code de sortie est 1, la sortie le nomme, et aucun autre fichier n'est créé.
  - Dans `tests/test_cli.py` :
    - `test_generated_project_auth_install` (sous-processus, fixture `project`) :
      1. `flask auth:install` sort avec 0 ;
      2. `pytest` du projet sort avec 0 et la sortie contient `skipped` ;
      3. on ajoute `MustVerifyEmail` au `User`, par remplacement de texte dans `app/models/user.py` (import et bases) ;
      4. `pytest` sort avec 0 et la sortie ne contient pas `skipped` ;
      5. `flask make:migration "auth install"` produit un fichier qui contient `password_reset_tokens` et `email_verified_at`, puis `flask migrate` sort avec 0 ;
      6. un second `flask auth:install` sort avec 1.
- [ ] **Step 2 : lancer les tests.** `.venv/bin/pytest tests/test_console.py -k auth_install tests/test_cli.py::test_generated_project_auth_install -q`. Attendu : ÉCHEC (commande inconnue).
- [ ] **Step 3 : implémenter** la commande, les stubs et `package-data`.
- [ ] **Step 4 : relancer les tests.** Même commande, attendu : SUCCÈS. Puis `.venv/bin/pytest -q`, attendu : SUCCÈS. Vérifier aussi `python -m build` ou `pip wheel . --no-deps -w <scratchpad>`, et `unzip -l` sur la wheel, qui doit montrer `stubs/auth/tests/test_auth_flows.py.stub` et les templates des mails.
- [ ] **Step 5 : commit.** `git commit -m "feat: flask auth:install (#59)"`

### Task 7: documentation

**Files:**
- Modify: `docs/authentification.md` (sections « Kit de démarrage : `flask auth:install` », « Mot de passe oublié », « Vérification de l'e-mail », « URLs signées »)
- Modify: `CHANGELOG.md` (`## [Non publié]`, section Ajouté)
- Modify: `CLAUDE.md` (une puce Architecture sur `auth:install`, `signing`, `passwords` importé à l'usage, et les templates du package en dernier dans le `ChoiceLoader`)

La doc doit dire :
- les cinq étapes manuelles ;
- le compteur `throttle:6,1` partagé entre les routes ;
- l'absence de retour à l'URL demandée après la connexion ;
- la révocation des jetons d'API à la réinitialisation ;
- comment surcharger un mail : template `resources/views/flask_artisan/emails/…`, ou méthode `send_*_notification` sur le `User` ;
- que l'URL absolue des mails vient de la requête en cours (derrière un proxy : `TRUSTED_PROXIES`).

- [ ] **Step 1 : écrire la doc.**
- [ ] **Step 2 : vérifier.** `.venv/bin/mkdocs build --strict`, attendu : aucune erreur. Puis `.venv/bin/ruff check . && .venv/bin/ruff format --check .`, attendu : propre.
- [ ] **Step 3 : commit.** `git commit -m "docs: kit de démarrage auth:install (#59)"`

# Notifications : plan d'implémentation

> **Pour les agents :** sous-skill requise : superpowers:subagent-driven-development (recommandé) ou superpowers:executing-plans pour exécuter ce plan tâche par tâche. Les étapes utilisent des cases à cocher (`- [ ]`).

**Objectif :** `user.notify(InvoicePaid(invoice))`, avec des canaux `mail` et `database`, une mise en file par canal, `Notification.route(...)` et `Notification.fake()`.

**Architecture :**
- Le paquet `flask_artisan/notifications/` contient :
  - `models.py` : `DatabaseNotification`, la table polymorphe avec un `id` UUID ;
  - `base.py` : `Notification`, qui porte les méthodes de classe `send`, `route`, `fake` et `restore` ;
  - `notifiable.py` : `Notifiable` et `AnonymousNotifiable` ;
  - `sender.py` : `NotificationSender`, les canaux, le mode fake et le job `SendQueuedNotification`.
- `Application` enregistre `"notifications"` par un `singleton` dont la fabrique importe le sender à la première résolution.

**Stack :** les modèles du framework (`Model`, `Builder`), `Mail.to(...).send`, `Queue.push`, la sérialisation de la file (`dump`/`load`, `class_path`, `import_class`).

**Spec :** [docs/superpowers/specs/GH-51-spec.md](../specs/GH-51-spec.md)

## Contraintes globales

- `Application` n'importe jamais `flask_artisan.notifications`. Après `Application(...)`, `"flask_artisan.notifications.models"` n'est pas dans `sys.modules`.
- **Table `notifications`** :
  - `id` en `String(36)`, clé primaire, `str(uuid4())` par défaut ;
  - `type`, `notifiable_type`, `notifiable_id` (index composite avec `notifiable_type`), `data` en JSON, `read_at` nullable, plus les timestamps.
- `type` et `notifiable_type` sont des chemins `class_path(...)`.
- Noms des canaux : `"mail"` et `"database"`. Une autre valeur lève `ValueError`, avec les canaux connus.
- Les modèles de test portent des noms uniques dans la suite : préfixe `N` (`NUser`, `NTeam`).
- Commits et PR : `(#51)`.

## Points à surveiller

1. **Un canal en échec** ne bloque pas les autres canaux ni les autres destinataires, en direct comme avec le pilote `sync`. Couvert par `test_failing_channel_does_not_stop_others` (tâche 2) et `test_queued_sync_failure_does_not_stop_others` (tâche 3).
2. **`to_database` qui renvoie un objet non JSON** (un modèle, un `datetime`) : `TypeError` clair, aucune ligne écrite. Couvert par `test_database_data_must_be_json` (tâche 1).
3. **Une notification en file** dont un attribut privé (`_x`) est injecté dans le payload, ou dont la classe n'est pas une `Notification` : refus. Couvert par `test_queued_payload_rejects_private_and_foreign_class` (tâche 3).
4. **Le hard delete d'un destinataire** supprime ses notifications, mais pas celles d'un autre type qui a le même `id`. Couvert par `test_hard_delete_removes_only_own_notifications` (tâche 1).
5. **Un destinataire sans email** sur le canal mail : rien n'est envoyé, un avertissement est loggé, sans exception. Couvert par `test_mail_without_route_is_skipped` (tâche 2).

---

### Task 1: model, Notification, Notifiable, database channel

**Fichiers :**
- Créer : `src/flask_artisan/notifications/__init__.py`, `models.py`, `base.py`, `notifiable.py`, `sender.py`, ainsi que `tests/notifications/__init__.py`, `conftest.py`, `models.py` et `test_database.py`.
- Modifier : `src/flask_artisan/application.py` (`self.singleton("notifications", fabrique)` à côté du mailer).

**Interfaces :**
- Produit :
  - `DatabaseNotification(Model)`, avec `mark_as_read()`, `mark_as_unread()`, `read() -> bool` et `unread() -> bool` ;
  - `Notification`, avec `via(notifiable) -> list[str]` (qui lève `NotImplementedError`), et les méthodes de classe `send(notifiables, notification)`, `route(channel, value) -> AnonymousNotifiable`, `fake() -> NotificationFake` et `restore()` ;
  - `Notifiable`, avec `notify(notification)`, les propriétés `notifications` et `unread_notifications` (qui renvoient un `Builder`), `route_notification_for(channel)` et la surcharge de `_hard_delete` ;
  - `NotificationSender(app)`, avec `send(notifiables, notification)` et `send_now(notifiable, notification, channels=None)`.
- Les méthodes de classe de `Notification` résolvent le service par `Application.get_instance().make("notifications")`.

- [ ] **Étape 1 : écrire les tests.**
  - **Fixture et modèles de test :**
    - `tests/notifications/conftest.py` construit une app par `db_app()`, crée les tables et ouvre un `app_context` ;
    - `models.py` déclare `NUser(Notifiable, Model)` (avec `email` et `name`) et `NTeam(Notifiable, Model)` (avec `name`).
  - **Tests :**
    - `test_application_does_not_import_notifications` : dans un sous-processus (`sys.executable -c`), créer une `Application` sur un projet de `make_project`, puis vérifier que `flask_artisan.notifications.models` est absent de `sys.modules` ;
    - `test_notify_database` : une notification `via → ["database"]` dont `to_database` renvoie `{"n": 1}`. Après `user.notify(...)`, `user.notifications.count() == 1`. La ligne a `type == class_path(Cls)`, `notifiable_type == class_path(NUser)`, `data == {"n": 1}`, `read_at is None`, et un `id` de 36 caractères ;
    - `test_polymorphic` : un `NUser` et un `NTeam` qui ont le même `id` ne voient que leurs propres notifications ;
    - `test_unread_and_mark` : deux notifications ; `mark_as_read()` sur la plus récente, puis `unread_notifications.count() == 1` et `notifications.first()` est la plus récente ; `mark_as_unread()` remet `read_at` à `None` ;
    - `test_database_data_must_be_json` : `to_database` qui renvoie `{"u": user}` lève `TypeError`, avec le nom de la classe ; aucune ligne n'est écrite ;
    - `test_unknown_channel` : `via → ["sms"]` lève `ValueError`, avec `"sms"` ;
    - `test_missing_to_method` : `via → ["database"]` sans `to_database` lève `NotImplementedError`, avec `to_database` ;
    - `test_hard_delete_removes_only_own_notifications` : on notifie le `NUser` 1 et le `NTeam` 1 ; le hard delete du `NUser` laisse la notification du `NTeam`.
- [ ] **Étape 2 : RED.** Lancer `.venv/bin/pytest tests/notifications -q`.
  Attendu : ÉCHEC à l'import.
- [ ] **Étape 3 : implémenter.**
  - `send_now` applique la règle d'échec de la spec : essayer tous les canaux, puis relever la première exception. Le canal mail arrive à la tâche 2. Ici, un canal `mail` lève encore `NotImplementedError`.
  - `data` est validé par `json.dumps` avant le `create`.
  - La fabrique du singleton est une fonction de module dans `application.py` qui importe `NotificationSender` dans son corps. Vérifier que `Container._container_build` appelle une fonction en lui injectant l'app ; sinon, enregistrer une classe paresseuse et le noter en ruling.
- [ ] **Étape 4 : GREEN.** Lancer `.venv/bin/pytest tests/notifications tests/test_application.py tests/orm -q`.
  Attendu : tout passe.
- [ ] **Étape 5 : commit** `feat: notifications, canal database et Notifiable (#51)`.

### Task 2: mail channel, on-demand, several notifiables

**Fichiers :**
- Modifier : `src/flask_artisan/notifications/sender.py`, `notifiable.py` et `__init__.py` (export d'`AnonymousNotifiable`).
- Créer : `tests/notifications/test_mail.py`.

**Interfaces :**
- Consomme : `NotificationSender.send_now` de la tâche 1.
- Produit : `AnonymousNotifiable`, avec `route(channel, value) -> self`, `notify(notification)` et `route_notification_for(channel)`. Le canal `mail` appelle `Mail.to(route).send(notification.to_mail(n))`.

- [ ] **Étape 1 : écrire les tests.** On utilise `Mail.fake()` du framework.
  - `test_notify_mail` : `via → ["mail"]`, et `to_mail` renvoie un `Mailable` de test ; `fake.assert_sent(TheMail, lambda m: m.has_to("a@x.org"))` ;
  - `test_route_notification_for_mail_override` : un modèle qui définit `route_notification_for_mail()` et renvoie `("Ada", "ada@x.org")` ; le mail part vers `ada@x.org` ;
  - `test_mail_without_route_is_skipped` : un `NUser` avec `email=None` ; rien n'est envoyé, un avertissement est loggé (`caplog`), sans exception ;
  - `test_send_many` : `Notification.send([u1, u2], n)` envoie deux mails et crée deux lignes en base ;
  - `test_on_demand` : `Notification.route("mail", "x@y.org").notify(n)` envoie le mail ; avec `via → ["database"]`, l'envoi lève `ValueError` ;
  - `test_failing_channel_does_not_stop_others` : `to_mail` lève `RuntimeError("boom")`, et `via → ["mail", "database"]` pour deux destinataires ; les deux lignes en base existent, et `RuntimeError` est relevée une fois.
- [ ] **Étape 2 : RED.** Lancer `.venv/bin/pytest tests/notifications/test_mail.py -q`.
  Attendu : ÉCHEC.
- [ ] **Étape 3 : implémenter.** Le destinataire mail par défaut de `Notifiable` est `getattr(self, "email", None)`. Une méthode `route_notification_for_<canal>` sur le modèle a la priorité.
- [ ] **Étape 4 : GREEN.** Lancer `.venv/bin/pytest tests/notifications tests/mail -q`.
  Attendu : tout passe.
- [ ] **Étape 5 : commit** `feat: canal mail, notifications à la demande et envoi groupé (#51)`.

### Task 3: queued notifications

**Fichiers :**
- Modifier : `src/flask_artisan/notifications/sender.py` (le job `SendQueuedNotification(Job)` et la mise en file dans `send`).
- Créer : `tests/notifications/test_queue.py`.

**Interfaces :**
- Consomme : `Job`, `ShouldQueue`, `class_path`, `import_class`, `dump` et `load` de la file.
- Produit :
  - `SendQueuedNotification.wrap(notification, notifiable, channel) -> SendQueuedNotification` ;
  - `handle(self, sender: NotificationSender)`, qui appelle `sender.send_now(notifiable, notification, [channel])`.
- Pour un `AnonymousNotifiable`, le job porte `notifiable = {"routes": {...}}` et le reconstruit.

- [ ] **Étape 1 : écrire les tests.**
  - `test_queued_one_job_per_channel_and_notifiable` : avec `Queue.fake()`, une notification `ShouldQueue` sur `["mail", "database"]` et deux destinataires donne quatre `SendQueuedNotification` ; `queue = "notifs"` sur la classe donne des jobs sur `"notifs"` ;
  - `test_queued_sync_runs` : avec le pilote `sync` (le défaut des tests), la ligne en base est créée et le mail est enregistré par `Mail.fake()` ;
  - `test_queued_round_trip_json` : `dump` du job, `json.dumps`, puis `load`, puis `handle` crée la ligne. Le destinataire voyage par identifiant, et un attribut modèle de la notification aussi ;
  - `test_queued_sync_failure_does_not_stop_others` : la même chose que la tâche 2, en `ShouldQueue` et avec le pilote `sync` ;
  - `test_queued_payload_rejects_private_and_foreign_class` : un `notification_data` avec `"_secret"` lève `TypeError` ; un `notification_class` qui vaut `"collections.OrderedDict"` lève `TypeError` ;
  - `test_queued_on_demand` : `Notification.route("mail", "x@y.org").notify(queued)` envoie le mail par le job.
- [ ] **Étape 2 : RED.** Lancer `.venv/bin/pytest tests/notifications/test_queue.py -q`.
  Attendu : ÉCHEC.
- [ ] **Étape 3 : implémenter.**
  - On prend le modèle de `CallQueuedListener.wrap` et `handle` : les attributs publics passent par la sérialisation, et `tries`, `backoff`, `timeout` et `queue` sont repris de la classe de la notification.
  - Dans `send`, chaque `push` est entouré d'un `try`. La première erreur est relevée à la fin.
- [ ] **Étape 4 : GREEN.** Lancer `.venv/bin/pytest tests/notifications tests/queues -q`.
  Attendu : tout passe.
- [ ] **Étape 5 : commit** `feat: notifications mises en file, un job par canal (#51)`.

### Task 4: Notification.fake()

**Fichiers :**
- Modifier : `src/flask_artisan/notifications/sender.py` (mode fake et `NotificationFake`).
- Créer : `tests/notifications/test_fake.py`.

**Interfaces :**
- Produit : `NotificationFake`, avec `restore()`, `__enter__` et `__exit__`, `sent(cls) -> list[(notifiable, notification, channels)]`, `assert_sent_to(notifiable, cls, callback=None)`, `assert_not_sent_to(...)`, `assert_sent_times(cls, n)`, `assert_nothing_sent()` et `assert_sent_on_demand(cls, callback=None)`.

- [ ] **Étape 1 : écrire les tests.**
  - `test_fake_records_without_sending` : `with Notification.fake() as fake:` puis `user.notify(n)` ; aucune ligne en base, aucun mail (`Mail.fake()`), aucun job (`Queue.fake()`) ; `assert_sent_to(user, Cls)` passe ; `assert_sent_to(other_user, Cls)` lève `AssertionError` ;
  - `test_fake_matches_model_by_identity_of_row` : un `NUser.find(user.id)` rechargé compte comme le même destinataire ;
  - `test_fake_callback_and_times` : le `callback(notification, channels)` reçoit `["mail", "database"]` ; `assert_sent_times(Cls, 2)` passe ;
  - `test_fake_on_demand` : `assert_sent_on_demand(Cls, lambda n, ch: True)` ;
  - `test_fake_restore` : après le `with`, `user.notify` écrit de nouveau en base ;
  - `test_assert_nothing_sent`.
- [ ] **Étape 2 : RED.** Lancer `.venv/bin/pytest tests/notifications/test_fake.py -q`.
  Attendu : ÉCHEC.
- [ ] **Étape 3 : implémenter.** C'est un mode du sender, sur le modèle de `Mail.fake()`. Les canaux enregistrés sont ceux de `via(notifiable)`.
- [ ] **Étape 4 : GREEN.** Lancer `.venv/bin/pytest tests/notifications -q`.
  Attendu : tout passe.
- [ ] **Étape 5 : commit** `feat: Notification.fake() et ses assertions (#51)`.

### Task 5: make:notification, skeleton, docs

**Fichiers :**
- Créer : `src/flask_artisan/stubs/notification.stub`, `src/flask_artisan/skeleton/app/notifications/.gitkeep` et `docs/notifications.md`.
- Modifier :
  - le code et le squelette : `src/flask_artisan/console.py` (`make_notification`, dans `COMMANDS`), `skeleton/app/models/user.py` (`Notifiable`) et `pyproject.toml` (`package-data` : `skeleton/app/notifications/.gitkeep`) ;
  - les tests : `tests/test_console.py`, et `tests/test_cli.py`, où `test_generated_project_notifications` vérifie dans un projet généré : `make:migration`, `migrate`, un utilisateur notifié en base, puis la lecture de `unread_notifications`.
  - le site et le repo : `mkdocs.yml` (après Mail), `docs/console.md`, `README.md`, `CLAUDE.md` et `CHANGELOG.md`.

- [ ] **Étape 1 : écrire les tests.**
  - `test_make_notification` : le fichier `app/notifications/invoice_paid.py` contient `class InvoicePaid(Notification)` ; une deuxième exécution sans `--force` échoue.
  - `test_generated_project_notifications`, voir plus haut.
- [ ] **Étape 2 : RED.** Lancer `.venv/bin/pytest tests/test_console.py -k notification tests/test_cli.py::test_generated_project_notifications -q`.
  Attendu : ÉCHEC.
- [ ] **Étape 3 : implémenter.** `make:notification` reprend `make:job` (`write_stub("app/notifications", name, "notification")`). Les sous-dossiers sont acceptés comme pour `make:job` : les notifications sont importées explicitement, jamais découvertes. C'est un écart avec la spec, à noter en ruling.
- [ ] **Étape 4 : écrire la doc,** comme le dit la spec, section « Doc ».
- [ ] **Étape 5 : vérification complète.** Lancer `.venv/bin/pytest -q`, `.venv/bin/ruff check .`, `.venv/bin/ruff format --check .` et `.venv/bin/mkdocs build --strict`.
  Attendu : tout passe.
- [ ] **Étape 6 : commit** `feat: make:notification, squelette, page Notifications (#51)`.

# Mail (GH-24) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `Mailable` + `Mail.to(...).send(...)`, transports `smtp` / `log` / `array` choisis par `config/mail.py`, `Mail.fake()`, `flask make:mail`, templates cherchés dans `resources/views/` puis `templates/`, doc complète.

**Architecture:** un module `src/flask_artisan/mail.py` (`Mailable`, `Attachment`, `Mailer`, `PendingMail`, transports, `MailFake`), bibliothèque standard seulement (`email.message`, `email.utils`, `smtplib`, `mimetypes`). `Application.__init__` crée le `Mailer` à côté du `Dispatcher` et affecte à l'instance un `ChoiceLoader` Jinja sur les deux dossiers. Le fake est un mode du `Mailer` (comme `Event.fake()`).

**Tech Stack:** Flask ≥ 3 (Jinja), click, pytest, ruff.

**Spec:** `docs/superpowers/specs/GH-24-spec.md`

## Global Constraints

- Aucune nouvelle dépendance. Aucun attribut ni méthode de classe ajouté à `Application` qui existe dans `dir(Flask)` (`test_application_does_not_override_flask`) : `jinja_loader` est affecté **à l'instance**.
- Config lue à chaque envoi ; seul un transport `array` est gardé (un par nom de mailer) ; `smtp` et `log` reconstruits à chaque envoi.
- Défauts sans `config/mail.py` : `default = "log"`, mailers `smtp` (127.0.0.1:2525, sans chiffrement), `log`, `array` ; `from = hello@example.com`, nom = `app.name` sinon `"Flask-Artisan"`.
- Erreurs : forme de destinataire invalide → `TypeError` ; adresse sans `@`, `\r`/`\n` dans une adresse, un nom ou le sujet, aucun destinataire, ni `view` ni `text`, mailer / transport / `encryption` inconnus → `ValueError` qui nomme la valeur. Les exceptions de `smtplib` remontent telles quelles.
- `Bcc` jamais en en-tête. `Message-ID` généré avec le domaine de l'expéditeur (`make_msgid(domain=…)`, pas de résolution du nom d'hôte).
- Fake : enregistre `copy.copy(mailable)` avec ses destinataires, ne rend ni n'envoie ; les erreurs de destinataires restent levées.
- Exports : `Mail` dans `flask_artisan.__all__` ; `Mailable`, `Attachment`, `Mailer`, `MailFake` dans `flask_artisan.mail.__all__`.
- Commits `… (#24)` ; code et fichiers générés passent `ruff check` / `ruff format --check`. Aucun test ne touche le réseau.

## Review Focus

1. Envoi hors de tout contexte d'application (commande CLI, écouteur appelé depuis un script) : le template est rendu, avec l'app du `Mailer` — test dans la Task 2.
2. Un même objet mailable envoyé à deux personnes sous fake : chaque enregistrement garde ses propres destinataires — test dans la Task 4.
3. Saut de ligne dans le sujet ou un nom de destinataire : `ValueError`, rien n'est passé au transport — test dans la Task 2.
4. Un service qui a reçu le `Mailer` par injection avant `Mail.fake()` passe par le fake — test dans la Task 4.
5. Un projet qui n'a que `templates/` : `render_template` d'une route le trouve toujours ; un nom présent dans les deux dossiers vient de `resources/views/` — test dans la Task 1.

---

### Task 1: Templates dans `resources/views/` puis `templates/`

**Files:**
- Modify: `src/flask_artisan/application.py`
- Test: `tests/test_application.py`

**Interfaces:**
- Produces: `app.jinja_loader` = `jinja2.ChoiceLoader([FileSystemLoader(base/"resources/views"), FileSystemLoader(base/"templates")])`, affecté dans `__init__` juste après `Flask.__init__`.

- [ ] **Step 1: Write the failing tests** — dans `tests/test_application.py`, un helper qui écrit des fichiers sous le projet de `make_project()`, puis :

```python
def test_templates_found_in_resources_views(make_project):
    base = make_project()
    write(base / "resources/views/hello.html", "views {{ name }}")
    app = Application(base)
    with app.app_context():
        assert render_template("hello.html", name="A") == "views A"

def test_templates_folder_still_works(make_project):
    base = make_project()
    write(base / "templates/old.html", "flask")
    app = Application(base)
    with app.test_request_context():
        assert render_template("old.html") == "flask"

def test_resources_views_wins_over_templates(make_project):
    base = make_project()
    write(base / "resources/views/same.html", "views")
    write(base / "templates/same.html", "flask")
    with Application(base).app_context():
        assert render_template("same.html") == "views"
```

- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_application.py -q` — Expected: les deux tests `resources/views` échouent (`TemplateNotFound`), `templates_folder_still_works` passe déjà (défaut Flask).

- [ ] **Step 3: Implement** — `from jinja2 import ChoiceLoader, FileSystemLoader` ; dans `__init__` après `Flask.__init__`, `self.jinja_loader = ChoiceLoader([...])` avec un commentaire d'une ligne (convention Laravel d'abord, défaut Flask ensuite ; affecté à l'instance pour ne pas masquer Flask).

- [ ] **Step 4: Run** `.venv/bin/pytest tests/test_application.py -q` — Expected: PASS, y compris `test_application_does_not_override_flask`.

- [ ] **Step 5: Commit** `feat: templates cherchés dans resources/views puis templates (#24)`

---

### Task 2: `Mailable`, destinataires, `Mailer`, transport `array`, façade `Mail`

**Files:**
- Create: `src/flask_artisan/mail.py`, `tests/mail/__init__.py`, `tests/mail/conftest.py`, `tests/mail/test_mailable.py`, `tests/mail/test_mailer.py`
- Modify: `src/flask_artisan/application.py`, `src/flask_artisan/facades.py`, `src/flask_artisan/__init__.py`

**Interfaces:**
- Produces:
  - `class Attachment` : `from_path(path, name=None, mime=None)`, `from_data(data: bytes | str, name: str, mime=None)` (classmethods) ; attributs `name`, `mime` (deviné par `mimetypes.guess_type(name)`, sinon `application/octet-stream`), méthode `read() -> bytes`.
  - `class Mailable` : attributs de classe `subject = ""`, `view = None`, `text = None`, `reply_to = None` ; `context() -> dict` (attributs d'instance sans `_`) ; `attachments() -> list` (`[]`) ; `has_to(x)`, `has_cc(x)`, `has_bcc(x) -> bool` (lisent `self._recipients = {"to": [...], "cc": [...], "bcc": [...]}`, adresses nues en minuscules).
  - `_addresses(value) -> list[tuple[str, str]]` : `(nom, adresse)` depuis chaîne (`email.utils.parseaddr`), tuple `(adresse, nom)`, objet avec `email` (+ `name` facultatif), ou liste ; erreurs selon Global Constraints.
  - `class Mailer` : `__init__(self, app)`, `to(*recipients) -> PendingMail`, `mailer(name: str) -> PendingMail`, `transport(name: str | None = None)`, `_send(pending, mailable) -> None`, `_build(mailable, envelope) -> EmailMessage`.
  - `class PendingMail` : `to(*r)`, `cc(*r)`, `bcc(*r)` → `self` ; `send(mailable) -> None`.
  - `class ArrayTransport` : `messages: list[EmailMessage]`, `send(message, recipients)`, `flush()`.
  - `app.make("mail") is app.make(Mailer)` ; `class Mail(Facade): accessor = "mail"`.

- [ ] **Step 1: Write the failing tests.** `tests/mail/conftest.py` : fixture `mail_app(make_project)` qui crée le projet, écrit `resources/views/emails/hello.html` (`<p>Hello {{ name }}</p>`) et `emails/hello.txt` (`Hello {{ name }}`), écrit `config/mail.py` avec `default = "array"` et `from = {"address": "shop@x.org", "name": "Shop"}`, et renvoie `Application(base)`. Mailables de test au niveau module : `Hello(Mailable)` (`subject="Hi"`, `view`, `text`, `__init__(self, name)`), `HtmlOnly`, `TextOnly`, `Empty`.

`test_mailable.py` :

```python
def test_context_is_public_attributes():
    m = Hello("A"); m._secret = 1
    assert m.context() == {"name": "A"}

def test_attachment_from_path_guesses_name_and_mime(tmp_path):
    p = tmp_path / "facture.pdf"; p.write_bytes(b"%PDF")
    a = Attachment.from_path(p)
    assert (a.name, a.mime, a.read()) == ("facture.pdf", "application/pdf", b"%PDF")

def test_attachment_from_data_defaults_to_octet_stream():
    assert Attachment.from_data(b"x", "blob").mime == "application/octet-stream"

@pytest.mark.parametrize(("value", "expected"), [
    ("a@x.org", [("", "a@x.org")]),
    ("Alice <a@x.org>", [("Alice", "a@x.org")]),
    (("a@x.org", "Alice"), [("Alice", "a@x.org")]),
    (SimpleNamespace(email="a@x.org", name="Alice"), [("Alice", "a@x.org")]),
    (SimpleNamespace(email="a@x.org"), [("", "a@x.org")]),
    (["a@x.org", ("b@x.org", "B")], [("", "a@x.org"), ("B", "b@x.org")]),
])
def test_addresses_forms(value, expected): assert _addresses(value) == expected

def test_addresses_invalid_form(): pytest.raises(TypeError, _addresses, 42)
def test_addresses_without_at(): pytest.raises(ValueError, _addresses, "nobody")
@pytest.mark.parametrize("bad", ["a@x.org\nBcc: z@x.org", ("a@x.org", "A\r\nB")])
def test_addresses_reject_newlines(bad): pytest.raises(ValueError, _addresses, bad)
```

`test_mailer.py` (via `mail_app`) :

```python
def test_registered_in_container(mail_app):
    assert mail_app.make("mail") is mail_app.make(Mailer)

def test_send_renders_html_and_text(mail_app):
    Mail.to("Alice <a@x.org>").send(Hello("A"))
    [msg] = Mail.transport("array").messages
    assert msg["Subject"] == "Hi" and msg["From"] == "Shop <shop@x.org>"
    assert msg["To"] == "Alice <a@x.org>" and msg["Message-ID"] and msg["Date"]
    assert msg.get_body(("plain",)).get_content().strip() == "Hello A"
    assert "<p>Hello A</p>" in msg.get_body(("html",)).get_content()

def test_html_escaped_text_not(mail_app):  # nom "<b>" échappé en HTML, brut en texte

def test_html_only_and_text_only(mail_app):  # content-type text/html, puis text/plain, non multipart

def test_without_view_or_text_raises(mail_app):
    with pytest.raises(ValueError, match="Empty"): Mail.to("a@x.org").send(Empty())

def test_bcc_not_in_headers_but_delivered(mail_app):
    transport = Mail.transport("array")
    Mail.to("a@x.org").cc("c@x.org").bcc("b@x.org").send(Hello("A"))
    msg = transport.messages[0]
    assert "Bcc" not in msg and msg["Cc"] == "c@x.org"
    assert transport.recipients[0] == ["a@x.org", "c@x.org", "b@x.org"]

def test_reply_to_and_attachments(mail_app, tmp_path): ...  # Reply-To présent ; 2 pièces jointes (from_path, from_data) avec nom et type

def test_subject_with_newline_raises_and_sends_nothing(mail_app):
    class Bad(Hello): subject = "Hi\nBcc: z@x.org"
    with pytest.raises(ValueError): Mail.to("a@x.org").send(Bad("A"))
    assert Mail.transport("array").messages == []

def test_no_recipient_raises(mail_app): pytest.raises(ValueError, Mail.to([]).send, Hello("A"))

def test_send_outside_app_context(mail_app):
    # hors de tout `with app_context()` : le Mailer pousse celui de son app
    mail_app.make(Mailer).to("a@x.org").send(Hello("A"))
    assert len(Mail.transport("array").messages) == 1

def test_mailer_by_name_and_unknown(mail_app):
    Mail.mailer("array").to("a@x.org").send(Hello("A"))
    with pytest.raises(ValueError, match="nope"): Mail.mailer("nope")

def test_config_read_on_each_send(mail_app):
    mail_app.make("config").set("mail.from.address", "new@x.org")
    Mail.to("a@x.org").send(Hello("A"))
    assert "new@x.org" in Mail.transport("array").messages[0]["From"]

def test_defaults_without_config_file(make_project):
    app = Application(make_project())
    with app.app_context():
        assert app.make("config").get("mail") is None
        assert type(Mail.transport()).__name__ == "LogTransport"   # défaut log

def test_flush(mail_app): ...  # flush() vide messages et recipients
```

(`ArrayTransport` garde aussi `recipients: list[list[str]]`, en parallèle de `messages`.)

- [ ] **Step 2: Run** `.venv/bin/pytest tests/mail -q` — Expected: erreur d'import (`flask_artisan.mail` absent).

- [ ] **Step 3: Implement** `mail.py` (sans `smtp`/`log` réels : `_transport` lève `ValueError` pour un nom de transport inconnu ; `log` et `smtp` arrivent en Task 3 — pour le test des défauts, créer dès maintenant une `LogTransport` minimale), le `Mailer` dans `Application.__init__` (`"mail"` et `Mailer`), la façade et l'export. Points non déterminés par les tests :
  - rendu : `if has_app_context() and current_app._get_current_object() is self._app: render_template(...)`, sinon `with self._app.app_context(): ...` ;
  - adresses dans les en-têtes avec `email.utils.formataddr` ; sujet et adresses vérifiés (`\r`, `\n`) avant toute construction ;
  - destinataires du transport = adresses nues To + Cc + Bcc, dans cet ordre ;
  - le `Mailer` enregistre l'enveloppe sur le mailable (`mailable._recipients`) avant d'appeler le transport.

- [ ] **Step 4: Run** `.venv/bin/pytest tests/mail tests/test_application.py -q` — Expected: PASS.

- [ ] **Step 5: Commit** `feat: Mailable, Mail.to().send(), transport array et façade Mail (#24)`

---

### Task 3: Transports `smtp` et `log`

**Files:**
- Modify: `src/flask_artisan/mail.py`
- Test: `tests/mail/test_transports.py`

**Interfaces:**
- Consumes: `Mailer._transport(name)` / config `mail.mailers.<nom>` de la Task 2.
- Produces: `SmtpTransport(host, port, username=None, password=None, encryption=None, timeout=10)`, `LogTransport(logger)` ; tous deux `send(message, recipients)`.

- [ ] **Step 1: Write the failing tests.** Un `FakeSMTP` qui enregistre dans une liste de classe `calls` : `__init__(host, port, timeout=...)`, `starttls()`, `login(u, p)`, `send_message(msg, to_addrs=...)`, `quit()` / context manager ; `monkeypatch.setattr("flask_artisan.mail.smtplib.SMTP", FakeSMTP)` et `SMTP_SSL` vers une sous-classe `FakeSSL`. Config écrite par un helper `use(mail_app, **smtp)` qui met `mail.default = "smtp"` et `mail.mailers.smtp` dans le `Repository`.

```python
def test_smtp_starttls_and_login(...):  # encryption="tls", port="587" → FakeSMTP("h", 587), starttls, login("u","p"), send_message(to_addrs=[...])
def test_smtp_ssl(...):                 # encryption="ssl" → FakeSSL, pas de starttls
@pytest.mark.parametrize("enc", [None, ""])
def test_smtp_plain_without_login(...): # pas de starttls ni login quand username vide
def test_smtp_unknown_encryption(...):  # ValueError match "starttls"
def test_smtp_error_propagates(...):    # FakeSMTP.send_message lève SMTPRecipientsRefused → remonte telle quelle
def test_smtp_rebuilt_each_send(...):   # changer host entre deux envois → deux hosts vus
def test_unknown_transport(...):        # mailers.x = {"transport": "carrier-pigeon"} → ValueError match "carrier-pigeon"
def test_log_transport(mail_app, caplog):
    # default "log", password "s3cret" dans mailers.smtp ; caplog.at_level(INFO)
    # le log contient "a@x.org", le sujet, "Hello A" ; pas "s3cret"
```

- [ ] **Step 2: Run** `.venv/bin/pytest tests/mail/test_transports.py -q` — Expected: FAIL (`SmtpTransport` absent / transport non géré).

- [ ] **Step 3: Implement** — `SmtpTransport.send` : `cls = smtplib.SMTP_SSL if ssl else smtplib.SMTP` ; `with cls(host, int(port), timeout=timeout) as smtp:` ; `starttls()` si `tls` ; `login` si `username` ; `send_message(message, to_addrs=recipients)`. `encryption` vide → `None`. `LogTransport.send` : `logger.info("Mail pour %s :\n%s", ", ".join(recipients), message.as_string())` avec `app.logger`.

- [ ] **Step 4: Run** `.venv/bin/pytest tests/mail -q` — Expected: PASS.

- [ ] **Step 5: Commit** `feat: transports smtp (STARTTLS, SSL) et log (#24)`

---

### Task 4: `Mail.fake()`

**Files:**
- Modify: `src/flask_artisan/mail.py`
- Test: `tests/mail/test_mail_fake.py`

**Interfaces:**
- Consumes: `PendingMail.send`, `Mailer`, `mailable._recipients` (Task 2).
- Produces: `Mailer.fake() -> MailFake` ; `MailFake` : `restore()`, `__enter__`/`__exit__`, `sent(cls) -> list`, `assert_sent(cls, callback=None)`, `assert_sent_times(cls, n)`, `assert_not_sent(cls, callback=None)`, `assert_nothing_sent()`. Chaque élément de `sent()` porte `mailer` (nom du mailer utilisé) comme attribut privé `_mailer`.

- [ ] **Step 1: Write the failing tests** (sur le modèle de `tests/test_event_fake.py`) :

```python
def test_fake_records_without_rendering_or_sending(mail_app):
    with Mail.fake() as fake:
        Mail.to("a@x.org").send(Empty())          # Empty ne se rend pas : pas d'erreur sous fake
    fake.assert_sent(Empty)
    assert Mail.transport("array").messages == []

def test_assert_sent_with_callback_and_recipients(mail_app):
    with Mail.fake() as fake:
        Mail.to("a@x.org").cc("c@x.org").send(Hello("A"))
    fake.assert_sent(Hello, lambda m: m.name == "A" and m.has_to("A@X.org") and m.has_cc("c@x.org"))
    with pytest.raises(AssertionError, match="Hello"):
        fake.assert_sent(Hello, lambda m: m.has_to("z@x.org"))

def test_same_instance_two_recipients(mail_app):
    m = Hello("A")
    with Mail.fake() as fake:
        Mail.to("a@x.org").send(m); Mail.to("b@x.org").send(m)
    first, second = fake.sent(Hello)
    assert first.has_to("a@x.org") and not first.has_to("b@x.org") and second.has_to("b@x.org")

def test_assert_sent_times_not_sent_nothing_sent(mail_app): ...  # succès et messages d'échec (nom de classe + compte)
def test_subclass_counts(mail_app): ...                          # class Welcome(Hello) ; assert_sent(Hello) passe
def test_invalid_recipient_still_raises(mail_app):
    with Mail.fake(): pytest.raises(ValueError, Mail.to("nobody").send, Hello("A"))
def test_injected_mailer_is_faked(mail_app):
    held = mail_app.make(Mailer)
    with Mail.fake() as fake: held.to("a@x.org").send(Hello("A"))
    fake.assert_sent(Hello); assert Mail.transport("array").messages == []
def test_restore_and_superseded_fake(mail_app):
    # après restore, envoi réel ; un fake remplacé ne restaure pas le plus récent
```

- [ ] **Step 2: Run** `.venv/bin/pytest tests/mail/test_mail_fake.py -q` — Expected: FAIL (`fake` absent).

- [ ] **Step 3: Implement** — état `_faking`, `_recorded` sur le `Mailer` ; dans l'envoi, normaliser les destinataires (erreurs levées), puis si `_faking` : `copy.copy(mailable)`, poser `_recipients` et `_mailer` sur la copie, l'ajouter, retourner. Messages d'assertion en français, sur le modèle d'`EventFake` (« Mail Hello envoyé 0 fois, attendu au moins 1. »).

- [ ] **Step 4: Run** `.venv/bin/pytest tests/mail -q` — Expected: PASS.

- [ ] **Step 5: Commit** `feat: Mail.fake() et ses assertions (#24)`

---

### Task 5: `make:mail`, squelette, bout en bout

**Files:**
- Create: `src/flask_artisan/stubs/mail.stub`, `src/flask_artisan/stubs/mail.view.stub`, `src/flask_artisan/skeleton/config/mail.py`, `src/flask_artisan/skeleton/app/mail/__init__.py`, `src/flask_artisan/skeleton/resources/views/emails/.gitkeep`
- Modify: `src/flask_artisan/console.py` (`make_mail`, ajout à `COMMANDS`), `src/flask_artisan/skeleton/.env.example`, `pyproject.toml` (`package-data` : `"skeleton/resources/views/emails/.gitkeep"`)
- Test: `tests/test_console.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: `write_stub`, `split_name`, `class_to_file`, `_import_line` ; `Mail`, `Mailable` (Tasks 2–4).
- Produces: `flask make:mail NAME [--force]` → `app/mail/<dirs>/<file>.py` (`view = "emails/<dirs>/<file>.html"`) et `resources/views/emails/<dirs>/<file>.html`.

- [ ] **Step 1: Write the failing tests.** `tests/test_console.py` :

```python
def test_make_mail_creates_class_and_template(artisan):
    app, run = artisan
    result = run("make:mail", "OrderShipped")
    assert result.exit_code == 0, result.output
    path = app.base_path("app/mail/order_shipped.py")
    cls = load(path).OrderShipped
    assert issubclass(cls, Mailable) and cls.view == "emails/order_shipped.html"
    assert app.base_path("resources/views/emails/order_shipped.html").is_file()
    assert "Mail.to(" in result.output and "from app.mail.order_shipped import OrderShipped" in result.output
    assert_ruff_clean(path)

def test_make_mail_subfolder(artisan):  # Admin/Invoice → app/mail/admin/invoice.py, emails/admin/invoice.html, view correspondant

def test_make_mail_existing_template_writes_nothing(artisan):
    app, run = artisan
    tpl = app.base_path("resources/views/emails/order_shipped.html"); tpl.parent.mkdir(parents=True); tpl.write_text("mine")
    assert run("make:mail", "OrderShipped").exit_code != 0
    assert not app.base_path("app/mail/order_shipped.py").exists() and tpl.read_text() == "mine"

def test_make_mail_force_overwrites_both(artisan): ...
```

`tests/test_cli.py` : ajouter `"config/mail.py"`, `"app/mail/__init__.py"`, `"resources/views/emails/.gitkeep"` à un test d'existence, `MAIL_MAILER=log` dans `.env`, et :

```python
def test_generated_project_mail_flow(project):
    assert run(project, "-m", "flask", "make:mail", "Welcome").returncode == 0
    (project / "resources/views/emails/welcome.html").write_text("<p>Bienvenue {{ name }}</p>")
    mail = project / "app/mail/welcome.py"
    mail.write_text(mail.read_text() + "\n\nWelcome.__init__ = lambda self, name: setattr(self, 'name', name)\n")
    code = (
        "from wsgi import app\nfrom flask_artisan import Mail\nfrom app.mail.welcome import Welcome\n"
        "with Mail.fake() as fake:\n    Mail.to('a@x.org').send(Welcome('A'))\n"
        "fake.assert_sent(Welcome, lambda m: m.has_to('a@x.org'))\n"
        "Mail.to('a@x.org').send(Welcome('A'))\n"          # transport log par défaut : ne plante pas
        "Mail.mailer('array').to('a@x.org').send(Welcome('A'))\n"
        "print(Mail.transport('array').messages[0].get_body(('html',)).get_content())\n"
    )
    out = run(project, "-c", code)
    assert "Bienvenue A" in out.stdout, out.stdout + out.stderr
```

(Le monkeypatch d'`__init__` évite de dépendre du contenu commenté du stub ; si l'exécutant préfère éditer le stub généré, c'est équivalent.)

- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_console.py tests/test_cli.py -q -k "mail or creates_project"` — Expected: FAIL (`make:mail` inconnu, fichiers absents).

- [ ] **Step 3: Implement.** `make_mail` : calcule `dirs, cls = split_name(name, True)`, le chemin du template ; si le template existe sans `--force` → `ClickException` qui le nomme, **avant** `write_stub` ; puis `write_stub("app/mail", name, "mail", force=force, view=...)`, puis écrit le template depuis `mail.view.stub` (`Créé : resources/views/emails/...`), puis affiche l'import et `Mail.to(user).send(<Cls>(...))`. `config/mail.py` et le bloc `.env.example` : texte exact de la spec (section « `config/mail.py` »).

- [ ] **Step 4: Run** `.venv/bin/pytest -q` (suite complète) puis `.venv/bin/ruff check . && .venv/bin/ruff format --check .` — Expected: tout vert.

- [ ] **Step 5: Commit** `feat: make:mail, config/mail.py et resources/views du squelette (#24)`

---

### Task 6: Documentation

**Files:**
- Modify: `README.md`, `CLAUDE.md`, `CHANGELOG.md`

- [ ] **Step 1: README, section « Mail »**, au niveau de la section « Événements », couvrant chaque point de la spec (section « Documentation ») : configuration (`.env`, `config/mail.py`, trois transports, exemple Mailtrap et fournisseur sur 587/`tls` et 465/`ssl`, `log` visible avec `APP_DEBUG=true`), écrire un mailable (sujet, templates HTML/texte, `resources/views/` puis `templates/`, contexte et `context()`, pièces jointes, `reply_to`), envoyer (`to`, `cc`, `bcc`, formes de destinataires, `Mail.mailer`), depuis un écouteur, erreurs, tests (`with Mail.fake() as fake`, chaque assertion, `has_to`/`has_cc`/`has_bcc`, transport `array` et `Mail.transport("array").messages`), `flask make:mail`. Ajouter `make:mail` à « Console » et « ✅ Mail » à « Après la v0.1 ».
- [ ] **Step 2: CLAUDE.md** — puce « Mail » dans Architecture (Mailer créé par `Application`, config lue à chaque envoi, seul `array` gardé, fake = mode, `jinja_loader` affecté à l'instance sur `resources/views` puis `templates`).
- [ ] **Step 3: CHANGELOG** — entrées sous « Non publié ».
- [ ] **Step 4: Vérifier** que chaque exemple de code du README utilise des noms qui existent (`grep` des symboles dans `src/flask_artisan/mail.py`) ; `.venv/bin/pytest -q` vert.
- [ ] **Step 5: Commit** `docs: mail dans le README, CLAUDE.md et le CHANGELOG (#24)`

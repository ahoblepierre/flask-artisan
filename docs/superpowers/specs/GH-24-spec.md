# GH-24 — Mail : Mailables, transports `smtp` / `log` / `array`, `Mail.fake()`, `make:mail`

Ticket : https://github.com/ahoblepierre/flask-artisan/issues/24
Statut : en attente d'approbation (relecture constructeur faite)

## Intention

Envoyer des mails depuis une application Flask-Artisan comme on le fait dans Laravel. Un développeur Laravel s'attend à écrire :

```python
# app/mail/order_shipped.py
from flask_artisan.mail import Attachment, Mailable


class OrderShipped(Mailable):
    subject = "Votre commande est expédiée"
    view = "emails/order_shipped.html"     # resources/views/emails/order_shipped.html
    text = "emails/order_shipped.txt"      # facultatif : version texte

    def __init__(self, order):
        self.order = order                 # attribut public → disponible dans le template

    def attachments(self):
        return [Attachment.from_path(self.order.invoice_path, name="facture.pdf")]


# n'importe où : un controller, un écouteur d'événement, une commande
Mail.to(order.user).send(OrderShipped(order))
```

et, dans ses tests, `Mail.fake()` puis `fake.assert_sent(OrderShipped, lambda mail: mail.has_to("a@x.org"))`.

Les mails partent par SMTP en production, s'écrivent dans les logs en développement, et le transport se choisit dans `.env` (`MAIL_MAILER=smtp`), sans toucher au code. Pierre a validé la recommandation : trois transports, templates Jinja HTML et texte, `Mail.fake()` ; Markdown et API HTTP hors périmètre.

Ce chantier pose aussi le dossier de templates du projet (`resources/views/`), que reprendra le chantier des vues HTML (#19).

## Objectifs

1. Une classe `Mailable` : sujet, template HTML et/ou texte, contexte du template, pièces jointes, `reply_to`.
2. Un `Mailer` toujours présent dans le conteneur (`"mail"`, façade `Mail`) : `Mail.to(...).cc(...).bcc(...).send(mailable)` et `Mail.mailer("smtp").to(...)`.
3. Trois transports choisis par `config/mail.py` : `smtp`, `log`, `array`.
4. `Mail.fake()` pour vérifier dans les tests qu'un mail est parti, à qui, sans le rendre ni l'envoyer.
5. `flask make:mail` : la classe et son template HTML.
6. Une section README complète : elle servira de base à la documentation publique.

## Non-objectifs (hors périmètre)

- Envoi en file d'attente (`Mail.queue`, `Mail.later`) : chantier queues.
- Mails Markdown (composants `@component('mail::button')`) et thèmes.
- Transports par API HTTP (SES, Mailgun, Postmark, Resend…) : ces fournisseurs ont tous une entrée SMTP. Le transport reste une interface d'une méthode, pour en brancher un plus tard.
- Notifications (`Notification`, canaux mail/SMS/base de données).
- Événements `MessageSending` / `MessageSent`.
- Pièces jointes inline (`cid:`), images intégrées.
- Prévisualisation d'un mail dans le navigateur.
- Changement de l'expéditeur par mailable (`from`) : un seul expéditeur, celui de la config.
- Pool de connexions SMTP : une connexion par envoi.

## Anti-objectifs

- Avaler une erreur d'envoi : une erreur SMTP remonte à l'appelant de `send`.
- Laisser passer une injection d'en-tête (saut de ligne dans un sujet ou une adresse).
- Envoyer un vrai mail depuis la suite de tests d'un projet généré : le `.env.example` du squelette vaut `log`.
- Écrire un mot de passe SMTP dans les logs.

## Approches considérées

1. **Module maison sur la bibliothèque standard** (`email.message.EmailMessage` + `smtplib`), templates par le Jinja de Flask. **Retenue** : aucune dépendance, assez pour SMTP avec STARTTLS ou SSL et les pièces jointes, et calqué sur l'API de Laravel.
2. **Flask-Mail** : extension connue, mais son API (`Message`, `mail.send(msg)`) n'est pas celle de Laravel, elle n'a ni transport `log` ni fake, et il faudrait l'envelopper. Une dépendance de plus pour peu de code évité.
3. **Mailables + API HTTP de fournisseurs** : plus de code et une dépendance par fournisseur, alors que tous offrent SMTP. Reporté.

## Décisions

### `Mailable`

- Classe de base dans `flask_artisan.mail`. Attributs de classe, surchargeables par une propriété :
  - `subject: str` ;
  - `view: str | None` : template HTML, chemin relatif à `resources/views/` ;
  - `text: str | None` : template texte ;
  - `reply_to` : facultatif, mêmes formes qu'un destinataire (voir plus bas).
- Au moins un de `view` / `text` est requis : sinon `ValueError` au rendu, qui nomme la classe. Un `subject` vide est permis.
- **Contexte du template** : `context()` renvoie par défaut les attributs publics de l'instance (`vars(self)` sans ceux qui commencent par `_`), comme les propriétés publiques d'un mailable Laravel. Surchargeable.
- **Pièces jointes** : `attachments()` renvoie `[]` par défaut. Chaque élément est un `Attachment` :
  - `Attachment.from_path(path, name=None, mime=None)` : le nom par défaut est celui du fichier ; le fichier est lu au rendu ;
  - `Attachment.from_data(data: bytes | str, name, mime=None)`.
  - Le type MIME est deviné par `mimetypes` à partir du nom, sinon `application/octet-stream`.
- **Destinataires enregistrés** : à l'envoi, le mailable reçoit ses destinataires (attribut privé, pour ne pas entrer dans le contexte). `has_to(x)`, `has_cc(x)`, `has_bcc(x)` acceptent les mêmes formes qu'un destinataire et comparent les adresses sans tenir compte de la casse. Ils servent surtout au fake.

### Destinataires

Une adresse s'écrit sous l'une de ces formes, ou une liste de ces formes :

- une chaîne : `"a@x.org"` ou `"Alice <a@x.org>"` ;
- un tuple `(adresse, nom)` ;
- un objet avec un attribut `email` et, s'il existe et n'est pas vide, `name` : le modèle `User` du squelette convient tel quel.

Toute autre forme lève `TypeError`. Une adresse sans `@` lève `ValueError`. Aucun destinataire (`Mail.to([])`, ou `send` sans `to`) lève `ValueError`.

### `Mailer` et `Mail`

- Créé par `Application.__init__` à côté du `Dispatcher`, enregistré sous `"mail"` et `Mailer`. Façade `Mail` (accesseur `"mail"`). Un projet déjà généré (sans `config/mail.py`) fonctionne donc sans modification, avec le transport `log`.
- La config est lue **à chaque envoi** (comme les guards de l'auth), pour qu'un test puisse la changer.
- `Mail.to(*recipients)` renvoie un `PendingMail` ; `.cc(...)`, `.bcc(...)` complètent et renvoient le même objet ; `.send(mailable)` envoie. `Mail.mailer(name)` renvoie un `PendingMail` qui passera par ce mailer ; `.to(...)` s'enchaîne. Un nom absent de `mail.mailers` lève `ValueError` qui le nomme.
- `send` ne renvoie rien. Il rend le mailable en un `EmailMessage`, puis appelle le transport.
- **Construction du message** :
  - `From` : `mail.from.address` et `mail.from.name` ;
  - `To`, `Cc`, `Reply-To` en en-têtes ; `Bcc` jamais en en-tête, seulement dans la liste des destinataires passée au transport ;
  - texte seul : `set_content(texte)` ; HTML seul : `set_content(html, subtype="html")` ; les deux : texte puis `add_alternative(html, subtype="html")` ;
  - pièces jointes avec `add_attachment` ;
  - `Date` et `Message-ID` ajoutés (`email.utils`).
- **Rendu** : les templates passent par le Jinja de l'application (`render_template` dans un contexte d'application, poussé s'il n'y en a pas), donc avec les filtres et globals de Flask. L'autoescape suit Flask : actif pour `.html`, inactif pour `.txt`.
- **Dossiers des templates** (choix de Pierre : les deux) : Jinja cherche d'abord dans `resources/views/` (convention Laravel, que réutilisera #19), puis dans `templates/` (défaut de Flask). Un projet qui utilise déjà `templates/` continue de marcher ; à nom égal, `resources/views/` gagne. Mis en place par un `ChoiceLoader` affecté à l'instance (`self.jinja_loader = …` dans `__init__`, avant toute création de `jinja_env`) : aucune méthode ni attribut de classe ne masque Flask. Les templates des blueprints ne changent pas.

### Transports

Un transport a une méthode `send(message: EmailMessage, recipients: list[str]) -> None`. Ils sont construits depuis `mail.mailers.<nom>.transport`. **Choix du rédacteur** : `smtp` et `log` sont reconstruits à chaque envoi (la config lue à chaque envoi s'applique donc à tout) ; seul un transport `array` est gardé par le `Mailer`, un par nom de mailer, pour conserver ses messages.

- **`smtp`** : `host`, `port` (converti en entier : `env` renvoie une chaîne), `username`, `password`, `encryption` (`"tls"` = STARTTLS, `"ssl"` = SMTP_SSL, `None` ou vide = en clair), `timeout` (10 s par défaut). Une connexion par envoi ; `login` seulement si `username` est rempli. Les exceptions de `smtplib` remontent telles quelles. Une valeur d'`encryption` inconnue lève `ValueError` qui la nomme.
- **`log`** : écrit le message complet (`as_string()`) avec `app.logger.info`, précédé d'une ligne qui nomme les destinataires. Visible quand `APP_DEBUG=true` (niveau de Flask).
- **`array`** : garde les messages dans `transport.messages` (liste d'`EmailMessage`). `Mail.transport("array")` renvoie le transport gardé (nom de mailer, défaut : le mailer par défaut) ; `.messages` les lit, `.flush()` les vide.
- Un nom de transport inconnu lève `ValueError` qui le nomme.

### `config/mail.py` (squelette)

```python
config = {
    # smtp, log (écrit dans les logs) ou array (gardé en mémoire).
    "default": env("MAIL_MAILER", "log"),
    "mailers": {
        "smtp": {
            "transport": "smtp",
            "host": env("MAIL_HOST", "127.0.0.1"),
            "port": env("MAIL_PORT", 2525),
            "username": env("MAIL_USERNAME"),
            "password": env("MAIL_PASSWORD"),
            "encryption": env("MAIL_ENCRYPTION"),   # tls, ssl ou vide
            "timeout": 10,
        },
        "log": {"transport": "log"},
        "array": {"transport": "array"},
    },
    "from": {
        "address": env("MAIL_FROM_ADDRESS", "hello@example.com"),
        "name": env("MAIL_FROM_NAME", env("APP_NAME", "Flask-Artisan")),
    },
}
```

Sans fichier `config/mail.py`, le `Mailer` utilise ces mêmes valeurs par défaut (`log`, `hello@example.com`).

`.env.example` gagne un bloc commenté `MAIL_MAILER=log`, `MAIL_HOST`, `MAIL_PORT`, `MAIL_USERNAME`, `MAIL_PASSWORD`, `MAIL_ENCRYPTION`, `MAIL_FROM_ADDRESS`, `MAIL_FROM_NAME`, avec un mot sur les ports 587 (`tls`) et 465 (`ssl`).

### `Mail.fake()`

Même modèle qu'`Event.fake()` : un **mode** du `Mailer`, pas une instance de remplacement.

- `Mail.fake()` renvoie un `MailFake` et remet à zéro les enregistrements. En mode fake, `send` enregistre le mailable avec ses destinataires et le nom du mailer, **sans le rendre ni l'envoyer**. Il enregistre une copie superficielle du mailable (`copy.copy`), pour qu'un même objet envoyé à plusieurs personnes garde chacun ses destinataires (choix du rédacteur).
- `MailFake` : `restore()` (seulement s'il n'a pas été remplacé par un `fake()` plus récent), utilisable en `with`, `sent(cls)` (liste des mailables), `assert_sent(cls, callback=None)`, `assert_sent_times(cls, n)`, `assert_not_sent(cls, callback=None)`, `assert_nothing_sent()`. Le callback reçoit le mailable ; `has_to` / `has_cc` / `has_bcc` y vérifient les destinataires.
- `isinstance` : `assert_sent(Base)` compte aussi les sous-classes, comme `Event.fake()`.
- Les erreurs de destinataires (`TypeError`, `ValueError`) restent levées en mode fake : un test doit voir une adresse invalide.

### Générateur

- `flask make:mail OrderShipped` crée :
  - `app/mail/order_shipped.py` (classe avec `subject` et `view = "emails/order_shipped.html"`, `__init__` commenté) ;
  - `resources/views/emails/order_shipped.html` (HTML minimal qui affiche le sujet) ; un `--force` écrase les deux, et sans `--force` un fichier existant fait échouer la commande **avant** d'écrire l'autre.
- Sous-dossiers acceptés (`Admin/Invoice` → `app/mail/admin/invoice.py` et `emails/admin/invoice.html`).
- Affiche ensuite l'exemple d'envoi : `Mail.to(user).send(OrderShipped(...))` avec l'import.

### Squelette

- `config/mail.py`, bloc `MAIL_*` dans `.env.example` (et donc dans `.env` généré).
- `app/mail/__init__.py`.
- `resources/views/emails/.gitkeep` (ajouté à `package-data`).
- Aucun mail d'exemple : le squelette n'en envoie pas.

### Exports

- `Mail` exporté par `flask_artisan` (façade).
- `Mailable`, `Attachment`, `Mailer`, `MailFake` importés depuis `flask_artisan.mail`.

### Documentation

- README : section « Mail ». Elle doit suffire à un lecteur qui ne connaît pas Laravel et servir de base à la future documentation publique. Elle couvre :
  - configurer (`.env`, `config/mail.py`, les trois transports, exemples SMTP avec Mailtrap ou un fournisseur, ports 587/465) ;
  - écrire un mailable (sujet, templates HTML et texte, contexte, `context()` surchargé, pièces jointes, `reply_to`) ;
  - envoyer (`Mail.to`, `cc`, `bcc`, formes de destinataires, `Mail.mailer`) ;
  - envoyer depuis un écouteur d'événement ;
  - les erreurs (SMTP qui remonte, destinataire invalide) ;
  - tester avec `Mail.fake()` (dans un `with`) et chaque assertion, et avec le transport `array` pour vérifier le rendu ;
  - `flask make:mail`.
- `make:mail` ajouté à la section « Console » ; « ✅ Mail » dans la liste « Après la v0.1 ».
- CLAUDE.md : puce « Mail » dans l'architecture.
- CHANGELOG : section « Non publié ».

## Pièges connus

- **Tests du conteneur.** `test_application_does_not_override_flask` interdit de redéfinir `jinja_loader` dans la classe : il est affecté à l'instance ; le `Mailer` vit dans le conteneur. Rien ne doit masquer un attribut de Flask.
- **Contexte d'application.** Un envoi depuis une commande CLI ou un écouteur hors requête doit rendre ses templates : pousser le contexte de l'application du `Mailer` s'il n'y en a pas, ou si le contexte actif est celui d'une autre app.
- **Tests du squelette.** Ils partagent une app : `Mail.fake()` doit se restaurer (`with`).
- **Aucun réseau dans la suite.** Le transport `smtp` se teste contre un faux serveur local (classe qui remplace `smtplib.SMTP` / `SMTP_SSL` par monkeypatch), jamais contre un vrai serveur.
- **`port` en chaîne.** `env("MAIL_PORT")` renvoie `"587"`.

## Laissé au constructeur

- Structure interne du `Mailer`, du `PendingMail` et des transports.
- Texte exact des messages d'erreur et d'assertion.
- Contenu exact des modèles de fichiers.

## Livraison

- Tests pytest :
  - mailable : contexte par défaut et surchargé, `view` seul, `text` seul, les deux, aucun (`ValueError`), pièces jointes `from_path` et `from_data`, MIME deviné, `reply_to` ;
  - destinataires : chaîne, « Nom <adresse> », tuple, objet avec `email`/`name`, liste, forme invalide, adresse sans `@`, liste vide, saut de ligne refusé ;
  - message : `From` depuis la config, `Bcc` absent des en-têtes mais présent dans les destinataires du transport ;
  - transports : `array` (messages, `flush`), `log` (destinataires et contenu dans le log, aucun mot de passe), `smtp` contre un faux serveur (STARTTLS, SSL, sans chiffrement, login conditionnel, port en chaîne, erreur qui remonte), transport et mailer inconnus ;
  - templates : trouvés dans `resources/views/`, puis dans `templates/`, `resources/views/` gagne à nom égal, `render_template` d'une route y accède aussi ;
  - `Mail.mailer(name)`, `Mail.transport(name)`, config lue à chaque envoi, valeurs par défaut sans `config/mail.py` ;
  - fake : enregistrement sans rendu, chaque assertion (succès et message d'échec), sous-classes, `restore`, `with`, fake remplacé ;
  - `make:mail` : deux fichiers, sous-dossier, refus sans `--force` sans écrire l'autre fichier, `--force` ;
  - projet généré : `make:mail`, envoi avec `MAIL_MAILER=array` qui rend le template, test du projet avec `Mail.fake()`.
- README, CLAUDE.md, CHANGELOG mis à jour.
- PR `feat/24-mail`, commits et titre avec `(#24)`, corps avec `Closes #24`.

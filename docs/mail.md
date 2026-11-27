# Mail

Chaque mail de l'application est une classe, un *mailable*, qui décrit son sujet, ses templates et ses pièces jointes. On l'envoie en une ligne, depuis un controller, un écouteur d'événement ou une commande :

```python
from flask_artisan import Mail

Mail.to(order.user).send(OrderShipped(order))
```

La façon dont le mail part se choisit dans `.env`, sans toucher au code : écrit dans les logs pendant le développement, envoyé par SMTP en production.

## Configurer

Le transport se choisit avec `MAIL_MAILER` dans `.env` :

| Transport | Effet | Usage |
|---|---|---|
| `log` (défaut) | le mail complet est écrit dans les logs de l'application (visible quand `APP_DEBUG=true`) | développement |
| `smtp` | le mail est envoyé à un serveur SMTP | production, ou Mailtrap pour tester |
| `array` | le mail est gardé en mémoire (`Mail.transport("array").messages`) | tests qui vérifient le rendu |

Pour SMTP, renseignez le serveur de votre fournisseur. Tous les fournisseurs courants (Brevo, Mailgun, Amazon SES, SendGrid, Postmark, Mailtrap…) proposent un accès SMTP :

```ini
MAIL_MAILER=smtp
MAIL_HOST=smtp.mailtrap.io
MAIL_PORT=587
MAIL_USERNAME=votre-identifiant
MAIL_PASSWORD=votre-mot-de-passe
MAIL_ENCRYPTION=tls          # tls pour le port 587 (STARTTLS), ssl pour le port 465, vide sinon (certificat vérifié)
MAIL_FROM_ADDRESS=hello@monsite.fr
MAIL_FROM_NAME="Mon site"
```

Ces variables sont lues par `config/mail.py`. On peut y déclarer plusieurs *mailers* (par exemple deux serveurs SMTP) et en choisir un à l'envoi avec `Mail.mailer("nom")`. La configuration est relue à chaque envoi. Un projet sans `config/mail.py` (créé avant la 0.4) fonctionne aussi : il utilise le transport `log` et l'expéditeur `hello@example.com`.

L'expéditeur (`From`) est celui de la config, le même pour tous les mails.

## Écrire un mailable

```bash
flask make:mail OrderShipped
# Créé : app/mail/order_shipped.py
# Créé : resources/views/emails/order_shipped.html
```

```python
# app/mail/order_shipped.py
from flask_artisan.mail import Attachment, Mailable


class OrderShipped(Mailable):
    subject = "Votre commande est expédiée"
    view = "emails/order_shipped.html"     # version HTML
    text = "emails/order_shipped.txt"      # version texte (facultative)
    reply_to = "support@monsite.fr"        # facultatif

    def __init__(self, order):
        self.order = order

    def attachments(self):
        return [
            Attachment.from_path(self.order.invoice_path, name="facture.pdf"),
            Attachment.from_data(self.order.to_csv(), "commande.csv"),
        ]
```

```html
<!-- resources/views/emails/order_shipped.html -->
<p>Bonjour {{ order.user.name }},</p>
<p>Votre commande n° {{ order.id }} est partie.</p>
```

- **Templates.** Ce sont des templates Jinja, ceux de Flask. Ils sont cherchés dans `resources/views/`, puis dans `templates/` (le dossier habituel de Flask, qui continue de fonctionner). Les variables sont échappées dans un `.html`, pas dans un `.txt`.
- **HTML, texte ou les deux.** Avec `view` et `text`, le mail contient les deux versions et la messagerie choisit. Il en faut au moins une.
- **Variables du template.** Les attributs publics du mailable (`self.order`) sont disponibles dans le template, ainsi que `subject`. Les attributs qui commencent par `_` ne le sont pas. Pour choisir soi-même, surchargez `context()` :

  ```python
  def context(self):
      return {"order": self.order, "total": self.order.total_ttc()}
  ```

- **Sujet calculé.** `subject` peut être une propriété :

  ```python
  @property
  def subject(self):
      return f"Commande n° {self.order.id} expédiée"
  ```

- **Pièces jointes.** `Attachment.from_path(chemin, name=None, mime=None)` lit le fichier au moment de l'envoi. `Attachment.from_data(contenu, nom, mime=None)` joint des octets ou du texte. Le type MIME est deviné à partir du nom.

## Envoyer

```python
from flask_artisan import Mail

Mail.to(user).send(Welcome(user))
Mail.to("alice@x.org").cc("compta@x.org").bcc("archive@x.org").send(InvoicePaid(invoice))
Mail.to(["a@x.org", "b@x.org"]).send(Newsletter())
Mail.mailer("smtp").to(user).send(Welcome(user))   # un mailer précis de config/mail.py
```

Un destinataire peut s'écrire :

- `"alice@x.org"` ou `"Alice <alice@x.org>"` ;
- `("alice@x.org", "Alice")` ;
- un objet avec un attribut `email` (et `name`, s'il existe) : le modèle `User` convient tel quel ;
- une liste de ces formes.

Les adresses en copie cachée (`bcc`) reçoivent le mail mais n'apparaissent pas dans ses en-têtes.

**Depuis un écouteur d'événement**, c'est l'usage le plus courant :

```python
# app/listeners/send_shipment_notification.py
from flask_artisan import Mail

from app.events.order_shipped import OrderShipped
from app.mail.order_shipped import OrderShipped as OrderShippedMail


class SendShipmentNotification:
    def handle(self, event: OrderShipped):
        Mail.to(event.order.user).send(OrderShippedMail(event.order))
```

L'envoi marche aussi hors d'une requête (commande `flask`, script) : les templates sont rendus avec l'application. Pour qu'un `url_for(...)` y construise un lien absolu, Flask doit connaître l'adresse du site : déclarez-la dans `config/flask.py`, sinon `url_for` lève une erreur hors requête.

```python
# config/flask.py
config = {
    "SERVER_NAME": "monsite.fr",
    "PREFERRED_URL_SCHEME": "https",
}
```

Dans un template de mail, utilisez `url_for("nom.de.route", _external=True)` pour un lien complet.

**Erreurs.** `send` lève une erreur plutôt que de perdre un mail en silence :

- une erreur du serveur SMTP (connexion, authentification, destinataire refusé) remonte telle quelle (exceptions de `smtplib`) ;
- un destinataire d'une forme inconnue lève `TypeError` ; une adresse invalide (sans `@`, ou plusieurs adresses dans une seule chaîne), aucun destinataire, ou un mailable sans `view` ni `text` lève `ValueError` ;
- un expéditeur (`MAIL_FROM_ADDRESS`) ou un port (`MAIL_PORT`) invalide lève `ValueError` qui nomme le réglage ;
- une option inconnue dans un mailer `smtp` de `config/mail.py` lève `TypeError` : une faute de frappe ne fait pas partir le mail en clair ;
- un saut de ligne dans le sujet, un nom ou une adresse lève `ValueError` : il servirait à injecter des en-têtes.

`send` est synchrone : la requête attend la réponse du serveur SMTP. Pour ne pas la faire attendre, mettez le mail en file : `Mail.to(user).queue(Welcome(user))` (voir « Queues »).

## Tester avec `Mail.fake()`

`Mail.fake()` enregistre les mails envoyés **sans les rendre ni les envoyer**, puis permet de vérifier ce qui est parti et à qui. Utilisé comme bloc `with`, il rend au mailer son fonctionnement normal à la sortie :

```python
from wsgi import app

from flask_artisan import Mail
from app.mail.invoice_paid import InvoicePaid
from app.mail.order_shipped import OrderShipped


def test_shipping_mails_the_customer():
    with Mail.fake() as fake:
        app.test_client().post("/api/orders/1/ship")

    fake.assert_sent(OrderShipped)
    fake.assert_sent(OrderShipped, lambda mail: mail.order.id == 1 and mail.has_to("a@x.org"))
    fake.assert_sent_times(OrderShipped, 1)
    fake.assert_not_sent(InvoicePaid)
```

| Méthode | Vérifie que… |
|---|---|
| `assert_sent(Classe, callback=None)` | le mail a été envoyé au moins une fois (et que `callback(mail)` est vrai pour l'un d'eux) |
| `assert_sent_times(Classe, n)` | le mail a été envoyé exactement `n` fois |
| `assert_not_sent(Classe, callback=None)` | le mail n'a pas été envoyé (ou aucun ne satisfait `callback`) |
| `assert_nothing_sent()` | aucun mail n'a été envoyé |
| `sent(Classe)` | (pas une assertion) la liste des mails envoyés de cette classe |

- Dans le callback, `mail.has_to(x)`, `mail.has_cc(x)` et `mail.has_bcc(x)` vérifient les destinataires. Ils acceptent les mêmes formes qu'un destinataire et ignorent la casse.
- Une sous-classe compte pour sa parente : `assert_sent(Mailable)` vérifie qu'un mail quelconque est parti.
- Un destinataire invalide lève toujours son erreur, même sous fake.
- Le fake est un mode du mailer de l'application : un service qui a reçu le mailer avant l'appel à `fake()` passe aussi par le fake. Rappeler `Mail.fake()` repart de zéro.
- L'objet envoyé connaît ensuite ses destinataires (`mail.has_to(...)`), avec ou sans fake.
- **Mails en file.** `Mail.to(...).queue(...)` et `later(...)` sont enregistrés à part : `assert_queued(Classe, callback=None)`, `assert_not_queued(Classe, callback=None)`, `assert_nothing_queued()` et `queued(Classe)`. `assert_sent` ne compte pas les mails mis en file.
- **Restaurer.** Les tests du projet généré partagent une seule application : utilisez `with Mail.fake() as fake:`, ou appelez `fake.restore()` en fin de test.

**Vérifier le rendu.** Le fake ne rend pas les templates. Pour tester le contenu réel du mail, envoyez-le par le transport `array` :

```python
def test_welcome_mail_content():
    Mail.mailer("array").to("a@x.org").send(Welcome(user))
    message = Mail.transport("array").messages[-1]   # un EmailMessage de la bibliothèque standard
    assert message["Subject"] == "Bienvenue"
    assert "Bonjour" in message.get_body(("html",)).get_content()
    Mail.transport("array").flush()                  # vide les messages gardés
```

## Générateur

```bash
flask make:mail OrderShipped        # app/mail/order_shipped.py + resources/views/emails/order_shipped.html
flask make:mail Billing/Invoice     # app/mail/billing/invoice.py + resources/views/emails/billing/invoice.html
```

Si l'un des deux fichiers existe, rien n'est écrit (sauf avec `--force`, qui écrase les deux). La commande affiche ensuite l'import et l'appel `Mail.to(...).send(...)`.

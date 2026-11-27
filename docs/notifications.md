# Notifications

Une notification prévient quelqu'un d'un événement (une facture payée, un commentaire reçu) sur un ou plusieurs **canaux** : `mail`, et `database` pour l'afficher dans l'app (« 3 non lues »).

```python
user.notify(InvoicePaid(invoice))
```

## Créer une notification

```bash
flask make:notification InvoicePaid     # app/notifications/invoice_paid.py
```

```python
from flask_artisan.notifications import Notification

from app.mail.invoice_paid_mail import InvoicePaidMail


class InvoicePaid(Notification):
    def __init__(self, invoice):
        self.invoice = invoice

    def via(self, notifiable):
        return ["mail", "database"]          # les canaux, choisis par destinataire si besoin

    def to_mail(self, notifiable):
        return InvoicePaidMail(self.invoice)  # un Mailable (flask make:mail)

    def to_database(self, notifiable):
        return {"invoice_id": self.invoice.id, "amount": str(self.invoice.amount)}
```

- `via(notifiable)` est obligatoire. Un canal inconnu lève `ValueError`.
- Chaque canal listé demande sa méthode `to_<canal>`, sinon l'envoi lève `NotImplementedError`.
- `to_mail` renvoie un [Mailable](mail.md) : son template, ses pièces jointes et le transport configuré servent tels quels.
- `to_database` renvoie un dict **JSON** (pas de modèle ni de `datetime`), sinon `TypeError`.

## Destinataires : `Notifiable`

Le `User` du squelette hérite de `Notifiable`. N'importe quel modèle peut en hériter (une `Team`, une `Company`) :

```python
from flask_artisan.notifications import Notifiable


class Team(Notifiable, Model):
    ...
```

Placez `Notifiable` **avant** `Model` (`class Team(Notifiable, Model)`), sinon la suppression du modèle ne supprimerait pas ses notifications : l'ordre inverse lève `TypeError`. Une colonne nommée `notify`, `notifications`, `unread_notifications` ou `route_notification_for` masquerait le mixin et lève aussi `TypeError` : renommez-la (`notifications_enabled`, par exemple).

Pour le canal mail, le destinataire est l'attribut `email` du modèle. Pour en choisir un autre :

```python
class Team(Notifiable, Model):
    def route_notification_for_mail(self):
        return (self.billing_email, self.name)   # adresse, ou (adresse, nom)
```

Sans adresse (`email` vide), le canal mail est ignoré pour ce destinataire, avec un avertissement dans les logs.

## Envoyer

```python
user.notify(InvoicePaid(invoice))

from flask_artisan.notifications import Notification

Notification.send(team.members, InvoicePaid(invoice))                 # liste, set, User.where(...)
Notification.route("mail", "compta@example.org").notify(InvoicePaid(invoice))   # sans compte
Notification.route("mail", ("compta@example.org", "Compta")).notify(...)        # avec un nom
```

Une notification « à la demande » (`Notification.route`) n'a pas de destinataire en base : le canal `database` y lève `ValueError`.

Si un canal échoue (serveur SMTP injoignable, par exemple), les autres canaux et les autres destinataires sont essayés quand même, puis la première erreur remonte ; les suivantes sont écrites dans les logs.

## Le canal `database`

### Créer la table

La table `notifications` entre dans les migrations dès qu'un modèle hérite de `Notifiable` (ou que `flask_artisan.notifications` est importé) :

```bash
flask make:migration notifications
flask migrate
```

| Colonne | Contenu |
|---------|---------|
| `id` | UUID (texte) |
| `type` | la classe de la notification (`app.notifications.invoice_paid.InvoicePaid`) |
| `notifiable_type`, `notifiable_id` | le destinataire : n'importe quel modèle |
| `data` | le dict de `to_database` (JSON, clés en texte, sans `NaN`) |
| `read_at` | date de lecture, `None` si non lue |
| `created_at`, `updated_at` | |

Un projet qui n'utilise pas les notifications retire `Notifiable` de son `User` : la table n'est alors plus générée.

### Lire

```python
user.notifications.get()               # les plus récentes d'abord
user.unread_notifications.count()
notification = user.notifications.first()
notification.data["invoice_id"]
notification.mark_as_read()            # mark_as_unread(), read(), unread()
```

`notifications` et `unread_notifications` sont des requêtes : `.get()`, `.first()`, `.count()`, `.limit(10)`… s'enchaînent.

L'ordre suit `created_at`, puis l'`id` (un UUID version 7, croissant dans le temps) pour deux notifications créées au même instant.

Exemple de routes JSON pour une cloche de notifications :

```python
# routes/api.py
with Route.middleware("auth:api"):   # sans middleware auth, Auth.user() vaut None
    Route.get("/notifications", NotificationController.index)
    Route.post("/notifications/<id>/read", NotificationController.read)
```

```python
from flask_artisan import Auth


class NotificationController:
    def index(self):
        return Auth.user().unread_notifications.limit(20).get()

    def read(self, id):
        notification = Auth.user().notifications.where("id", id).first_or_fail()
        return notification.mark_as_read()
```

Filtrez toujours par `Auth.user().notifications` (et non `DatabaseNotification.find(id)`) : sinon n'importe qui pourrait marquer la notification d'un autre. Les modèles renvoyés en JSON contiennent aussi `type` et `notifiable_type` (des chemins de classes) : renvoyez plutôt `{"id": n.id, "data": n.data, "read_at": n.read_at}` si vous ne voulez pas les exposer.

Supprimer un destinataire (suppression définitive) supprime ses notifications.

## Envoyer par la file

```python
from flask_artisan.queue import ShouldQueue


class InvoicePaid(Notification, ShouldQueue):
    queue = "notifications"   # facultatif, comme tries, backoff et timeout
    ...
```

Chaque canal de chaque destinataire devient un [job](queues.md) séparé : si le mail échoue et est réessayé, la ligne en base n'est pas créée deux fois. Comme pour un job, les attributs publics de la notification voyagent en JSON et un modèle par son identifiant. Une notification mise en file doit donc être définie au niveau d'un module (pas dans une fonction), et ses attributs doivent être sérialisables.

Si le destinataire est supprimé avant l'exécution du job, le job échoue (`ModelNotFound`) et est réessayé selon `tries`.

## Tester

```python
from flask_artisan.notifications import Notification


def test_invoice_paid_notifies_owner(client, user):
    with Notification.fake() as fake:
        client.acting_as(user, "api").post("/api/invoices/1/pay").assert_ok()

    fake.assert_sent_to(user, InvoicePaid)
    fake.assert_sent_to(user, InvoicePaid, lambda notification, channels: "mail" in channels)
    fake.assert_sent_times(InvoicePaid, 1)
```

| Assertion | Vérifie |
|-----------|---------|
| `assert_sent_to(destinataire, Classe, callback=None)` | envoyée à ce destinataire (même modèle et même id) |
| `assert_not_sent_to(…)` | l'inverse |
| `assert_sent_times(Classe, n)` | envoyée `n` fois en tout |
| `assert_sent_on_demand(Classe, callback=None)` | envoyée par `Notification.route(...)` |
| `assert_nothing_sent()` | aucune notification |

`fake.sent(Classe)` renvoie les `(destinataire, notification, canaux)` enregistrés. Pour une notification `ShouldQueue`, le fake vérifie aussi qu'elle se sérialise (comme `Queue.fake()`) : un attribut impossible à mettre en file échoue dans le test, pas en production. En mode fake, rien n'est envoyé, écrit en base ni mis en file. Le mode s'arrête à la sortie du `with` (ou par `fake.restore()`).

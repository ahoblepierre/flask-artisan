# GH-51 : notifications (canaux mail et database, `Notifiable`, fake)

Ticket : https://github.com/ahoblepierre/flask-artisan/issues/51

## Pourquoi

Prévenir quelqu'un d'un événement (facture payée, commentaire reçu) demande aujourd'hui d'écrire à la main l'envoi du mail, l'enregistrement en base pour l'afficher dans l'app (« 3 non lues »), et la mise en file. Laravel réunit tout ça dans une classe de notification : `$user->notify(new InvoicePaid($invoice))`, qui part sur les canaux choisis par `via()`. Le mail (#24), les queues (#28) et l'ORM sont livrés. Ce chantier les assemble.

## Objectifs (approche A, choisie par Pierre)

- **Une classe `Notification`** porte `via(notifiable) -> list[str]` et une méthode par canal : `to_mail(notifiable) -> Mailable` et `to_database(notifiable) -> dict`.
- **Le mixin `Notifiable`** d'un modèle apporte :
  - `notify(notification)` ;
  - `notifications` (requête, des plus récentes aux plus anciennes) et `unread_notifications` ;
  - `route_notification_for(channel)`.
- **Envoi groupé et à la demande :**
  - `Notification.send(notifiables, notification)` ;
  - `Notification.route("mail", "a@x.org").notify(notification)`, pour quelqu'un qui n'a pas de compte.
- **Le canal `database`** enregistre dans une table `notifications` polymorphe (`notifiable_type`, `notifiable_id`), avec `mark_as_read()` et `mark_as_unread()`, et `read_at`.
- **La mise en file** passe par `ShouldQueue` sur la notification. On a un job par canal et par destinataire, comme Laravel.
- **`Notification.fake()`** et ses assertions.
- **`flask make:notification Nom`**.
- **Doc :** une page « Notifications ».

## Non-objectifs

- Les canaux SMS, Slack, broadcast et les canaux personnalisés enregistrés par le projet. Une valeur de `via()` inconnue lève une erreur claire.
- La « notification mail » à la Laravel (`MailMessage` avec `line()` et `action()` et un template fourni) : `to_mail` renvoie un `Mailable` existant.
- Le préfixe d'événements (`NotificationSent`), `shouldSend()`, `locale()` et `afterCommit()`.
- Une interface pour lire les notifications : c'est au projet de l'écrire, avec un exemple dans la doc.
- `notifications:table` : la table vient de `flask make:migration`, comme celle des tokens d'API.

## Anti-objectifs

- **Un projet dont aucun modèle n'hérite de `Notifiable` et qui n'importe pas `flask_artisan.notifications`** ne doit ni avoir la table `notifications` dans ses migrations, ni importer le module, et `Application` ne l'importe jamais d'elle-même. Le `User` du squelette hérite de `Notifiable`, donc un projet neuf a la table, comme il a déjà celle des tokens par `HasApiTokens` (choix du rédacteur, à la suite de la relecture). Un projet qui n'en veut pas retire `Notifiable` de son `User`.
- **Une notification mise en file ne passe jamais par `pickle`.** Elle est reconstruite comme les écouteurs en file : attributs publics en JSON, modèles par identifiant, et une classe qui doit hériter de `Notification`.
- **L'échec d'un canal** ne doit pas empêcher l'envoi sur les autres canaux. L'erreur remonte une fois tous les canaux essayés, en envoi direct. En file, chaque canal est un job séparé.
- **Une notification `database`** ne stocke jamais de modèle sérialisé dans `data` : seulement du JSON.

## Approches envisagées

- **A. Destinataire polymorphe** (`notifiable_type` + `notifiable_id`) : retenue par Pierre.
- **B. `user_id` seul** : écartée, car il faudrait migrer la table le jour où l'on notifie une `Team`.
- **Pas de façade séparée** (choix du rédacteur). Laravel a une façade et une classe de base qui portent le même nom, `Notification`. En Python, les deux se heurteraient dans un même fichier. Le choix est d'avoir une seule classe de base, `flask_artisan.notifications.Notification`, dont les méthodes de classe `send`, `route`, `fake` et `restore` délèguent au service. On garde l'écriture de Laravel (`Notification.fake()`) sans conflit de noms.
- **`to_mail` renvoie un `Mailable`** (choix du rédacteur) : il réutilise les templates, les pièces jointes et les transports du mail, sans nouveau format.

## Décisions

### Modules

- **Le paquet `src/flask_artisan/notifications/`** contient :
  - `__init__.py`, qui exporte `Notification`, `Notifiable`, `DatabaseNotification` et `AnonymousNotifiable` ;
  - `models.py` (`DatabaseNotification`) ;
  - `sender.py` (`NotificationSender`) ;
  - `channels.py`.
- **L'import du paquet enregistre la table.** C'est voulu : qui utilise les notifications a la table.
- **Le service `"notifications"`** est enregistré par `Application` sans importer le paquet : `self.singleton("notifications", fabrique)`, et la fabrique importe `NotificationSender` à la première résolution. Un test vérifie qu'après `Application(...)`, `"flask_artisan.notifications.models"` n'est pas dans `sys.modules`.

### Table `notifications` (`DatabaseNotification`)

| Colonne | Type |
|---------|------|
| `id` | `String(36)`, UUID4 en texte (comme Laravel, pas l'auto-incrément) |
| `type` | `str`, chemin `module.Classe` de la notification |
| `notifiable_type` | `str`, chemin `module.Classe` du modèle destinataire |
| `notifiable_id` | `int`, indexé avec `notifiable_type` |
| `data` | `JSON` |
| `read_at` | `datetime` ou `None` |
| `created_at`, `updated_at` | timestamps du `Model` |

- Il n'y a pas de clé étrangère, comme pour les tokens.
- `id` est déclaré par le modèle (`String(36)`, clé primaire, UUID4 par défaut) : `Model.__init_subclass__` n'ajoute pas d'`id` entier si une clé primaire existe déjà.
- Méthodes : `mark_as_read()`, `mark_as_unread()`, `read()` et `unread()`, qui renvoient un booléen.
- Quand le destinataire est supprimé en hard delete, ses notifications sont supprimées, comme ses tokens, en surchargeant `_hard_delete` sur `Notifiable`, comme le fait `HasApiTokens`. Sinon, SQLite réutiliserait les identifiants.

### `Notification`

```python
from flask_artisan.notifications import Notification
from flask_artisan.queue import ShouldQueue


class InvoicePaid(Notification, ShouldQueue):     # ShouldQueue : facultatif
    def __init__(self, invoice):
        self.invoice = invoice

    def via(self, notifiable):
        return ["mail", "database"]

    def to_mail(self, notifiable):
        return InvoicePaidMail(self.invoice)      # un Mailable

    def to_database(self, notifiable):
        return {"invoice_id": self.invoice.id, "amount": self.invoice.amount}
```

- `via` est obligatoire et lève `NotImplementedError` par défaut.
- Un canal listé sans sa méthode `to_<canal>` lève `NotImplementedError`, qui nomme la classe et la méthode.
- `queue`, `tries`, `backoff` et `timeout`, s'ils sont présents, passent au job, comme pour un écouteur en file.

### `Notifiable`

- C'est un mixin de `Model`. Le `User` du squelette en hérite.
- `notify(notification)` revient à `Notification.send([self], notification)`.
- `notifications` renvoie une requête du `Builder` sur `DatabaseNotification`, filtrée par `notifiable_type == class_path(type(self))` et `notifiable_id == self.id`, triée par `created_at` décroissant (puis `id`). `unread_notifications` ajoute `read_at IS NULL`. Ce sont des propriétés qui renvoient le `Builder`, et `.get()`, `.count()` et `.first()` s'enchaînent.
- `route_notification_for(channel)` :
  - pour `mail`, la valeur de `self.email`. Il faut pouvoir la surcharger par une méthode `route_notification_for_mail()` sur le modèle (un nom et un email, comme pour `Mail.to`) ;
  - pour `database`, il n'y en a pas besoin.

### Envoi (`NotificationSender`)

- `send(notifiables, notification)` accepte un seul destinataire ou une liste.
- Si la notification est `ShouldQueue` : pour chaque destinataire et chaque canal de `via(destinataire)`, un job `SendQueuedNotification` est envoyé par `Queue`, sur la `queue` de la notification. Sinon, l'envoi est direct.
- **Canal `mail`** :
  - `mailable = notification.to_mail(n)` ;
  - le destinataire est `n.route_notification_for("mail")`. S'il est vide, rien n'est envoyé et un avertissement est loggé ;
  - l'envoi se fait par `Mail.to(destinataire).send(mailable)`.

  Il n'y a donc pas de double mise en file : le job de notification envoie le mail de façon synchrone.
- **Canal `database`** : `DatabaseNotification.create(...)`, avec `data = to_database(n)`. `data` passe par `json.dumps` pour rejeter tout objet non JSON, avec un message qui nomme la notification. `DatabaseNotification` est refusé pour un `AnonymousNotifiable` (`ValueError`).
- **Échec d'un canal, envoi direct comme mise en file :** les autres canaux et les autres destinataires sont essayés quand même, puis la première exception est relevée. En file, le sender capture l'erreur de chaque `push`, parce que le pilote `sync` exécute le job tout de suite et propagerait l'exception (choix du rédacteur, à la suite de la relecture).

### `SendQueuedNotification` (job du framework)

- Il porte :
  - `notification_class` et `notification_data`, les attributs publics passés par la sérialisation de la file ;
  - `notifiable`, un modèle par identifiant, ou `{"routes": …}` pour un `AnonymousNotifiable` ;
  - `channel`.
- `handle()` :
  - reconstruit la notification par `import_class(..., Notification)`, puis `__new__` et les attributs publics. Un attribut qui commence par `_` est refusé, comme `CallQueuedListener` ;
  - recharge le destinataire et envoie sur le seul `channel`.
- Un destinataire supprimé entre-temps fait échouer le job avec `ModelNotFound` dès sa reconstruction, comme n'importe quel job qui porte un modèle. Le job est réessayé selon `tries` (1 par défaut), sans appel à `failed()`. C'est le comportement actuel de la file, sans changement au code partagé (choix du rédacteur, à la suite de la relecture).

### À la demande (`AnonymousNotifiable`)

- `Notification.route("mail", "a@x.org")` renvoie un `AnonymousNotifiable`. `.route(canal, valeur)` s'enchaîne, et `.notify(notification)` envoie.
- Son `route_notification_for(canal)` lit les routes enregistrées.
- Le canal `database` lève une `ValueError` (il n'y a pas de destinataire à enregistrer).

### `Notification.fake()`

- C'est un mode du `NotificationSender`, comme `Mail.fake()`. Il enregistre `(destinataire, notification, canaux)` sans rien envoyer ni mettre en file, et renvoie un `NotificationFake`.
- Quitter le mode : `NotificationFake.restore()` ou la sortie du `with`.
- **Assertions :**
  - `assert_sent_to(notifiable, NotificationClass, callback=None)` ;
  - `assert_not_sent_to(…)` ;
  - `assert_sent_times(NotificationClass, n)` ;
  - `assert_nothing_sent()` ;
  - `assert_sent_on_demand(NotificationClass, callback=None)`.

  Le `callback(notification, channels)` renvoie un booléen.
- La comparaison des destinataires se fait par `(type, id)` pour un modèle, et par identité pour un `AnonymousNotifiable`.

### Console

- `flask make:notification InvoicePaid` crée `app/notifications/invoice_paid.py` depuis le stub `notification.stub`. Le stub contient `via` → `["mail", "database"]`, un `to_mail` à compléter, `to_database` et une ligne commentée `ShouldQueue`.
- Comme `make:model` et `make:command`, il refuse les sous-dossiers.

### Squelette

- `User` hérite de `Notifiable`.
- Le dossier `app/notifications/` est créé avec `.gitkeep`.
- `config/` ne change pas.

### Doc

- **Nouvelle page `docs/notifications.md`,** ajoutée au nav dans « Tâches de fond », après Mail. Elle couvre :
  - la classe ;
  - les canaux ;
  - `Notifiable` et la lecture (exemple de route JSON « non lues » et de `mark_as_read`) ;
  - l'envoi groupé et à la demande ;
  - la file ;
  - la migration (`flask make:migration notifications` après l'import) ;
  - `fake`.
- Mises à jour aussi : `console.md` (`make:notification`), le README, CLAUDE.md et le CHANGELOG.

## Laissé au constructeur

- La structure interne du sender et des canaux.
- Le texte des messages.
- La forme exacte des tests.
- L'`id` UUID : voir la section sur la table.

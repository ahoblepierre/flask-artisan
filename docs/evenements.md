# Événements

Un événement annonce ce qui s'est passé ; des écouteurs, déclarés ailleurs, y réagissent. Le code qui émet ne connaît pas ceux qui écoutent : ajouter un effet (un mail, un log, une statistique) ne touche pas au code métier.

## Définir un événement

Un événement est un objet ordinaire qui transporte des données, en général une `dataclass` :

```python
# app/events/order_shipped.py   (flask make:event OrderShipped)
from dataclasses import dataclass


@dataclass
class OrderShipped:
    order: Order
```

Aucune classe de base n'est imposée. Un événement est identifié par sa **classe**.

## Écrire un écouteur

La forme habituelle est une classe avec une méthode `handle(self, event)` :

```python
# app/listeners/send_shipment_notification.py   (flask make:listener SendShipmentNotification --event OrderShipped)
from app.events.order_shipped import OrderShipped


class SendShipmentNotification:
    def __init__(self, mailer: Mailer):   # dépendances injectées par le conteneur
        self.mailer = mailer

    def handle(self, event: OrderShipped):
        self.mailer.send(event.order.user, "Votre commande est partie")
```

L'écouteur est construit par le conteneur **à chaque émission** : ses dépendances sont injectées dans `__init__` comme pour un controller.

Deux autres formes sont acceptées :

```python
Event.listen(OrderShipped, (ShipmentListeners, "on_shipped"))   # une autre méthode que handle
Event.listen(OrderShipped, lambda event: print(event.order.id))  # une simple fonction
```

Un écouteur invalide (classe sans `handle`, méthode inexistante, objet non appelable) est refusé immédiatement par une `TypeError`, pas à la première émission.

## Déclarer les écouteurs

Dans `app/providers/event_service_provider.py` (fourni par le squelette et déjà présent dans `config/app.py`) :

```python
from app.events.order_shipped import OrderShipped
from app.listeners.send_shipment_notification import SendShipmentNotification
from app.listeners.update_stock import UpdateStock
from flask_artisan.events import EventServiceProvider as BaseEventServiceProvider


class EventServiceProvider(BaseEventServiceProvider):
    listen = {
        OrderShipped: [SendShipmentNotification, UpdateStock],
    }
```

On peut aussi déclarer un écouteur dans le `boot()` de n'importe quel provider : `Event.listen(OrderShipped, UpdateStock)` (un écouteur ou une liste).

## Émettre

```python
from flask_artisan import Event

Event.dispatch(OrderShipped(order))
```

Le helper `event(OrderShipped(order))` fait la même chose (importé de `flask_artisan` ; attention au conflit de nom si vous importez aussi `sqlalchemy.event`).

- **Synchrone** : les écouteurs s'exécutent tout de suite, dans la requête ou la commande qui émet. Pas besoin de contexte de requête : une commande `flask` ou un script peuvent émettre.
- **Valeur renvoyée** : `dispatch` rend la liste des valeurs renvoyées par les écouteurs appelés, dans l'ordre.
- **Ordre** : d'abord les écouteurs de la classe exacte, puis ceux des classes parentes (un écouteur de `Shipped` reçoit aussi un `ExpressShipped(Shipped)`) ; pour une même classe, l'ordre de déclaration.
- **Arrêt** : un écouteur qui renvoie `False` empêche les suivants d'être appelés.
- **Erreurs** : une exception levée par un écouteur interrompt l'émission et remonte à l'appelant (une erreur dans une route donne donc une 500, comme une erreur du controller).

Autres méthodes : `Event.has_listeners(OrderShipped)`, `Event.forget(OrderShipped)` (retire les écouteurs de cette classe).

## Tester avec `Event.fake()`

`Event.fake()` enregistre les événements émis **sans exécuter leurs écouteurs**, puis permet de vérifier ce qui a été émis. Utilisé comme bloc `with`, il rend au dispatcher son fonctionnement normal à la sortie :

```python
from wsgi import app

from flask_artisan import Event


def test_shipping_announces_the_order():
    with Event.fake() as fake:
        app.test_client().post("/api/orders/1/ship")

    fake.assert_dispatched(OrderShipped)
    fake.assert_dispatched(OrderShipped, lambda e: e.order.id == 1)
    fake.assert_dispatched_times(OrderShipped, 1)
    fake.assert_not_dispatched(OrderCancelled)
```

| Méthode | Vérifie que… |
|---|---|
| `assert_dispatched(Classe, callback=None)` | l'événement a été émis au moins une fois (et que `callback(event)` est vrai pour l'un d'eux) |
| `assert_dispatched_times(Classe, n)` | l'événement a été émis exactement `n` fois |
| `assert_not_dispatched(Classe, callback=None)` | l'événement n'a pas été émis (ou aucun ne satisfait `callback`) |
| `assert_nothing_dispatched()` | aucun événement n'a été émis |
| `dispatched(Classe)` | (pas une assertion) la liste des événements émis de cette classe |

- Un événement simulé n'exécute aucun écouteur : `Event.dispatch` renvoie alors `[]`.
- `Event.fake(OrderShipped, …)` ne simule que ces événements (et leurs sous-classes) ; les autres exécutent normalement leurs écouteurs. **Tous** restent vérifiables par les assertions.
- Le fake est un mode du dispatcher de l'application : un service qui a reçu le dispatcher avant l'appel à `fake()` passe aussi par le fake.
- Rappeler `Event.fake(...)` remplace le précédent et repart de zéro.
- **Restaurer.** Les tests du projet généré partagent une seule application (`from wsgi import app`) : un fake laissé actif bloquerait les écouteurs des tests suivants. Utilisez `with Event.fake() as fake:`, ou appelez `fake.restore()` en fin de test. Les assertions restent utilisables après la restauration.

## Générateurs

```bash
flask make:event OrderShipped                                       # app/events/order_shipped.py
flask make:listener SendShipmentNotification --event OrderShipped   # app/listeners/send_shipment_notification.py
flask make:listener Billing/MarkPaid --event Billing/InvoicePaid    # sous-dossiers permis
```

Avec `--event`, le fichier de l'événement doit déjà exister : sinon rien n'est écrit et la commande indique le chemin attendu. Après création, `make:listener` affiche les imports et l'entrée à ajouter dans `listen`.

Un écouteur qui hérite de `ShouldQueue` est exécuté en arrière-plan par la file d'attente : voir « Queues ».

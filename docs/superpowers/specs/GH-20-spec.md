# GH-20 — Événements applicatifs : `Event.dispatch` / `listen`, écouteurs, `Event.fake()`

Ticket : https://github.com/ahoblepierre/flask-artisan/issues/20
Statut : en attente d'approbation (relecture constructeur faite)

## Intention

Laisser le code d'une application **annoncer** ce qui s'est passé (« commande expédiée », « utilisateur inscrit ») sans connaître ceux qui y réagissent. Un développeur Laravel s'attend à écrire :

```python
# app/events/order_shipped.py
@dataclass
class OrderShipped:
    order: Order


# app/listeners/send_shipment_notification.py
class SendShipmentNotification:
    def __init__(self, mailer: Mailer):      # dépendances injectées par le conteneur
        self.mailer = mailer

    def handle(self, event: OrderShipped):
        self.mailer.send(event.order.user, "Votre commande est partie")


# app/providers/event_service_provider.py
class EventServiceProvider(BaseEventServiceProvider):
    listen = {OrderShipped: [SendShipmentNotification]}


# n'importe où dans l'application
Event.dispatch(OrderShipped(order))          # ou event(OrderShipped(order))
```

et, dans ses tests, `Event.fake()` puis `fake.assert_dispatched(OrderShipped)`.

Ce chantier prépare les queues : un écouteur pourra plus tard être mis en file d'attente sans changer la façon de déclarer ni d'émettre.

## Objectifs

1. Un `Dispatcher` du framework, toujours présent dans le conteneur (`"events"`, façade `Event`, helper `event()`).
2. Des écouteurs déclarés dans un `EventServiceProvider` (dictionnaire `listen`) ou par `Event.listen(...)`.
3. Des écouteurs en classes construites par le conteneur (injection dans `__init__`), ou en simples fonctions.
4. `Event.fake()` pour vérifier dans les tests qu'un événement a été émis, sans exécuter ses écouteurs.
5. `flask make:event` et `flask make:listener`.
6. Une section README complète : elle servira de base à la documentation publique.

## Non-objectifs (hors périmètre)

- Événements de modèle (`creating`, `created`, `updated`, `deleted`…).
- Écouteurs en file d'attente (`ShouldQueue`) : chantier queues.
- Événements nommés par une chaîne (`"user.login"`) et jokers (`"user.*"`).
- Subscribers (une classe qui déclare plusieurs écouteurs), découverte automatique des écouteurs.
- `Event.until()` (premier résultat non nul), écouteurs « après commit ».
- Pont avec les signaux `blinker` de Flask.

## Anti-objectifs

- Avaler une exception d'un écouteur : elle remonte à l'appelant de `dispatch`.
- Perdre un écouteur sans le dire (références faibles façon blinker).
- Exiger un contexte de requête pour émettre : une commande `flask` ou un script doit pouvoir émettre.
- Un fake qui survit d'une app à l'autre, ou qui masque des événements qu'on n'a pas demandé de simuler.

## Approches considérées

- **A. Dispatcher maison façon Laravel** (retenue). API connue d'un dev Laravel, écouteurs résolus par le conteneur, arrêt de propagation, prêt pour les queues. Environ 150 lignes, aucune dépendance.
- **B. Façade sur les signaux `blinker`.** Références faibles par défaut, pas d'arrêt de propagation, pas de résolution par le conteneur : trois contournements pour un pont que personne n'a demandé.
- **C. Décorateurs `@Event.listen`.** Plus « Python », mais l'écouteur n'existe que si son module est importé (il faudrait une découverte), et on perd la liste centrale du provider.

## Décisions

### Événements

- Un événement est un objet de n'importe quelle classe (une `dataclass` dans les modèles de fichiers). Aucune classe de base imposée.
- Il est identifié par sa classe. Un écouteur déclaré pour une classe parente reçoit aussi les événements des sous-classes.
- `dispatch` refuse ce qui n'est pas une instance (une classe, une chaîne) par une `TypeError` claire.

### `Dispatcher`

- Module : `flask_artisan/events.py` (exporte `Dispatcher`, `EventFake`, `EventServiceProvider`).
- Créé par le constructeur d'`Application`, comme le `Router` : enregistré sous `"events"` et `Dispatcher`. Façade `Event` (accesseur `"events"`) dans `facades.py` ; helper `event(obj)` dans `helpers.py`. Les deux sont exportés par `flask_artisan` et listés dans `__all__`, comme `DB` et `Auth`. La documentation utilise `Event.dispatch`, parce que `event` porte le même nom que `sqlalchemy.event`.
- Méthodes :
  - `listen(event_class, listener)` ; `listener` peut aussi être une liste.
  - `dispatch(event) -> list` : la liste des valeurs renvoyées par les écouteurs appelés, dans l'ordre.
  - `has_listeners(event_class) -> bool` (en tenant compte des classes parentes).
  - `forget(event_class)` : retire les écouteurs déclarés pour cette classe exacte.
  - `fake(*event_classes) -> EventFake` (voir plus bas).
- Formes d'écouteur acceptées :
  - une classe avec `handle(self, event)` : construite par `app.make` **à chaque émission** (pas de cache, comme Laravel), puis `handle(event)` ;
  - un tuple `(Classe, "méthode")` : même chose avec la méthode nommée (forme déjà utilisée par le routage) ;
  - une fonction ou tout appelable non-classe : appelé avec l'événement.
- Un écouteur invalide (classe sans `handle`, tuple dont la méthode n'existe pas, objet non appelable) est refusé **dès `listen`** par une `TypeError` qui nomme l'écouteur et l'événement.
- Ordre d'appel : d'abord les écouteurs de la classe exacte, puis ceux de chaque classe parente dans l'ordre du MRO (`object` exclu) ; pour une même classe, l'ordre de déclaration.
- Un écouteur qui renvoie `False` arrête la propagation : les suivants ne sont pas appelés (`False` figure dans la liste renvoyée).
- Une exception d'un écouteur interrompt `dispatch` et remonte telle quelle.
- Pas de contexte requis. Un écouteur en classe est construit par l'app qui possède le dispatcher.
- Un écouteur peut émettre d'autres événements (récursion ordinaire, aucune protection particulière).

### `EventServiceProvider`

- Classe de base du framework, `flask_artisan.events.EventServiceProvider(ServiceProvider)`, avec l'attribut de classe `listen: dict = {}` (`{ClasseÉvénement: [écouteurs…]}`).
- Son `register()` appelle `listen` pour chaque entrée. Les écouteurs du provider sont donc déclarés avant tout `boot()`.
- Le squelette fournit `app/providers/event_service_provider.py` (sous-classe vide avec un exemple commenté), ajouté à `config/app.py` après `AuthServiceProvider` et avant `AppServiceProvider`.

### `Event.fake()`

- `Event.fake()` met **le dispatcher lui-même** en mode enregistrement et renvoie un `EventFake` : un objet d'assertions lié à ce dispatcher. Aucun remplacement dans le conteneur, donc tout code qui tient déjà le `Dispatcher` (injecté pendant un `boot()`, gardé par un singleton) voit le fake (choix du constructeur de la spec, plus sûr que le remplacement d'instance de Laravel).
- `Event.fake()` sans argument : **aucun** écouteur n'est exécuté.
- `Event.fake(OrderShipped, …)` : seuls ces événements (et leurs sous-classes) sont simulés ; les autres exécutent normalement leurs écouteurs.
- Pendant le mode fake, **tous** les événements émis sont enregistrés, simulés ou non : `assert_dispatched(B)` fonctionne aussi pour un événement transmis (choix du constructeur).
- Un événement simulé : `dispatch` renvoie `[]`.
- Rappeler `fake(...)` remplace la liste des événements simulés et vide les enregistrements ; il n'y a pas d'empilement. Il renvoie un nouvel `EventFake`, et l'ancien lit le même dispatcher.
- `listen`, `has_listeners` et `forget` continuent de fonctionner normalement en mode fake.
- Assertions de `EventFake` (lèvent `AssertionError` avec un message qui nomme l'événement et le nombre d'émissions) :
  - `assert_dispatched(event_class, callback=None)` : au moins une émission ; avec `callback(event) -> bool`, au moins une émission pour laquelle il renvoie vrai ;
  - `assert_dispatched_times(event_class, times)` ;
  - `assert_not_dispatched(event_class, callback=None)` ;
  - `assert_nothing_dispatched()`.
- `dispatched(event_class) -> list` : les événements enregistrés de cette classe (sous-classes comprises).
- Portée : le dispatcher de l'app sur laquelle `fake()` a été appelé, donc jusqu'à la disparition de cette app. Pas de restauration explicite (chaque test crée son app).

### Générateurs

- `flask make:event OrderShipped` → `app/events/order_shipped.py` : `@dataclass class OrderShipped` avec un champ d'exemple commenté.
- `flask make:listener SendShipmentNotification [--event OrderShipped]` → `app/listeners/send_shipment_notification.py` : classe avec `handle(self, event)`. Avec `--event`, le fichier importe l'événement depuis `app.events.<fichier>` et annote `event: OrderShipped`.
  - `--event` suit la même syntaxe que `make:event` (sous-dossiers permis : `Billing/InvoicePaid` → `from app.events.billing.invoice_paid import InvoicePaid`). Le fichier de l'événement doit déjà exister ; sinon la commande échoue, en nommant le chemin attendu, sans rien écrire (choix du constructeur).
  - Après création, la commande affiche la ligne à ajouter dans `listen` de l'`EventServiceProvider`.
- Sous-dossiers permis pour les deux, comme `make:controller`. Mêmes règles que les autres générateurs (`--force`, noms invalides, sortie qui passe ruff).

### Squelette

- `app/events/__init__.py`, `app/listeners/__init__.py` (vides).
- `app/providers/event_service_provider.py` et son ajout dans `config/app.py`.
- Pas d'événement d'exemple livré.

### Documentation

- README : section « Événements ». Elle doit suffire à un lecteur qui ne connaît pas Laravel et servir de base à la future documentation publique. Elle couvre :
  - définir un événement ;
  - écrire un écouteur (classe, tuple, fonction ; injection) ;
  - les déclarer (`EventServiceProvider`, `Event.listen`) ;
  - émettre (`Event.dispatch`, `event()`, valeur renvoyée) ;
  - l'ordre d'appel, l'arrêt par `False`, les exceptions, l'héritage ;
  - tester avec `Event.fake()` et chaque assertion ;
  - les générateurs.
- `make:event` et `make:listener` ajoutés à la section « Console ».
- CLAUDE.md : le `Dispatcher` créé par `Application`, et le fake qui remplace l'instance dans le conteneur.
- CHANGELOG : section « Non publié ».

## Pièges connus

- **Références déjà prises.** Des services ont pu recevoir le `Dispatcher` pendant le `boot()`, avant qu'un test appelle `fake()`. C'est pour ça que le fake est un mode du dispatcher, et non une instance de remplacement.
- **Tests du conteneur.** Tout nouvel attribut d'`Application` doit passer les deux tests qui interdisent de masquer un attribut de Flask. Ce module n'en ajoute aucun : le dispatcher vit dans le conteneur.
- **Classes locales dans les tests.** Un écouteur en classe locale fonctionne avec `app.make` (aucune résolution par nom, contrairement au routage).
- **Le nom `Event`.** Il ne doit pas entrer en conflit avec un nom de Flask ou de SQLAlchemy importé dans `flask_artisan/__init__.py`.

## Laissé au constructeur

- Structure interne du `Dispatcher` (dictionnaire de listes, normalisation des écouteurs à `listen`).
- Texte exact des messages d'erreur et d'assertion, dans le respect des points ci-dessus.
- Contenu exact des modèles de fichiers.

## Livraison

- Tests pytest :
  - dispatch : classe, tuple, fonction, injection dans `__init__`, nouvelle instance à chaque émission, héritage et ordre, arrêt par `False`, valeur renvoyée, exception qui remonte, écouteur invalide refusé à `listen`, dispatch d'une non-instance refusé, émission hors requête, `has_listeners`, `forget` ;
  - `EventServiceProvider` : un provider de test avec `listen` ;
  - fake :
    - complet ou partiel ;
    - transmission des autres événements, eux aussi enregistrés ;
    - chaque assertion, en succès et en échec avec son message ;
    - callback et `dispatched` ;
    - un service qui a reçu le `Dispatcher` avant `fake()` passe lui aussi par le fake ;
    - un second `fake()` remplace le premier et vide les enregistrements ;
  - générateurs : `make:event`, `make:listener` avec et sans `--event` (sous-dossier compris), `--event` vers un fichier absent, ruff.
- Test de bout en bout du projet généré :
  - `make:event` puis `make:listener --event` ;
  - ajout de l'écouteur dans `listen` ;
  - un script qui émet l'événement et constate l'effet de l'écouteur.
- README, CLAUDE.md, CHANGELOG à jour.
- PR `feat/20-events`, titre avec `(#20)`, corps avec `Closes #20`. CI verte sur 3.10 à 3.13.

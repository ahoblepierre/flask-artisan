# Événements applicatifs (GH-20) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `Dispatcher` toujours présent (`"events"`, façade `Event`, helper `event()`), écouteurs classe / tuple / fonction résolus par le conteneur, `EventServiceProvider`, `Event.fake()` en mode du dispatcher, `make:event` / `make:listener`, doc complète.

**Architecture:** un module `src/flask_artisan/events.py` (`Dispatcher`, `EventFake`, `EventServiceProvider`). `Application.__init__` crée le dispatcher à côté du `Router`. Le fake est un état interne du dispatcher (`_faking`, `_faked`, `_recorded`) lu par un `EventFake` d'assertions : aucune substitution dans le conteneur.

**Tech Stack:** Flask ≥ 3, click, pytest, ruff.

**Spec:** `docs/superpowers/specs/GH-20-spec.md`

## Global Constraints

- Aucune nouvelle dépendance ; aucun nouvel attribut sur `Application` (le dispatcher vit dans le conteneur).
- Écouteur en classe construit par `app.make` **à chaque émission**.
- Ordre : classe exacte, puis MRO (sans `object`) ; ordre de déclaration pour une même classe. `False` arrête ; les exceptions remontent.
- Écouteur invalide → `TypeError` dès `listen`, message qui nomme l'écouteur et l'événement. `dispatch` d'une classe ou d'une chaîne → `TypeError`.
- Fake : mode du dispatcher ; tous les événements enregistrés pendant le fake ; simulés → `[]` sans écouteurs ; second `fake()` remplace le filtre et vide les enregistrements.
- Exports `flask_artisan` : `Event`, `event` dans `__all__`.
- Commits `… (#20)` ; code et fichiers générés passent `ruff check` / `ruff format --check`.

## Review Focus

1. Un service qui a reçu le `Dispatcher` par injection **avant** `Event.fake()` passe par le fake (pas d'écouteur exécuté).
2. Fake partiel `fake(A)` avec `B(A)` sous-classe : `B` est simulé ; `C` non lié exécute ses écouteurs et reste vérifiable par `assert_dispatched(C)`.
3. Un écouteur qui émet un autre événement pendant le fake : les deux sont enregistrés, dans l'ordre.
4. `make:listener --event Typo` : aucun fichier écrit, message qui nomme `app/events/typo.py`.
5. Même écouteur déclaré pour une classe et sa parente : appelé deux fois (une par déclaration), comme Laravel — pas de dédoublonnage.

---

### Task 1: `Dispatcher`, façade `Event`, helper `event()`

**Files:**
- Create: `src/flask_artisan/events.py`
- Modify: `src/flask_artisan/application.py` (création à côté du `Router`), `src/flask_artisan/facades.py` (`class Event(Facade): accessor = "events"`), `src/flask_artisan/helpers.py` (`event`), `src/flask_artisan/__init__.py` (exports)
- Test: `tests/test_events.py`

**Interfaces:**
- Produces:
  - `class Dispatcher` : `__init__(self, app)`, `listen(event_class: type, listener) -> None` (listener ou liste), `dispatch(event) -> list`, `has_listeners(event_class: type) -> bool`, `forget(event_class: type) -> None`.
  - `app.make("events") is app.make(Dispatcher)`.
  - `event(obj) -> list` dans `helpers.py` = `app("events").dispatch(obj)`.

- [ ] **Step 1: Write the failing tests** (`tests/test_events.py`) — fixture `app` = `Application(make_project())`; classes d'événements locales `Shipped`, `Express(Shipped)`, `Other`; un journal `log = []`.

```python
def test_registered_in_container(app):
    assert app.make("events") is app.make(Dispatcher)

def test_function_listener_and_return_values(app):
    Event.listen(Shipped, lambda e: log.append(("fn", e)) or "r1")
    e = Shipped()
    assert Event.dispatch(e) == ["r1"] and log == [("fn", e)]

def test_class_listener_injected_and_fresh_each_time(app):
    class Service: ...
    app.singleton(Service)
    seen = []
    class Listener:
        def __init__(self, service: Service): self.service = service
        def handle(self, e): seen.append(self)
    Event.listen(Shipped, Listener)
    event(Shipped()); event(Shipped())
    assert len(seen) == 2 and seen[0] is not seen[1] and seen[0].service is app.make(Service)

def test_tuple_listener(app):
    class L:
        def on_ship(self, e): log.append("tuple")
    Event.listen(Shipped, (L, "on_ship")); event(Shipped())
    assert log == ["tuple"]

def test_parent_listeners_after_exact_class_in_declaration_order(app):
    Event.listen(Shipped, [lambda e: log.append("parent1"), lambda e: log.append("parent2")])
    Event.listen(Express, lambda e: log.append("child"))
    event(Express())
    assert log == ["child", "parent1", "parent2"]
    assert Event.has_listeners(Express) and not Event.has_listeners(Other)

def test_false_stops_propagation(app):
    Event.listen(Shipped, [lambda e: False, lambda e: log.append("never")])
    assert event(Shipped()) == [False] and log == []

def test_exception_propagates_and_stops(app):
    def boom(e): raise RuntimeError("boom")
    Event.listen(Shipped, [boom, lambda e: log.append("never")])
    with pytest.raises(RuntimeError, match="boom"): event(Shipped())
    assert log == []

@pytest.mark.parametrize("bad", [object(), type("NoHandle", (), {}), ("x", "y"), (type("C", (), {}), "missing")])
def test_invalid_listener_rejected_at_listen(app, bad):
    with pytest.raises(TypeError, match="Shipped"): Event.listen(Shipped, bad)

@pytest.mark.parametrize("bad", [Shipped, "shipped"])
def test_dispatch_requires_instance(app, bad):
    with pytest.raises(TypeError): Event.dispatch(bad)

def test_forget(app):
    Event.listen(Shipped, lambda e: log.append("x")); Event.forget(Shipped); event(Shipped())
    assert log == [] and not Event.has_listeners(Shipped)

def test_dispatch_outside_request_and_app_context(app):
    Event.listen(Shipped, lambda e: log.append("ok")); app.make("events").dispatch(Shipped())
    assert log == ["ok"]

def test_same_listener_on_child_and_parent_runs_twice(app):
    fn = lambda e: log.append("x")  # noqa: E731
    Event.listen(Shipped, fn); Event.listen(Express, fn); event(Express())
    assert log == ["x", "x"]

def test_top_level_exports():
    import flask_artisan
    assert {"Event", "event"} <= set(flask_artisan.__all__)
```

- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_events.py -q` — Expected: FAIL (`ModuleNotFoundError: flask_artisan.events`).
- [ ] **Step 3: Implement** `Dispatcher` (dictionnaire `{classe: [appelables normalisés]}` ; normalisation à `listen` : classe → `lambda e: app.make(cls).handle(e)`, tuple → idem avec la méthode, appelable non-classe tel quel ; validation `TypeError`), puis branchement `Application`, façade, helper, exports.
- [ ] **Step 4: Run** `.venv/bin/pytest -q` — Expected: PASS (toute la suite, dont les tests qui interdisent de masquer un attribut Flask).
- [ ] **Step 5: Commit** `feat: Dispatcher d'événements, façade Event et helper event() (#20)`

### Task 2: `EventServiceProvider` et `Event.fake()`

**Files:**
- Modify: `src/flask_artisan/events.py`
- Test: `tests/test_event_fake.py`

**Interfaces:**
- Consumes: `Dispatcher` (Task 1), `ServiceProvider`.
- Produces:
  - `class EventServiceProvider(ServiceProvider)` : `listen: ClassVar[dict] = {}` ; `register()` appelle `self.app.make("events").listen(cls, listeners)` pour chaque entrée.
  - `Dispatcher.fake(*event_classes) -> EventFake`.
  - `class EventFake` : `dispatched(event_class) -> list`, `assert_dispatched(event_class, callback=None)`, `assert_dispatched_times(event_class, times)`, `assert_not_dispatched(event_class, callback=None)`, `assert_nothing_dispatched()`.

- [ ] **Step 1: Write the failing tests** (`tests/test_event_fake.py`) — mêmes classes d'événements que Task 1 (redéfinies localement au fichier).

```python
def test_provider_listen_map(make_project):
    from flask_artisan.events import EventServiceProvider
    class Provider(EventServiceProvider):
        listen = {Shipped: [lambda e: log.append("provider")]}
    app = Application(make_project()); app.register(Provider)
    event(Shipped()); assert log == ["provider"]

def test_full_fake_runs_no_listener_and_records(app):
    Event.listen(Shipped, lambda e: log.append("x"))
    fake = Event.fake()
    e = Shipped()
    assert Event.dispatch(e) == [] and log == []
    fake.assert_dispatched(Shipped); assert fake.dispatched(Shipped) == [e]

def test_partial_fake_simulates_subclasses_and_forwards_others(app):
    Event.listen(Express, lambda e: log.append("express")); Event.listen(Other, lambda e: log.append("other"))
    fake = Event.fake(Shipped)
    event(Express()); event(Other())
    assert log == ["other"]
    fake.assert_dispatched(Express); fake.assert_dispatched(Other)

def test_service_holding_dispatcher_before_fake_sees_it(app):
    class Notifier:
        def __init__(self, events: Dispatcher): self.events = events
    app.singleton(Notifier); notifier = app.make(Notifier)
    Event.listen(Shipped, lambda e: log.append("x"))
    fake = Event.fake(); notifier.events.dispatch(Shipped())
    assert log == []; fake.assert_dispatched_times(Shipped, 1)

def test_nested_dispatch_recorded_in_order(app):
    Event.listen(Other, lambda e: event(Shipped()))
    fake = Event.fake(Shipped)
    event(Other())
    assert [type(e) for e in fake.dispatched(object)] == [Other, Shipped]

def test_second_fake_replaces_and_clears(app):
    Event.fake(); event(Shipped())
    fake = Event.fake(Other)
    Event.listen(Shipped, lambda e: log.append("x")); event(Shipped())
    assert log == ["x"]; fake.assert_dispatched_times(Shipped, 1)

def test_callback_assertions(app):
    fake = Event.fake(); event(Shipped())
    fake.assert_dispatched(Shipped, lambda e: isinstance(e, Shipped))
    fake.assert_not_dispatched(Shipped, lambda e: False)
    with pytest.raises(AssertionError, match="Shipped"):
        fake.assert_dispatched(Shipped, lambda e: False)

@pytest.mark.parametrize("check", [
    lambda f: f.assert_dispatched(Other),
    lambda f: f.assert_dispatched_times(Shipped, 2),
    lambda f: f.assert_not_dispatched(Shipped),
    lambda f: f.assert_nothing_dispatched(),
])
def test_failing_assertions_name_event_and_count(app, check):
    fake = Event.fake(); event(Shipped())
    with pytest.raises(AssertionError, match=r"(Shipped|Other).*\d"):
        check(fake)

def test_listen_and_forget_still_work_in_fake_mode(app):
    Event.fake(Other); Event.listen(Shipped, lambda e: log.append("x")); event(Shipped())
    Event.forget(Shipped); event(Shipped())
    assert log == ["x"]
```

- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_event_fake.py -q` — Expected: FAIL (`ImportError: EventServiceProvider` / `AttributeError: fake`).
- [ ] **Step 3: Implement** the provider, the fake state in `Dispatcher.dispatch` (enregistrer si `_faking`, retourner `[]` si `_faked is None` ou `isinstance(event, _faked)`), and `EventFake` (messages : `"Événement Shipped émis 1 fois, attendu 2."` etc.).
- [ ] **Step 4: Run** `.venv/bin/pytest tests/test_events.py tests/test_event_fake.py -q` — Expected: PASS.
- [ ] **Step 5: Commit** `feat: EventServiceProvider et Event.fake() avec assertions (#20)`

### Task 3: `make:event` et `make:listener`

**Files:**
- Create: `src/flask_artisan/stubs/event.stub`, `src/flask_artisan/stubs/listener.stub`, `src/flask_artisan/stubs/listener.event.stub`
- Modify: `src/flask_artisan/console.py` (`make_event`, `make_listener`, `COMMANDS`)
- Test: `tests/test_console.py`

**Interfaces:**
- Consumes: `split_name`, `write_stub(folder, name, stub, *, force, **values)`, `class_to_file`.
- Produces: `listener.event.stub` reçoit `$event_import` (ex. `from app.events.billing.invoice_paid import InvoicePaid`) et `$event_class`. Après création, `make:listener` affiche `Ajoutez-le à "listen" dans app/providers/event_service_provider.py :` suivi de la ligne d'import de l'écouteur.

- [ ] **Step 1: Write the failing tests** (ajoutés à `tests/test_console.py`)

```python
def test_make_event(artisan):
    import dataclasses
    app, run = artisan
    assert run("make:event", "OrderShipped").exit_code == 0
    path = app.base_path("app/events/order_shipped.py")
    assert dataclasses.is_dataclass(load(path).OrderShipped)
    assert_ruff_clean(path)

def test_make_listener_without_event(artisan):
    app, run = artisan
    result = run("make:listener", "SendShipmentNotification")
    assert result.exit_code == 0, result.output
    assert "event_service_provider.py" in result.output
    path = app.base_path("app/listeners/send_shipment_notification.py")
    assert callable(load(path).SendShipmentNotification().handle)
    assert_ruff_clean(path)

def test_make_listener_with_event_in_subfolder(artisan):
    app, run = artisan
    assert run("make:event", "Billing/InvoicePaid").exit_code == 0
    assert run("make:listener", "MarkPaid", "--event", "Billing/InvoicePaid").exit_code == 0
    source = app.base_path("app/listeners/mark_paid.py").read_text()
    assert "from app.events.billing.invoice_paid import InvoicePaid" in source
    assert "event: InvoicePaid" in source
    assert_ruff_clean(app.base_path("app/listeners/mark_paid.py"))

def test_make_listener_with_missing_event_writes_nothing(artisan):
    app, run = artisan
    result = run("make:listener", "MarkPaid", "--event", "Typo")
    assert result.exit_code != 0 and "app/events/typo.py" in result.output
    assert not app.base_path("app/listeners/mark_paid.py").exists()
```

- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_console.py -q -k "make_event or make_listener"` — Expected: FAIL (`No such command`).
- [ ] **Step 3: Implement** stubs and commands (`--event` validé par `split_name(..., allow_dirs=True)`, existence du fichier vérifiée **avant** `write_stub`).
- [ ] **Step 4: Run** `.venv/bin/pytest tests/test_console.py -q` — Expected: PASS.
- [ ] **Step 5: Commit** `feat: make:event et make:listener (#20)`

### Task 4: Squelette, bout en bout, documentation

**Files:**
- Create: `src/flask_artisan/skeleton/app/events/__init__.py`, `src/flask_artisan/skeleton/app/listeners/__init__.py`, `src/flask_artisan/skeleton/app/providers/event_service_provider.py`
- Modify: `src/flask_artisan/skeleton/config/app.py`, `tests/test_cli.py`, `README.md`, `CLAUDE.md`, `CHANGELOG.md`

**Interfaces:**
- Consumes: `EventServiceProvider` (Task 2), générateurs (Task 3).

- [ ] **Step 1: Write the failing test** (`tests/test_cli.py`)

```python
def test_generated_project_events_flow(project):
    for args in (("make:event", "OrderShipped"), ("make:listener", "LogShipment", "--event", "OrderShipped")):
        result = run(project, "-m", "flask", *args)
        assert result.returncode == 0, result.stdout + result.stderr
    listener = project / "app/listeners/log_shipment.py"
    listener.write_text(listener.read_text().replace("pass", 'print("SHIPPED")'))  # ajuster au contenu réel du stub
    provider = project / "app/providers/event_service_provider.py"
    provider.write_text(
        "from app.events.order_shipped import OrderShipped\n"
        "from app.listeners.log_shipment import LogShipment\n"
        "from flask_artisan.events import EventServiceProvider as Base\n\n\n"
        "class EventServiceProvider(Base):\n    listen = {OrderShipped: [LogShipment]}\n"
    )
    out = run(project, "-c", "from wsgi import app\nfrom flask_artisan import Event\n"
              "from app.events.order_shipped import OrderShipped\nEvent.dispatch(OrderShipped())")
    assert "SHIPPED" in out.stdout, out.stdout + out.stderr
```

(Si le modèle d'événement a un champ obligatoire, le stub doit n'en avoir aucun d'actif : seulement un exemple commenté.)

- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_cli.py::test_generated_project_events_flow -q` — Expected: FAIL (`EventServiceProvider` du squelette absent → l'import de provider ou le script échoue).
- [ ] **Step 3: Implement** squelette (provider vide avec exemple commenté, ajouté à `config/app.py` après `AuthServiceProvider`, avant `AppServiceProvider`), puis documentation :
  - README section « Événements » couvrant chaque point listé dans la spec (définir, écouteurs classe/tuple/fonction et injection, déclaration provider / `Event.listen`, émission et valeur renvoyée, ordre, `False`, exceptions, héritage, `Event.fake()` et chaque assertion, générateurs) ; `make:event` / `make:listener` dans « Console » ; « Après la v0.1 » : ✅ Événements ;
  - CLAUDE.md : puce « Événements » dans Architecture (dispatcher créé par `Application`, fake = mode du dispatcher, écouteurs reconstruits à chaque émission) ;
  - CHANGELOG : `## [Non publié]` / « Ajouté : événements… ».
- [ ] **Step 4: Run** `.venv/bin/pytest -q && .venv/bin/ruff check . && .venv/bin/ruff format --check .` — Expected: tout passe.
- [ ] **Step 5: Commit** `feat: EventServiceProvider dans le squelette, docs des événements (#20)`

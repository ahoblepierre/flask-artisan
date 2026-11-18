import inspect
import threading
import typing
from collections.abc import Callable
from typing import Any

Abstract = type | str
Concrete = type | Callable[["Container"], Any] | None


class BindingResolutionError(Exception):
    pass


class Container:
    """Conteneur de services façon Laravel : bind, singleton, instance, make.

    Tout l'état interne est préfixé `_container_` pour ne jamais masquer un attribut de Flask.
    """

    def __init__(self):
        self._container_bindings: dict = {}
        self._container_instances: dict = {}
        self._container_lock = threading.RLock()
        self._container_local = threading.local()

    def bind(self, abstract: Abstract, concrete: Concrete = None) -> None:
        self._container_register(abstract, concrete, shared=False)

    def singleton(self, abstract: Abstract, concrete: Concrete = None) -> None:
        self._container_register(abstract, concrete, shared=True)

    def instance(self, abstract: Abstract, obj: Any) -> Any:
        self._container_instances[abstract] = obj
        return obj

    def bound(self, abstract: Abstract) -> bool:
        return abstract in self._container_bindings or abstract in self._container_instances

    def make(self, abstract: Abstract, **params) -> Any:
        if abstract in self._container_instances and not params:
            return self._container_instances[abstract]

        concrete, shared = self._container_bindings.get(abstract, (abstract, False))
        if not shared or params:
            return self._container_build(abstract, concrete, params)

        with self._container_lock:
            if abstract not in self._container_instances:
                self._container_instances[abstract] = self._container_build(abstract, concrete, {})
            return self._container_instances[abstract]

    def _container_register(self, abstract: Abstract, concrete: Concrete, shared: bool) -> None:
        if concrete is None:
            if not isinstance(abstract, type):
                raise BindingResolutionError(f"Aucune implémentation fournie pour '{abstract}'.")
            concrete = abstract
        self._container_instances.pop(abstract, None)
        self._container_bindings[abstract] = (concrete, shared)

    def _container_build(self, abstract: Abstract, concrete: Any, params: dict) -> Any:
        if isinstance(concrete, type):
            return self._container_autowire(concrete, params)
        if callable(concrete):
            return concrete(self)
        raise BindingResolutionError(
            f"Impossible de résoudre '{abstract}' : rien n'est enregistré."
        )

    def _container_autowire(self, cls: type, params: dict) -> Any:
        stack = self._container_stack()
        if cls in stack:
            chain = " -> ".join(c.__name__ for c in [*stack, cls])
            raise BindingResolutionError(f"Dépendance circulaire détectée : {chain}")
        stack.append(cls)
        try:
            return cls(**self._container_arguments(cls, params))
        finally:
            stack.pop()

    def _container_arguments(self, cls: type, params: dict) -> dict:
        if cls.__init__ is object.__init__:
            return dict(params)
        try:
            hints = typing.get_type_hints(cls.__init__)
        except Exception as exc:
            raise BindingResolutionError(
                f"Annotations illisibles dans {cls.__name__}.__init__ : {exc}"
            ) from exc

        args = {}
        for name, param in list(inspect.signature(cls.__init__).parameters.items())[1:]:
            if param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
                continue
            if name in params:
                args[name] = params[name]
                continue
            hint = hints.get(name)
            if self._container_resolvable(hint):
                args[name] = self.make(hint)
            elif param.default is not param.empty:
                args[name] = param.default
            else:
                raise BindingResolutionError(
                    f"Impossible de résoudre le paramètre '{name}' de {cls.__name__} : "
                    "ajoutez une annotation de classe, une valeur par défaut ou passez-le à make()."
                )
        return args

    def _container_resolvable(self, hint: Any) -> bool:
        if hint is None:
            return False
        if self.bound(hint):
            return True
        # Les types natifs (str, int…) ne sont pas auto-construits : valeur par défaut ou erreur.
        return isinstance(hint, type) and hint.__module__ != "builtins"

    def _container_stack(self) -> list:
        if not hasattr(self._container_local, "stack"):
            self._container_local.stack = []
        return self._container_local.stack

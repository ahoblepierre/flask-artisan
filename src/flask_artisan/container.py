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

        stack = self._container_stack()
        if abstract in stack:
            chain = " -> ".join(_name(a) for a in [*stack, abstract])
            raise BindingResolutionError(f"Dépendance circulaire détectée : {chain}")
        stack.append(abstract)
        try:
            concrete, shared = self._container_bindings.get(abstract, (abstract, False))
            if not shared or params:
                return self._container_build(abstract, concrete, params)

            with self._container_lock:
                if abstract not in self._container_instances:
                    built = self._container_build(abstract, concrete, {})
                    self._container_instances[abstract] = built
                return self._container_instances[abstract]
        finally:
            stack.pop()

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
        if inspect.isabstract(cls):
            raise BindingResolutionError(
                f"{cls.__name__} est abstraite : liez-la à une implémentation avec bind()."
            )
        if cls.__init__ is object.__init__:
            return cls(**params)
        args = self._container_arguments(
            cls.__init__, cls.__name__, params, keep_unknown=False, skip_first=True
        )
        return cls(**args)

    def call(self, fn: Callable, **params) -> Any:
        """Appelle `fn` en injectant ses paramètres (valeurs passées, puis ordre de make)."""
        owner = getattr(fn, "__qualname__", repr(fn))
        return fn(**self._container_arguments(fn, owner, params, keep_unknown=True))

    def _container_arguments(
        self, fn: Callable, owner: str, params: dict, *, keep_unknown: bool, skip_first=False
    ) -> dict:
        try:
            hints = typing.get_type_hints(fn)
        except Exception as exc:
            raise BindingResolutionError(f"Annotations illisibles dans {owner} : {exc}") from exc

        parameters = list(inspect.signature(fn).parameters.items())[1 if skip_first else 0 :]
        args = {}
        for name, param in parameters:
            if param.kind == param.VAR_KEYWORD:
                if keep_unknown:
                    args.update({k: v for k, v in params.items() if k not in args})
                continue
            if param.kind == param.VAR_POSITIONAL:
                continue
            if name in params:
                args[name] = params[name]
                continue
            hint = hints.get(name)
            # Ordre Laravel : binding explicite, puis valeur par défaut, puis autowiring.
            if hint is not None and self._container_is_key(hint) and self.bound(hint):
                args[name] = self.make(hint)
            elif param.default is not param.empty:
                args[name] = param.default
            elif self._container_autowirable(hint):
                args[name] = self.make(hint)
            else:
                raise BindingResolutionError(
                    f"Impossible de résoudre le paramètre '{name}' de {owner} : "
                    "ajoutez une annotation de classe, une valeur par défaut ou passez-le "
                    "explicitement."
                )
        return args

    @staticmethod
    def _container_is_key(hint: Any) -> bool:
        return isinstance(hint, (type, str))

    @staticmethod
    def _container_autowirable(hint: Any) -> bool:
        # Les types natifs (str, int…), Any et les classes abstraites ne sont pas auto-construits.
        return (
            isinstance(hint, type)
            and hint.__module__ != "builtins"
            and hint is not Any
            and not inspect.isabstract(hint)
        )

    def _container_stack(self) -> list:
        if not hasattr(self._container_local, "stack"):
            self._container_local.stack = []
        return self._container_local.stack


def _name(abstract: Any) -> str:
    return abstract.__name__ if isinstance(abstract, type) else str(abstract)

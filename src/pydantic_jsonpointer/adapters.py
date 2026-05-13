"""Container adapter Protocol and registry.

A ContainerAdapter teaches the traversal layer how to read/write a specific
container type. The registry maps runtime types to adapter instances, with
MRO-aware lookup so subclasses inherit registration.

`unwrap()` uses the built-in `Ellipsis` singleton (`...`) as its "no unwrap"
return marker. Adapters MUST return `...` to mean "use the value as-is";
returning a real Ellipsis payload (e.g. a RootModel wrapping `Ellipsis`)
would be indistinguishable from "no unwrap". This is a documented constraint
on adapter authors; the practical impact is nil because no real document
contains `...`.
"""

from __future__ import annotations

from typing import Any, Protocol, TypeGuard, runtime_checkable

from .errors import AdapterNotFoundError, InvalidTokenError, PointerNotFoundError


def _is_ascii_digits(s: str) -> bool:
    """True iff ``s`` is a non-empty sequence of ASCII ``0``-``9`` characters."""
    return bool(s) and all("0" <= c <= "9" for c in s)


def _is_int_index(key: Any) -> TypeGuard[int]:
    """True iff ``key`` is a real int (rejects ``bool`` since ``True``/``False``
    would otherwise be accepted as valid indices via ``isinstance(True, int)``).
    """
    return isinstance(key, int) and not isinstance(key, bool)


@runtime_checkable
class ContainerAdapter(Protocol):
    """Per-type strategy for reading/writing a container at a JSON-pointer key.

    Every public method receives `parent` (the container) and (for non-resolve
    methods) `key` (already coerced via resolve_token). Adapters are expected
    to be stateless — they are shared across calls.

    `unwrap` returns `...` (Ellipsis) to mean "no unwrap; use value as-is",
    or the inner value to substitute transparently.

    Adapters may OPTIONALLY define ``is_value_frozen(value) -> bool``: when
    present, the walker treats it as an additional taint source so that an
    immutable wrapper (e.g. a frozen ``RootModel``) propagates the freeze
    bit through ``unwrap`` to its inner payload. Adapters that omit the hook
    — including any third-party adapter written against the canonical
    8-method contract — are treated as if it returned False. The hook is
    deliberately outside the required Protocol surface so legacy adapters
    keep satisfying ``isinstance(adapter, ContainerAdapter)`` and static
    type-checks against ``register()``.
    """

    def resolve_token(self, parent: Any, raw_token: str) -> int | str: ...
    def has(self, parent: Any, key: int | str) -> bool: ...
    def get(self, parent: Any, key: int | str) -> Any: ...
    def set(self, parent: Any, key: int | str, value: Any) -> None: ...
    def add(self, parent: Any, key: int | str, value: Any) -> None: ...
    def remove(self, parent: Any, key: int | str) -> Any: ...
    def unwrap(self, value: Any) -> Any: ...
    def is_step_frozen(self, parent: Any, key: int | str) -> bool: ...


_REGISTRY: dict[type, ContainerAdapter] = {}


def register(
    container_type: type,
    adapter: ContainerAdapter,
    *,
    override: bool = False,
) -> None:
    """Register `adapter` as the handler for `container_type`.

    Subsequent `adapter_for(value)` calls return `adapter` when
    `type(value)` is `container_type` or a subclass of it (via MRO walk).

    Raises ValueError if the type is already registered unless override=True.
    """
    if not override and container_type in _REGISTRY:
        raise ValueError(
            f"adapter already registered for {container_type!r}; "
            f"pass override=True to replace it"
        )
    _REGISTRY[container_type] = adapter


def adapter_for(value: Any, *, resolver: Any = None) -> ContainerAdapter:
    """Look up the adapter for `type(value)` via MRO walk.

    If `resolver` is provided AND the resolved adapter is a
    ``BaseModelAdapter`` (or subclass), returns a per-call clone produced by
    ``adapter.with_resolver(resolver)`` — a shallow copy of the registered
    instance with its resolver substituted. Subclass identity and any extra
    state on the registered instance are preserved; subclasses with state
    that needs custom cloning can override ``with_resolver``. The registered
    adapter itself is never mutated.

    Raises AdapterNotFoundError if no adapter is registered for any class
    in the value's MRO.
    """
    for cls in type(value).__mro__:
        adapter = _REGISTRY.get(cls)
        if adapter is not None:
            if resolver is not None:
                from .pydantic_adapter import BaseModelAdapter

                if isinstance(adapter, BaseModelAdapter):
                    return adapter.with_resolver(resolver)
            return adapter
    raise AdapterNotFoundError(
        f"no adapter registered for type {type(value).__name__!r}"
    )


class DictAdapter:
    """Adapter for built-in ``dict`` containers.

    Tokens are used verbatim as keys (already RFC-6901-unescaped by JsonPointer).
    """

    def resolve_token(self, parent: Any, raw_token: str) -> str:
        return raw_token

    def has(self, parent: Any, key: int | str) -> bool:
        return key in parent

    def get(self, parent: Any, key: int | str) -> Any:
        try:
            return parent[key]
        except KeyError as exc:
            raise PointerNotFoundError(repr(key)) from exc

    def set(self, parent: Any, key: int | str, value: Any) -> None:
        if key not in parent:
            raise PointerNotFoundError(
                f"cannot replace {key!r}: key not present"
            )
        parent[key] = value

    def add(self, parent: Any, key: int | str, value: Any) -> None:
        parent[key] = value

    def remove(self, parent: Any, key: int | str) -> Any:
        try:
            return parent.pop(key)
        except KeyError as exc:
            raise PointerNotFoundError(repr(key)) from exc

    def unwrap(self, value: Any) -> Any:
        return ...

    def is_step_frozen(self, parent: Any, key: int | str) -> bool:
        return False


register(dict, DictAdapter())


class ListAdapter:
    """Adapter for built-in ``list`` containers.

    RFC 6901 array-index rules: the token must be either ``"-"`` (tail marker,
    only valid for ``add``) or a run of decimal digits with no leading zero
    (except the single-character ``"0"``).
    """

    DASH = "-"

    def resolve_token(self, parent: Any, raw_token: str) -> int | str:
        if raw_token == self.DASH:
            return self.DASH
        # RFC 6901 §4: array index tokens are ASCII decimal digits only.
        # ``str.isdecimal`` would accept non-ASCII Unicode digits (e.g. Arabic-Indic).
        if not raw_token or not _is_ascii_digits(raw_token):
            raise InvalidTokenError(
                f"invalid array index {raw_token!r}: "
                "expected non-negative decimal or '-'"
            )
        if len(raw_token) > 1 and raw_token[0] == "0":
            raise InvalidTokenError(
                f"invalid array index {raw_token!r}: leading zero not permitted"
            )
        return int(raw_token)

    def has(self, parent: Any, key: int | str) -> bool:
        if not _is_int_index(key):
            return False
        return 0 <= key < len(parent)

    def get(self, parent: Any, key: int | str) -> Any:
        if key == self.DASH:
            raise InvalidTokenError(
                "cannot get '-': no element exists at the tail position"
            )
        if not _is_int_index(key):
            raise InvalidTokenError(
                f"invalid array index {key!r}: expected int"
            )
        if not (0 <= key < len(parent)):
            raise PointerNotFoundError(
                f"list index {key} out of range (len={len(parent)})"
            )
        return parent[key]

    def set(self, parent: Any, key: int | str, value: Any) -> None:
        if key == self.DASH:
            raise InvalidTokenError(
                "cannot replace at '-': no element exists at the tail position"
            )
        if not _is_int_index(key):
            raise InvalidTokenError(
                f"invalid array index {key!r}: expected int"
            )
        if not (0 <= key < len(parent)):
            raise PointerNotFoundError(
                f"list index {key} out of range (len={len(parent)})"
            )
        parent[key] = value

    def add(self, parent: Any, key: int | str, value: Any) -> None:
        if key == self.DASH:
            parent.append(value)
            return
        if not _is_int_index(key):
            raise InvalidTokenError(
                f"invalid array index {key!r}: expected int"
            )
        if not (0 <= key <= len(parent)):
            raise InvalidTokenError(
                f"list index {key} out of range for add (len={len(parent)})"
            )
        parent.insert(key, value)

    def remove(self, parent: Any, key: int | str) -> Any:
        if key == self.DASH:
            raise InvalidTokenError(
                "cannot remove '-': no element exists at the tail position"
            )
        if not _is_int_index(key):
            raise InvalidTokenError(
                f"invalid array index {key!r}: expected int"
            )
        if not (0 <= key < len(parent)):
            raise PointerNotFoundError(
                f"list index {key} out of range (len={len(parent)})"
            )
        return parent.pop(key)

    def unwrap(self, value: Any) -> Any:
        return ...

    def is_step_frozen(self, parent: Any, key: int | str) -> bool:
        return False


register(list, ListAdapter())

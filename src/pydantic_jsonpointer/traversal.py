"""Pointer-traversal API: Ptr cursor, walker, and convenience functions.

Layered above `adapters` and `errors`. The Pydantic-specific
`BaseModelAdapter` is registered against `pydantic.BaseModel` in
`__init__.py`, so this module does not import Pydantic directly.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from .adapters import ContainerAdapter, adapter_for
from .errors import (
    AdapterNotFoundError,
    ImmutableTargetError,
    PointerError,
    PointerNotFoundError,
    RootRebindError,
)
from .types import JsonPointer


@dataclass(frozen=True, slots=True)
class Ptr:
    """A live cursor into a ``(parent, key)`` slot of a document.

    ``Ptr`` instances are produced by ``resolve(doc, pointer)``. Reads and
    mutations always re-execute through ``_adapter``; the cursor does not
    cache the value at ``(_parent, _key)``.
    """

    pointer: JsonPointer
    _parent: Any
    _key: int | str | None
    _adapter: ContainerAdapter
    _frozen: bool = False

    @property
    def parent(self) -> Any:
        return self._parent

    @property
    def key(self) -> int | str | None:
        return self._key

    @property
    def is_root(self) -> bool:
        return self._key is None

    @property
    def is_frozen(self) -> bool:
        return self._frozen

    def get(self) -> Any:
        """Return the value at this slot.

        For the root Ptr returns the document itself. For non-root Ptrs
        re-fetches through the adapter and raises ``PointerNotFoundError``
        when the slot does not exist.
        """
        if self._key is None:
            return self._parent
        return self._adapter.get(self._parent, self._key)

    def try_get(self, default: Any = ...) -> Any:
        """Return the value at this slot, or ``default`` if missing.

        With no ``default`` (or ``default=...``), behaves like ``get()`` —
        raises ``PointerNotFoundError`` on missing. The ``Ellipsis`` singleton
        serves as the "no default supplied" sentinel.
        """
        if self.exists():
            return self.get()
        if default is ...:
            raise PointerNotFoundError(str(self.pointer))
        return default

    def exists(self) -> bool:
        """True for the root Ptr, otherwise ``_adapter.has(_parent, _key)``."""
        if self._key is None:
            return True
        return self._adapter.has(self._parent, self._key)

    def set(self, value: Any) -> None:
        """Replace the value at this slot. Target must already exist.

        Raises ``RootRebindError`` on the root Ptr, ``ImmutableTargetError``
        if any ancestor binding was frozen, ``PointerNotFoundError`` if the
        slot does not exist.
        """
        self._guard_mutation()
        assert self._key is not None
        self._adapter.set(self._parent, self._key, value)

    def add(self, value: Any) -> None:
        """Insert (lists) or set (dicts/models) at this slot.

        For dicts/models this creates-or-replaces; for lists this inserts at
        the resolved index, with the ``"-"`` marker appending at the tail.
        Raises ``RootRebindError`` on the root Ptr or ``ImmutableTargetError``
        if any ancestor binding was frozen.
        """
        self._guard_mutation()
        assert self._key is not None
        self._adapter.add(self._parent, self._key, value)

    def remove(self) -> Any:
        """Remove and return the value at this slot.

        Raises ``RootRebindError`` on the root Ptr, ``ImmutableTargetError``
        if any ancestor binding was frozen, ``PointerNotFoundError`` if the
        slot does not exist.
        """
        self._guard_mutation()
        assert self._key is not None
        return self._adapter.remove(self._parent, self._key)

    def _guard_mutation(self) -> None:
        if self._key is None:
            raise RootRebindError(
                "cannot mutate the root pointer; callers must rebind the "
                "document variable themselves"
            )
        if self._frozen:
            raise ImmutableTargetError(
                f"target at {self.pointer!s} is under a frozen binding"
            )


_MAX_UNWRAP_DEPTH = 64


def _prefix_adapter_not_found(
    exc: AdapterNotFoundError, prefix: JsonPointer
) -> AdapterNotFoundError:
    """Re-wrap ``exc`` with the pointer prefix that reached the un-adaptable value.

    ``str(exc)`` is used instead of ``exc.args[0]`` so the rewrap is safe even
    if a caller raised ``AdapterNotFoundError`` with no args (degenerate case
    that the library itself never produces, but third-party code could).
    """
    return AdapterNotFoundError(f"{exc} at pointer {str(prefix)!r}")


class _RootSentinelAdapter:
    """No-op adapter for root Ptrs whose document has no registered adapter.

    A root Ptr never invokes its adapter — ``Ptr.get``/``exists`` short-circuit
    on ``_key is None`` and mutations raise ``RootRebindError`` before reaching
    the adapter. This sentinel exists only to satisfy ``Ptr._adapter``'s shape
    when ``resolve(doc, JsonPointer(""))`` is called with an un-adaptable
    ``doc`` (e.g. a scalar). Every method raises if reached.
    """

    @staticmethod
    def _unreachable() -> Any:
        raise AssertionError("internal: root sentinel adapter must not be invoked")

    def resolve_token(self, parent: Any, raw_token: str) -> int | str:
        return self._unreachable()  # type: ignore[no-any-return]

    def has(self, parent: Any, key: int | str) -> bool:
        return self._unreachable()  # type: ignore[no-any-return]

    def get(self, parent: Any, key: int | str) -> Any:
        return self._unreachable()

    def set(self, parent: Any, key: int | str, value: Any) -> None:
        self._unreachable()

    def add(self, parent: Any, key: int | str, value: Any) -> None:
        self._unreachable()

    def remove(self, parent: Any, key: int | str) -> Any:
        return self._unreachable()

    def unwrap(self, value: Any) -> Any:
        return ...

    def is_step_frozen(self, parent: Any, key: int | str) -> bool:
        return False


_ROOT_SENTINEL_ADAPTER: ContainerAdapter = _RootSentinelAdapter()


def _unwrap_to_fixed_point(value: Any, *, resolver: Any = None) -> tuple[Any, bool]:
    """Repeatedly apply the current adapter's ``unwrap`` until it returns ``...``.

    Lets transparent wrappers (e.g. ``RootModel``) be invisible to the walker.
    If no adapter is registered for ``value``'s type, the value is returned
    unchanged so the walker can raise ``AdapterNotFoundError`` at the next
    step with the original (non-unwrapped) value in context. The ``resolver``
    kwarg is threaded into ``adapter_for`` so per-call Pydantic resolvers
    apply during unwrapping too.

    Returns ``(value, frozen)``: the freeze taint accumulates across the chain
    so a frozen wrapper (e.g. a ``RootModel`` with ``ConfigDict(frozen=True)``)
    propagates immutability to its unwrapped payload — descents into the inner
    container inherit the taint and refuse writes.

    A depth cap (``_MAX_UNWRAP_DEPTH``) bounds the loop so a misbehaving
    third-party adapter that never returns ``...`` cannot wedge traversal
    into an unkillable busy-loop.
    """
    frozen = False
    for _ in range(_MAX_UNWRAP_DEPTH):
        try:
            adapter = adapter_for(value, resolver=resolver)
        except AdapterNotFoundError:
            return value, frozen
        # ``is_value_frozen`` is an opt-in hook (matches ``is_step_frozen``'s
        # role as a taint source). Adapters predating the hook — or those that
        # simply don't care about whole-value immutability — may omit it and
        # are treated as if it returned False, mirroring the built-in
        # ``DictAdapter``/``ListAdapter`` behavior.
        is_value_frozen = getattr(adapter, "is_value_frozen", None)
        if is_value_frozen is not None and is_value_frozen(value):
            frozen = True
        unwrapped = adapter.unwrap(value)
        if unwrapped is ...:
            return value, frozen
        value = unwrapped
    raise PointerError(
        f"unwrap chain exceeded {_MAX_UNWRAP_DEPTH} levels; a registered "
        "adapter's unwrap() likely never returns ... (Ellipsis)"
    )


def _iter_resolve(
    doc: Any,
    pointer: JsonPointer,
    *,
    resolver: Any = None,
) -> Iterator[Ptr]:
    """Yield Ptrs along ``pointer`` against ``doc``.

    The sequence is: the root Ptr first, then one Ptr per token. For every
    non-final token the value at ``(parent, key)`` is fetched and unwrapped
    so the next iteration descends into the child container. The final Ptr
    is yielded without fetching, so it may refer to a non-existent slot
    (JSON-Patch ``add`` semantics, including the ``"-"`` array tail).

    Private: not re-exported. Iteration shape may evolve; public callers go
    through ``resolve`` or the convenience helpers.

    The root Ptr is yielded with ``_parent=doc`` (the original document)
    so ``get()`` returns exactly what the caller passed in, as the spec
    mandates for the empty pointer. The unwrapped value is used only for
    descent into child slots.

    ``AdapterNotFoundError`` raised by ``adapter_for`` is re-thrown with the
    pointer prefix that reached the un-adaptable value, per the spec edge-case
    matrix.
    """
    descent_value, frozen = _unwrap_to_fixed_point(doc, resolver=resolver)
    tokens = pointer.tokens

    root_adapter: ContainerAdapter
    try:
        root_adapter = adapter_for(descent_value, resolver=resolver)
    except AdapterNotFoundError as exc:
        if tokens:
            raise _prefix_adapter_not_found(exc, JsonPointer("")) from exc
        root_adapter = _ROOT_SENTINEL_ADAPTER

    yield Ptr(
        pointer=JsonPointer(""),
        _parent=doc,
        _key=None,
        _adapter=root_adapter,
        _frozen=False,
    )

    value = descent_value
    last_index = len(tokens) - 1

    for i, token in enumerate(tokens):
        try:
            adapter = adapter_for(value, resolver=resolver)
        except AdapterNotFoundError as exc:
            prefix = JsonPointer.from_tokens(*tokens[:i])
            raise _prefix_adapter_not_found(exc, prefix) from exc
        key = adapter.resolve_token(value, token)
        step_frozen = frozen or adapter.is_step_frozen(value, key)

        partial_pointer = JsonPointer.from_tokens(*tokens[: i + 1])
        ptr = Ptr(
            pointer=partial_pointer,
            _parent=value,
            _key=key,
            _adapter=adapter,
            _frozen=step_frozen,
        )

        if i != last_index:
            value, unwrap_frozen = _unwrap_to_fixed_point(
                adapter.get(value, key), resolver=resolver
            )
            frozen = step_frozen or unwrap_frozen

        yield ptr


def resolve(doc: Any, pointer: JsonPointer, *, resolver: Any = None) -> Ptr:
    """Resolve ``pointer`` against ``doc`` and return a Ptr to the target slot.

    The returned Ptr may have ``exists() == False`` (for JSON-Patch ``add`` on
    a missing key, or for the array-tail ``"-"`` marker). For the empty
    pointer the root Ptr is returned. The optional ``resolver`` kwarg
    overrides the default ``BaseModelAdapter`` field-name policy for this
    call only (no registry mutation).
    """
    last: Ptr | None = None
    for ptr in _iter_resolve(doc, pointer, resolver=resolver):
        last = ptr
    if last is None:
        raise PointerError("internal: _iter_resolve yielded no Ptr")
    return last


def get_value(doc: Any, pointer: JsonPointer, *, resolver: Any = None) -> Any:
    """Return the value at ``pointer`` in ``doc``."""
    return resolve(doc, pointer, resolver=resolver).get()


def set_value(
    doc: Any, pointer: JsonPointer, value: Any, *, resolver: Any = None
) -> None:
    """Replace the value at ``pointer`` in ``doc``. Target must already exist."""
    resolve(doc, pointer, resolver=resolver).set(value)


def add_value(
    doc: Any, pointer: JsonPointer, value: Any, *, resolver: Any = None
) -> None:
    """Insert (lists) or set (dicts/models) ``value`` at ``pointer`` in ``doc``."""
    resolve(doc, pointer, resolver=resolver).add(value)


def remove_value(doc: Any, pointer: JsonPointer, *, resolver: Any = None) -> Any:
    """Remove and return the value at ``pointer`` in ``doc``."""
    return resolve(doc, pointer, resolver=resolver).remove()

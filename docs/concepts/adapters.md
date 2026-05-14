# Adapters

The walker is container-agnostic. Every step delegates to a `ContainerAdapter` — a `@runtime_checkable` `Protocol` with eight methods (plus one optional). Three adapters ship pre-registered: `dict`, `list`, and `pydantic.BaseModel`.

## The protocol

| Method | Purpose |
|---|---|
| `resolve_token(parent, raw_token) -> int \| str` | parse an RFC 6901 token into the adapter's native key type |
| `has(parent, key) -> bool` | does the slot exist? |
| `get(parent, key) -> Any` | read the slot |
| `set(parent, key, value) -> None` | replace an existing slot |
| `add(parent, key, value) -> None` | create a new slot (RFC 6902 "add" semantics) |
| `remove(parent, key) -> Any` | delete the slot and return its old value |
| `unwrap(value) -> Any` | return the inner value of a transparent wrapper, or `...` for "no unwrap" |
| `is_step_frozen(parent, key) -> bool` | is mutation of this slot disallowed? |

### The optional `is_value_frozen` hook

Adapters MAY additionally define:

```python
def is_value_frozen(self, value: Any) -> bool: ...
```

This is a second freeze-taint source consulted by the unwrap loop. The hook is deliberately outside the Protocol surface so legacy 8-method adapters keep satisfying `isinstance(adapter, ContainerAdapter)` and the `register()` type annotation. The walker probes for it via `getattr` and treats its absence as `False`.

`BaseModelAdapter` uses `is_value_frozen` to surface:

- Whole-model `ConfigDict(frozen=True)`
- `Field(frozen=True)` on a `RootModel.root` — this is the only place this configuration can be observed, because the walker unwraps straight through `.root` without yielding a token step where `is_step_frozen` could see it.

## The registry

```python
from pydantic_jsonpointer import register, adapter_for
```

`register(cls, adapter, *, override=False)` records an adapter for a type. Duplicate registrations raise `ValueError` unless `override=True`. The registry is read-mostly: populate it at import time. Tests can snapshot and restore via the autouse fixture in `tests/test_adapters.py`.

`adapter_for(value, *, resolver=None)` looks up an adapter by walking `type(value).__mro__`. When a non-None `resolver` is supplied and the registered adapter is a `BaseModelAdapter`, a per-call `BaseModelAdapter(resolver=resolver)` is returned — the registry itself is never mutated by a resolver-scoped call.

If no adapter is found, the walker raises `AdapterNotFoundError` with the pointer prefix that reached the un-adaptable value (e.g. `at pointer '/items/0/payload'`).

## Built-in adapters

### `DictAdapter`

- Tokens map directly to string keys (Python dicts can have non-string keys; `resolve_token` always returns a `str`, so an `int`-keyed dict is unreachable by RFC 6901 pointers).
- `add` and `set` are both implemented as `parent[key] = value`. Their difference at the walker level comes from how the caller invoked them.

### `ListAdapter`

- Enforces RFC 6901 array-index shape: ASCII decimal digits only (rejects non-ASCII digits like Arabic-Indic), no leading zero except the single `"0"`, plus the `"-"` tail marker (end-of-array).
- `bool` is explicitly rejected as an index — `isinstance(True, int)` would otherwise silently accept `True`/`False` as `1`/`0`.
- `add(parent, "-", v)` appends; `add(parent, k, v)` with an integer inserts; `set` replaces in place.

### `BaseModelAdapter`

See [Field resolvers](field-resolvers.md) for the full alias-handling story. The adapter:

- Uses [field resolvers](field-resolvers.md) to map tokens to attribute names.
- Sets `is_step_frozen` to `True` if `model_fields[name].frozen` is `True` or `is_value_frozen(parent)` is `True`.
- Sets `is_value_frozen` to `True` when `model_config["frozen"]` is truthy or when the value is a `RootModel` subclass whose `root` field is `Field(frozen=True)`.
- `unwrap` returns `value.root` for `RootModel` subclasses, otherwise `...`.
- `remove` requires the field's annotation to accept `None` (checks `typing.Union`, `types.UnionType` origins, plus the degenerate `type(None)` case). The captured previous value is returned; the slot is set to `None`.

## Writing a custom adapter

Adapters that don't care about freezing or wrapping can return `...` from `unwrap`, `False` from `is_step_frozen`, and simply omit `is_value_frozen`.

```python
from dataclasses import dataclass, replace
from typing import Any

from pydantic_jsonpointer import (
    ContainerAdapter, InvalidTokenError, PointerNotFoundError, register,
)


class FrozenDataclassAdapter:
    """Adapter for frozen dataclasses — fields are accessible but immutable."""

    def resolve_token(self, parent: Any, raw_token: str) -> str:
        if raw_token not in {f.name for f in parent.__dataclass_fields__.values()}:
            raise InvalidTokenError(f"unknown field {raw_token!r}")
        return raw_token

    def has(self, parent: Any, key: str) -> bool:
        return hasattr(parent, key)

    def get(self, parent: Any, key: str) -> Any:
        return getattr(parent, key)

    def set(self, parent: Any, key: str, value: Any) -> None:
        raise PointerNotFoundError("frozen")  # unreachable: is_step_frozen guards

    def add(self, parent: Any, key: str, value: Any) -> None:
        raise PointerNotFoundError("frozen")

    def remove(self, parent: Any, key: str) -> Any:
        raise PointerNotFoundError("frozen")

    def unwrap(self, value: Any) -> Any:
        return ...

    def is_step_frozen(self, parent: Any, key: str) -> bool:
        return True  # every slot is frozen


# register(MyDataclass, FrozenDataclassAdapter())
```

Because the freeze taint propagates, attempts to mutate any slot in the dataclass — or any descendant container — raise `ImmutableTargetError` *before* the adapter's `set`/`add`/`remove` is called.

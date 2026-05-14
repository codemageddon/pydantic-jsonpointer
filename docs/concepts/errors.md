# Errors

Every error raised by `pydantic-jsonpointer` derives from `PointerError`. Most of them *also* derive from a stdlib exception type so callers can catch under the expected built-in category — for example, `PointerNotFoundError` is both a `PointerError` and a `KeyError`.

## Hierarchy

| Class | Inherits from | Raised when |
|---|---|---|
| `PointerError` | `Exception` | Base for all errors in this package. |
| `PointerNotFoundError` | `PointerError`, `KeyError` | A token doesn't resolve to an existing slot, or `set` is called on a slot that doesn't exist. |
| `AdapterNotFoundError` | `PointerError`, `TypeError` | `adapter_for` could not find a registered adapter for a value's type. The error message includes the pointer prefix that reached the un-adaptable value. |
| `InvalidTokenError` | `PointerError`, `ValueError` | A token's shape is wrong (e.g., non-numeric for a list, malformed escape sequence), or no field matches the token under the active resolver. |
| `RootRebindError` | `PointerError` | A mutation (`set`/`add`/`remove`) was attempted on the root `Ptr` — rebind your own variable instead. |
| `ImmutableTargetError` | `PointerError` | Mutation was blocked by transitive frozen taint accumulated during traversal. |

## Catching by stdlib type

The multiple inheritance lets you catch with whichever class fits the calling code's mental model:

```python
from pydantic_jsonpointer import (
    get_value, JsonPointer,
    PointerError, PointerNotFoundError, InvalidTokenError,
)

doc = {"items": []}

try:
    get_value(doc, JsonPointer("/items/abc"))
except KeyError:
    ...        # catches PointerNotFoundError (and any other KeyError)

try:
    get_value(doc, JsonPointer("/items/abc"))
except ValueError:
    ...        # catches InvalidTokenError ("abc" is not a valid list index)

try:
    get_value(doc, JsonPointer("/items/abc"))
except PointerError:
    ...        # catches every error this package raises
```

## When each error fires

### `InvalidTokenError`

- Constructing a malformed pointer: `JsonPointer("items/0")` (missing leading `/`), `JsonPointer("/~2")` (invalid escape).
- Traversal-time: `ListAdapter` rejects a non-numeric token; `BaseModelAdapter` finds no field matching the token under the active resolver.

### `PointerNotFoundError`

- Reading: `get()` on a missing dict key, out-of-range list index, or `None`-valued model attribute.
- Writing: `set()` on a slot that does not yet exist (use `add()` instead).
- Removing: `remove()` on a slot that does not exist.

### `AdapterNotFoundError`

- Traversal reached a value whose type (or any base in its MRO) has no registered adapter. The pointer prefix is included in the message:

    ```
    no adapter registered for <class 'X'> at pointer '/items/0/payload'
    ```

### `RootRebindError`

- `set_value(doc, JsonPointer(""), …)`, `add_value(doc, JsonPointer(""), …)`, `remove_value(doc, JsonPointer(""))`.
- The root is identity-preserving by design — to "replace" the document, bind your own variable to a new value.

### `ImmutableTargetError`

- Any mutation through a `Ptr` whose `is_frozen` is `True`. The taint may have been introduced several steps earlier (e.g., descending into a `ConfigDict(frozen=True)` model, then traversing further still raises on mutation).

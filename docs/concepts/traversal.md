# Traversal

The traversal API walks a document one token at a time, dispatching to a `ContainerAdapter` at every step. The output is a `Ptr` — an immutable handle that remembers where it came from and supports four operations: read, set, add, remove.

## The `Ptr` handle

`Ptr` is a `@dataclass(frozen=True, slots=True)` with five fields:

| Field | Meaning |
|---|---|
| `pointer` | the `JsonPointer` that produced this handle |
| `_parent` | the container the last step descended into |
| `_key` | the resolved key on `_parent` (int for lists, str for dicts/models) |
| `_adapter` | the adapter selected for `_parent` |
| `_frozen` | transitive freeze taint — see below |

Public properties: `parent`, `key`, `is_root`, `is_frozen`. The constructor is private — `Ptr` instances are always produced by `_iter_resolve` (the single allocation point).

## `resolve` and the helpers

```python
from pydantic_jsonpointer import resolve, get_value, set_value, add_value, remove_value
```

| Function | Equivalent to |
|---|---|
| `resolve(doc, p)` | returns the terminal `Ptr` |
| `get_value(doc, p)` | `resolve(doc, p).get()` |
| `set_value(doc, p, v)` | `resolve(doc, p).set(v)` |
| `add_value(doc, p, v)` | `resolve(doc, p).add(v)` |
| `remove_value(doc, p)` | `resolve(doc, p).remove()` |

All five accept a `resolver=` keyword for Pydantic [field resolvers](field-resolvers.md).

## Reads

```python
ptr.get()                  # raises PointerNotFoundError if missing
ptr.try_get(default=...)   # returns default if missing; default=... means "no default" → raises
ptr.exists()               # bool
```

`try_get` uses the `Ellipsis` (`...`) singleton as the "no default supplied" sentinel — the same singleton `ContainerAdapter.unwrap` uses for "no unwrap". Identity checks (`x is ...`) work because `...` is a language-level singleton; you can pass `None` as a real default without ambiguity.

## Mutations

```python
ptr.set(value)     # replace an existing slot (RFC 6902 "replace")
ptr.add(value)     # create a new slot (RFC 6902 "add")
ptr.remove()       # delete a slot; returns the removed value
```

Every mutation calls `_guard_mutation()` first:

- **Root** → [`RootRebindError`](errors.md). `set`/`add`/`remove` on the document itself never makes sense — rebind your own variable instead.
- **Frozen** → [`ImmutableTargetError`](errors.md). The walker has accumulated a freeze taint at some ancestor.

Only after the guard passes does the adapter call happen — so a frozen subtree never sees a partial mutation.

## Frozen taint propagation

Once the walker observes a freeze marker at *any* step, every descendant `Ptr` is tainted. There are two cooperating taint sources:

1. **`ContainerAdapter.is_step_frozen(parent, key)`** — consulted at each token descent. The built-in `BaseModelAdapter` returns `True` for `model_fields[key].frozen`.
2. **`ContainerAdapter.is_value_frozen(value)`** (optional) — consulted by the unwrap loop on every container in the wrap chain. `BaseModelAdapter` uses this to surface whole-model `ConfigDict(frozen=True)` and `Field(frozen=True)`-on-`RootModel.root`.

Both signals OR into the same `_frozen` bit. Custom adapters can opt into either taint source by implementing the corresponding method.

## Auto-unwrap

Transparent wrappers (notably `RootModel`) are invisible to the walker. `_unwrap_to_fixed_point` loops `adapter.unwrap` until it returns the `Ellipsis` sentinel and accumulates the freeze bit across the chain. A depth cap (`_MAX_UNWRAP_DEPTH = 64`) guards against misbehaving adapters that fail to converge — a runaway chain raises `PointerError`.

## Root pointer

`resolve(doc, JsonPointer(""))` returns a root `Ptr` with `is_root = True` and `_parent = doc` (the caller's identity is preserved — the walker never substitutes the unwrapped payload). Reads on the root return `doc` itself; mutations raise `RootRebindError`.

If `doc` has no registered adapter and the pointer is empty, an internal sentinel adapter is substituted so the root `Ptr` can still be yielded — it is never actually invoked, because root reads and mutations short-circuit before reaching it.

# Model-based pointers

`pointer_from_model()` builds [JSONPointer](json-pointer.md) strings from Pydantic model attribute chains. Instead of hand-writing `/items/0/name`, you write `pointer_from_model(Order).items[0].name` and get the same pointer with automatic alias resolution.

## Basic usage

```python
from pydantic_jsonpointer import pointer_from_model

class Address(BaseModel):
    city: str

class User(BaseModel):
    name: str
    address: Address

pointer_from_model(User).name.build()         # → JsonPointer("/name")
pointer_from_model(User).address.city.build() # → JsonPointer("/address/city")
```

Each `.attr` access returns a `_ModelPath` proxy — call `.build()` (or its `()` alias) to finalize the chain into a `JsonPointer`. The `/` operator also finalizes immediately and returns a `JsonPointer` directly.

`pointer_from_model` accepts either a model **class** or an **instance**. Both produce identical pointer strings:

```python
user = User(name="alice", address=Address(city="NYC"))
pointer_from_model(User).name.build()   # → JsonPointer("/name")
pointer_from_model(user).name.build()   # → JsonPointer("/name") — same
```

## List fields and indexing

Chain `[index]` to descend into list fields:

```python
class Order(BaseModel):
    items: list[Address]

pointer_from_model(Order).items[0].city.build()   # → JsonPointer("/items/0/city")
```

The `[index]` step advances the model context to the list's item type, so further `.attr` chaining resolves against the inner model.

## RootModel entry

`pointer_from_model` can start directly from a `RootModel` subclass:

```python
class TagList(RootModel[list[Tag]]):
    pass

pointer_from_model(TagList)[0].label      # → "/0/label"
```

The initial `RootModel` wrapper is transparent — `[0]` resolves against the inner list without a preceding `.attr`.

## Union disambiguation

Fields typed as a `Union` of models are ambiguous by annotation alone. Narrow with `isinstance` and re-enter via `pointer_from_model` on the narrowed value:

```python
class JsonBody(BaseModel):
    body: str

class XmlBody(BaseModel):
    root: str

class Event(BaseModel):
    payload: JsonBody | XmlBody

# Cannot chain past .payload — the annotation is ambiguous:
pointer_from_model(Event).payload.build()          # → JsonPointer("/payload")
pointer_from_model(Event).payload.body             # AttributeError!

# Narrow first, then re-enter with the narrowed value:
event = Event(payload=JsonBody(body="hello"))
if isinstance(event.payload, JsonBody):
    ptr = pointer_from_model(event.payload).body  # → JsonPointer("/body")
```

The mypy plugin emits a type error (`field 'payload' is an ambiguous BaseModel Union; narrow via isinstance() …`) when you chain past such a field, pointing you at the narrowing pattern.

## Alias resolution

By default, `pointer_from_model` uses `BySerializationAlias` — field names are converted to their serialization alias (with a fallback to the attribute name):

```python
class Item(BaseModel):
    item_name: str = Field(serialization_alias="itemName")

pointer_from_model(Item).item_name.build()         # → JsonPointer("/itemName")
```

Pass a different resolver to change the policy:

```python
from pydantic_jsonpointer import ByAttribute

pointer_from_model(Item, resolver=ByAttribute()).item_name.build()  # → JsonPointer("/item_name")
```

The resolver is threaded through the entire chain — nested model attributes use the same policy.

## Appending raw tokens

Use `/` after a chain to append tokens without model awareness:

```python
pointer_from_model(Order).items / "3" / "name"  # → "/items/3/name"
```

`/` returns a `JsonPointer` immediately, ending the `_ModelPath` chain.

## How it works

Under the hood, `pointer_from_model` returns a private `_ModelPath` proxy. Each `.attr`:

1. Looks up the field on the current model class.
2. Resolves the attribute name to a token via the resolver.
3. Walks the field's type annotation to determine whether the model class advances (for nested models) or stays put (for leaf fields).

`[index]` appends a raw token and advances to the container's item type. The proxy is a frozen dataclass — each step produces a new instance.

## Type-checker integration

A mypy plugin ships with the library that validates field access at *every* depth in the chain:

```toml
# pyproject.toml
[tool.mypy]
plugins = "pydantic_jsonpointer.mypy_plugin"
```

With the plugin active:

```python
pointer_from_model(User).name                # OK
pointer_from_model(User).typo                # mypy error: 'User' has no field 'typo'
pointer_from_model(Order).items[0].typo      # implicit [idx] — validated
pointer_from_model(Order).items.__getitem__(0).typo
                                             # mypy error: 'Item' has no field 'typo'
pointer_from_model(Profile).address.city.typo
                                             # mypy error: 'City' has no field 'typo'
```

Implicit `[idx]` subscript syntax is validated via `get_method_signature_hook`. Both implicit and explicit (`.items.__getitem__(0)`) forms work.

The plugin is mypy-only. Pyright and other type checkers see `_ModelPath[Any, Any]` after the first attribute access.

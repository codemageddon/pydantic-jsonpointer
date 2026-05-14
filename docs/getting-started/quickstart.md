# Quickstart

This guide walks through the four operations every JSONPointer user needs: read, set, add, remove — across plain `dict`/`list` data and Pydantic models.

## Construct a pointer

`JsonPointer` is a `str` subclass. Construct it from a raw RFC 6901 string, from a sequence of unescaped tokens, or by chaining with `/`:

```python
from pydantic_jsonpointer import JsonPointer

JsonPointer("/items/0/name")
JsonPointer.from_tokens(["items", "0", "name"])
JsonPointer("/items") / "0" / "name"
```

All three produce the same value. Validation runs in `__new__`, so any of these paths will reject malformed input (RFC 6901 requires a leading `/`, and `~` must be followed by `0` or `1`):

```python
JsonPointer("items/0")  # raises InvalidTokenError — missing leading "/"
JsonPointer("/~2")      # raises InvalidTokenError — "~" must be followed by 0 or 1
```

## Read a value

```python
from pydantic_jsonpointer import JsonPointer, get_value

doc = {"items": [{"name": "apple"}, {"name": "banana"}]}
get_value(doc, JsonPointer("/items/1/name"))
# "banana"
```

For a missing key or out-of-range index, use `Ptr.try_get` with a default:

```python
from pydantic_jsonpointer import resolve

ptr = resolve(doc, JsonPointer("/items"))
ptr.try_get(default=None)  # returns the list
```

## Set / add / remove

```python
from pydantic_jsonpointer import (
    JsonPointer, set_value, add_value, remove_value,
)

doc = {"items": [1, 2, 3]}
set_value(doc, JsonPointer("/items/0"), 99)
# doc -> {"items": [99, 2, 3]}

add_value(doc, JsonPointer("/items/-"), 4)
# doc -> {"items": [99, 2, 3, 4]} — "-" appends to the list

add_value(doc, JsonPointer("/items/0"), 0)
# doc -> {"items": [0, 99, 2, 3, 4]} — index inserts

remove_value(doc, JsonPointer("/items/0"))
# doc -> {"items": [99, 2, 3, 4]}
```

The semantic difference between `set` and `add` matches [RFC 6902](https://www.rfc-editor.org/rfc/rfc6902) (JSON Patch):

- `set` requires the slot to already exist.
- `add` creates a new slot (a new dict key, a new list index, a new field on an alias-aware model).

## Pydantic models

The traversal API treats `BaseModel` like any other container. By default, tokens map to **serialization aliases** (falling back to attribute names):

```python
from pydantic import BaseModel, Field
from pydantic_jsonpointer import JsonPointer, get_value, set_value


class Item(BaseModel):
    name: str = Field(serialization_alias="itemName")
    qty: int


item = Item(name="apple", qty=3)
get_value(item, JsonPointer("/itemName"))   # "apple"
set_value(item, JsonPointer("/qty"), 10)
```

Need a different alias policy? See [Field resolvers](../concepts/field-resolvers.md).

## RootModel auto-unwrap

`RootModel[list[…]]` and `RootModel[dict[…]]` are transparent to the walker — pointers descend straight through `.root` without an explicit token:

```python
from pydantic import RootModel
from pydantic_jsonpointer import JsonPointer, get_value, add_value


class IntList(RootModel[list[int]]):
    pass


nums = IntList(root=[10, 20, 30])
get_value(nums, JsonPointer("/1"))          # 20
add_value(nums, JsonPointer("/-"), 40)      # nums.root -> [10, 20, 30, 40]
```

## What's next

- [JsonPointer type](../concepts/json-pointer.md) — escape rules, Pydantic integration, the `_tokens` invariant
- [Traversal](../concepts/traversal.md) — the `Ptr` handle, frozen taint, mutation guards
- [Adapters](../concepts/adapters.md) — write an adapter for your own container type
- [Field resolvers](../concepts/field-resolvers.md) — pick the right alias policy for Pydantic models

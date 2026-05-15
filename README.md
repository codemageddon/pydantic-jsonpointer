<p align="center">
  <img src="docs/assets/logo.png" alt="pydantic-jsonpointer logo" width="180">
</p>

# `pydantic-jsonpointer`

**JSONPointer ([RFC 6901](https://www.rfc-editor.org/rfc/rfc6901)) implementation for Pydantic 2.x.** A typed `JsonPointer` string for use in Pydantic models, plus a traversal API that walks `dict` / `list` / `tuple` / `pydantic.BaseModel` graphs through a pluggable adapter protocol. Supports read, set, add, and remove operations with alias-aware traversal and transitive freeze propagation.

## Installation

```bash
pip install pydantic-jsonpointer
# or: uv add pydantic-jsonpointer / poetry add pydantic-jsonpointer / pdm add pydantic-jsonpointer
```

## Quick example

```python
from pydantic import BaseModel, Field
from pydantic_jsonpointer import JsonPointer, resolve

class Item(BaseModel):
    name: str = Field(serialization_alias="itemName")
    qty: int

class Order(BaseModel):
    items: list[Item]

order = Order(items=[Item(name="apple", qty=3)])
ptr = resolve(order, JsonPointer("/items/0/itemName"))
print(ptr.get())           # "apple"
ptr.set("banana")
print(order.items[0].name) # "banana"
```

### With plain dicts/lists (no pydantic needed)

```python
from pydantic_jsonpointer import JsonPointer as P, get_value, set_value

doc = {"items": [{"name": "a"}, {"name": "b"}]}
get_value(doc, P("/items/1/name"))      # "b"
set_value(doc, P("/items/0/name"), "x")
```

### Building pointers from models (reverse)

```python
from pydantic import BaseModel
from pydantic_jsonpointer import pointer_from_model

class Address(BaseModel):
    city: str

class User(BaseModel):
    name: str
    address: Address

ptr = pointer_from_model(User).address.city.build()  # → JsonPointer("/address/city")
```

Also supports `RootModel`, list indexing, Union narrowing, and swappable alias resolvers.

### Mypy plugin (opt-in)

An opt-in mypy plugin validates `pointer_from_model` attribute chains at every depth, catching unknown field names and invalid array indices at type-check time:

```toml
# pyproject.toml
[tool.mypy]
plugins = "pydantic_jsonpointer.mypy_plugin"
```

With the plugin enabled, `pointer_from_model(User).typo` is a type error; invalid array indices like `-1` or `True` are caught statically; ambiguous `Union[ModelA, ModelB]` chains produce a hard error pointing to `isinstance` narrowing.

## Documentation

Full documentation at [pydantic-jsonpointer.codemageddon.me](https://pydantic-jsonpointer.codemageddon.me/) — covers traversal, adapters, model-based pointers, and all public APIs.

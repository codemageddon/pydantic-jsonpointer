# Field resolvers

When traversing `pydantic.BaseModel` instances, the walker has to map an RFC 6901 token (a string) onto a model attribute. Pydantic supports multiple naming sources — attribute names, `alias`, `serialization_alias`, `validation_alias` (with `AliasChoices` and `AliasPath`) — so the right mapping depends on whether the pointer comes from your wire format or your code.

The `FieldResolver` protocol abstracts this choice. Three implementations ship; choose by passing one via the `resolver=` kwarg on `resolve()` / `get_value()` / `set_value()` / etc., or by constructing `BaseModelAdapter(resolver=...)` directly.

## The protocol

```python
from typing import Protocol, runtime_checkable
from pydantic import BaseModel


@runtime_checkable
class FieldResolver(Protocol):
    def to_attr(self, model_cls: type[BaseModel], token: str) -> str | None: ...
    def to_token(self, model_cls: type[BaseModel], attr: str) -> str: ...
```

`to_attr` maps an inbound token → an attribute name (`None` means "no matching field — raise `InvalidTokenError`"). `to_token` is the inverse: given an attribute name, return the token that resolves back to it. Both directions are needed because some operations (e.g., building a pointer to a specific field) need the reverse mapping.

## Shipped resolvers

### `ByAttribute`

Strictest. Only attribute names match — every alias is ignored.

| Field declaration | Recognized token |
|---|---|
| `name: str` | `"name"` |
| `name: str = Field(alias="n")` | `"name"` (alias ignored) |
| `name: str = Field(serialization_alias="N")` | `"name"` (alias ignored) |

Use when your pointers are written by Python code against the model class and you want the schema to be wire-format-independent.

### `BySerializationAlias` (default)

Priority: `serialization_alias` → `alias` → attribute name.

| Field declaration | Recognized token |
|---|---|
| `name: str` | `"name"` |
| `name: str = Field(alias="n")` | `"n"` |
| `name: str = Field(alias="n", serialization_alias="N")` | `"N"` |

This is the default because pointers most commonly travel inside JSON Patch payloads — the same payloads your model serializes to. Aligning with the serialization shape means a roundtrip "serialize → patch → deserialize" pipeline works without translation.

### `ByValidationAlias`

Priority: `validation_alias` strings → `alias` → attribute name. Handles the full Pydantic validation-alias surface:

- A plain string alias — recognized directly.
- `AliasChoices(...)` — every string in the choices set is a recognized token.
- `AliasPath(...)` — flattened to the leading path component when it is a string.

Use when your pointers come from the same source as your *input* JSON (e.g., webhook payloads that you map onto an internal schema).

## Picking a resolver per call

```python
from pydantic_jsonpointer import JsonPointer, ByAttribute, get_value

get_value(model, JsonPointer("/qty"), resolver=ByAttribute())
```

A per-call `BaseModelAdapter` is constructed by `adapter_for` when `resolver` is non-None; the registry itself is not mutated.

## Constructing the adapter directly

```python
from pydantic_jsonpointer import BaseModelAdapter, ByValidationAlias, register
from pydantic import BaseModel

register(BaseModel, BaseModelAdapter(resolver=ByValidationAlias()), override=True)
```

Setting the resolver on the registered adapter changes the *default* for every traversal that doesn't pass an explicit `resolver=`. Use this when your whole project consistently uses validation aliases.

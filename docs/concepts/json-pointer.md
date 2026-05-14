# JsonPointer type

`JsonPointer` is a `str` subclass that carries an RFC 6901 pointer alongside its parsed token tuple. Because it *is* a string, it transparently serializes, compares, and interoperates with any API that expects `str` — no conversion needed.

## Construction

```python
from pydantic_jsonpointer import JsonPointer

JsonPointer("/items/0/name")
JsonPointer("")                       # the root pointer
JsonPointer.from_tokens(["a/b", "c"]) # JsonPointer("/a~1b/c")
JsonPointer("/items") / "0" / "name"  # chained
```

All construction paths run the same RFC 6901 validation in `__new__`:

- The string must be empty or start with `/`.
- `~` must always be followed by `0` (decodes to `~`) or `1` (decodes to `/`).

Anything else raises [`InvalidTokenError`](errors.md).

## Escape rules

JSONPointer reserves two characters in tokens: `~` and `/`. They are encoded as `~0` and `~1` respectively. `JsonPointer` centralizes escaping in `_escape_token` / `_unescape_token`:

| Token contains | Encoded as |
|---|---|
| `~` | `~0` |
| `/` | `~1` |
| `~/` (in that order) | `~0~1` |

`from_tokens` and `/`-chaining apply escaping; the `tokens` property returns unescaped tokens:

```python
p = JsonPointer.from_tokens(["a/b", "c~d"])
str(p)      # "/a~1b/c~0d"
p.tokens    # ("a/b", "c~d")
```

## Invariants

- For every instance, re-escaping `_tokens` and joining with `/` reproduces the stored string. The class enforces this by routing every allocation through one private classmethod (`__with_tokens`).
- The empty pointer `""` corresponds to "the document itself" — its token tuple is empty.

## Pydantic integration

`JsonPointer` provides `__get_pydantic_core_schema__` so it works as a Pydantic field type:

```python
from pydantic import BaseModel
from pydantic_jsonpointer import JsonPointer


class JsonPatchOperation(BaseModel):
    op: str
    path: JsonPointer
    value: object | None = None


op = JsonPatchOperation.model_validate(
    {"op": "replace", "path": "/items/0/name", "value": "x"}
)
op.path             # JsonPointer("/items/0/name")
op.model_dump()     # {"op": "replace", "path": "/items/0/name", "value": "x"}
```

The integration wraps Pydantic's `str_schema()` with a `no_info_wrap_validator_function` so:

1. Pydantic first validates the value as a string.
2. The wrapper constructs `JsonPointer`, which re-runs RFC 6901 validation.

Invalid pointers fail validation with Pydantic's standard `ValidationError` payload. Serialization uses `to_string_ser_schema()`, so models round-trip as plain JSON strings. The exported JSON Schema is the unadorned string schema.

## Equality and identity

Because `JsonPointer` is a `str` subclass, `JsonPointer("/a") == "/a"` is `True` — no special equality method. Hashing matches the underlying string, so pointers are usable as dict keys and set members alongside plain strings.

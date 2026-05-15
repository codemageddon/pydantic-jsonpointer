# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

`pydantic-jsonpointer` is a JSONPointer (RFC 6901) implementation for Pydantic 2.x. The package exposes `JsonPointer` (a typed string for Pydantic field use) plus a traversal API — `Ptr`, `resolve`, `get_value`/`set_value`/`add_value`/`remove_value` — with a pluggable `ContainerAdapter` protocol, built-in adapters for `dict`/`list`/`pydantic.BaseModel`, and three `FieldResolver` policies for alias-aware Pydantic traversal.

## Toolchain

Dev tooling is pinned through `mise.toml` (Python 3.10–3.14, `uv` latest, `pre-commit` 4). `UV_NO_MANAGED_PYTHON=true` is set so `uv` always uses the mise-provided interpreter rather than downloading its own. Always invoke tools through `uv run` to ensure the locked environment from `uv.lock` is used.

- Sync deps: `uv sync`
- Type check (strict mypy, configured in `pyproject.toml`): `uv run mypy src tests`
- Run tests: `uv run pytest` (tests live under `tests/`: `test_types.py`, `test_errors.py`, `test_adapters.py`, `test_pydantic_adapter.py`, `test_traversal.py`, `test_model_path.py`, `test_mypy_plugin.py`)
- Run a single test: `uv run pytest tests/test_traversal.py::test_name`
- Build distribution (hatchling): `uv build`

Version lives in `src/pydantic_jsonpointer/__version__.py` and is read dynamically by hatch — bump it there, not in `pyproject.toml`.

## Architecture

### `JsonPointer` (`src/pydantic_jsonpointer/types.py`)

- `JsonPointer` subclasses `str`. This means it transparently serializes and compares as the underlying RFC 6901 string, and existing string-typed APIs accept it without conversion.
- `JsonPointer` uses `__slots__ = ("_tokens",)` to store a `tuple[str, ...]` of unescaped reference tokens alongside the string value. The private `__with_tokens(cls, value, tokens)` classmethod (name-mangled) is the sole instance-allocation point; all construction paths (`__new__`, `from_tokens`, `__truediv__`) call it. New construction APIs must do the same — never call `str.__new__` directly.
- The invariant: for every instance, re-escaping `_tokens` and joining with `/` must reproduce the stored string.
- Validation happens in `__new__`, so any construction path (direct, `from_tokens`, `/`-chaining, Pydantic validation) goes through the same RFC 6901 rules: must be empty or start with `/`, and `~` must always be followed by `0` or `1`.
- Pydantic integration uses `__get_pydantic_core_schema__` with `no_info_wrap_validator_function` wrapping `str_schema()`. The wrapper first asks Pydantic to validate as a string, then constructs `JsonPointer` (which re-validates RFC 6901 rules). Serialization is `to_string_ser_schema()`, so models round-trip as plain JSON strings. JSON Schema output is the plain string schema via `__get_pydantic_json_schema__`.
- Token escaping/unescaping (`~` ↔ `~0`, `/` ↔ `~1`) is centralized in `_escape_token` / `_unescape_token`. `from_tokens` and `__truediv__` both escape; the `tokens` property unescapes. Any new pointer-manipulation API must go through these helpers — never hand-roll the escaping.

### `errors.py`

Six-class hierarchy with intentional multiple inheritance so callers can catch under stdlib exception types:

- `PointerError(Exception)` — base for all errors.
- `PointerNotFoundError(PointerError, KeyError)` — missing intermediate / replace-without-target.
- `AdapterNotFoundError(PointerError, TypeError)` — no adapter for a value's type.
- `InvalidTokenError(PointerError, ValueError)` — token shape wrong / no field matches.
- `RootRebindError(PointerError)` — mutation attempted on root Ptr.
- `ImmutableTargetError(PointerError)` — write blocked by transitive frozen taint.

### `adapters.py`

- `@runtime_checkable Protocol ContainerAdapter` with eight required methods: `resolve_token`, `has`, `get`, `set`, `add`, `remove`, `unwrap`, `is_step_frozen`. Adapters MAY additionally define `is_value_frozen(value) -> bool` (a second freeze-taint source, see `traversal.py`); the hook is deliberately outside the Protocol surface so legacy 8-method adapters keep satisfying `isinstance(adapter, ContainerAdapter)` and static type-checks against `register()`. The walker probes for it via `getattr` and treats its absence as `False`.
- Module-level `_REGISTRY: dict[type, ContainerAdapter]`. Treat as read-mostly: populate at import time via `register()`. Tests snapshot/restore via an autouse fixture in `test_adapters.py`.
- `register(cls, adapter, *, override=False)` — raises `ValueError` on duplicate unless `override=True`.
- `adapter_for(value, *, resolver=None)` walks `type(value).__mro__`. When a non-None `resolver` is supplied and the registered adapter is a `BaseModelAdapter`, returns a per-call `BaseModelAdapter(resolver=resolver)` (no registry mutation).
- Built-in `DictAdapter`, `ListAdapter`, and `TupleAdapter` self-register at module load. `ListAdapter.resolve_token` enforces RFC 6901 array index shape: ASCII decimal digits only (rejects non-ASCII digits like Arabic-Indic via `_is_ascii_digits`), no leading zero except single `"0"`, plus the `"-"` tail marker. Index helpers reject `bool` keys via `_is_int_index` (since `isinstance(True, int)` would otherwise silently accept `True`/`False` as `1`/`0`). `TupleAdapter` is read-only: `set`, `add`, and `remove` always raise `ImmutableTargetError`; `is_step_frozen` returns `False` so mutable objects inside tuple slots remain writable via their own adapters. Tuples do not support the `"-"` tail marker (rejected by `resolve_token`).

### `pydantic_adapter.py`

- `@runtime_checkable Protocol FieldResolver` with `to_attr(model_cls, token) -> str | None` and `to_token(model_cls, attr) -> str`.
- Three shipped resolvers:
  - `ByAttribute` — strictest; only attribute names.
  - `BySerializationAlias` — default; priority `serialization_alias` → `alias` → attribute name.
  - `ByValidationAlias` — priority `validation_alias` strings (handles `AliasChoices` and `AliasPath`) → `alias` → attribute name.
- `BaseModelAdapter(resolver=None)` defaults to `BySerializationAlias()`. `is_step_frozen` is True if `is_value_frozen(parent)` is True or `model_fields[name].frozen` is True; the walker propagates this taint to every descendant slot. `is_value_frozen(value)` is True when `model_config["frozen"]` is truthy or when `value` is a `RootModel` subclass whose `root` field is `Field(frozen=True)` — the latter is the only place a frozen binding on `RootModel.root` can be surfaced, because the walker unwraps straight through `.root` without ever yielding a token step where `is_step_frozen` could observe it. `remove` requires `_annotation_accepts_none(model_cls, attr)` (checks `typing.Union` and `types.UnionType` origins plus the degenerate `type(None)` case); it captures the previous value, sets `None`, returns the capture. `unwrap` returns `value.root` for `RootModel` subclasses, otherwise `...`.

### `traversal.py`

- `@dataclass(frozen=True, slots=True) Ptr` with slots `pointer`, `_parent`, `_key`, `_adapter`, `_frozen`. Public properties: `parent`, `key`, `is_root`, `is_frozen`.
- Reads: `get()`, `try_get(default=...)`, `exists()`. `try_get` uses the `Ellipsis` singleton (`...`) as the "no default supplied" sentinel — same singleton `ContainerAdapter.unwrap` uses to mean "no unwrap". Identity checks (`x is ...`) work because `...` is a language-level singleton.
- Mutations: `set(value)`, `add(value)`, `remove()`. Each calls `_guard_mutation()` first: root → `RootRebindError`, frozen → `ImmutableTargetError`. Only after the guard passes does the adapter call happen.
- `_iter_resolve(doc, pointer, *, resolver=None)` is the **single** `Ptr`-allocation point (mirrors `JsonPointer.__with_tokens` discipline). It yields the root `Ptr` first (always with `_frozen=False`, since root writes are guarded by `RootRebindError` not the freeze bit, and `_parent=doc` preserves caller identity per the spec), then one per token; `step_frozen = frozen or adapter.is_step_frozen(value, key)` propagates the taint across iterations. `AdapterNotFoundError` raised by `adapter_for` is re-raised with the pointer prefix that reached the un-adaptable value (e.g. `at pointer '/items/0/payload'`), per the spec edge-case matrix. When the document has no registered adapter AND the pointer is empty, an internal `_RootSentinelAdapter` is substituted so the root `Ptr` can be yielded (the sentinel is never invoked because root reads/mutations short-circuit before reaching it).
- `_unwrap_to_fixed_point(value, *, resolver=None)` loops `adapter.unwrap` until `...` and returns `(value, frozen)`: it probes each adapter for an OPTIONAL `is_value_frozen(value)` via `getattr` (so legacy 8-method adapters are tolerated) and accumulates the freeze bit across the chain so a frozen wrapper (e.g. a frozen `RootModel`) propagates immutability to its unwrapped payload. The walker `or`s this taint into `step_frozen` at every descent. A depth cap (`_MAX_UNWRAP_DEPTH = 64`) prevents a misbehaving adapter from wedging traversal into an infinite loop; a chain that fails to converge raises `PointerError`.
- `resolve(doc, pointer, *, resolver=None) -> Ptr` consumes `_iter_resolve` and returns the last yield. The four convenience helpers (`get_value`, `set_value`, `add_value`, `remove_value`) all accept the `resolver` kwarg and delegate to `resolve(...).<op>`.

When adding new operations (e.g., a parent pointer back-walker, JSON Patch dispatcher, equality with normalization), keep them as methods on `JsonPointer` / `Ptr` so the `str` identity and Pydantic schema remain the single source of truth.

### `_model_path.py`

- `pointer_from_model(model, *, resolver=None)` is the single public entry point. Accepts a `BaseModel` class or instance; instance entry uses `type(model)` only — no runtime instance peeking. When given a `RootModel`, peels the wrapper via `_advance_attr` and sets `_pending_annotation` to the inner type so `[index]` resolves against the item model immediately.
- For ambiguous Union fields, the runtime raises `AttributeError` when chained past; users must narrow with `isinstance` and re-enter `pointer_from_model` on the narrowed value.
- `_ModelPath` is `@dataclass(frozen=True, slots=True)` and `Generic[_T, _P]`. **Never construct it directly** — always go through `pointer_from_model()`. Tests may construct it directly for unit isolation (they are tightly coupled to the dataclass shape).
- `_T` tracks the current model class for `__getattr__` field resolution; `_P` carries the pending annotation for the next `__getitem__` step. `_model_ctx_lost` is set to `True` when a field annotation is a leaf type, an ambiguous Union, or a non-list container — further `.attr` access raises `AttributeError`.
- `__getattribute__` override: field names that shadow `_ModelPath` class methods (e.g. a field named `build`) are routed to `__getattr__` rather than the method. `build()` is always callable via `_ModelPath.build(self)` or the `__call__` alias.
- `__call__()` is an alias for `build()`. Use it when the chain has navigated to a field named `build` — `mp.build` yields the field `_ModelPath`, `mp.build()` invokes `__call__` on that result to finalize.
- `_advance(annotation, *, for_index, index=None)` is the annotation walker. Peels `Annotated`, `Optional`/`Union` (single non-None branch only), `RootModel` wrappers (via `model_fields["root"].annotation`), and `list` or `tuple` (when `for_index=True`). Fixed-length `tuple[A, B, C]` uses the `index` parameter to select the correct element type; homogeneous `tuple[T, ...]` without an `index` (i.e., the `"-"` sentinel case) returns `None` since `TupleAdapter` rejects that token. Depth-capped at `_MAX_ADVANCE_DEPTH = 64`; raises `PointerError` on overflow.
- `_advance_attr` / `_advance_index` are one-liner wrappers over `_advance` for call-site clarity — don't inline away.
- `_peel_item_annotation(annotation, *, index=None)` is a parallel walker that extracts the raw item annotation from a container without requiring the item to be a `BaseModel`. Used by `__getitem__` to carry `_pending_annotation` forward across chained index steps (e.g. `grid[0][0]` on `list[list[Item]]` needs `list[Item]` as pending context after the first `[0]`). Returns `None` when the annotation is not a recognizable container.

### `mypy_plugin.py`

- Ships `ModelPathPlugin(Plugin)` with two hooks registered via `get_attribute_hook` and `get_method_signature_hook`.
- `get_attribute_hook` fires for every `_ModelPath.<attr>` access. Validates the attribute name against the current model, emits `api.fail(...)` for unknown fields, and constructs a parametrized `_ModelPath[next_T, field_type]` return type via direct `Instance(typeinfo, args)` construction so further chaining types correctly. Chained `.attr` access is fully validated at every depth.
- `get_method_signature_hook` fires for `_ModelPath.__getitem__` calls (both explicit `.__getitem__(0)` and implicit `[0]` syntax). Validates that the pending type is list-like and returns a signature whose `ret_type` carries the advanced item model.
- Instance-based Union narrowing through the chain is no longer a runtime feature, so the plugin emits a hard type error (`api.fail`) on ambiguous BaseModel Unions pointing users to `isinstance` narrowing.
- The plugin is **opt-in** and not listed in this project's own `pyproject.toml`. Users enable it: `plugins = "pydantic_jsonpointer.mypy_plugin"` in their `mypy` config.

## Conventions and invariants

- `Ptr` is a `@dataclass(frozen=True, slots=True)`; **never** construct it outside `_iter_resolve`. Tests use private constructors (`_dict_ptr`, `_list_ptr` in `test_traversal.py`) for unit isolation — they reach into the underscore-prefixed fields and are tightly coupled to the dataclass shape.
- `...` (Ellipsis) is the project-wide sentinel for both "no unwrap" (`ContainerAdapter.unwrap`) and "no default" (`Ptr.try_get`). Adapters must not place a real `Ellipsis` payload inside a container (it would be indistinguishable from "no unwrap").
- Frozen taint is transitive: once the walker accumulates a freeze bit at any step, every descendant `Ptr` inherits it. There are two cooperating taint sources: `ContainerAdapter.is_step_frozen` (consulted at each token descent) and the OPTIONAL `is_value_frozen` (consulted by `_unwrap_to_fixed_point` on every container in the unwrap chain). Third-party adapters can become taint sources via either hook; `BaseModelAdapter` uses `is_value_frozen` to surface whole-model freeze configs (`ConfigDict(frozen=True)`) and the `Field(frozen=True)`-on-`RootModel.root` case, which `is_step_frozen` alone could not observe.
- The `ContainerAdapter` Protocol is `@runtime_checkable` with eight required methods. The 9th, `is_value_frozen`, is an OPTIONAL hook outside the Protocol surface — the walker probes via `getattr(adapter, "is_value_frozen", None)`, so adapters written against the canonical 8-method contract continue to satisfy `isinstance(adapter, ContainerAdapter)` and `register()`'s type annotation. Third-party adapters register via `register(cls, adapter)`. Adapters that don't care about wrapping/freezing should return `...` from `unwrap` and `False` from `is_step_frozen`, and may simply omit `is_value_frozen`.

## Public API surface

`src/pydantic_jsonpointer/__init__.py` re-exports the canonical 22 names listed in `__all__`: `JsonPointer`, `pointer_from_model`, `Ptr`, `resolve`, `get_value`, `set_value`, `add_value`, `remove_value`, `ContainerAdapter`, `register`, `adapter_for`, `FieldResolver`, `ByAttribute`, `BySerializationAlias`, `ByValidationAlias`, `BaseModelAdapter`, plus the six error classes. Importing the package **side-effect-registers** `BaseModelAdapter` against `pydantic.BaseModel` with `override=True` so `importlib.reload(pydantic_jsonpointer)` is safe. Agents touching `__init__.py` must preserve that registration line.

## Design references

- Authoritative design spec: `docs/superpowers/specs/2026-05-13-pointer-traversal-design.md`.
- Code-level companion plan: `docs/superpowers/plans/2026-05-14-pointer-traversal.md`.
- Ralphex execution checklist: `docs/plans/2026-05-14-pointer-traversal.md` (all 14 tasks completed).
- Model-attribute pointer builder spec: `docs/superpowers/specs/2026-05-15-model-attribute-pointer-builder.md`.
- Mypy-friendly `_ModelPath` spec: `docs/superpowers/specs/2026-05-15-modelpath-mypy-friendly.md`.

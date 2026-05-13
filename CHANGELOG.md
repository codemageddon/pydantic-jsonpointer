# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Optional `ContainerAdapter.is_value_frozen(value) -> bool` hook. A second freeze-taint source complementing `is_step_frozen` that propagates immutability across `unwrap` chains, fixing transitive freezing for `RootModel` containers declared with `ConfigDict(frozen=True)` or `Field(frozen=True)` on `root`. The hook lives outside the runtime-checkable Protocol surface (probed via `getattr` in the walker), so adapters written against the canonical 8-method contract keep working unchanged.

### Fixed

- Frozen `RootModel` (whole-model `ConfigDict(frozen=True)` or `Field(frozen=True)` on `root`) now correctly taints descendants reached via `unwrap`; previously inner-element writes silently succeeded.
- `AdapterNotFoundError` raised during traversal now includes the pointer prefix that reached the un-adaptable value (e.g. `... at pointer '/items/0/payload'`), matching the spec's edge-case matrix. The empty-pointer case at the root reports `at pointer ''`.
- `resolve(doc, JsonPointer("")).get()` returns the caller's original document — including `RootModel` instances and scalars — instead of the unwrapped inner value. Resolving an empty pointer on a scalar (e.g. `resolve(42, JsonPointer(""))`) no longer raises `AdapterNotFoundError`; a no-op sentinel adapter satisfies the dataclass shape without ever being invoked. Resolving a non-empty pointer on a scalar still raises `AdapterNotFoundError`, now with the empty-pointer prefix.

## [0.1.0b1]

### Added

- `Ptr` live cursor (frozen `@dataclass`, slotted) with `pointer` / `parent` / `key` / `is_root` / `is_frozen` properties; reads via `get()` / `try_get(default=...)` / `exists()`; mutations via `set` / `add` / `remove`. Root and frozen-target writes raise `RootRebindError` / `ImmutableTargetError` before the adapter call.
- `resolve(doc, pointer, *, resolver=None) -> Ptr` plus `get_value` / `set_value` / `add_value` / `remove_value` convenience helpers, all accepting the per-call `resolver` kwarg.
- `ContainerAdapter` runtime-checkable Protocol with eight methods, plus `register(cls, adapter, *, override=False)` and `adapter_for(value, *, resolver=None)` for pluggable container types. `adapter_for` walks `type(value).__mro__` and, when a non-None `resolver` is supplied, returns a per-call `BaseModelAdapter(resolver=resolver)` without mutating the registry.
- Built-in `DictAdapter` and `ListAdapter` auto-registered for `dict` and `list`. `ListAdapter` enforces RFC 6901 array-index shape: ASCII decimal digits only (non-ASCII Unicode decimals are rejected), no leading zero except single `"0"`, plus the `"-"` tail token; index methods reject `bool` keys.
- First-class Pydantic integration: `BaseModelAdapter` auto-registered against `pydantic.BaseModel` at package import (idempotent, so `importlib.reload` is safe). `FieldResolver` Protocol with three shipped policies — `ByAttribute`, `BySerializationAlias` (default), `ByValidationAlias` (handles `AliasChoices` and `AliasPath`).
- `RootModel` auto-unwrap via `_unwrap_to_fixed_point` (handles nested `RootModel`s). A depth cap of 64 prevents a misbehaving adapter from wedging traversal into an infinite loop; chains that fail to converge raise `PointerError`.
- Transitive frozen-field enforcement: `Field(frozen=True)` and `ConfigDict(frozen=True)` taint every descendant `Ptr` in the resolution path; writes raise `ImmutableTargetError`.
- Six-class error hierarchy with intentional multiple inheritance under stdlib types: `PointerError(Exception)`, `PointerNotFoundError(PointerError, KeyError)`, `AdapterNotFoundError(PointerError, TypeError)`, `InvalidTokenError(PointerError, ValueError)`, `RootRebindError(PointerError)`, `ImmutableTargetError(PointerError)`.
- Public `__all__` enumerating 21 names re-exported from `pydantic_jsonpointer`.

### Changed

- `JsonPointer` now stores its reference tokens internally at construction time; the `tokens` property returns `tuple[str, ...]` instead of `list[str]`.
- `_pydantic_validate` no longer short-circuits on already-constructed `JsonPointer` instances; it always re-constructs via `cls(raw)` to ensure `_tokens` is valid.

### Known limitations

- The root `Ptr` (pointer `""`) cannot rebind the caller's variable; mutations raise `RootRebindError`. Callers must replace the document themselves.

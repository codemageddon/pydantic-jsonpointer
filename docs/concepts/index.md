# Concepts

This section explains the design behind `pydantic-jsonpointer`. Read these pages to understand *why* the library is structured the way it is before diving into the reference.

<div class="grid cards" markdown>

- :material-code-string: **[JsonPointer type](json-pointer.md)**

    A `str` subclass with parsed-token storage, RFC 6901 validation in `__new__`, escape/unescape helpers, and full Pydantic v2 schema integration.

- :material-source-branch: **[Traversal](traversal.md)**

    `Ptr` handles, `resolve()` semantics, the four convenience helpers, frozen taint propagation, and the `Ellipsis` sentinel.

- :material-puzzle: **[Adapters](adapters.md)**

    The `ContainerAdapter` protocol, the eight required methods plus the optional `is_value_frozen` hook, and the module-level registry.

- :material-tag: **[Field resolvers](field-resolvers.md)**

    The three shipped policies — `ByAttribute`, `BySerializationAlias`, `ByValidationAlias` — and when to pick each.

- :material-alert-circle: **[Errors](errors.md)**

    The six-class exception hierarchy with intentional multiple inheritance so callers can catch under stdlib exception types.

</div>

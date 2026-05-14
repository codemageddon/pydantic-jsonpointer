"""Pydantic-specific traversal support.

Provides:
- FieldResolver Protocol: maps RFC 6901 tokens <-> Python attribute names
- Three shipped resolvers: ByAttribute, BySerializationAlias, ByValidationAlias
- BaseModelAdapter: ContainerAdapter for pydantic.BaseModel instances

``BaseModelAdapter`` is auto-registered against ``pydantic.BaseModel`` in
``pydantic_jsonpointer/__init__.py``; importing *this* module alone has no
side effects on the adapter registry.
"""

from __future__ import annotations

import copy
import sys
import types
import typing
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from pydantic import AliasChoices, AliasPath, BaseModel, RootModel

from .errors import InvalidTokenError, PointerNotFoundError

if TYPE_CHECKING:
    if sys.version_info >= (3, 11):
        from typing import Self
    else:
        from typing_extensions import Self


@runtime_checkable
class FieldResolver(Protocol):
    """Maps RFC 6901 tokens to Python attribute names on a Pydantic model.

    Implementations must be stateless and side-effect-free.
    """

    def to_attr(self, model_cls: type[BaseModel], token: str) -> str | None:
        """Return the Python attribute name on `model_cls` that this token
        addresses, or None if no field matches under this resolver's policy.
        """
        ...

    def to_token(self, model_cls: type[BaseModel], attr: str) -> str:
        """Inverse of `to_attr`: given an attribute name, return the token
        that should appear in a pointer addressing that field under this
        resolver's policy.
        """
        ...


class ByAttribute:
    """Resolves tokens against Python attribute names only.

    Strictest policy — no aliases are consulted. Useful when patches are
    authored in code against models with attribute-name access patterns.
    """

    def to_attr(self, model_cls: type[BaseModel], token: str) -> str | None:
        if token in model_cls.model_fields:
            return token
        return None

    def to_token(self, model_cls: type[BaseModel], attr: str) -> str:
        return attr


class BySerializationAlias:
    """Resolves tokens against the name that appears in ``model_dump(by_alias=True)``.

    Match priority for ``to_attr`` (and equivalent precedence for ``to_token``):
        1. ``field.serialization_alias``
        2. ``field.alias``
        3. attribute name (only if neither alias is set)

    This is the default resolver because JSON-Patch documents typically
    originate from the same serialized vocabulary the model emits.
    """

    def to_attr(self, model_cls: type[BaseModel], token: str) -> str | None:
        for attr_name, field in model_cls.model_fields.items():
            if field.serialization_alias is not None:
                if token == field.serialization_alias:
                    return attr_name
                continue
            if field.alias is not None:
                if token == field.alias:
                    return attr_name
                continue
            if token == attr_name:
                return attr_name
        return None

    def to_token(self, model_cls: type[BaseModel], attr: str) -> str:
        field = model_cls.model_fields[attr]
        if field.serialization_alias is not None:
            return str(field.serialization_alias)
        if field.alias is not None:
            return str(field.alias)
        return attr


def _validation_alias_strings(field: Any) -> list[str]:
    """Extract every string token usable to validate this field.

    Handles plain string aliases, ``AliasChoices`` (each choice may itself be
    a string or an ``AliasPath``), and a bare ``AliasPath`` (whose first path
    component is the top-level key). Returns an empty list if no
    ``validation_alias`` is set on the field.
    """
    va = field.validation_alias
    if va is None:
        return []
    if isinstance(va, str):
        return [va]
    if isinstance(va, AliasPath):
        first = va.path[0] if va.path else None
        return [first] if isinstance(first, str) else []
    if isinstance(va, AliasChoices):
        out: list[str] = []
        for choice in va.choices:
            if isinstance(choice, str):
                out.append(choice)
            elif isinstance(choice, AliasPath):
                first = choice.path[0] if choice.path else None
                if isinstance(first, str):
                    out.append(first)
        return out
    return []


class ByValidationAlias:
    """Resolves tokens against the names accepted by ``model_validate``.

    Match priority for ``to_attr``:
        1. any string in ``field.validation_alias`` (handling
           ``AliasChoices``/``AliasPath``)
        2. ``field.alias``
        3. attribute name (only if neither ``validation_alias`` nor ``alias``
           is set)
    """

    def to_attr(self, model_cls: type[BaseModel], token: str) -> str | None:
        for attr_name, field in model_cls.model_fields.items():
            va_strings = _validation_alias_strings(field)
            if va_strings:
                if token in va_strings:
                    return attr_name
                continue
            if field.alias is not None:
                if token == field.alias:
                    return attr_name
                continue
            if token == attr_name:
                return attr_name
        return None

    def to_token(self, model_cls: type[BaseModel], attr: str) -> str:
        field = model_cls.model_fields[attr]
        va_strings = _validation_alias_strings(field)
        if va_strings:
            return va_strings[0]
        if field.alias is not None:
            return str(field.alias)
        return attr


_MAX_ALIAS_UNWRAP_DEPTH = 16


def _annotation_accepts_none(model_cls: type[BaseModel], attr: str) -> bool:
    """True if the field's annotation includes ``None``.

    Covers ``Optional[X]`` / ``Union[X, None]``, PEP 604 ``X | None`` (the two
    distinct ``Union`` origins), the degenerate ``annotation is type(None)``
    case, and PEP 695 ``type`` aliases (``TypeAliasType``) whose underlying
    ``__value__`` resolves to one of the above. Aliases are unwrapped in a
    bounded loop so a pathological self-referential alias cannot wedge here.
    """
    annotation = model_cls.model_fields[attr].annotation
    for _ in range(_MAX_ALIAS_UNWRAP_DEPTH):
        if annotation is None:
            return False
        origin = typing.get_origin(annotation)
        if origin is typing.Union or origin is types.UnionType:
            return type(None) in typing.get_args(annotation)
        if annotation is type(None):
            return True
        # PEP 695 ``type Foo = X`` produces a ``TypeAliasType`` whose
        # ``get_origin`` is ``None`` but whose ``__value__`` is the aliased
        # annotation. Unwrap and retry.
        inner = getattr(annotation, "__value__", None)
        if inner is None or inner is annotation:
            return False
        annotation = inner
    return False


class BaseModelAdapter:
    """ContainerAdapter for ``pydantic.BaseModel`` instances.

    Resolves tokens via a configurable ``FieldResolver`` (default
    ``BySerializationAlias``). ``RootModel`` containers are transparently
    unwrapped to their ``.root`` value via ``unwrap``.

    Notes on semantics:
    - ``set`` and ``add`` are equivalent: a BaseModel's field set is fixed,
      so "create-or-replace" collapses to "replace".
    - ``remove`` sets the field to ``None`` and returns the previous value;
      only permitted when the field annotation accepts ``None``.
    - ``is_step_frozen`` reports True when the parent model has
      ``ConfigDict(frozen=True)`` or the addressed field has
      ``Field(frozen=True)``; the walker propagates this taint to every
      descendant slot.
    """

    def __init__(self, resolver: FieldResolver | None = None) -> None:
        self._resolver: FieldResolver = resolver or BySerializationAlias()

    def with_resolver(self, resolver: FieldResolver) -> Self:
        """Return a copy of this adapter with ``resolver`` substituted.

        Used by ``adapter_for(..., resolver=...)`` to apply a per-call
        resolver override without mutating the registered adapter. Subclasses
        that carry extra state inherit this behavior automatically because
        ``copy.copy`` preserves it; subclasses whose extra state needs custom
        cloning should override this method.
        """
        new = copy.copy(self)
        new._resolver = resolver
        return new

    def resolve_token(self, parent: BaseModel, raw_token: str) -> str:
        attr = self._resolver.to_attr(type(parent), raw_token)
        if attr is None:
            raise InvalidTokenError(
                f"no field on {type(parent).__name__!r} matches token "
                f"{raw_token!r} under resolver {type(self._resolver).__name__}"
            )
        return attr

    def has(self, parent: BaseModel, key: int | str) -> bool:
        if key not in type(parent).model_fields:
            return False
        # ``model_construct()`` may produce instances where a declared field
        # was never set on the instance dict; in that case ``getattr`` would
        # raise ``AttributeError``. Surface this as "no value present" so
        # ``has`` and ``get`` agree.
        return hasattr(parent, str(key))

    def get(self, parent: BaseModel, key: int | str) -> Any:
        model_cls = type(parent)
        if key not in model_cls.model_fields:
            raise PointerNotFoundError(f"{model_cls.__name__} has no field {key!r}")
        try:
            return getattr(parent, str(key))
        except AttributeError as exc:
            raise PointerNotFoundError(
                f"{model_cls.__name__} field {str(key)!r} is not set on "
                "this instance (declared but missing value)"
            ) from exc

    def set(self, parent: BaseModel, key: int | str, value: Any) -> None:
        model_cls = type(parent)
        if key not in model_cls.model_fields:
            raise PointerNotFoundError(f"{model_cls.__name__} has no field {key!r}")
        # Mirror ``has``: ``model_construct()`` can leave a declared field
        # without a value on the instance. JSON-Patch ``replace`` requires the
        # slot to already exist, so refuse rather than silently materializing
        # the field. ``add`` retains the create-or-replace semantics below.
        if not hasattr(parent, str(key)):
            raise PointerNotFoundError(
                f"{model_cls.__name__} field {str(key)!r} is not set on "
                "this instance (declared but missing value)"
            )
        setattr(parent, str(key), value)

    def add(self, parent: BaseModel, key: int | str, value: Any) -> None:
        # ``add`` is create-or-replace: the field must be declared on the
        # model (the schema is fixed), but unlike ``set`` it may materialize a
        # field that ``model_construct()`` left unset on the instance.
        model_cls = type(parent)
        if key not in model_cls.model_fields:
            raise PointerNotFoundError(f"{model_cls.__name__} has no field {key!r}")
        setattr(parent, str(key), value)

    def remove(self, parent: BaseModel, key: int | str) -> Any:
        model_cls = type(parent)
        if key not in model_cls.model_fields:
            raise PointerNotFoundError(f"{model_cls.__name__} has no field {key!r}")
        if not _annotation_accepts_none(model_cls, str(key)):
            raise InvalidTokenError(
                f"cannot remove non-Optional field "
                f"{model_cls.__name__}.{str(key)!r}; field annotation does "
                "not include None"
            )
        try:
            captured = getattr(parent, str(key))
        except AttributeError as exc:
            raise PointerNotFoundError(
                f"{model_cls.__name__} field {str(key)!r} is not set on "
                "this instance (declared but missing value)"
            ) from exc
        setattr(parent, str(key), None)
        return captured

    def unwrap(self, value: Any) -> Any:
        if isinstance(value, RootModel):
            return value.root
        return ...

    def is_step_frozen(self, parent: BaseModel, key: int | str) -> bool:
        if self.is_value_frozen(parent):
            return True
        field = type(parent).model_fields.get(str(key))
        if field is None:
            return False
        return bool(field.frozen)

    def is_value_frozen(self, value: BaseModel) -> bool:
        model_cls = type(value)
        if model_cls.model_config.get("frozen"):
            return True
        # For ``RootModel``, ``root`` is the sole field and the walker unwraps
        # straight through it — there is no descent step at which the field's
        # frozen flag could be observed. Surface it here so the unwrap chain
        # propagates the taint to descendants.
        if isinstance(value, RootModel):
            root_field = model_cls.model_fields.get("root")
            if root_field is not None and root_field.frozen:
                return True
        return False

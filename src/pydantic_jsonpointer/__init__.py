"""Public API surface for pydantic-jsonpointer.

Importing this package auto-registers ``BaseModelAdapter`` against
``pydantic.BaseModel`` so traversal of any BaseModel subclass works out of
the box without explicit setup.
"""

from pydantic import BaseModel as _BaseModel

from ._model_path import pointer_from_model
from .adapters import ContainerAdapter, adapter_for, register
from .errors import (
    AdapterNotFoundError,
    ImmutableTargetError,
    InvalidTokenError,
    PointerError,
    PointerNotFoundError,
    RootRebindError,
)
from .pydantic_adapter import (
    BaseModelAdapter,
    ByAttribute,
    BySerializationAlias,
    ByValidationAlias,
    FieldResolver,
)
from .traversal import (
    Ptr,
    add_value,
    get_value,
    remove_value,
    resolve,
    set_value,
)
from .types import JsonPointer

register(_BaseModel, BaseModelAdapter(), override=True)

__all__ = [
    "JsonPointer",
    "pointer_from_model",
    "Ptr",
    "resolve",
    "get_value",
    "set_value",
    "add_value",
    "remove_value",
    "ContainerAdapter",
    "register",
    "adapter_for",
    "FieldResolver",
    "ByAttribute",
    "BySerializationAlias",
    "ByValidationAlias",
    "BaseModelAdapter",
    "PointerError",
    "PointerNotFoundError",
    "AdapterNotFoundError",
    "RootRebindError",
    "InvalidTokenError",
    "ImmutableTargetError",
]

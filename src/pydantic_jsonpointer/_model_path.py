from __future__ import annotations

import types as _stdlib_types
import typing
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Generic, TypeVar, cast, overload

from pydantic import BaseModel, RootModel
from typing_extensions import TypeVar as _TypeVarExt

from .errors import PointerError
from .pydantic_adapter import BySerializationAlias, FieldResolver

if TYPE_CHECKING:
    from .types import JsonPointer

_T = TypeVar("_T", bound=BaseModel)
_P = _TypeVarExt("_P", default=Any)

_MAX_ADVANCE_DEPTH = 64


def _advance(
    annotation: Any,
    *,
    for_index: bool = False,
    index: int | None = None,
) -> type[BaseModel] | None:
    """Walk a type annotation extracting the BaseModel subclass for traversal.

    Returns the BaseModel subclass that the next navigation step should resolve
    against, or ``None`` when the annotation is a leaf type, an ambiguous
    Union, a container (without ``for_index``), or any type lacking model
    context.
    """
    for _ in range(_MAX_ADVANCE_DEPTH):
        origin = typing.get_origin(annotation)

        # PEP 695 type alias (Python 3.12+): ``type Foo = X`` produces a
        # TypeAliasType whose get_origin() is None but whose __value__ holds
        # the aliased type. Probe with getattr so this works on all supported
        # Python versions and with typing_extensions.TypeAliasType too.
        if origin is None:
            _alias_val = getattr(annotation, "__value__", None)
            if _alias_val is not None and _alias_val is not annotation:
                annotation = _alias_val
                continue

        if origin is typing.Annotated:
            args = typing.get_args(annotation)
            if args:
                annotation = args[0]
                continue
            return None

        if origin is typing.Union or origin is _stdlib_types.UnionType:
            args = typing.get_args(annotation)
            non_none = [a for a in args if a is not type(None)]
            if len(non_none) == 1:
                annotation = non_none[0]
                continue
            return None

        if isinstance(annotation, type) and issubclass(annotation, RootModel):
            root_field = annotation.model_fields.get("root")
            if root_field is not None and root_field.annotation is not None:
                annotation = root_field.annotation
                continue
            return None

        if for_index and origin in (list, tuple):
            args = typing.get_args(annotation)
            if args:
                if origin is tuple and args[-1] is not ...:
                    # Fixed-length heterogeneous tuple: index determines which type.
                    if index is None or index < 0 or index >= len(args):
                        return None
                    annotation = args[index]
                else:
                    # list or homogeneous tuple[T, ...]
                    if index is None:
                        # index=None is the "-" tail sentinel (RFC 6901 §4). "-" is
                        # only valid as a terminal add-position token; chaining further
                        # (.attr or [i]) produces a pointer that can never be resolved
                        # via get/set/remove. Lose model context for both list and tuple
                        # so any further chaining raises AttributeError at build time.
                        return None
                    annotation = args[0]
                for_index = False
                continue

        if not for_index:
            if (
                origin is not None
                and isinstance(origin, type)
                and issubclass(origin, BaseModel)
            ):
                return origin
            if isinstance(annotation, type) and issubclass(annotation, BaseModel):
                return annotation

        return None
    raise PointerError(  # _advance depth exceeded
        "annotation traversal depth exceeded; possible self-referential type"
    )


def _advance_attr(annotation: Any) -> type[BaseModel] | None:
    """Return the BaseModel subclass for the *next* ``.attr`` access."""
    return _advance(annotation, for_index=False)


def _advance_index(
    annotation: Any, *, index: int | None = None
) -> type[BaseModel] | None:
    """Return the BaseModel subclass for the *next* ``[index]`` access."""
    return _advance(annotation, for_index=True, index=index)


def _peel_item_annotation(annotation: Any, *, index: int | None = None) -> Any:
    """Return the raw item annotation from a container after peeling wrappers.

    Unlike _advance_index, this does not require the item to be a BaseModel — it
    stops as soon as it extracts the item type from a list or tuple. Used to carry
    _pending_annotation forward across chained __getitem__ calls (e.g. grid[0][0]
    on grid: list[list[Item]] needs list[Item] as pending context after the first [0]).
    Returns None when annotation is not a recognizable container.
    """
    for _ in range(_MAX_ADVANCE_DEPTH):
        origin = typing.get_origin(annotation)

        if origin is None:
            _alias_val = getattr(annotation, "__value__", None)
            if _alias_val is not None and _alias_val is not annotation:
                annotation = _alias_val
                continue
            # fall through: let the RootModel check below handle bare RootModel subclasses

        if origin is typing.Annotated:
            args = typing.get_args(annotation)
            if args:
                annotation = args[0]
                continue
            return None

        if origin is typing.Union or origin is _stdlib_types.UnionType:
            args = typing.get_args(annotation)
            non_none = [a for a in args if a is not type(None)]
            if len(non_none) == 1:
                annotation = non_none[0]
                continue
            return None

        if isinstance(annotation, type) and issubclass(annotation, RootModel):
            root_field = annotation.model_fields.get("root")
            if root_field is not None and root_field.annotation is not None:
                annotation = root_field.annotation
                continue
            return None

        if origin in (list, tuple):
            args = typing.get_args(annotation)
            if not args:
                return None
            if origin is tuple and args[-1] is not ...:
                if index is None or index < 0 or index >= len(args):
                    return None
                return args[index]
            if origin is tuple and index is None:
                return None
            return args[0]

        return None

    raise PointerError(  # _peel_item_annotation depth exceeded
        "annotation traversal depth exceeded; possible self-referential type"
    )


@overload
def pointer_from_model(
    model: type[_T],
    *,
    resolver: FieldResolver | None = None,
) -> _ModelPath[_T, Any]: ...


@overload
def pointer_from_model(
    model: _T,
    *,
    resolver: FieldResolver | None = None,
) -> _ModelPath[_T, Any]: ...


def pointer_from_model(
    model: type[BaseModel] | BaseModel,
    *,
    resolver: FieldResolver | None = None,
) -> _ModelPath[Any, Any]:
    """Start building a ``JsonPointer`` from a pydantic model's attribute chain.

    Accepts either a model *class* or an *instance*. Instance entry uses
    only ``type(model)`` — no runtime instance peeking. For Union-typed
    fields, narrow with ``isinstance`` and pass the narrowed value.

    Usage::

        ptr = pointer_from_model(User).name
        ptr = pointer_from_model(User).address.city
        ptr = pointer_from_model(Order).items[0].name
        if isinstance(event.payload, JsonBody):
            ptr = pointer_from_model(event.payload).body
    """
    if resolver is None:
        resolver = BySerializationAlias()

    if isinstance(model, BaseModel):
        model_cls = type(model)
    elif isinstance(model, type) and issubclass(model, BaseModel):
        model_cls = model
    else:
        msg = (
            f"pointer_from_model expects a BaseModel class or instance, "
            f"got {type(model).__name__}"
        )
        raise TypeError(msg)

    pending: Any = None
    effective_model_cls = model_cls
    if issubclass(model_cls, RootModel):
        root_field = model_cls.model_fields.get("root")
        if root_field is not None and root_field.annotation is not None:
            pending = root_field.annotation
            inner_cls = _advance_attr(pending)
            if inner_cls is not None:
                effective_model_cls = inner_cls

    return _ModelPath(
        _model_cls=effective_model_cls,
        _resolver=resolver,
        _pending_annotation=pending,
    )


@dataclass(frozen=True, slots=True)
class _ModelPath(Generic[_T, _P]):
    """Proxy that captures attribute chains on a pydantic model.

    Produced by ``pointer_from_model()``. Each ``.attr`` access records the
    attribute name (resolved to a token via a ``FieldResolver``) and may
    advance the model class for deeper chaining. ``[index]`` inserts a raw
    token and may advance the model to the container's item type.

    Private — not exported. The public API is ``pointer_from_model()``.
    """

    _model_cls: type[_T]
    _tokens: tuple[str, ...] = ()
    _resolver: FieldResolver | None = None
    _pending_annotation: _P = cast(_P, None)
    _model_ctx_lost: bool = False

    def __getattribute__(self, name: str) -> Any:
        # Model fields take priority over class-defined methods/attributes so
        # fields named e.g. 'build' are reachable via attribute chaining.
        # Skip field routing when context is lost — the user is calling a class
        # method (e.g. build()) to finalize, not navigating a field.
        if not name.startswith("_"):
            model_ctx_lost: bool = object.__getattribute__(self, "_model_ctx_lost")
            if not model_ctx_lost:
                model_cls: type[BaseModel] = object.__getattribute__(self, "_model_cls")
                if name in model_cls.model_fields:
                    return _ModelPath.__getattr__(self, name)
        return object.__getattribute__(self, name)

    def build(self) -> JsonPointer:
        """Resolve accumulated tokens into a ``JsonPointer``."""
        from .types import JsonPointer

        return JsonPointer.from_tokens(*self._tokens)

    def __call__(self) -> JsonPointer:
        """Finalize the chain and return a ``JsonPointer``.

        Use this instead of ``.build()`` when the underlying model has a field
        named ``build`` — in that case ``.build`` navigates to the field, and
        ``()`` is the safe way to finalize without adding an extra token.
        """
        return _ModelPath.build(self)

    def __str__(self) -> str:
        return str(_ModelPath.build(self))

    def __repr__(self) -> str:
        return (
            f"_ModelPath(model={self._model_cls.__name__!r}, tokens={self._tokens!r})"
        )

    def __getattr__(self, name: str) -> _ModelPath[Any, Any]:
        if self._model_ctx_lost:
            raise AttributeError(
                f"cannot chain .{name}: model type context was lost "
                "(leaf type, ambiguous Union, or non-list container); "
                "narrow via isinstance() and pass the narrowed value to "
                "pointer_from_model()"
            )
        if issubclass(self._model_cls, RootModel):
            raise AttributeError(
                f"cannot chain .{name} on {self._model_cls.__name__!r}: "
                "RootModel subclasses are traversed transparently at runtime; "
                "use [index] to navigate into the wrapped container instead"
            )
        field_info = self._model_cls.model_fields.get(name)
        if field_info is None:
            raise AttributeError(f"{self._model_cls.__name__!r} has no field {name!r}")
        if self._resolver is None:
            raise AttributeError(
                "_ModelPath has no resolver; construct via pointer_from_model()"
            )
        token = self._resolver.to_token(self._model_cls, name)
        annotation = field_info.annotation
        next_cls = _advance_attr(annotation)
        return _ModelPath(
            _model_cls=next_cls or self._model_cls,
            _tokens=self._tokens + (token,),
            _resolver=self._resolver,
            _pending_annotation=annotation,
            _model_ctx_lost=next_cls is None,
        )

    def __getitem__(self, index: int | str) -> _ModelPath[Any, Any]:
        if self._pending_annotation is None and not self._model_ctx_lost:
            raise TypeError(
                f"cannot index into {self._model_cls.__name__!r}: "
                "navigate to a list or tuple field first"
            )
        if not isinstance(index, (int, str)):
            raise TypeError(
                f"list index must be int or str, got {type(index).__name__!r}"
            )
        if isinstance(index, bool) or (isinstance(index, int) and index < 0):
            raise ValueError(
                f"invalid list index {index!r} is not a valid RFC 6901 array token"
            )
        if isinstance(index, str) and index != "-":
            _ascii_digits = bool(index) and all("0" <= c <= "9" for c in index)
            if not _ascii_digits or (len(index) > 1 and index[0] == "0"):
                raise ValueError(
                    f"invalid array token {index!r}: "
                    "must be a non-negative integer string or '-'"
                )
        token = str(index)
        is_dash = isinstance(index, str) and index == "-"
        int_index: int | None = None
        if isinstance(index, int):
            int_index = index
        elif isinstance(index, str) and index != "-":
            int_index = int(index)
        next_cls = _advance_index(self._pending_annotation, index=int_index)
        next_pending_annotation: Any = None
        # "-" is a terminal add-position token: context loss must not be recovered
        # by a subsequent [i] step. Keeping _pending_annotation=None prevents
        # _advance_index from resolving a nested container's item type.
        if next_cls is None and not is_dash:
            next_pending_annotation = _peel_item_annotation(
                self._pending_annotation, index=int_index
            )
        return _ModelPath(
            _model_cls=next_cls or self._model_cls,
            _tokens=self._tokens + (token,),
            _resolver=self._resolver,
            _pending_annotation=next_pending_annotation,
            _model_ctx_lost=next_cls is None,
        )

    def __truediv__(self, token: str | int) -> JsonPointer:
        """Append a raw token to the pointer (terminal — model-awareness ends)."""
        return _ModelPath.build(self) / token

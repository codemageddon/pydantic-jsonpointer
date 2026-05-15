"""Mypy plugin for pydantic-jsonpointer.

Validates that ``_ModelPath`` attribute and index access respects the
model class's field declarations.

In mypy 2.x, implicit attribute access on ``_ModelPath`` (e.g.,
``mp.name``) is intercepted via ``get_attribute_hook`` rather than
``get_method_signature_hook`` for ``__getattr__``.  Explicit method calls
(e.g., ``mp[0]`` via ``__getitem__``) use ``get_method_signature_hook``.
"""

from __future__ import annotations

from typing import Any, Callable

from mypy.nodes import Expression, IntExpr, NameExpr, StrExpr, TypeInfo, UnaryExpr, Var
from mypy.plugin import AttributeContext, MethodSigContext, Plugin
from mypy.types import (
    AnyType,
    Instance,
    LiteralType,
    NoneType,
    ProperType,
    TupleType,
    Type,
    TypeOfAny,
    UnionType,
    get_proper_type,
)

_MODEL_PATH_FULLNAME = "pydantic_jsonpointer._model_path._ModelPath"


def _is_base_model(info: TypeInfo) -> bool:
    for base in info.mro:
        if base.fullname == "pydantic.main.BaseModel":
            return True
    return False


_ROOTMODEL_FULLNAMES = frozenset(
    {
        "pydantic.main.RootModel",
        "pydantic.root_model.RootModel",
    }
)

_MAX_ROOTMODEL_PEEL_DEPTH = 64


def _is_root_model(info: TypeInfo) -> bool:
    for base in info.mro:
        if base.fullname in _ROOTMODEL_FULLNAMES:
            return True
    return False


def _get_rootmodel_inner_raw(inst: Instance) -> ProperType | None:
    """Return the raw inner type T from a RootModel Instance, not limited to Instance.

    Handles two cases:
    - Direct ``RootModel[T]`` annotation: reads the type arg from inst.args[0].
    - Named subclass (e.g. ``TagList(RootModel[list[Item]])``) with no type args:
      falls back to MRO walk on inst.type.

    Unlike _get_rootmodel_inner, does not restrict the return type to Instance,
    so TupleType and multi-branch UnionType inner types are returned as-is.
    """
    if inst.type.fullname in _ROOTMODEL_FULLNAMES and inst.args:
        return get_proper_type(inst.args[0])
    for mro_type in inst.type.mro:
        for base in mro_type.bases:
            if not isinstance(base, Instance):
                continue
            if base.type.fullname not in _ROOTMODEL_FULLNAMES:
                continue
            if not base.args:
                continue
            return get_proper_type(base.args[0])
    return None


def _is_indexed_container_type(info: TypeInfo) -> bool:
    return info.fullname in (
        "builtins.list",
        "builtins.tuple",
    )


def _advance_attr_mypy(typ: Type) -> Instance | None:
    """Mypy-level _advance_attr. Returns model Instance or None."""
    typ = get_proper_type(typ)

    if isinstance(typ, UnionType):
        items = [t for t in typ.items if not isinstance(get_proper_type(t), NoneType)]
        if len(items) == 1:
            return _advance_attr_mypy(items[0])
        return None

    if isinstance(typ, Instance):
        # Check RootModel before BaseModel: RootModel IS a BaseModel subclass,
        # so _is_base_model would match first and return the wrapper type unchanged.
        if _is_root_model(typ.type):
            # Use _get_rootmodel_inner_raw so that direct RootModel[T] annotations
            # (not just named subclasses) are unwrapped via inst.args[0].
            inner = _get_rootmodel_inner_raw(typ)
            if inner is not None:
                return _advance_attr_mypy(inner)
            return None
        if _is_base_model(typ.type):
            return typ

    return None


def _advance_index_mypy(typ: Type, *, _list_peeled: bool = False) -> Instance | None:
    """Mypy-level _advance_index. Returns item Instance or None.

    A BaseModel is only returned after peeling exactly one list or tuple
    container, mirroring what _advance_index does at runtime.  Peeling a
    RootModel wrapper alone does not count — the inner type must still be a
    list/tuple for indexing to be valid.

    Uses _get_rootmodel_inner_raw rather than typ.args so that both generic
    RootModel[T] usages and concrete subclasses (TagList, DoubleWrap) are
    handled uniformly.

    Returns None when the item is a non-BaseModel type (e.g. list[list[Item]]
    yields list[Item] as the item — use _raw_item_annotation_mypy to get that).
    """
    typ = get_proper_type(typ)

    if isinstance(typ, UnionType):
        items = [t for t in typ.items if not isinstance(get_proper_type(t), NoneType)]
        if len(items) == 1:
            return _advance_index_mypy(items[0], _list_peeled=_list_peeled)
        return None

    if isinstance(typ, Instance):
        if _is_root_model(typ.type):
            inner = _get_rootmodel_inner_raw(typ)
            if inner is not None:
                return _advance_index_mypy(inner, _list_peeled=_list_peeled)
            return None

        if _is_indexed_container_type(typ.type) and typ.args:
            if _list_peeled:
                # Already peeled one container layer; item is another container,
                # not a BaseModel — caller must use _raw_item_annotation_mypy.
                return None
            return _advance_index_mypy(typ.args[0], _list_peeled=True)

        if _list_peeled and _is_base_model(typ.type):
            return typ

    return None


def _raw_item_annotation_mypy(typ: Type) -> Type | None:
    """Return the item annotation from a list/tuple container after peeling wrappers.

    Unlike _advance_index_mypy, does not require the item to be a BaseModel.
    Used by _hook_getitem to carry the pending annotation forward when the item
    is itself a container (e.g. list[list[Item]] -> list[Item]).
    """
    typ = get_proper_type(typ)

    if isinstance(typ, UnionType):
        items = [t for t in typ.items if not isinstance(get_proper_type(t), NoneType)]
        if len(items) == 1:
            return _raw_item_annotation_mypy(items[0])
        return None

    if isinstance(typ, Instance):
        if _is_root_model(typ.type):
            inner = _get_rootmodel_inner_raw(typ)
            if inner is not None:
                return _raw_item_annotation_mypy(inner)
            return None
        if _is_indexed_container_type(typ.type) and typ.args:
            return get_proper_type(typ.args[0])

    return None


def _make_modelpath_any(typeinfo: TypeInfo) -> Instance:
    """Build _ModelPath[Any, Any] from the live _ModelPath TypeInfo.

    Used to terminate the type chain cleanly when the next model can't be
    determined statically (leaf type, ambiguous Union, root-level Any).
    """
    any_t = AnyType(TypeOfAny.implementation_artifact)
    return Instance(typeinfo, [any_t, any_t])


def _extract_int_index(
    arg_expr: object, ctx: MethodSigContext | None = None
) -> int | None:
    """Extract a non-negative integer index from an IntExpr, digit-string StrExpr, or
    any expression whose inferred type is Literal[int] (e.g. a named Literal variable).

    Mirrors the runtime normalization in _ModelPath.__getitem__: a string index
    that is a valid RFC 6901 array token (ASCII digits, no leading zero except "0"
    itself) resolves to the same tuple slot as the equivalent integer literal.
    """
    if isinstance(arg_expr, IntExpr):
        return arg_expr.value
    if isinstance(arg_expr, StrExpr):
        v = arg_expr.value
        if v and all("0" <= c <= "9" for c in v) and (len(v) == 1 or v[0] != "0"):
            return int(v)
    if ctx is not None:
        if isinstance(arg_expr, Expression):
            try:
                expr_type = ctx.api.get_expression_type(arg_expr)
            except Exception:
                return None
            if expr_type is not None:
                proper = get_proper_type(expr_type)
                if isinstance(proper, LiteralType):
                    if (
                        isinstance(proper.value, int)
                        and proper.fallback.type.fullname != "builtins.bool"
                    ):
                        return proper.value
                    if isinstance(proper.value, str):
                        v = proper.value
                        if (
                            v
                            and all("0" <= c <= "9" for c in v)
                            and (len(v) == 1 or v[0] != "0")
                        ):
                            return int(v)
    return None


def _expr_has_bool_type(ctx: MethodSigContext, arg_expr: object) -> bool:
    """Return True when mypy has inferred a bool type for the expression.

    Covers all bool-typed expressions: literals, named variables, attribute
    access (obj.flag), calls (flag_fn()), and comparisons (1 == 1).
    Falls back to False when the type is not yet available (e.g. for exotic
    expression forms where get_expression_type returns None).
    """
    from mypy.nodes import Expression

    if not isinstance(arg_expr, Expression):
        return False
    try:
        typ = ctx.api.get_expression_type(arg_expr)
    except Exception:
        return False
    if typ is None:
        return False
    proper = get_proper_type(typ)
    if isinstance(proper, Instance) and proper.type.fullname == "builtins.bool":
        return True
    # Literal[True] / Literal[False] have a LiteralType with bool fallback.
    if (
        isinstance(proper, LiteralType)
        and proper.fallback.type.fullname == "builtins.bool"
    ):
        return True
    return False


def _check_literal_index(ctx: MethodSigContext) -> bool:
    """Validate the first argument against RFC 6901 array token rules.

    Emits ctx.api.fail() and returns False for invalid literal indices
    (negative integers, strings that are not valid RFC 6901 array tokens and
    not the tail marker "-") and for bool-typed expressions (which are always
    invalid regardless of value).  Returns True when the argument is absent,
    non-literal non-bool, or a valid token.
    """
    if not (ctx.args and ctx.args[0]):
        return True
    arg_expr = ctx.args[0][0]
    # General type-based bool check: covers attribute access (obj.flag),
    # function calls (flag_fn()), comparisons (1 == 1), named variables, and
    # literals — any expression whose inferred type is bool.
    if _expr_has_bool_type(ctx, arg_expr):
        ctx.api.fail(
            "invalid array index: bool is not a valid RFC 6901 array token",
            ctx.context,
        )
        return False
    # Fallback AST-based check for True/False literals in case get_expression_type
    # hasn't typed the expression yet (defensive guard only).
    if isinstance(arg_expr, NameExpr) and arg_expr.fullname in (
        "builtins.True",
        "builtins.False",
    ):
        ctx.api.fail(
            f"invalid array index {arg_expr.name!r}: "
            "bool is not a valid RFC 6901 array token",
            ctx.context,
        )
        return False
    # Negative literals appear as UnaryExpr('-', IntExpr(n)) in mypy's AST.
    # Note: -0 evaluates to 0 which is a valid RFC 6901 token; only truly
    # negative values (non-zero operand) should be rejected.
    if isinstance(arg_expr, UnaryExpr) and arg_expr.op == "-":
        if isinstance(arg_expr.expr, IntExpr) and arg_expr.expr.value > 0:
            ctx.api.fail(
                f"invalid array index {-arg_expr.expr.value!r}: "
                "negative integers are not valid RFC 6901 array tokens",
                ctx.context,
            )
            return False
    if isinstance(arg_expr, IntExpr) and arg_expr.value < 0:
        ctx.api.fail(
            f"invalid array index {arg_expr.value!r}: "
            "negative integers are not valid RFC 6901 array tokens",
            ctx.context,
        )
        return False
    if isinstance(arg_expr, StrExpr):
        v = arg_expr.value
        if v != "-":
            valid = (
                bool(v)
                and all("0" <= c <= "9" for c in v)
                and (len(v) == 1 or v[0] != "0")
            )
            if not valid:
                ctx.api.fail(
                    f"invalid array token {v!r}: "
                    "must be a non-negative integer string or '-'",
                    ctx.context,
                )
                return False
    # Named Literal variables not already caught by AST checks above: use type
    # inference to validate negative int literals and invalid string tokens.
    if isinstance(arg_expr, Expression):
        try:
            expr_type = ctx.api.get_expression_type(arg_expr)
        except Exception:
            pass
        else:
            if expr_type is not None:
                proper_t = get_proper_type(expr_type)
                if isinstance(proper_t, LiteralType):
                    val = proper_t.value
                    if (
                        isinstance(val, int)
                        and proper_t.fallback.type.fullname != "builtins.bool"
                        and val < 0
                    ):
                        ctx.api.fail(
                            f"invalid array index {val!r}: "
                            "negative integers are not valid RFC 6901 array tokens",
                            ctx.context,
                        )
                        return False
                    if isinstance(val, str) and val != "-":
                        valid_str = (
                            bool(val)
                            and all("0" <= c <= "9" for c in val)
                            and (len(val) == 1 or val[0] != "0")
                        )
                        if not valid_str:
                            ctx.api.fail(
                                f"invalid array token {val!r}: "
                                "must be a non-negative integer string or '-'",
                                ctx.context,
                            )
                            return False
    return True


def _is_dash_index(ctx: MethodSigContext) -> bool:
    """Return True when the first __getitem__ argument is or evaluates to '-'.

    Covers inline StrExpr("-") and named Literal["-"] variables via type
    inference so the tuple tail-marker context-loss path is symmetric with
    literal-index validation in _check_literal_index.
    """
    if not (ctx.args and ctx.args[0]):
        return False
    arg_expr = ctx.args[0][0]
    if isinstance(arg_expr, StrExpr):
        return arg_expr.value == "-"
    if isinstance(arg_expr, Expression):
        try:
            expr_type = ctx.api.get_expression_type(arg_expr)
        except Exception:
            return False
        if expr_type is not None:
            proper = get_proper_type(expr_type)
            if isinstance(proper, LiteralType) and proper.value == "-":
                return True
    return False


def _is_ambiguous_basemodel_union(field_type: Type) -> bool:
    """True iff field_type is a Union of >=2 BaseModel branches (non-None)."""
    proper = get_proper_type(field_type)
    if not isinstance(proper, UnionType):
        return False
    non_none = [t for t in proper.items if not isinstance(get_proper_type(t), NoneType)]
    if len(non_none) <= 1:
        return False
    for branch in non_none:
        inner = get_proper_type(branch)
        if not isinstance(inner, Instance):
            return False
        if not _is_base_model(inner.type):
            return False
    return True


def _has_any_indexable_branch(typ: Type) -> bool:
    """True iff typ is a Union containing at least one list or tuple branch.

    Used to avoid false-positive 'index applied to non-list type' errors for
    fields like list[A] | list[B] where indexing is valid at runtime (it just
    loses model context, matching the _model_ctx_lost=True runtime path).
    """
    proper = get_proper_type(typ)
    if not isinstance(proper, UnionType):
        return False
    for item in proper.items:
        branch = get_proper_type(item)
        if isinstance(branch, NoneType):
            continue
        if isinstance(branch, Instance) and _is_indexed_container_type(branch.type):
            return True
        if isinstance(branch, TupleType):
            return True
        # Peel RootModel[list[...]] / RootModel[tuple[...]] so that fields like
        # `wrapped: RootModel[list[Item]] | int` are not false-positived.
        if isinstance(branch, Instance) and _is_root_model(branch.type):
            inner = _get_rootmodel_inner_raw(branch)
            if inner is not None:
                if isinstance(inner, Instance) and _is_indexed_container_type(
                    inner.type
                ):
                    return True
                if isinstance(inner, TupleType):
                    return True
    return False


def _hook_modelpath_attr(ctx: AttributeContext, attr_name: str) -> Type:
    """Attribute hook for _ModelPath.* access.

    Synthesizes a parametrized _ModelPath[NextModel, FieldType] so chained
    .attr accesses fire this hook again with the advanced model class.
    """
    default = ctx.default_attr_type

    mp_type = ctx.type
    if mp_type is None or not isinstance(mp_type, Instance):
        return default
    if mp_type.type.fullname != _MODEL_PATH_FULLNAME:
        return default
    if len(mp_type.args) < 1:
        return default

    model_instance = get_proper_type(mp_type.args[0])
    # Chain already collapsed upstream (e.g. ambiguous Union, previous error) — propagate Any.
    # But if arg[1] (pending_type) is still a concrete type, model context was just lost at a
    # leaf field (not yet errored): emit an error so runtime AttributeError is caught statically.
    if isinstance(model_instance, AnyType):
        if len(mp_type.args) >= 2:
            pending_type = get_proper_type(mp_type.args[1])
            if not isinstance(pending_type, AnyType):
                ctx.api.fail(
                    f"cannot chain .{attr_name}: model type context was lost; "
                    "finalize with build() or ()",
                    ctx.context,
                )
        return _make_modelpath_any(mp_type.type)
    if not isinstance(model_instance, Instance):
        return default

    # Peel RootModel wrappers down to the inner BaseModel.
    # Use _get_rootmodel_inner_raw so that direct RootModel[T] (not just named
    # subclasses) is handled correctly via inst.args[0].
    for _ in range(_MAX_ROOTMODEL_PEEL_DEPTH):
        if not _is_root_model(model_instance.type):
            break
        inner_raw: ProperType | None = _get_rootmodel_inner_raw(model_instance)
        if inner_raw is None:
            break
        # Peel Optional[Inner] / Inner | None — mirrors _get_rootmodel_inner logic.
        if isinstance(inner_raw, UnionType):
            non_none = [
                t
                for t in inner_raw.items
                if not isinstance(get_proper_type(t), NoneType)
            ]
            inner_raw = get_proper_type(non_none[0]) if len(non_none) == 1 else None
        if not isinstance(inner_raw, Instance) or not _is_base_model(inner_raw.type):
            break
        model_instance = inner_raw

    if _is_root_model(model_instance.type):
        ctx.api.fail(
            f"cannot chain .{attr_name} on '{model_instance.type.name}': "
            "RootModel subclasses are traversed transparently; "
            "use [index] to navigate into the wrapped container instead",
            ctx.context,
        )
        return _make_modelpath_any(mp_type.type)

    sym = model_instance.type.get(attr_name)
    if sym is None or not isinstance(sym.node, Var) or sym.node.is_classvar:
        ctx.api.fail(
            f"'{model_instance.type.name}' has no field '{attr_name}'",
            ctx.context,
        )
        # Collapse to Any so follow-on accesses don't emit spurious cascade errors
        # against the now-invalid chain (runtime stops at the first bad access).
        return _make_modelpath_any(mp_type.type)

    field_type = sym.node.type
    next_model = _advance_attr_mypy(field_type) if field_type is not None else None

    if next_model is None:
        # Leaf type or ambiguous Union — model context is lost after this step.
        if field_type is not None and _is_ambiguous_basemodel_union(field_type):
            ctx.api.fail(
                f"field '{attr_name}' is an ambiguous BaseModel Union; "
                "narrow via isinstance() and call pointer_from_model() on "
                "the narrowed value for further static validation",
                ctx.context,
            )
            return _make_modelpath_any(mp_type.type)
        # Leaf field: set arg[0] to Any so subsequent .attr access propagates Any
        # without validating against the parent model (false-negative prevention),
        # but preserve field_type in arg[1] so __getitem__ can still reject
        # indexing into a non-list leaf type (e.g. .name[0] on str field).
        return Instance(
            mp_type.type,
            [
                AnyType(TypeOfAny.implementation_artifact),
                field_type
                if field_type is not None
                else AnyType(TypeOfAny.implementation_artifact),
            ],
        )

    pending: Type = (
        field_type
        if field_type is not None
        else AnyType(TypeOfAny.implementation_artifact)
    )
    return Instance(mp_type.type, [next_model, pending])


def _hook_getitem(ctx: MethodSigContext) -> Any:
    """Hook for _ModelPath.__getitem__. Validates list-like context and
    returns a signature whose ret_type carries the advanced item model so
    subsequent .attr access fires _hook_modelpath_attr against it.
    """
    sig = ctx.default_signature

    self_type = ctx.type
    if self_type is None or not isinstance(self_type, Instance):
        return sig
    if self_type.type.fullname != _MODEL_PATH_FULLNAME:
        return sig
    if len(self_type.args) < 2:
        return sig

    model_instance = get_proper_type(self_type.args[0])
    pending = get_proper_type(self_type.args[1])
    # AnyType model_instance means .attr context was already lost (leaf field), but
    # pending may carry a concrete type for indexability checking (.name[0] → error).
    if not isinstance(model_instance, (Instance, AnyType)):
        return sig

    # RootModel entry without a recorded pending annotation: peel via args/MRO.
    if isinstance(model_instance, Instance) and isinstance(pending, AnyType):
        if _is_root_model(model_instance.type):
            inner = _get_rootmodel_inner_raw(model_instance)
            if inner is not None:
                pending = inner

    if isinstance(pending, AnyType):
        # Context lost, but RFC 6901 token-form validation still applies.
        _check_literal_index(ctx)
        return sig

    if isinstance(pending, NoneType):
        # Hard context loss from a prior '-' dash step (NoneType sentinel set by
        # the dash-list branch above). Further indexing cannot recover model context.
        ctx.api.fail(
            "cannot chain [index]: model type context was lost after a '-' token; "
            "finalize with build() or ()",
            ctx.context,
        )
        return sig.copy_modified(ret_type=_make_modelpath_any(self_type.type))

    if not _check_literal_index(ctx):
        return sig

    # "-" is rejected by TupleAdapter at runtime for both tuple[T, ...] and
    # tuple[A, B]; emit a hard error and lose model context so that subsequent
    # [i] steps cannot "recover" into a specific model type.  This mirrors
    # _advance(..., index=None) → None in _model_path.py and prevents false
    # positives like pair["-"][0].city type-checking when the chain fails at
    # traversal time.  Use _is_dash_index so named Literal["-"] variables are
    # detected via type inference, not just inline StrExpr.
    if _is_dash_index(ctx):
        _pend = get_proper_type(pending)
        if isinstance(_pend, Instance) and _is_root_model(_pend.type):
            _inner = _get_rootmodel_inner_raw(_pend)
            if _inner is not None:
                _pend = get_proper_type(_inner)
        # Peel Optional / single-branch union so Optional[tuple[A, B]] is
        # recognised as a tuple for the dash-index diagnostic.
        if isinstance(_pend, UnionType):
            _non_none = [
                t for t in _pend.items if not isinstance(get_proper_type(t), NoneType)
            ]
            if len(_non_none) == 1:
                _pend = get_proper_type(_non_none[0])
        # After peeling Optional, retry RootModel peel for
        # Optional[RootModel[tuple[...]]] so the tuple-tail diagnostic fires.
        if isinstance(_pend, Instance) and _is_root_model(_pend.type):
            _inner_retry = _get_rootmodel_inner_raw(_pend)
            if _inner_retry is not None:
                _pend = _inner_retry
        if (
            isinstance(_pend, Instance) and _pend.type.fullname == "builtins.tuple"
        ) or isinstance(_pend, TupleType):
            ctx.api.fail(
                "index '-' is not valid for tuple fields: "
                "TupleAdapter rejects the tail-pointer token at traversal time; "
                "use a non-negative integer index instead",
                ctx.context,
            )
            return sig.copy_modified(ret_type=_make_modelpath_any(self_type.type))
        # For list (and any other non-tuple) fields: "-" is valid as a terminal
        # add-position token but must not allow further model-aware chaining.
        # Store NoneType() as a sentinel in arg[1] so both the attr hook
        # (items["-"].city) and the getitem hook (rows["-"][0]) can detect
        # this hard context-loss state and emit "context was lost" errors.
        # NoneType() is distinguishable from AnyType (which signals "fully lost")
        # and from a real field type (which signals "leaf-field context loss").
        return sig.copy_modified(
            ret_type=Instance(
                self_type.type,
                [AnyType(TypeOfAny.implementation_artifact), NoneType()],
            )
        )

    item_type = _advance_index_mypy(pending)
    if item_type is None:
        # Distinguish "not indexable" from "item is a non-BaseModel container".
        # For nested containers like list[list[Item]], carry the item annotation
        # forward so the next [0] can still validate against it.
        raw_item = _raw_item_annotation_mypy(pending)
        if raw_item is None:
            # Peel RootModel wrappers to check the actual underlying container type.
            # This handles fields like `wrapped: RootModel[tuple[A, B]]` and
            # `wrapped: RootModel[list[A] | list[B]]` where the inner type is
            # indexable at runtime but not reachable via _get_rootmodel_inner.
            proper_pending = get_proper_type(pending)
            if isinstance(proper_pending, Instance) and _is_root_model(
                proper_pending.type
            ):
                inner_raw = _get_rootmodel_inner_raw(proper_pending)
                if inner_raw is not None:
                    proper_pending = inner_raw
            # Peel Optional / single-branch union so Optional[tuple[A, B]] reaches
            # the TupleType branch below instead of falling through to _has_any_indexable_branch.
            if isinstance(proper_pending, UnionType):
                _non_none = [
                    t
                    for t in proper_pending.items
                    if not isinstance(get_proper_type(t), NoneType)
                ]
                if len(_non_none) == 1:
                    proper_pending = get_proper_type(_non_none[0])
            # After peeling Optional, retry RootModel peel for
            # Optional[RootModel[tuple[...]]] so the TupleType branch is reached.
            if isinstance(proper_pending, Instance) and _is_root_model(
                proper_pending.type
            ):
                _inner_opt_root = _get_rootmodel_inner_raw(proper_pending)
                if _inner_opt_root is not None:
                    proper_pending = _inner_opt_root
            if isinstance(proper_pending, TupleType):
                # Try to advance to the element model using the literal index so
                # that subsequent .attr access can be validated.
                if ctx.args and ctx.args[0]:
                    arg_expr = ctx.args[0][0]
                    idx = _extract_int_index(arg_expr, ctx)
                    if idx is not None:
                        n = len(proper_pending.items)
                        if 0 <= idx < n:
                            proper_item: ProperType = get_proper_type(
                                proper_pending.items[idx]
                            )
                            # Peel Optional[BaseModel] -> BaseModel
                            if isinstance(proper_item, UnionType):
                                non_none_items = [
                                    t
                                    for t in proper_item.items
                                    if not isinstance(get_proper_type(t), NoneType)
                                ]
                                if len(non_none_items) == 1:
                                    proper_item = get_proper_type(non_none_items[0])
                            # Bare BaseModel -> advance model context
                            if isinstance(proper_item, Instance) and _is_base_model(
                                proper_item.type
                            ):
                                new_ret = Instance(
                                    self_type.type,
                                    [
                                        proper_item,
                                        AnyType(TypeOfAny.implementation_artifact),
                                    ],
                                )
                                return sig.copy_modified(ret_type=new_ret)
                            # Container item (list[X], tuple[...]) -> carry
                            # forward as pending so the next [0] can resolve
                            if isinstance(
                                proper_item, Instance
                            ) and _is_indexed_container_type(proper_item.type):
                                new_ret = Instance(
                                    self_type.type,
                                    [model_instance, proper_item],
                                )
                                return sig.copy_modified(ret_type=new_ret)
                            # Fixed-length tuple element -> carry TupleType
                            # forward so the next [i] can still be validated
                            if isinstance(proper_item, TupleType):
                                new_ret = Instance(
                                    self_type.type,
                                    [model_instance, proper_item],
                                )
                                return sig.copy_modified(ret_type=new_ret)
                            # Leaf-type element: preserve proper_item as pending
                            # so the attr hook can emit a context-lost error on
                            # any subsequent .attr chain.
                            return sig.copy_modified(
                                ret_type=Instance(
                                    self_type.type,
                                    [
                                        AnyType(TypeOfAny.implementation_artifact),
                                        proper_item,
                                    ],
                                )
                            )
                        else:
                            # Literal index is out of range for this fixed-length tuple.
                            ctx.api.fail(
                                f"tuple index {idx} is out of range "
                                f"(tuple has {n} element(s))",
                                ctx.context,
                            )
                            return sig.copy_modified(
                                ret_type=_make_modelpath_any(self_type.type)
                            )
                return sig.copy_modified(ret_type=_make_modelpath_any(self_type.type))
            if _has_any_indexable_branch(proper_pending):
                return sig.copy_modified(
                    ret_type=Instance(
                        self_type.type,
                        [AnyType(TypeOfAny.implementation_artifact), proper_pending],
                    )
                )
            ctx.api.fail("index applied to non-list type", ctx.context)
            return sig
        new_ret = Instance(self_type.type, [model_instance, raw_item])
        return sig.copy_modified(ret_type=new_ret)

    new_ret = Instance(
        self_type.type,
        [item_type, AnyType(TypeOfAny.implementation_artifact)],
    )
    return sig.copy_modified(ret_type=new_ret)


class ModelPathPlugin(Plugin):
    """Mypy plugin that validates _ModelPath field access at type-check time."""

    def get_attribute_hook(
        self, fullname: str
    ) -> Callable[[AttributeContext], Type] | None:
        if fullname.startswith(f"{_MODEL_PATH_FULLNAME}."):
            attr_name = fullname[len(_MODEL_PATH_FULLNAME) + 1 :]
            return lambda ctx: _hook_modelpath_attr(ctx, attr_name)
        return None

    def get_method_signature_hook(
        self, fullname: str
    ) -> Callable[[MethodSigContext], Any] | None:
        if fullname == f"{_MODEL_PATH_FULLNAME}.__getitem__":
            return _hook_getitem
        return None


def plugin(version: str) -> type[Plugin]:
    return ModelPathPlugin

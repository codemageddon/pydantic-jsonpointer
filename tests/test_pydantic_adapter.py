"""Tests for FieldResolver Protocol and the three shipped resolvers.

Covers ByAttribute, BySerializationAlias, and ByValidationAlias against
shared _Plain (no aliases) and _Aliased (alias + AliasChoices validation_alias
+ serialization_alias) BaseModel fixtures.
"""

from __future__ import annotations

import pytest
from pydantic import AliasChoices, AliasPath, BaseModel, ConfigDict, Field

from pydantic_jsonpointer.pydantic_adapter import (
    ByAttribute,
    BySerializationAlias,
    ByValidationAlias,
    FieldResolver,
)


class _Plain(BaseModel):
    name: str = "alice"


class _Aliased(BaseModel):
    user_name: str = Field(
        alias="userName",
        validation_alias=AliasChoices("userName", "user-name"),
        serialization_alias="user.name",
        default="alice",
    )


# ---------- FieldResolver Protocol ----------------------------------------


@pytest.mark.parametrize(
    "resolver",
    [ByAttribute(), BySerializationAlias(), ByValidationAlias()],
)
def test_resolvers_implement_protocol(resolver: FieldResolver) -> None:
    assert isinstance(resolver, FieldResolver)


# ---------- ByAttribute ---------------------------------------------------


def test_by_attribute_plain_field() -> None:
    r = ByAttribute()
    assert r.to_attr(_Plain, "name") == "name"
    assert r.to_token(_Plain, "name") == "name"


def test_by_attribute_no_match_on_plain() -> None:
    r = ByAttribute()
    assert r.to_attr(_Plain, "userName") is None
    assert r.to_attr(_Plain, "user-name") is None


def test_by_attribute_aliased_only_matches_attr_name() -> None:
    r = ByAttribute()
    assert r.to_attr(_Aliased, "user_name") == "user_name"
    assert r.to_attr(_Aliased, "userName") is None  # alias ignored
    assert r.to_attr(_Aliased, "user-name") is None  # validation alias ignored
    assert r.to_attr(_Aliased, "user.name") is None  # serialization_alias ignored
    assert r.to_token(_Aliased, "user_name") == "user_name"


# ---------- BySerializationAlias ------------------------------------------


def test_by_serialization_alias_plain_field() -> None:
    r = BySerializationAlias()
    assert r.to_attr(_Plain, "name") == "name"
    assert r.to_token(_Plain, "name") == "name"


def test_by_serialization_alias_prefers_serialization_alias() -> None:
    r = BySerializationAlias()
    # Field has serialization_alias="user.name", alias="userName",
    # validation_alias=AliasChoices("userName","user-name"). Resolver should
    # match the serialization alias.
    assert r.to_attr(_Aliased, "user.name") == "user_name"
    assert r.to_token(_Aliased, "user_name") == "user.name"


def test_by_serialization_alias_falls_back_to_plain_alias() -> None:
    class _OnlyAlias(BaseModel):
        x: str = Field(alias="X", default="")

    r = BySerializationAlias()
    assert r.to_attr(_OnlyAlias, "X") == "x"
    assert r.to_token(_OnlyAlias, "x") == "X"


def test_by_serialization_alias_falls_back_to_attr_when_no_aliases() -> None:
    class _NoAliases(BaseModel):
        y: int = 0

    r = BySerializationAlias()
    assert r.to_attr(_NoAliases, "y") == "y"
    assert r.to_token(_NoAliases, "y") == "y"


def test_by_serialization_alias_does_not_match_attr_when_alias_exists() -> None:
    r = BySerializationAlias()
    # _Aliased has serialization_alias="user.name", so plain attr name should
    # NOT match.
    assert r.to_attr(_Aliased, "user_name") is None
    # ...nor the plain `alias`/validation_alias choices.
    assert r.to_attr(_Aliased, "userName") is None
    assert r.to_attr(_Aliased, "user-name") is None


def test_by_serialization_alias_returns_none_for_unknown_token() -> None:
    r = BySerializationAlias()
    assert r.to_attr(_Plain, "unknown") is None


# ---------- ByValidationAlias ---------------------------------------------


def test_by_validation_alias_plain_field() -> None:
    r = ByValidationAlias()
    assert r.to_attr(_Plain, "name") == "name"
    assert r.to_token(_Plain, "name") == "name"


def test_by_validation_alias_matches_any_choice() -> None:
    r = ByValidationAlias()
    # _Aliased.validation_alias = AliasChoices("userName", "user-name")
    assert r.to_attr(_Aliased, "userName") == "user_name"
    assert r.to_attr(_Aliased, "user-name") == "user_name"
    # serialization-only alias is NOT matched.
    assert r.to_attr(_Aliased, "user.name") is None
    # plain attr name is masked because a validation_alias is set.
    assert r.to_attr(_Aliased, "user_name") is None


def test_by_validation_alias_falls_back_to_alias_then_name() -> None:
    class _Mixed(BaseModel):
        a: str = Field(alias="A", default="")  # no validation_alias
        b: str = Field(default="")  # no aliases at all

    r = ByValidationAlias()
    assert r.to_attr(_Mixed, "A") == "a"
    assert r.to_attr(_Mixed, "b") == "b"
    # plain attr "a" is masked because alias is set
    assert r.to_attr(_Mixed, "a") is None
    # token "B" is unknown
    assert r.to_attr(_Mixed, "B") is None


def test_by_validation_alias_to_token_uses_first_choice() -> None:
    r = ByValidationAlias()
    # AliasChoices("userName","user-name") -> first choice "userName"
    assert r.to_token(_Aliased, "user_name") == "userName"


def test_by_validation_alias_to_token_no_validation_alias() -> None:
    class _OnlyAlias(BaseModel):
        x: str = Field(alias="X", default="")

    r = ByValidationAlias()
    assert r.to_token(_OnlyAlias, "x") == "X"


def test_by_validation_alias_handles_alias_path() -> None:
    class _PathModel(BaseModel):
        x: str = Field(validation_alias=AliasPath("outer", "inner"), default="")

    r = ByValidationAlias()
    # First component of the AliasPath is the top-level key.
    assert r.to_attr(_PathModel, "outer") == "x"
    assert r.to_attr(_PathModel, "inner") is None
    assert r.to_token(_PathModel, "x") == "outer"


def test_by_validation_alias_handles_choices_with_alias_paths() -> None:
    class _Mixed(BaseModel):
        x: str = Field(
            validation_alias=AliasChoices("alpha", AliasPath("beta", "gamma")),
            default="",
        )

    r = ByValidationAlias()
    assert r.to_attr(_Mixed, "alpha") == "x"
    assert r.to_attr(_Mixed, "beta") == "x"
    assert r.to_attr(_Mixed, "gamma") is None  # only the first component matters
    assert r.to_token(_Mixed, "x") == "alpha"


def test_by_validation_alias_plain_string_validation_alias() -> None:
    class _StrVA(BaseModel):
        x: str = Field(validation_alias="X", default="")

    r = ByValidationAlias()
    assert r.to_attr(_StrVA, "X") == "x"
    assert r.to_token(_StrVA, "x") == "X"


# ---------- BaseModelAdapter ----------------------------------------------

from typing import Optional  # noqa: E402

from pydantic import RootModel  # noqa: E402

from pydantic_jsonpointer.errors import (  # noqa: E402
    InvalidTokenError,
    PointerNotFoundError,
)
from pydantic_jsonpointer.pydantic_adapter import BaseModelAdapter  # noqa: E402


class _Doc(BaseModel):
    name: str = "alice"
    age: int = 30


def test_basemodel_resolve_token_default_is_serialization_alias() -> None:
    a = BaseModelAdapter()
    # Plain field: serialization-alias resolver falls back to attribute name.
    assert a.resolve_token(_Doc(), "name") == "name"
    # Aliased field: must address it via serialization_alias.
    assert a.resolve_token(_Aliased(), "user.name") == "user_name"


def test_basemodel_resolve_token_unknown_field_raises() -> None:
    a = BaseModelAdapter()
    with pytest.raises(InvalidTokenError):
        a.resolve_token(_Doc(), "missing")


def test_basemodel_resolve_token_with_aliased_model_rejects_attr_under_default() -> None:
    a = BaseModelAdapter()
    # Default resolver is BySerializationAlias, so the attribute name is
    # not a valid token for an aliased field.
    with pytest.raises(InvalidTokenError):
        a.resolve_token(_Aliased(), "user_name")


def test_basemodel_resolve_token_with_custom_resolver() -> None:
    a = BaseModelAdapter(resolver=ByAttribute())
    assert a.resolve_token(_Aliased(), "user_name") == "user_name"
    with pytest.raises(InvalidTokenError):
        a.resolve_token(_Aliased(), "user.name")


def test_basemodel_resolve_token_with_validation_resolver() -> None:
    a = BaseModelAdapter(resolver=ByValidationAlias())
    assert a.resolve_token(_Aliased(), "userName") == "user_name"
    assert a.resolve_token(_Aliased(), "user-name") == "user_name"
    with pytest.raises(InvalidTokenError):
        a.resolve_token(_Aliased(), "user.name")


def test_basemodel_has_returns_true_for_known_field() -> None:
    a = BaseModelAdapter()
    doc = _Doc()
    assert a.has(doc, "name") is True
    assert a.has(doc, "age") is True


def test_basemodel_has_returns_false_for_unknown_field() -> None:
    a = BaseModelAdapter()
    assert a.has(_Doc(), "missing") is False


def test_basemodel_get_returns_field_value() -> None:
    a = BaseModelAdapter()
    doc = _Doc(name="bob", age=42)
    assert a.get(doc, "name") == "bob"
    assert a.get(doc, "age") == 42


def test_basemodel_get_unknown_field_raises_pointer_not_found() -> None:
    a = BaseModelAdapter()
    with pytest.raises(PointerNotFoundError):
        a.get(_Doc(), "missing")


def test_basemodel_set_replaces_field() -> None:
    a = BaseModelAdapter()
    doc = _Doc()
    a.set(doc, "name", "charlie")
    assert doc.name == "charlie"


def test_basemodel_set_unknown_field_raises_pointer_not_found() -> None:
    a = BaseModelAdapter()
    with pytest.raises(PointerNotFoundError):
        a.set(_Doc(), "missing", "x")


def test_basemodel_set_aliased_field_via_attr_name() -> None:
    # Adapter's set takes the resolved attribute name (post resolve_token),
    # not the raw token, so even an aliased model's field is mutated by attr.
    a = BaseModelAdapter()
    doc = _Aliased()
    a.set(doc, "user_name", "bob")
    assert doc.user_name == "bob"


def test_basemodel_add_is_equivalent_to_set() -> None:
    a = BaseModelAdapter()
    doc = _Doc()
    a.add(doc, "name", "charlie")
    assert doc.name == "charlie"


def test_basemodel_add_unknown_field_raises_pointer_not_found() -> None:
    a = BaseModelAdapter()
    with pytest.raises(PointerNotFoundError):
        a.add(_Doc(), "missing", "x")


class _Removable(BaseModel):
    optional_old: Optional[str] = "default"  # via Optional[]
    optional_new: str | None = "default"  # PEP 604 union
    required: str = "required"


@pytest.mark.parametrize(
    "field_name",
    ["optional_old", "optional_new"],
)
def test_basemodel_remove_optional_field_returns_previous_and_sets_none(
    field_name: str,
) -> None:
    a = BaseModelAdapter()
    doc = _Removable(**{field_name: "x"})
    assert a.remove(doc, field_name) == "x"
    assert getattr(doc, field_name) is None


def test_basemodel_remove_non_optional_raises_invalid_token_with_message() -> None:
    a = BaseModelAdapter()
    doc = _Removable()
    with pytest.raises(InvalidTokenError, match="non-Optional"):
        a.remove(doc, "required")
    assert doc.required == "required"  # untouched


def test_basemodel_remove_unknown_field_raises_pointer_not_found() -> None:
    a = BaseModelAdapter()
    with pytest.raises(PointerNotFoundError):
        a.remove(_Removable(), "missing")


def test_basemodel_unwrap_rootmodel_returns_inner() -> None:
    class _WrapList(RootModel[list[int]]):
        pass

    a = BaseModelAdapter()
    rm = _WrapList([1, 2, 3])
    assert a.unwrap(rm) == [1, 2, 3]


def test_basemodel_unwrap_rootmodel_dict() -> None:
    class _WrapDict(RootModel[dict[str, int]]):
        pass

    a = BaseModelAdapter()
    rm = _WrapDict({"a": 1, "b": 2})
    assert a.unwrap(rm) == {"a": 1, "b": 2}


def test_basemodel_unwrap_plain_model_returns_sentinel() -> None:
    a = BaseModelAdapter()
    assert a.unwrap(_Doc()) is ...


def test_basemodel_is_step_frozen_false_for_ordinary_field() -> None:
    a = BaseModelAdapter()
    assert a.is_step_frozen(_Doc(), "name") is False
    assert a.is_step_frozen(_Doc(), "age") is False


class _FrozenField(BaseModel):
    locked: str = Field(default="immutable", frozen=True)
    free: str = "mutable"


class _FrozenWhole(BaseModel):
    model_config = ConfigDict(frozen=True)
    x: int = 1
    y: int = 2


def test_basemodel_is_step_frozen_for_frozen_field() -> None:
    a = BaseModelAdapter()
    doc = _FrozenField()
    assert a.is_step_frozen(doc, "locked") is True
    assert a.is_step_frozen(doc, "free") is False


def test_basemodel_is_step_frozen_for_whole_frozen_model() -> None:
    a = BaseModelAdapter()
    doc = _FrozenWhole()
    assert a.is_step_frozen(doc, "x") is True
    assert a.is_step_frozen(doc, "y") is True


def test_basemodel_is_step_frozen_unknown_field_returns_false() -> None:
    # Defensive: walker only calls is_step_frozen after resolve_token, but the
    # method itself must not error on an unknown key.
    a = BaseModelAdapter()
    assert a.is_step_frozen(_Doc(), "missing") is False


def test_basemodel_is_value_frozen_false_for_plain_model() -> None:
    a = BaseModelAdapter()
    assert a.is_value_frozen(_Doc()) is False


def test_basemodel_is_value_frozen_for_whole_frozen_model() -> None:
    a = BaseModelAdapter()
    assert a.is_value_frozen(_FrozenWhole()) is True


def test_basemodel_is_value_frozen_for_rootmodel_with_frozen_root_field() -> None:
    # ``Field(frozen=True)`` on a RootModel's ``root`` field is the only frozen
    # binding the unwrap chain ever sees — the walker descends straight through
    # ``.root`` without a token step, so this must be surfaced as a whole-value
    # freeze for the taint to propagate into the unwrapped payload.
    class _FrozenRootField(RootModel[list[int]]):
        root: list[int] = Field(frozen=True)

    a = BaseModelAdapter()
    assert a.is_value_frozen(_FrozenRootField([1, 2, 3])) is True


def test_basemodel_is_value_frozen_false_for_rootmodel_without_frozen_root() -> None:
    class _OpenRoot(RootModel[list[int]]):
        pass

    a = BaseModelAdapter()
    assert a.is_value_frozen(_OpenRoot([1, 2, 3])) is False


# ---------- model_construct: partially-built instances --------------------


class _ConstructDoc(BaseModel):
    x: int
    y: int = 7


def test_basemodel_has_false_for_unset_field_on_model_construct() -> None:
    # ``model_construct()`` may skip required fields without defaults; the
    # adapter must report ``has == False`` for them so ``has``/``get`` agree.
    a = BaseModelAdapter()
    doc = _ConstructDoc.model_construct()
    assert a.has(doc, "x") is False
    # Field with default is populated by model_construct, so still has.
    assert a.has(doc, "y") is True


def test_basemodel_get_unset_field_raises_pointer_not_found_not_attribute_error() -> None:
    a = BaseModelAdapter()
    doc = _ConstructDoc.model_construct()
    with pytest.raises(PointerNotFoundError, match="not set on this instance"):
        a.get(doc, "x")


class _RemovableUnset(BaseModel):
    optional_unset: Optional[str]


def test_basemodel_remove_unset_optional_field_raises_pointer_not_found() -> None:
    # model_construct on an Optional[str] field with no default leaves it
    # missing from the instance dict. remove() must surface that as
    # PointerNotFoundError rather than leaking AttributeError.
    a = BaseModelAdapter()
    doc = _RemovableUnset.model_construct()
    with pytest.raises(PointerNotFoundError, match="not set on this instance"):
        a.remove(doc, "optional_unset")


def test_basemodel_set_unset_field_raises_pointer_not_found() -> None:
    # set() implements JSON-Patch ``replace`` semantics: it requires the slot
    # to already hold a value. ``model_construct()`` leaves required fields
    # without a defined value on the instance, so set() must refuse rather
    # than silently materialize the field — that's add()'s job.
    a = BaseModelAdapter()
    doc = _ConstructDoc.model_construct()
    with pytest.raises(PointerNotFoundError, match="not set on this instance"):
        a.set(doc, "x", 99)
    assert not hasattr(doc, "x")  # untouched


def test_basemodel_add_materializes_unset_field() -> None:
    # add() is create-or-replace: it does materialize a field declared on the
    # model that ``model_construct()`` left unset, since the schema is fixed.
    a = BaseModelAdapter()
    doc = _ConstructDoc.model_construct()
    a.add(doc, "x", 99)
    assert doc.x == 99


import typing  # noqa: E402


@pytest.mark.skipif(
    not hasattr(typing, "TypeAliasType"),
    reason="PEP 695 TypeAliasType requires Python 3.12+",
)
def test_basemodel_remove_through_pep695_type_alias() -> None:
    # PEP 695 ``type Foo = X | None`` produces a ``TypeAliasType`` whose
    # ``typing.get_origin`` returns ``None`` — the naive Union/UnionType check
    # would wrongly reject ``None`` as outside the field's annotation. Verify
    # the unwrap to ``__value__`` recovers the underlying Union.
    MaybeStr = typing.TypeAliasType("MaybeStr", str | None)

    class M(BaseModel):
        x: MaybeStr = "hi"
    a = BaseModelAdapter()
    m = M(x="hi")
    assert a.remove(m, "x") == "hi"
    assert m.x is None


@pytest.mark.skipif(
    not hasattr(typing, "TypeAliasType"),
    reason="PEP 695 TypeAliasType requires Python 3.12+",
)
def test_basemodel_remove_pep695_alias_without_none_still_refuses() -> None:
    # Sanity check: a PEP 695 alias whose value does NOT include None must
    # still raise InvalidTokenError on remove.
    NeverNull = typing.TypeAliasType("NeverNull", str)

    class M(BaseModel):
        x: NeverNull = "hi"
    a = BaseModelAdapter()
    m = M(x="hi")
    with pytest.raises(InvalidTokenError, match="non-Optional"):
        a.remove(m, "x")

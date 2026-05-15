from __future__ import annotations

import sys
import typing as _typing

import pytest
from pydantic import BaseModel
from pydantic import Field as _Field
from pydantic import RootModel as _RootModel

from pydantic_jsonpointer import JsonPointer, pointer_from_model
from pydantic_jsonpointer._model_path import (
    _advance,
    _advance_attr,
    _advance_index,
    _ModelPath,
)
from pydantic_jsonpointer.pydantic_adapter import (
    BySerializationAlias,
    ByValidationAlias,
)


class _LeafModel(BaseModel):
    name: str
    count: int


class _ItemModel(BaseModel):
    label: str


class _TagList(_RootModel[list[_ItemModel]]):
    pass


class _DoubleWrap(_RootModel[_TagList]):
    pass


class _User(BaseModel):
    name: str


class _Address(BaseModel):
    city: str


class _Profile(BaseModel):
    address: _Address


def test_advance_attr_leaf_returns_none() -> None:
    assert _advance(str, for_index=False) is None
    assert _advance(int, for_index=False) is None
    assert _advance(float, for_index=False) is None
    assert _advance(bool, for_index=False) is None


def test_advance_attr_basemodel_returns_model() -> None:
    assert _advance(_LeafModel, for_index=False) is _LeafModel


def test_advance_attr_optional_basemodel_returns_model() -> None:
    assert _advance(_LeafModel | None, for_index=False) is _LeafModel


def test_advance_attr_union_ambiguous_returns_none() -> None:
    class _A(BaseModel):
        x: str

    class _B(BaseModel):
        y: str

    assert _advance(_A | _B, for_index=False) is None
    assert _advance(_typing.Union[_A, _B], for_index=False) is None


def test_advance_attr_list_returns_none() -> None:
    assert _advance(list[_LeafModel], for_index=False) is None


def test_advance_attr_rootmodel_parameterized_returns_none() -> None:
    assert _advance(_RootModel[list[int]], for_index=False) is None


def test_advance_attr_annotated_peels_wrapper() -> None:
    from typing import Annotated as _A

    assert _advance(_A[_LeafModel, "meta"], for_index=False) is _LeafModel
    assert _advance(_A[str, "meta"], for_index=False) is None


def test_advance_index_list_extracts_item() -> None:
    assert _advance(list[_LeafModel], for_index=True, index=0) is _LeafModel
    assert _advance(list[int], for_index=True, index=0) is None


def test_advance_index_list_dash_loses_context() -> None:
    # index=None is the "-" tail sentinel: model context must be lost for lists
    # so chains like items["-"].city cannot silently generate impossible pointers.
    assert _advance(list[_LeafModel], for_index=True, index=None) is None


def test_advance_index_rootmodel_wrapping_list() -> None:
    assert _advance(_RootModel[list[_LeafModel]], for_index=True, index=0) is _LeafModel


def test_advance_index_double_rootmodel() -> None:
    assert (
        _advance(_RootModel[_RootModel[list[_LeafModel]]], for_index=True, index=0)
        is _LeafModel
    )


def test_advance_index_leaf_returns_none() -> None:
    assert _advance(str, for_index=True) is None
    assert _advance(int, for_index=True) is None


def test_advance_index_basemodel_returns_none() -> None:
    assert _advance(_LeafModel, for_index=True) is None


def test_advance_index_annotated_list() -> None:
    from typing import Annotated as _A

    assert _advance(_A[list[_LeafModel], "meta"], for_index=True, index=0) is _LeafModel


def test_advance_index_optional_list() -> None:
    assert _advance(list[_LeafModel] | None, for_index=True, index=0) is _LeafModel


def test_advance_index_dict_ignored() -> None:
    assert _advance(dict[str, _LeafModel], for_index=True) is None


def test_advance_index_set_not_indexable() -> None:
    # set/frozenset are unordered and not RFC 6901 indexable — _advance returns None.
    assert _advance(set[_LeafModel], for_index=True) is None


def test_advance_index_frozenset_not_indexable() -> None:
    assert _advance(frozenset[_LeafModel], for_index=True) is None


def test_advance_index_tuple_homogeneous() -> None:
    # With a concrete integer index, homogeneous tuple advances to the item type.
    assert _advance(tuple[_LeafModel, ...], for_index=True, index=5) is _LeafModel
    # Without an integer index (i.e. the "-" token): tuples reject "-", so return None.
    assert _advance(tuple[_LeafModel, ...], for_index=True) is None


def test_advance_index_tuple_heterogeneous() -> None:
    # Fixed-length tuple[A, B] → requires a concrete index; without one, returns None
    assert _advance(tuple[_LeafModel, str], for_index=True) is None
    assert _advance(tuple[_LeafModel, str], for_index=True, index=0) is _LeafModel
    assert _advance(tuple[_LeafModel, str], for_index=True, index=1) is None  # str
    assert _advance(tuple[int, str], for_index=True) is None
    assert (
        _advance(tuple[int, str], for_index=True, index=0) is None
    )  # int not BaseModel
    # out of range
    assert _advance(tuple[_LeafModel, str], for_index=True, index=5) is None


def test_advance_attr_wrapper() -> None:
    assert _advance_attr(_LeafModel) is _LeafModel
    assert _advance_attr(str) is None


def test_advance_index_wrapper() -> None:
    assert _advance_index(list[_LeafModel], index=0) is _LeafModel
    assert _advance_index(str) is None


def test_modelpath_build_returns_jsonpointer() -> None:
    mp = _ModelPath(_model_cls=_User, _resolver=BySerializationAlias())
    result = mp.build()
    from pydantic_jsonpointer import JsonPointer as _JP

    assert isinstance(result, _JP)
    assert str(result) == ""
    assert result.tokens == ()


def test_modelpath_str_delegates_to_build() -> None:
    mp = _ModelPath(_model_cls=_User, _resolver=BySerializationAlias())
    assert str(mp) == ""


def test_modelpath_build_with_tokens() -> None:
    mp = _ModelPath(
        _model_cls=_User,
        _tokens=("name",),
        _resolver=BySerializationAlias(),
    )
    result = mp.build()
    assert str(result) == "/name"
    assert result.tokens == ("name",)


def test_modelpath_getattr_basic() -> None:
    mp = _ModelPath(_model_cls=_User, _resolver=BySerializationAlias()).name
    result = mp.build()
    assert str(result) == "/name"
    assert result.tokens == ("name",)


def test_modelpath_getattr_chained() -> None:
    mp = _ModelPath(_model_cls=_Profile, _resolver=BySerializationAlias()).address.city
    result = mp.build()
    assert str(result) == "/address/city"
    assert result.tokens == ("address", "city")


def test_modelpath_getattr_advances_model_for_nested() -> None:
    mp = _ModelPath(_model_cls=_Profile, _resolver=BySerializationAlias()).address
    assert mp._model_cls is _Address
    assert mp._pending_annotation is _Address


def test_modelpath_getattr_unknown_field_raises_attributeerror() -> None:
    with pytest.raises(AttributeError):
        _ = _ModelPath(_model_cls=_User, _resolver=BySerializationAlias()).typo


def test_modelpath_getattr_leaf_field_does_not_advance() -> None:
    mp = _ModelPath(_model_cls=_User, _resolver=BySerializationAlias()).name
    assert mp._model_cls is _User
    assert mp._pending_annotation is str
    assert mp._model_ctx_lost is True


def test_modelpath_getattr_list_field_does_not_advance() -> None:
    class _Order(BaseModel):
        items: list[_Address]

    mp = _ModelPath(_model_cls=_Order, _resolver=BySerializationAlias()).items
    assert mp._model_cls is _Order
    assert mp._model_ctx_lost is True


def test_modelpath_getitem_basic() -> None:
    class _Order(BaseModel):
        items: list[_Address]

    mp = _ModelPath(_model_cls=_Order, _resolver=BySerializationAlias()).items[0]
    result = mp.build()
    assert str(result) == "/items/0"
    assert result.tokens == ("items", "0")


def test_modelpath_getitem_advances_to_item_type() -> None:
    class _Order(BaseModel):
        items: list[_Address]

    mp = _ModelPath(_model_cls=_Order, _resolver=BySerializationAlias()).items[0]
    assert mp._model_cls is _Address


def test_modelpath_getitem_chained_with_attr() -> None:
    class _Order(BaseModel):
        items: list[_Address]

    mp = _ModelPath(_model_cls=_Order, _resolver=BySerializationAlias()).items[0].city
    result = mp.build()
    assert str(result) == "/items/0/city"
    assert result.tokens == ("items", "0", "city")


def test_modelpath_getitem_other_ints() -> None:
    class _Order(BaseModel):
        items: list[_Address]

    mp = _ModelPath(_model_cls=_Order, _resolver=BySerializationAlias()).items[42]
    assert str(mp) == "/items/42"


def test_modelpath_getitem_on_non_container() -> None:
    mp = _ModelPath(_model_cls=_User, _resolver=BySerializationAlias()).name[0]
    assert str(mp) == "/name/0"
    assert mp._model_cls is _User
    assert mp._model_ctx_lost is True


def test_modelpath_getitem_rootmodel_field() -> None:
    class _Holder(BaseModel):
        tags: _TagList

    mp = _ModelPath(_model_cls=_Holder, _resolver=BySerializationAlias()).tags[0].label
    result = mp.build()
    assert str(result) == "/tags/0/label"
    assert result.tokens == ("tags", "0", "label")


def test_modelpath_truediv_appends_raw_tokens() -> None:
    mp = _ModelPath(_model_cls=_User, _resolver=BySerializationAlias())
    result = mp / "extra" / "0"
    from pydantic_jsonpointer import JsonPointer as _JP

    assert isinstance(result, _JP)
    assert str(result) == "/extra/0"


def test_modelpath_truediv_after_attr() -> None:
    class _Order(BaseModel):
        items: list[_Address]

    mp = _ModelPath(_model_cls=_Order, _resolver=BySerializationAlias()).items
    result = mp / "3" / "name"
    assert isinstance(result, JsonPointer)
    assert str(result) == "/items/3/name"
    assert result.tokens == ("items", "3", "name")


def test_from_model_class_basic() -> None:
    ptr = pointer_from_model(_User).name
    assert isinstance(ptr, _ModelPath)
    assert str(ptr) == "/name"


def test_from_model_class_nested() -> None:
    ptr = pointer_from_model(_Profile).address.city
    assert str(ptr) == "/address/city"


def test_from_model_class_empty_chain() -> None:
    ptr = pointer_from_model(_User).build()
    assert str(ptr) == ""


def test_from_model_instance_entry() -> None:
    user = _User(name="alice")
    ptr = pointer_from_model(user).name
    assert str(ptr) == "/name"


def test_from_model_instance_class_and_instance_produce_same_pointer() -> None:
    user = _User(name="alice")
    assert str(pointer_from_model(_User).name) == str(pointer_from_model(user).name)


def test_from_model_with_explicit_resolver() -> None:
    from pydantic_jsonpointer import ByAttribute

    class _AliasedUser(BaseModel):
        user_name: str = _Field(alias="userName")

    ptr = pointer_from_model(_AliasedUser, resolver=ByAttribute()).user_name
    assert str(ptr) == "/user_name"


def test_from_model_default_resolver_uses_serialization_alias() -> None:
    class _AliasedUser(BaseModel):
        user_name: str = _Field(serialization_alias="userName")

    ptr = pointer_from_model(_AliasedUser).user_name
    assert str(ptr) == "/userName"


def test_from_model_rootmodel_entry() -> None:
    ptr = pointer_from_model(_TagList)[0].label
    assert str(ptr) == "/0/label"


def test_from_model_double_rootmodel_entry() -> None:
    ptr = pointer_from_model(_DoubleWrap)[0].label
    assert str(ptr) == "/0/label"


def test_from_model_list_field_with_index() -> None:
    class _Order(BaseModel):
        items: list[_Address]

    ptr = pointer_from_model(_Order).items[0].city
    assert str(ptr) == "/items/0/city"


def test_from_model_rootmodel_field() -> None:
    class _Holder(BaseModel):
        tags: _TagList

    ptr = pointer_from_model(_Holder).tags[0].label
    assert str(ptr) == "/tags/0/label"


def test_from_model_union_disambiguation_with_instance() -> None:
    class _JsonBody(BaseModel):
        body: str

    class _XmlBody(BaseModel):
        root: str

    class _Event(BaseModel):
        payload: _JsonBody | _XmlBody

    event = _Event(payload=_JsonBody(body="hello"))
    assert isinstance(event.payload, _JsonBody)
    ptr = pointer_from_model(event.payload).body
    assert str(ptr) == "/body"


def test_from_model_union_disambiguation_with_instance_and_index() -> None:
    class _Other(BaseModel):
        data: str

    class _Event(BaseModel):
        payload: _TagList | _Other

    event = _Event(payload=_TagList([_ItemModel(label="x")]))
    assert isinstance(event.payload, _TagList)
    ptr = pointer_from_model(event.payload)[0].label
    assert str(ptr) == "/0/label"


def test_from_model_union_ambiguous_without_instance() -> None:
    class _JsonBody(BaseModel):
        body: str

    class _XmlBody(BaseModel):
        root: str

    class _Event(BaseModel):
        payload: _JsonBody | _XmlBody

    ptr = pointer_from_model(_Event).payload
    assert str(ptr) == "/payload"

    with pytest.raises(AttributeError):
        pointer_from_model(_Event).payload.body


def test_from_model_instance_preserved_after_index() -> None:
    class _JsonBody(BaseModel):
        body: str

    class _Event(BaseModel):
        payloads: list[_JsonBody]

    event = _Event(payloads=[_JsonBody(body="x")])
    ptr = pointer_from_model(event).payloads[0].body
    assert str(ptr) == "/payloads/0/body"


def test_from_model_union_disambiguation_after_index() -> None:
    class _JsonBody(BaseModel):
        body: str

    class _XmlBody(BaseModel):
        xml_root: str

    class _Event(BaseModel):
        payloads: list[_JsonBody | _XmlBody]

    event = _Event(payloads=[_JsonBody(body="x"), _XmlBody(xml_root="y")])
    assert isinstance(event.payloads[0], _JsonBody)
    assert isinstance(event.payloads[1], _XmlBody)
    ptr0 = pointer_from_model(event.payloads[0]).body
    assert str(ptr0) == "/body"
    ptr1 = pointer_from_model(event.payloads[1]).xml_root
    assert str(ptr1) == "/xml_root"


def test_from_model_instance_pass_through_non_union() -> None:
    class _Inner(BaseModel):
        thing: str

    class _Outer(BaseModel):
        inner: _Inner

    outer = _Outer(inner=_Inner(thing="hi"))
    ptr = pointer_from_model(outer).inner.thing
    assert str(ptr) == "/inner/thing"


def test_from_model_with_validation_alias_resolver() -> None:
    class _AliasedUser(BaseModel):
        user_name: str = _Field(validation_alias="userName")

    ptr = pointer_from_model(_AliasedUser, resolver=ByValidationAlias()).user_name
    assert str(ptr) == "/userName"


def test_from_model_resolver_threads_through_nested_models() -> None:
    class _Inner(BaseModel):
        inner_field: str = _Field(serialization_alias="innerAlias")

    class _Outer(BaseModel):
        outer_field: _Inner = _Field(serialization_alias="outerAlias")

    from pydantic_jsonpointer import ByAttribute

    ptr = pointer_from_model(_Outer, resolver=ByAttribute()).outer_field.inner_field
    assert str(ptr) == "/outer_field/inner_field"


def test_from_model_rejects_non_basemodel() -> None:
    with pytest.raises(TypeError):
        pointer_from_model(str)  # type: ignore[type-var]

    with pytest.raises(TypeError):
        pointer_from_model(123)  # type: ignore[call-overload]


def test_from_model_annotated_union_disambiguation() -> None:
    from typing import Annotated as _A
    from typing import Literal as _L

    class _Cat(BaseModel):
        pet_type: _L["cat"] = "cat"
        meows: int

    class _Dog(BaseModel):
        pet_type: _L["dog"] = "dog"
        barks: int

    class _Owner(BaseModel):
        pet: _A[_Cat | _Dog, _Field(discriminator="pet_type")]

    owner = _Owner(pet=_Cat(meows=3))
    assert isinstance(owner.pet, _Cat)
    ptr = pointer_from_model(owner.pet).meows
    assert str(ptr) == "/meows"


def test_from_model_optional_nested() -> None:
    class _Inner(BaseModel):
        thing: str

    class _Outer(BaseModel):
        opt_inner: _Inner | None = None

    outer = _Outer(opt_inner=_Inner(thing="hi"))
    ptr = pointer_from_model(outer).opt_inner.thing
    assert str(ptr) == "/opt_inner/thing"


def test_from_model_literal_field_does_not_crash() -> None:
    from typing import Literal as _L

    class _Status(BaseModel):
        state: _L["active", "inactive"]

    ptr = pointer_from_model(_Status).state
    assert str(ptr) == "/state"


def test_advance_depth_guard_self_referential_rootmodel() -> None:
    from pydantic_jsonpointer.errors import PointerError

    class _SelfRef(_RootModel["_SelfRef"]):
        pass

    with pytest.raises(PointerError, match="depth exceeded"):
        _advance(_SelfRef, for_index=True)


def test_modelpath_getitem_rejects_leading_zero_string() -> None:
    class _Order(BaseModel):
        items: list[_Address]

    mp = _ModelPath(_model_cls=_Order, _resolver=BySerializationAlias()).items
    with pytest.raises(ValueError, match="invalid array token"):
        mp["00"]


def test_modelpath_getitem_rejects_non_digit_string() -> None:
    class _Order(BaseModel):
        items: list[_Address]

    mp = _ModelPath(_model_cls=_Order, _resolver=BySerializationAlias()).items
    with pytest.raises(ValueError, match="invalid array token"):
        mp["abc"]


def test_modelpath_getitem_accepts_dash_token() -> None:
    """'-' is valid as a terminal add-position token; build() must work,
    but model context must be lost so further chaining raises AttributeError."""

    class _Order(BaseModel):
        items: list[_Address]

    mp = _ModelPath(_model_cls=_Order, _resolver=BySerializationAlias()).items["-"]
    assert str(mp) == "/items/-"
    assert mp._model_ctx_lost is True


def test_modelpath_getitem_dash_token_chaining_raises() -> None:
    """Chaining .attr after ['-'] on a list field must raise AttributeError.

    ['-'] is only valid as a terminal RFC 6901 add-position token; further
    traversal (e.g. items['-'].city) produces a pointer that can never be
    resolved at runtime, so the builder must reject it eagerly.
    """

    class _Order(BaseModel):
        items: list[_Address]

    base = _ModelPath(_model_cls=_Order, _resolver=BySerializationAlias()).items["-"]
    with pytest.raises(AttributeError, match="model type context was lost"):
        _ = base.city


def test_modelpath_getitem_dash_token_nested_list_chaining_raises() -> None:
    """rows['-'][0].name must raise: '-' on list[list[Item]] produces context loss
    that must propagate through the subsequent [0] step."""

    class _Item(BaseModel):
        name: str

    class _Grid(BaseModel):
        rows: list[list[_Item]]

    base = _ModelPath(_model_cls=_Grid, _resolver=BySerializationAlias()).rows["-"]
    assert base._model_ctx_lost is True
    with pytest.raises(AttributeError, match="model type context was lost"):
        _ = base.name
    # Context loss must propagate through a subsequent [i] step too.
    step = base[0]
    assert step._model_ctx_lost is True
    with pytest.raises(AttributeError, match="model type context was lost"):
        _ = step.name


def test_modelpath_getitem_accepts_string_digit_index() -> None:
    class _Order(BaseModel):
        items: list[_Address]

    mp = _ModelPath(_model_cls=_Order, _resolver=BySerializationAlias()).items["0"]
    assert str(mp) == "/items/0"
    mp2 = (
        _ModelPath(_model_cls=_Order, _resolver=BySerializationAlias()).items["0"].city
    )
    assert str(mp2) == "/items/0/city"


def test_modelpath_field_named_build_is_reachable() -> None:
    class _Widget(BaseModel):
        build: str
        version: int

    mp = _ModelPath(_model_cls=_Widget, _resolver=BySerializationAlias()).build
    assert isinstance(mp, _ModelPath)
    assert str(mp) == "/build"
    assert mp._tokens == ("build",)


def test_modelpath_build_method_still_callable_when_no_such_field() -> None:
    result = _ModelPath(
        _model_cls=_User,
        _tokens=("name",),
        _resolver=BySerializationAlias(),
    ).build()
    assert str(result) == "/name"


def test_from_model_leaf_chaining_raises_attributeerror() -> None:
    class _Flat(BaseModel):
        name: str
        city: str

    # .name is a leaf (str) — further chaining must raise even if the sibling
    # field exists on the same model class
    with pytest.raises(AttributeError, match="model type context was lost"):
        pointer_from_model(_Flat).name.city


def test_from_model_union_sibling_chaining_raises_attributeerror() -> None:
    class _A(BaseModel):
        x: str

    class _B(BaseModel):
        y: str

    class _Container(BaseModel):
        payload: _A | _B
        body: str

    # ambiguous union — should not bleed into sibling field 'body'
    with pytest.raises(AttributeError, match="model type context was lost"):
        pointer_from_model(_Container).payload.body


def test_from_model_rootmodel_union_disambiguation_attr_chain() -> None:
    class _Inner(BaseModel):
        field: str

    class _Wrap(_RootModel[_Inner]):
        pass

    class _OtherBranch(BaseModel):
        other: str

    class _Outer(BaseModel):
        payload: _Wrap | _OtherBranch

    event = _Outer(payload=_Wrap(_Inner(field="x")))
    assert isinstance(event.payload, _Wrap)
    ptr = pointer_from_model(event.payload).field
    assert str(ptr) == "/field"


def test_from_model_rootmodel_wrapping_basemodel_class_entry() -> None:
    class _Inner(BaseModel):
        field: str

    class _Wrap(_RootModel[_Inner]):
        pass

    ptr = pointer_from_model(_Wrap).field
    assert str(ptr) == "/field"
    assert ptr._tokens == ("field",)


def test_from_model_rootmodel_wrapping_basemodel_instance_entry() -> None:
    class _Inner(BaseModel):
        field: str

    class _Wrap(_RootModel[_Inner]):
        pass

    wrap = _Wrap(_Inner(field="hello"))
    ptr = pointer_from_model(wrap).field
    assert str(ptr) == "/field"


def test_from_model_rootmodel_nested_union_disambiguation() -> None:
    """Outer.wrapped: Wrap=RootModel[Inner], Inner.payload: A|B — instance must
    peel Wrap and then narrow the inner Union via isinstance."""

    class _JsonBody(BaseModel):
        body: str

    class _XmlBody(BaseModel):
        root: str

    class _Inner(BaseModel):
        payload: _JsonBody | _XmlBody

    class _Wrap(_RootModel[_Inner]):
        pass

    class _Outer(BaseModel):
        wrapped: _Wrap

    outer = _Outer(wrapped=_Wrap(_Inner(payload=_JsonBody(body="hi"))))
    inner = outer.wrapped.root
    assert isinstance(inner.payload, _JsonBody)
    ptr = pointer_from_model(inner.payload).body
    assert str(ptr) == "/body"


def test_from_model_double_rootmodel_instance_entry_union_disambiguation() -> None:
    """Double-nested RootModel at entry point: instance must peel both layers."""

    class _JsonBody(BaseModel):
        body: str

    class _XmlBody(BaseModel):
        root: str

    class _Inner(BaseModel):
        payload: _JsonBody | _XmlBody

    class _Wrap(_RootModel[_Inner]):
        pass

    class _DoubleWrap(_RootModel[_Wrap]):
        pass

    dw = _DoubleWrap(_Wrap(_Inner(payload=_JsonBody(body="hi"))))
    wrap = dw.root
    inner = wrap.root
    assert isinstance(inner.payload, _JsonBody)
    ptr = pointer_from_model(inner.payload).body
    assert str(ptr) == "/body"


def test_from_model_rootmodel_union_instance_entry_disambiguation() -> None:
    """RootModel[A | B] entry with an instance must use runtime root type."""

    class _JsonBody(BaseModel):
        body: str

    class _XmlBody(BaseModel):
        root_elem: str

    class _Wrap(_RootModel[_JsonBody | _XmlBody]):
        pass

    wrap = _Wrap(_JsonBody(body="hi"))
    assert isinstance(wrap.root, _JsonBody)
    ptr = pointer_from_model(wrap.root).body
    assert str(ptr) == "/body"


def test_modelpath_build_callable_via_call_when_build_is_field() -> None:
    class _Widget(BaseModel):
        build: str
        version: int

    mp = _ModelPath(_model_cls=_Widget, _resolver=BySerializationAlias())
    # .build navigates to the 'build' field; () invokes __call__ to finalize
    result = mp.build()
    assert isinstance(result, JsonPointer)
    assert str(result) == "/build"
    assert result.tokens == ("build",)


def test_modelpath_getitem_rejects_bool_index() -> None:
    class _Order(BaseModel):
        items: list[_Address]

    mp = _ModelPath(_model_cls=_Order, _resolver=BySerializationAlias()).items
    with pytest.raises(ValueError, match="not a valid RFC 6901 array token"):
        mp[True]
    with pytest.raises(ValueError, match="not a valid RFC 6901 array token"):
        mp[False]


def test_modelpath_getitem_rejects_negative_int() -> None:
    class _Order(BaseModel):
        items: list[_Address]

    mp = _ModelPath(_model_cls=_Order, _resolver=BySerializationAlias()).items
    with pytest.raises(ValueError, match="not a valid RFC 6901 array token"):
        mp[-1]


def test_modelpath_getitem_rejects_non_int_non_str() -> None:
    class _Order(BaseModel):
        items: list[_Address]

    mp = _ModelPath(_model_cls=_Order, _resolver=BySerializationAlias()).items
    with pytest.raises(TypeError, match="list index must be int or str"):
        mp[1.0]


def test_modelpath_getattr_raises_attributeerror_without_resolver() -> None:
    mp = _ModelPath(_model_cls=_User, _resolver=None)
    with pytest.raises(AttributeError, match="no resolver"):
        _ = mp.name


@pytest.mark.skipif(
    sys.version_info < (3, 12), reason="PEP 695 type aliases require Python 3.12+"
)
def test_advance_type_alias_attr() -> None:
    """_advance must unwrap a PEP 695 TypeAliasType to the underlying BaseModel."""
    import typing as _t

    _AliasedLeaf = _t.TypeAliasType("_AliasedLeaf", _LeafModel)
    assert _advance(_AliasedLeaf, for_index=False) is _LeafModel


@pytest.mark.skipif(
    sys.version_info < (3, 12), reason="PEP 695 type aliases require Python 3.12+"
)
def test_advance_type_alias_index() -> None:
    """_advance must unwrap a PEP 695 TypeAliasType wrapping list[Model]."""
    import typing as _t

    _AliasList = _t.TypeAliasType("_AliasList", list[_LeafModel])
    assert _advance(_AliasList, for_index=True, index=0) is _LeafModel


@pytest.mark.skipif(
    sys.version_info < (3, 12), reason="PEP 695 type aliases require Python 3.12+"
)
def test_from_model_type_alias_field() -> None:
    """pointer_from_model must chain through a field annotated with a PEP 695 type alias.

    Uses create_model() to inject the TypeAliasType directly into model_fields,
    bypassing Python 3.14 annotation-deferral (PEP 749) which would otherwise
    store a ForwardRef before Pydantic can see the TypeAliasType.
    """
    import typing as _t

    from pydantic import create_model as _create_model

    _AliasAddr = _t.TypeAliasType("_AliasAddr", _Address)
    _AliasHolder = _create_model("_AliasHolder", location=(_AliasAddr, ...))
    ptr = pointer_from_model(_AliasHolder).location.city
    assert str(ptr) == "/location/city"


def test_from_model_rootmodel_union_of_containers_instance_entry() -> None:
    """RootModel[list[A] | list[B]] with an instance uses runtime indexing to
    disambiguate the concrete container branch."""

    class _JsonBody(BaseModel):
        body: str

    class _XmlBody(BaseModel):
        xml_root: str

    class _Wrap(_RootModel[list[_JsonBody] | list[_XmlBody]]):
        pass

    wrap = _Wrap([_JsonBody(body="hi"), _JsonBody(body="there")])
    item = wrap.root[0]
    assert isinstance(item, _JsonBody)
    ptr = pointer_from_model(item).body
    assert str(ptr) == "/body"


def test_from_model_nested_list_chained_index_class() -> None:
    """grid: list[list[Item]] — class-based entry must resolve grid[0][0].name."""

    class _Item(BaseModel):
        name: str

    class _Outer(BaseModel):
        grid: list[list[_Item]]

    ptr = pointer_from_model(_Outer).grid[0][0].name
    assert str(ptr) == "/grid/0/0/name"
    assert ptr._tokens == ("grid", "0", "0", "name")


def test_from_model_triple_nested_list_class() -> None:
    """list[list[list[Item]]] — three chained indices must reach Item.name."""

    class _Item(BaseModel):
        value: str

    class _Outer(BaseModel):
        cube: list[list[list[_Item]]]

    ptr = pointer_from_model(_Outer).cube[0][0][0].value
    assert str(ptr) == "/cube/0/0/0/value"


def test_modelpath_getitem_dash_on_tuple_field_loses_model_context() -> None:
    """'-' is rejected by TupleAdapter at runtime; model context must be lost
    at build time so the user sees an AttributeError before traversal fails."""

    class _Holder(BaseModel):
        items: tuple[_Address, ...]

    mp = _ModelPath(_model_cls=_Holder, _resolver=BySerializationAlias()).items["-"]
    assert str(mp) == "/items/-"
    assert mp._model_ctx_lost is True


def test_from_model_rootmodel_wrapping_nested_list_chained_index() -> None:
    """payload: RootModel[list[list[Item]]] — chained indexing must work through the wrapper."""

    class _Item(BaseModel):
        label: str

    class _GridList(_RootModel[list[list[_Item]]]):
        pass

    class _Outer(BaseModel):
        payload: _GridList

    ptr = pointer_from_model(_Outer).payload[0][0].label
    assert str(ptr) == "/payload/0/0/label"
    assert ptr._tokens == ("payload", "0", "0", "label")


def test_from_model_rootmodel_optional_wrapping_nested_list_chained_index() -> None:
    """payload: RootModel[list[list[Item]]] | None — chained indexing must work."""

    class _Item(BaseModel):
        label: str

    class _GridList(_RootModel[list[list[_Item]]]):
        pass

    class _Outer(BaseModel):
        payload: _GridList | None

    ptr = pointer_from_model(_Outer).payload[0][0].label
    assert str(ptr) == "/payload/0/0/label"


def test_from_model_rootmodel_root_attr_raises_attributeerror() -> None:
    """pointer_from_model(TagList).root must raise: RootModel is transparent at runtime."""
    with pytest.raises(AttributeError, match="traversed transparently"):
        pointer_from_model(_TagList).root


def test_from_model_rootmodel_any_attr_raises_attributeerror() -> None:
    """Any attribute access on a RootModel entry-point must raise."""

    class _NumList(_RootModel[list[int]]):
        pass

    with pytest.raises(AttributeError, match="traversed transparently"):
        pointer_from_model(_NumList).root


def test_from_model_basemodel_with_root_field_still_works() -> None:
    """A plain BaseModel (not RootModel) with a field named 'root' must work normally."""

    class _Node(BaseModel):
        root: str

    ptr = pointer_from_model(_Node).root
    assert str(ptr) == "/root"


def test_from_model_union_of_rootmodel_containers_chained_index_with_instance() -> None:
    """payloads: list[AList | BList] where AList = RootModel[list[A]].

    Narrow via isinstance after the first index, then chained index into the
    RootModel and attribute access on the inner model.
    """

    class _A(BaseModel):
        label: str

    class _B(BaseModel):
        value: int

    class _AList(_RootModel[list[_A]]):
        pass

    class _BList(_RootModel[list[_B]]):
        pass

    class _Outer(BaseModel):
        payloads: list[_AList | _BList]

    outer = _Outer(payloads=[_AList([_A(label="hi"), _A(label="there")])])
    assert isinstance(outer.payloads[0], _AList)
    ptr = pointer_from_model(outer.payloads[0])[0].label
    assert str(ptr) == "/0/label"
    assert ptr._tokens == ("0", "label")


def test_from_model_rootmodel_container_instance_index_union_disambiguation() -> None:
    """RootModel wrapping a list: [index] followed by isinstance() narrowing works.

    Regression test that removing _instance did not break the recommended narrowing
    pattern: index into the RootModel list, narrow with isinstance(), then re-enter
    pointer_from_model() on the narrowed value.
    """

    class _JsonBody(BaseModel):
        body: str

    class _XmlBody(BaseModel):
        xml_root: str

    class _Event(BaseModel):
        payload: _JsonBody | _XmlBody

    class _EventList(_RootModel[list[_Event]]):
        pass

    # Case 1: double-wrapped RootModel entry (Outer = RootModel[EventList])
    class _Outer(_RootModel[_EventList]):
        pass

    outer = _Outer(_EventList([_Event(payload=_JsonBody(body="hi"))]))
    event1 = outer.root.root[0]
    assert isinstance(event1.payload, _JsonBody)
    ptr = pointer_from_model(event1.payload).body
    assert str(ptr) == "/body"

    # Case 2: normal model field typed as EventList
    class _Holder(BaseModel):
        events: _EventList

    holder = _Holder(events=_EventList([_Event(payload=_JsonBody(body="hi"))]))
    event2 = holder.events.root[0]
    assert isinstance(event2.payload, _JsonBody)
    ptr2 = pointer_from_model(event2.payload).body
    assert str(ptr2) == "/body"

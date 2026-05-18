from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from pydantic_jsonpointer import JsonPointer
from pydantic_jsonpointer.adapters import DictAdapter, ListAdapter
from pydantic_jsonpointer.errors import (
    AdapterNotFoundError,
    ImmutableTargetError,
    InvalidTokenError,
    PointerNotFoundError,
    RootRebindError,
)
from pydantic_jsonpointer.traversal import (
    Ptr,
    add_value,
    get_value,
    remove_value,
    resolve,
    set_value,
)


def _dict_ptr(
    pointer: str,
    parent: Any,
    key: int | str | None,
    *,
    frozen: bool = False,
) -> Ptr:
    return Ptr(
        pointer=JsonPointer(pointer),
        _parent=parent,
        _key=key,
        _adapter=DictAdapter(),
        _frozen=frozen,
    )


def _list_ptr(
    pointer: str,
    parent: Any,
    key: int | str | None,
    *,
    frozen: bool = False,
) -> Ptr:
    return Ptr(
        pointer=JsonPointer(pointer),
        _parent=parent,
        _key=key,
        _adapter=ListAdapter(),
        _frozen=frozen,
    )


def test_ptr_is_frozen_dataclass() -> None:
    p = _dict_ptr("/x", {"x": 1}, "x")
    with pytest.raises(dataclasses.FrozenInstanceError):
        p.pointer = JsonPointer("/y")  # type: ignore[misc]


@pytest.mark.parametrize(
    ("pointer", "key", "expected_root", "expected_frozen"),
    [
        ("", None, True, False),
        ("/x", "x", False, False),
        ("/x", "x", False, True),
    ],
)
def test_ptr_properties(
    pointer: str,
    key: int | str | None,
    expected_root: bool,
    expected_frozen: bool,
) -> None:
    doc = {"x": 1}
    p = _dict_ptr(pointer, doc, key, frozen=expected_frozen)
    assert p.is_root is expected_root
    assert p.is_frozen is expected_frozen
    assert p.key == key
    assert p.parent is doc


def test_ptr_root_get_returns_doc() -> None:
    doc = {"x": 42}
    root = _dict_ptr("", doc, None)
    assert root.get() is doc


def test_ptr_get_returns_value() -> None:
    doc = {"x": 42}
    p = _dict_ptr("/x", doc, "x")
    assert p.get() == 42


def test_ptr_get_missing_raises() -> None:
    doc: dict[str, Any] = {"x": 42}
    p = _dict_ptr("/y", doc, "y")
    with pytest.raises(PointerNotFoundError):
        p.get()


def test_ptr_get_live_after_external_mutation() -> None:
    doc = {"x": 1}
    p = _dict_ptr("/x", doc, "x")
    assert p.get() == 1
    doc["x"] = 99
    assert p.get() == 99


def test_ptr_try_get_returns_default_when_missing() -> None:
    doc: dict[str, Any] = {}
    p = _dict_ptr("/y", doc, "y")
    assert p.try_get("fallback") == "fallback"


def test_ptr_try_get_returns_value_when_present() -> None:
    doc = {"x": 42}
    p = _dict_ptr("/x", doc, "x")
    assert p.try_get("fallback") == 42


def test_ptr_try_get_without_default_raises_when_missing() -> None:
    doc: dict[str, Any] = {}
    p = _dict_ptr("/y", doc, "y")
    with pytest.raises(PointerNotFoundError):
        p.try_get()


def test_ptr_try_get_with_none_default_returns_none() -> None:
    doc: dict[str, Any] = {}
    p = _dict_ptr("/y", doc, "y")
    assert p.try_get(None) is None


@pytest.mark.parametrize(
    ("doc", "key", "expected"),
    [
        ({"x": 1}, "x", True),
        ({"x": 1}, "missing", False),
    ],
)
def test_ptr_exists_dict(doc: dict[str, Any], key: str, expected: bool) -> None:
    p = _dict_ptr(f"/{key}", doc, key)
    assert p.exists() is expected


def test_ptr_exists_root_always_true() -> None:
    doc: dict[str, Any] = {}
    root = _dict_ptr("", doc, None)
    assert root.exists() is True


def test_ptr_exists_list_in_range() -> None:
    p = _list_ptr("/0", [10, 20], 0)
    assert p.exists() is True


def test_ptr_exists_list_out_of_range() -> None:
    p = _list_ptr("/5", [10, 20], 5)
    assert p.exists() is False


def test_ptr_set_replaces_value() -> None:
    doc = {"x": 1}
    p = _dict_ptr("/x", doc, "x")
    p.set(99)
    assert doc == {"x": 99}


def test_ptr_set_missing_raises_not_found() -> None:
    doc: dict[str, Any] = {}
    p = _dict_ptr("/y", doc, "y")
    with pytest.raises(PointerNotFoundError):
        p.set(99)


def test_ptr_set_on_root_raises_rebind() -> None:
    doc = {"x": 1}
    root = _dict_ptr("", doc, None)
    with pytest.raises(RootRebindError):
        root.set({"other": 2})
    assert doc == {"x": 1}


def test_ptr_set_when_frozen_raises_immutable() -> None:
    doc = {"x": 1}
    p = _dict_ptr("/x", doc, "x", frozen=True)
    with pytest.raises(ImmutableTargetError):
        p.set(99)
    assert doc == {"x": 1}


def test_ptr_add_creates_key() -> None:
    doc: dict[str, Any] = {}
    p = _dict_ptr("/x", doc, "x")
    p.add(7)
    assert doc == {"x": 7}


def test_ptr_add_replaces_existing_key() -> None:
    doc = {"x": 1}
    p = _dict_ptr("/x", doc, "x")
    p.add(2)
    assert doc == {"x": 2}


def test_ptr_add_appends_to_list_via_dash() -> None:
    lst: list[int] = [10, 20]
    p = _list_ptr("/-", lst, "-")
    p.add(30)
    assert lst == [10, 20, 30]


def test_ptr_add_on_root_raises_rebind() -> None:
    doc: dict[str, Any] = {}
    root = _dict_ptr("", doc, None)
    with pytest.raises(RootRebindError):
        root.add({"new": 1})
    assert doc == {}


def test_ptr_add_when_frozen_raises_immutable() -> None:
    doc: dict[str, Any] = {}
    p = _dict_ptr("/x", doc, "x", frozen=True)
    with pytest.raises(ImmutableTargetError):
        p.add(7)
    assert doc == {}


def test_ptr_remove_pops_value() -> None:
    doc = {"x": 1, "y": 2}
    p = _dict_ptr("/x", doc, "x")
    assert p.remove() == 1
    assert doc == {"y": 2}


def test_ptr_remove_missing_raises_not_found() -> None:
    doc: dict[str, Any] = {"x": 1}
    p = _dict_ptr("/y", doc, "y")
    with pytest.raises(PointerNotFoundError):
        p.remove()


def test_ptr_remove_on_root_raises_rebind() -> None:
    doc = {"x": 1}
    root = _dict_ptr("", doc, None)
    with pytest.raises(RootRebindError):
        root.remove()
    assert doc == {"x": 1}


def test_ptr_remove_when_frozen_raises_immutable() -> None:
    doc = {"x": 1}
    p = _dict_ptr("/x", doc, "x", frozen=True)
    with pytest.raises(ImmutableTargetError):
        p.remove()
    assert doc == {"x": 1}


def test_resolve_empty_pointer_returns_root() -> None:
    doc = {"x": 1}
    p = resolve(doc, JsonPointer(""))
    assert p.is_root is True
    assert p.get() is doc
    assert p.exists() is True
    assert p.key is None
    assert p.parent is doc


def test_resolve_into_dict() -> None:
    doc = {"foo": {"bar": 42}}
    p = resolve(doc, JsonPointer("/foo/bar"))
    assert p.exists()
    assert p.get() == 42
    assert p.key == "bar"
    assert p.parent is doc["foo"]
    assert p.is_frozen is False


def test_resolve_single_token_dict() -> None:
    doc = {"foo": {"bar": 42}}
    p = resolve(doc, JsonPointer("/foo"))
    assert p.exists()
    assert p.get() is doc["foo"]
    assert p.key == "foo"
    assert p.parent is doc


def test_resolve_into_list() -> None:
    doc = {"xs": [10, 20, 30]}
    p = resolve(doc, JsonPointer("/xs/1"))
    assert p.get() == 20
    assert p.key == 1
    assert p.parent is doc["xs"]


def test_resolve_mixed_path() -> None:
    doc = {"users": [{"name": "Alice"}, {"name": "Bob"}]}
    p = resolve(doc, JsonPointer("/users/1/name"))
    assert p.get() == "Bob"


def test_resolve_missing_leaf_yields_non_existent_ptr() -> None:
    doc: dict[str, Any] = {"foo": {}}
    p = resolve(doc, JsonPointer("/foo/bar"))
    assert p.exists() is False
    with pytest.raises(PointerNotFoundError):
        p.get()
    p.add(7)
    assert doc == {"foo": {"bar": 7}}


def test_resolve_missing_intermediate_raises() -> None:
    doc: dict[str, Any] = {}
    with pytest.raises(PointerNotFoundError):
        resolve(doc, JsonPointer("/missing/bar"))


def test_resolve_dash_tail_returns_non_existent_ptr() -> None:
    doc = {"xs": [10, 20]}
    p = resolve(doc, JsonPointer("/xs/-"))
    assert p.exists() is False
    assert p.key == "-"
    p.add(30)
    assert doc == {"xs": [10, 20, 30]}


def test_resolve_dash_mid_path_raises() -> None:
    doc = {"xs": [[1, 2], [3, 4]]}
    with pytest.raises(InvalidTokenError):
        resolve(doc, JsonPointer("/xs/-/0"))


def test_resolve_into_scalar_mid_path_raises_adapter_not_found() -> None:
    doc = {"x": 42}
    with pytest.raises(AdapterNotFoundError) as excinfo:
        resolve(doc, JsonPointer("/x/sub"))
    # Spec edge-case matrix: error names the type AND the pointer prefix that
    # reached the un-adaptable value. Assert the exact framing so a regression
    # that drops the suffix can't satisfy a loose substring check.
    msg = str(excinfo.value)
    assert "type 'int'" in msg
    assert msg.endswith("at pointer '/x'")


def test_adapter_not_found_at_root_includes_empty_prefix() -> None:
    with pytest.raises(AdapterNotFoundError) as excinfo:
        resolve(42, JsonPointer("/0"))
    msg = str(excinfo.value)
    assert "type 'int'" in msg
    assert msg.endswith("at pointer ''")


def test_adapter_not_found_under_list_includes_path_to_scalar() -> None:
    doc = {"items": [{"payload": "x"}, {"payload": "y"}]}
    with pytest.raises(AdapterNotFoundError) as excinfo:
        resolve(doc, JsonPointer("/items/0/payload/sub"))
    msg = str(excinfo.value)
    assert "type 'str'" in msg
    assert msg.endswith("at pointer '/items/0/payload'")


def test_resolve_rfc6901_escapes_via_jsonpointer_tokens() -> None:
    doc = {"a/b": 1, "m~n": 2}
    assert resolve(doc, JsonPointer("/a~1b")).get() == 1
    assert resolve(doc, JsonPointer("/m~0n")).get() == 2


_RFC6901_DOC: dict[str, Any] = {
    "foo": ["bar", "baz"],
    "": 0,
    "a/b": 1,
    "c%d": 2,
    "e^f": 3,
    "g|h": 4,
    "i\\j": 5,
    'k"l': 6,
    " ": 7,
    "m~n": 8,
}


@pytest.mark.parametrize(
    ("pointer", "expected"),
    [
        ("", _RFC6901_DOC),
        ("/foo", ["bar", "baz"]),
        ("/foo/0", "bar"),
        ("/", 0),
        ("/a~1b", 1),
        ("/c%d", 2),
        ("/e^f", 3),
        ("/g|h", 4),
        ("/i\\j", 5),
        ('/k"l', 6),
        ("/ ", 7),
        ("/m~0n", 8),
    ],
)
def test_resolve_rfc6901_section_5_examples(pointer: str, expected: Any) -> None:
    p = resolve(_RFC6901_DOC, JsonPointer(pointer))
    assert p.get() == expected


def test_get_value_root_returns_doc() -> None:
    doc = {"x": 1}
    assert get_value(doc, JsonPointer("")) is doc


def test_get_value_dict() -> None:
    doc = {"foo": {"bar": 42}}
    assert get_value(doc, JsonPointer("/foo/bar")) == 42


def test_get_value_list() -> None:
    doc = {"xs": [10, 20, 30]}
    assert get_value(doc, JsonPointer("/xs/1")) == 20


def test_get_value_missing_raises() -> None:
    doc: dict[str, Any] = {"x": 1}
    with pytest.raises(PointerNotFoundError):
        get_value(doc, JsonPointer("/missing"))


def test_set_value_dict_replaces() -> None:
    doc = {"x": 1}
    set_value(doc, JsonPointer("/x"), 99)
    assert doc == {"x": 99}


def test_set_value_list_replaces() -> None:
    doc = {"xs": [10, 20, 30]}
    set_value(doc, JsonPointer("/xs/1"), 99)
    assert doc == {"xs": [10, 99, 30]}


def test_set_value_missing_raises() -> None:
    doc: dict[str, Any] = {}
    with pytest.raises(PointerNotFoundError):
        set_value(doc, JsonPointer("/x"), 1)


def test_set_value_on_root_raises_rebind() -> None:
    doc = {"x": 1}
    with pytest.raises(RootRebindError):
        set_value(doc, JsonPointer(""), {"y": 2})


def test_add_value_creates_dict_key() -> None:
    doc: dict[str, Any] = {}
    add_value(doc, JsonPointer("/x"), 7)
    assert doc == {"x": 7}


def test_add_value_replaces_dict_key() -> None:
    doc = {"x": 1}
    add_value(doc, JsonPointer("/x"), 2)
    assert doc == {"x": 2}


def test_add_value_appends_list_via_dash() -> None:
    doc = {"xs": [10, 20]}
    add_value(doc, JsonPointer("/xs/-"), 30)
    assert doc == {"xs": [10, 20, 30]}


def test_add_value_inserts_list_index() -> None:
    doc = {"xs": [10, 30]}
    add_value(doc, JsonPointer("/xs/1"), 20)
    assert doc == {"xs": [10, 20, 30]}


def test_remove_value_pops_dict_entry() -> None:
    doc = {"x": 1, "y": 2}
    assert remove_value(doc, JsonPointer("/x")) == 1
    assert doc == {"y": 2}


def test_remove_value_pops_list_entry() -> None:
    doc = {"xs": [10, 20, 30]}
    assert remove_value(doc, JsonPointer("/xs/1")) == 20
    assert doc == {"xs": [10, 30]}


def test_remove_value_missing_raises() -> None:
    doc: dict[str, Any] = {}
    with pytest.raises(PointerNotFoundError):
        remove_value(doc, JsonPointer("/x"))


def test_remove_value_on_root_raises_rebind() -> None:
    doc = {"x": 1}
    with pytest.raises(RootRebindError):
        remove_value(doc, JsonPointer(""))


# ---------- Transitive frozen taint via BaseModelAdapter ------------------

from pydantic import BaseModel as _BM  # noqa: E402
from pydantic import ConfigDict as _CD  # noqa: E402
from pydantic import Field as _F  # noqa: E402

from pydantic_jsonpointer.adapters import _REGISTRY  # noqa: E402
from pydantic_jsonpointer.adapters import register as _register  # noqa: E402
from pydantic_jsonpointer.pydantic_adapter import (  # noqa: E402
    BaseModelAdapter as _BaseModelAdapter,
)


@pytest.fixture
def _basemodel_registered() -> Any:
    # The walker calls adapter_for(value), so BaseModel must be in the
    # registry for resolve(doc, ...) to reach a Pydantic model. The dedicated
    # __init__.py registration arrives in a later task; tests opt in via this
    # fixture and clean up afterwards so other tests stay isolated.
    snapshot = dict(_REGISTRY)
    _register(_BM, _BaseModelAdapter(), override=True)
    try:
        yield
    finally:
        _REGISTRY.clear()
        _REGISTRY.update(snapshot)


class _OuterFrozenField(_BM):
    inner: list[int] = _F(default_factory=lambda: [10, 20, 30], frozen=True)


class _OuterFrozenWhole(_BM):
    model_config = _CD(frozen=True)
    items: list[int] = _F(default_factory=lambda: [10, 20, 30])


class _SubWithFrozenConfig(_BM):
    model_config = _CD(frozen=True)
    x: int = 1


class _OuterHostsSubFrozen(_BM):
    sub: _SubWithFrozenConfig = _F(default_factory=_SubWithFrozenConfig)


def test_frozen_field_blocks_direct_write(_basemodel_registered: Any) -> None:
    doc = _OuterFrozenField()
    p = resolve(doc, JsonPointer("/inner"))
    assert p.is_frozen is True
    with pytest.raises(ImmutableTargetError):
        p.set([99])
    assert doc.inner == [10, 20, 30]


def test_frozen_field_transitive_blocks_list_element_write(
    _basemodel_registered: Any,
) -> None:
    doc = _OuterFrozenField()
    p = resolve(doc, JsonPointer("/inner/0"))
    assert p.is_frozen is True
    with pytest.raises(ImmutableTargetError):
        p.set(99)
    assert doc.inner == [10, 20, 30]


def test_frozen_field_transitive_blocks_list_tail_add(
    _basemodel_registered: Any,
) -> None:
    doc = _OuterFrozenField()
    p = resolve(doc, JsonPointer("/inner/-"))
    assert p.is_frozen is True
    with pytest.raises(ImmutableTargetError):
        p.add(40)
    assert doc.inner == [10, 20, 30]


def test_frozen_field_reads_still_work(_basemodel_registered: Any) -> None:
    doc = _OuterFrozenField()
    assert resolve(doc, JsonPointer("/inner/1")).get() == 20
    assert resolve(doc, JsonPointer("/inner")).get() == [10, 20, 30]


def test_whole_frozen_model_blocks_field_write(
    _basemodel_registered: Any,
) -> None:
    doc = _OuterFrozenWhole()
    p = resolve(doc, JsonPointer("/items"))
    assert p.is_frozen is True
    with pytest.raises(ImmutableTargetError):
        p.set([])
    assert doc.items == [10, 20, 30]


def test_whole_frozen_model_blocks_list_element_write(
    _basemodel_registered: Any,
) -> None:
    doc = _OuterFrozenWhole()
    p = resolve(doc, JsonPointer("/items/0"))
    assert p.is_frozen is True
    with pytest.raises(ImmutableTargetError):
        p.set(99)
    assert doc.items == [10, 20, 30]


def test_descending_into_whole_frozen_submodel_taints_descendants(
    _basemodel_registered: Any,
) -> None:
    doc = _OuterHostsSubFrozen()
    # `sub` itself is a normal field on the outer model (so writing /sub is
    # fine), but the sub-model has ConfigDict(frozen=True), so /sub/x is
    # tainted.
    p_sub = resolve(doc, JsonPointer("/sub"))
    assert p_sub.is_frozen is False
    p_field = resolve(doc, JsonPointer("/sub/x"))
    assert p_field.is_frozen is True
    with pytest.raises(ImmutableTargetError):
        p_field.set(99)
    assert doc.sub.x == 1


# ---------- Public API exports + Pydantic auto-registration ----------------


def test_public_package_exports_full_surface() -> None:
    import pydantic_jsonpointer as pjp

    expected = {
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
    }
    assert set(pjp.__all__) == expected
    for name in expected:
        assert hasattr(pjp, name), f"missing public export: {name}"


def test_public_imports_are_importable_by_name() -> None:
    from pydantic_jsonpointer import (  # noqa: F401
        AdapterNotFoundError,
        BaseModelAdapter,
        ByAttribute,
        BySerializationAlias,
        ByValidationAlias,
        ContainerAdapter,
        FieldResolver,
        ImmutableTargetError,
        InvalidTokenError,
        JsonPointer,
        PointerError,
        PointerNotFoundError,
        Ptr,
        RootRebindError,
        adapter_for,
        add_value,
        get_value,
        pointer_from_model,
        register,
        remove_value,
        resolve,
        set_value,
    )


class _AutoRegM(_BM):
    name: str = "alice"


def test_basemodel_adapter_auto_registered_on_import() -> None:
    # Importing the package alone is enough to walk a BaseModel — no
    # explicit registration required (no `_basemodel_registered` fixture).
    assert get_value(_AutoRegM(), JsonPointer("/name")) == "alice"


class _AliasedM(_BM):
    user_name: str = _F(serialization_alias="user.name", default="x")


def test_per_call_resolver_override_via_get_value() -> None:
    from pydantic_jsonpointer import ByAttribute as _ByAttribute

    # Default resolver is BySerializationAlias → matches the alias.
    assert get_value(_AliasedM(), JsonPointer("/user.name")) == "x"
    # ByAttribute → matches the attribute name.
    assert (
        get_value(_AliasedM(), JsonPointer("/user_name"), resolver=_ByAttribute())
        == "x"
    )


def test_per_call_resolver_does_not_match_under_default() -> None:
    # Same model under the default resolver: the attribute-name token is
    # rejected because a serialization_alias is set on the field.
    with pytest.raises(InvalidTokenError):
        get_value(_AliasedM(), JsonPointer("/user_name"))


def test_per_call_resolver_does_not_mutate_registry() -> None:
    from pydantic_jsonpointer import ByAttribute as _ByAttribute

    # Per-call override:
    get_value(_AliasedM(), JsonPointer("/user_name"), resolver=_ByAttribute())
    # Default behavior must remain BySerializationAlias on the next call.
    assert get_value(_AliasedM(), JsonPointer("/user.name")) == "x"
    with pytest.raises(InvalidTokenError):
        get_value(_AliasedM(), JsonPointer("/user_name"))


def test_set_value_threads_resolver() -> None:
    from pydantic_jsonpointer import ByAttribute as _ByAttribute

    doc = _AliasedM()
    set_value(doc, JsonPointer("/user_name"), "bob", resolver=_ByAttribute())
    assert doc.user_name == "bob"


def test_add_value_threads_resolver() -> None:
    from pydantic_jsonpointer import ByAttribute as _ByAttribute

    doc = _AliasedM()
    add_value(doc, JsonPointer("/user_name"), "bob", resolver=_ByAttribute())
    assert doc.user_name == "bob"


class _AliasedOptional(_BM):
    user_name: str | None = _F(serialization_alias="user.name", default="x")


def test_remove_value_threads_resolver() -> None:
    from pydantic_jsonpointer import ByAttribute as _ByAttribute

    doc = _AliasedOptional()
    assert remove_value(doc, JsonPointer("/user_name"), resolver=_ByAttribute()) == "x"
    assert doc.user_name is None


def test_resolve_threads_resolver_into_nested_models() -> None:
    from pydantic_jsonpointer import ByAttribute as _ByAttribute

    class _Inner(_BM):
        thing: str = _F(serialization_alias="t", default="hi")

    class _Outer(_BM):
        inner: _Inner = _F(default_factory=_Inner)

    doc = _Outer()
    # Under ByAttribute, both outer and inner are accessed by attr name.
    assert get_value(doc, JsonPointer("/inner/thing"), resolver=_ByAttribute()) == "hi"
    # Under default resolver, the inner field needs its serialization_alias "t".
    assert get_value(doc, JsonPointer("/inner/t")) == "hi"


# ---------- RootModel auto-unwrap end-to-end --------------------------------

from pydantic import RootModel as _RootModel  # noqa: E402


class _IntList(_RootModel[list[int]]):
    pass


class _StrToIntMap(_RootModel[dict[str, int]]):
    pass


class _DoubleWrap(_RootModel[_IntList]):
    pass


def test_rootmodel_list_get_reads_inner() -> None:
    doc = _IntList([10, 20, 30])
    assert get_value(doc, JsonPointer("/1")) == 20


def test_rootmodel_list_set_mutates_inner() -> None:
    doc = _IntList([10, 20, 30])
    set_value(doc, JsonPointer("/1"), 99)
    assert doc.root == [10, 99, 30]


def test_rootmodel_list_append_via_dash() -> None:
    doc = _IntList([10, 20])
    add_value(doc, JsonPointer("/-"), 30)
    assert doc.root == [10, 20, 30]


def test_rootmodel_dict_get_reads_inner() -> None:
    doc = _StrToIntMap({"a": 1, "b": 2})
    assert get_value(doc, JsonPointer("/a")) == 1


def test_rootmodel_dict_add_creates_new_key() -> None:
    doc = _StrToIntMap({"a": 1, "b": 2})
    add_value(doc, JsonPointer("/c"), 3)
    assert doc.root == {"a": 1, "b": 2, "c": 3}


def test_rootmodel_nested_unwraps_to_fixed_point() -> None:
    inner = _IntList([1, 2, 3])
    doc = _DoubleWrap(inner)
    # Two layers of RootModel must be unwrapped to reach the underlying list.
    assert get_value(doc, JsonPointer("/0")) == 1


def test_resolve_empty_pointer_on_rootmodel_preserves_caller_identity() -> None:
    # Spec line 426: "_parent=doc; get() returns doc". When doc is a
    # RootModel, the unwrap must not leak through the root Ptr.
    doc = _IntList([10, 20, 30])
    p = resolve(doc, JsonPointer(""))
    assert p.is_root is True
    assert p.get() is doc
    assert p.parent is doc
    assert get_value(doc, JsonPointer("")) is doc


def test_resolve_empty_pointer_on_scalar_returns_root_ptr() -> None:
    # Spec line 426 mandates "_parent=doc; get() returns doc" for the empty
    # pointer; the walker must not eagerly require a registered adapter when
    # there are no tokens to traverse.
    p = resolve(42, JsonPointer(""))
    assert p.is_root is True
    assert p.get() == 42
    assert get_value("hello", JsonPointer("")) == "hello"


def test_resolve_scalar_root_with_token_still_raises_adapter_not_found() -> None:
    from pydantic_jsonpointer import AdapterNotFoundError as _AdapterErr

    with pytest.raises(_AdapterErr):
        resolve(42, JsonPointer("/0"))


# ---------- Frozen RootModel propagates taint through unwrap ---------------


class _FrozenIntList(_RootModel[list[int]]):
    model_config = _CD(frozen=True)


class _FrozenStrToIntMap(_RootModel[dict[str, int]]):
    model_config = _CD(frozen=True)


def test_frozen_rootmodel_list_taints_inner_element() -> None:
    # Spec edge-case: writes anywhere under a frozen-bound container fail.
    # Without freeze-through-unwrap, the inner list would stay writable here.
    doc = _FrozenIntList([10, 20, 30])
    p = resolve(doc, JsonPointer("/0"))
    assert p.is_frozen is True
    with pytest.raises(ImmutableTargetError):
        p.set(99)
    with pytest.raises(ImmutableTargetError):
        set_value(doc, JsonPointer("/0"), 99)
    assert doc.root == [10, 20, 30]


def test_frozen_rootmodel_list_taints_tail_add() -> None:
    doc = _FrozenIntList([10, 20])
    p = resolve(doc, JsonPointer("/-"))
    assert p.is_frozen is True
    with pytest.raises(ImmutableTargetError):
        p.add(30)
    assert doc.root == [10, 20]


def test_frozen_rootmodel_dict_taints_inner_key() -> None:
    doc = _FrozenStrToIntMap({"a": 1, "b": 2})
    p = resolve(doc, JsonPointer("/a"))
    assert p.is_frozen is True
    with pytest.raises(ImmutableTargetError):
        p.set(99)
    with pytest.raises(ImmutableTargetError):
        add_value(doc, JsonPointer("/c"), 3)
    assert doc.root == {"a": 1, "b": 2}


def test_frozen_rootmodel_reads_still_work() -> None:
    doc = _FrozenIntList([10, 20, 30])
    assert get_value(doc, JsonPointer("/1")) == 20
    assert resolve(doc, JsonPointer("/1")).get() == 20


def test_root_ptr_is_never_frozen_even_for_frozen_doc() -> None:
    # Root Ptr is mutation-guarded by ``RootRebindError`` (never by the freeze
    # bit). ``is_frozen`` on the root must report False unconditionally,
    # regardless of any whole-value freeze reported by the doc's adapter.
    doc = _FrozenIntList([10, 20, 30])
    p = resolve(doc, JsonPointer(""))
    assert p.is_root is True
    assert p.is_frozen is False


class _FrozenInnerWrap(_RootModel[list[int]]):
    model_config = _CD(frozen=True)


class _OuterHostsFrozenRootModel(_BM):
    inner: _FrozenInnerWrap = _F(default_factory=lambda: _FrozenInnerWrap([1, 2, 3]))


def test_frozen_rootmodel_nested_under_normal_model_taints_descendants() -> None:
    doc = _OuterHostsFrozenRootModel()
    # /inner descends into the frozen RootModel (parent is the outer model,
    # which is not frozen, so /inner itself is writable). /inner/0 crosses
    # the frozen wrapper via unwrap and must be tainted.
    p_inner = resolve(doc, JsonPointer("/inner"))
    assert p_inner.is_frozen is False
    p_element = resolve(doc, JsonPointer("/inner/0"))
    assert p_element.is_frozen is True
    with pytest.raises(ImmutableTargetError):
        p_element.set(99)
    assert doc.inner.root == [1, 2, 3]


# ---------- RootModel with Field(frozen=True) on .root propagates taint -----


class _RootFrozenFieldList(_RootModel[list[int]]):
    root: list[int] = _F(frozen=True)


class _RootFrozenFieldMap(_RootModel[dict[str, int]]):
    root: dict[str, int] = _F(frozen=True)


def test_field_frozen_rootmodel_list_taints_inner_element() -> None:
    # ``Field(frozen=True)`` on a RootModel's ``root`` field is the only frozen
    # binding on the path — the walker unwraps straight through ``.root``, so
    # the taint must be detected on the wrapper itself and propagated to its
    # unwrapped payload. Otherwise writes to inner slots would silently succeed.
    doc = _RootFrozenFieldList([10, 20, 30])
    p = resolve(doc, JsonPointer("/0"))
    assert p.is_frozen is True
    with pytest.raises(ImmutableTargetError):
        p.set(99)
    with pytest.raises(ImmutableTargetError):
        set_value(doc, JsonPointer("/0"), 99)
    assert doc.root == [10, 20, 30]


def test_field_frozen_rootmodel_list_taints_tail_add() -> None:
    doc = _RootFrozenFieldList([10, 20])
    p = resolve(doc, JsonPointer("/-"))
    assert p.is_frozen is True
    with pytest.raises(ImmutableTargetError):
        p.add(30)
    assert doc.root == [10, 20]


def test_field_frozen_rootmodel_dict_taints_inner_key() -> None:
    doc = _RootFrozenFieldMap({"a": 1, "b": 2})
    p = resolve(doc, JsonPointer("/a"))
    assert p.is_frozen is True
    with pytest.raises(ImmutableTargetError):
        p.set(99)
    with pytest.raises(ImmutableTargetError):
        add_value(doc, JsonPointer("/c"), 3)
    assert doc.root == {"a": 1, "b": 2}


def test_field_frozen_rootmodel_reads_still_work() -> None:
    doc = _RootFrozenFieldList([10, 20, 30])
    assert get_value(doc, JsonPointer("/1")) == 20


class _OuterHostsRootFieldFrozen(_BM):
    inner: _RootFrozenFieldList = _F(
        default_factory=lambda: _RootFrozenFieldList([1, 2, 3])
    )


def test_field_frozen_rootmodel_nested_under_normal_model_taints_descendants() -> None:
    # The outer model is not frozen and ``inner`` is not declared frozen, so
    # ``/inner`` is writable. ``/inner/0`` crosses the inner RootModel whose
    # ``root`` field is frozen — the unwrap chain must surface that taint.
    doc = _OuterHostsRootFieldFrozen()
    p_inner = resolve(doc, JsonPointer("/inner"))
    assert p_inner.is_frozen is False
    p_element = resolve(doc, JsonPointer("/inner/0"))
    assert p_element.is_frozen is True
    with pytest.raises(ImmutableTargetError):
        p_element.set(99)
    assert doc.inner.root == [1, 2, 3]


# ---------- RFC 6901 §5 examples via the public get_value helper -----------


@pytest.mark.parametrize(
    ("pointer", "expected"),
    [
        ("", _RFC6901_DOC),
        ("/foo", ["bar", "baz"]),
        ("/foo/0", "bar"),
        ("/", 0),
        ("/a~1b", 1),
        ("/c%d", 2),
        ("/e^f", 3),
        ("/g|h", 4),
        ("/i\\j", 5),
        ('/k"l', 6),
        ("/ ", 7),
        ("/m~0n", 8),
    ],
)
def test_get_value_rfc6901_section_5_examples(pointer: str, expected: Any) -> None:
    assert get_value(_RFC6901_DOC, JsonPointer(pointer)) == expected


# ---------- Custom adapter integration -------------------------------------


class _Box:
    """Single-slot named container used to exercise custom adapter registration."""

    __slots__ = ("slot_name", "value")

    def __init__(self, slot_name: str, value: Any) -> None:
        self.slot_name = slot_name
        self.value = value


class _BoxAdapter:
    """Full ContainerAdapter implementation for ``_Box``."""

    def resolve_token(self, parent: Any, raw_token: str) -> str:
        return raw_token

    def has(self, parent: Any, key: int | str) -> bool:
        return isinstance(key, str) and key == parent.slot_name

    def get(self, parent: Any, key: int | str) -> Any:
        if key != parent.slot_name:
            raise PointerNotFoundError(
                f"no slot {key!r} on _Box (slot is {parent.slot_name!r})"
            )
        return parent.value

    def set(self, parent: Any, key: int | str, value: Any) -> None:
        if key != parent.slot_name:
            raise PointerNotFoundError(
                f"no slot {key!r} on _Box (slot is {parent.slot_name!r})"
            )
        parent.value = value

    def add(self, parent: Any, key: int | str, value: Any) -> None:
        if key != parent.slot_name:
            raise PointerNotFoundError(
                f"no slot {key!r} on _Box (slot is {parent.slot_name!r})"
            )
        parent.value = value

    def remove(self, parent: Any, key: int | str) -> Any:
        if key != parent.slot_name:
            raise PointerNotFoundError(
                f"no slot {key!r} on _Box (slot is {parent.slot_name!r})"
            )
        prior = parent.value
        parent.value = None
        return prior

    def unwrap(self, value: Any) -> Any:
        return ...

    def is_step_frozen(self, parent: Any, key: int | str) -> bool:
        return False

    def is_value_frozen(self, value: Any) -> bool:
        return False


class _FrozenBoxAdapter(_BoxAdapter):
    """Variant whose every step is reported as frozen."""

    def is_step_frozen(self, parent: Any, key: int | str) -> bool:
        return True


def test_custom_box_adapter_walk_read_and_mutate() -> None:
    _register(_Box, _BoxAdapter())
    try:
        doc = {"holder": _Box("slot", 42)}
        p = resolve(doc, JsonPointer("/holder/slot"))
        assert p.exists() is True
        assert p.is_frozen is False
        assert p.key == "slot"
        assert p.parent is doc["holder"]
        assert p.get() == 42

        p.set(99)
        assert doc["holder"].value == 99

        # add on the same slot replaces the value (single-slot container).
        add_value(doc, JsonPointer("/holder/slot"), 7)
        assert doc["holder"].value == 7

        # round-trip via the public helpers too.
        assert get_value(doc, JsonPointer("/holder/slot")) == 7
    finally:
        _REGISTRY.pop(_Box, None)


def test_custom_frozen_box_adapter_taints_descendants() -> None:
    _register(_Box, _FrozenBoxAdapter())
    try:
        doc = {"holder": _Box("slot", 42)}
        p = resolve(doc, JsonPointer("/holder/slot"))
        assert p.is_frozen is True
        with pytest.raises(ImmutableTargetError):
            p.set(99)
        assert doc["holder"].value == 42
        # The convenience helper goes through the same Ptr.set path.
        with pytest.raises(ImmutableTargetError):
            set_value(doc, JsonPointer("/holder/slot"), 100)
        assert doc["holder"].value == 42
    finally:
        _REGISTRY.pop(_Box, None)


class _WrapBox:
    """A transparent wrapper that unwraps to an inner dict."""

    def __init__(self, inner: dict[str, Any], *, frozen: bool = False) -> None:
        self.inner = inner
        self.frozen = frozen


class _WrapBoxAdapter:
    """Adapter that unwraps ``_WrapBox`` to its inner dict and reports the
    wrapper's frozen flag via ``is_value_frozen``.

    Used to verify that a third-party adapter (i.e. not ``BaseModelAdapter``)
    can act as a whole-value freeze-taint source via the opt-in hook.
    """

    def resolve_token(self, parent: Any, raw_token: str) -> str:
        raise AssertionError("walker must unwrap before tokenizing")

    def has(self, parent: Any, key: int | str) -> bool:
        raise AssertionError("walker must unwrap before reading")

    def get(self, parent: Any, key: int | str) -> Any:
        raise AssertionError("walker must unwrap before reading")

    def set(self, parent: Any, key: int | str, value: Any) -> None:
        raise AssertionError("walker must unwrap before writing")

    def add(self, parent: Any, key: int | str, value: Any) -> None:
        raise AssertionError("walker must unwrap before adding")

    def remove(self, parent: Any, key: int | str) -> Any:
        raise AssertionError("walker must unwrap before removing")

    def unwrap(self, value: Any) -> Any:
        return value.inner

    def is_step_frozen(self, parent: Any, key: int | str) -> bool:
        return False

    def is_value_frozen(self, value: Any) -> bool:
        return bool(value.frozen)


def test_third_party_is_value_frozen_taints_descendants() -> None:
    # Frozen wrapper around a normal dict — the inner dict is not itself
    # frozen, but the wrapper's ``is_value_frozen`` must propagate the taint
    # through unwrap so writes into the inner slot are refused.
    _register(_WrapBox, _WrapBoxAdapter())
    try:
        doc = _WrapBox({"x": 1, "y": 2}, frozen=True)
        p = resolve(doc, JsonPointer("/x"))
        assert p.is_frozen is True
        with pytest.raises(ImmutableTargetError):
            p.set(99)
        with pytest.raises(ImmutableTargetError):
            set_value(doc, JsonPointer("/x"), 99)
        # Reads must still succeed across the frozen wrapper.
        assert get_value(doc, JsonPointer("/x")) == 1
        assert doc.inner == {"x": 1, "y": 2}
    finally:
        _REGISTRY.pop(_WrapBox, None)


def test_third_party_is_value_frozen_false_does_not_taint() -> None:
    # Same wrapper with frozen=False must NOT taint — proves the hook's
    # return value is what gates the taint (not the mere presence of the hook).
    _register(_WrapBox, _WrapBoxAdapter())
    try:
        doc = _WrapBox({"x": 1}, frozen=False)
        p = resolve(doc, JsonPointer("/x"))
        assert p.is_frozen is False
        p.set(99)
        assert doc.inner == {"x": 99}
    finally:
        _REGISTRY.pop(_WrapBox, None)


# ---------- Defensive unwrap-loop cap -------------------------------------


class _PingPong:
    """Container whose adapter's ``unwrap`` always returns a fresh instance.

    Used to exercise the depth cap that protects against misbehaving adapters
    that never return ``...`` from ``unwrap``.
    """


class _PingPongAdapter(_BoxAdapter):
    def unwrap(self, value: Any) -> Any:
        # Never converges; always hands back a new wrapper instance.
        return _PingPong()


def test_unwrap_fixed_point_raises_when_chain_never_converges() -> None:
    from pydantic_jsonpointer.errors import PointerError

    _register(_PingPong, _PingPongAdapter())
    try:
        with pytest.raises(PointerError, match="unwrap chain exceeded"):
            resolve(_PingPong(), JsonPointer("/x"))
    finally:
        _REGISTRY.pop(_PingPong, None)


class _CountDownBox:
    """Wrapper whose adapter unwraps to a shallower instance until ``remaining``
    reaches 1, at which point it returns ``...``. Lets the test pin the depth
    cap to its declared constant: a chain of exactly ``N`` boxes consumes
    exactly ``N`` iterations of the unwrap loop.
    """

    def __init__(self, remaining: int) -> None:
        self.remaining = remaining


class _CountDownBoxAdapter(_BoxAdapter):
    def unwrap(self, value: Any) -> Any:
        if value.remaining <= 1:
            return ...
        return _CountDownBox(value.remaining - 1)


def test_unwrap_fixed_point_succeeds_at_depth_cap() -> None:
    # The cap is a *maximum*, not a strict-less-than bound: a chain whose
    # iterations exactly equal ``_MAX_UNWRAP_DEPTH`` must resolve cleanly.
    # Anchor the test on the constant so any drift is caught.
    from pydantic_jsonpointer.traversal import _MAX_UNWRAP_DEPTH

    _register(_CountDownBox, _CountDownBoxAdapter())
    try:
        doc = _CountDownBox(_MAX_UNWRAP_DEPTH)
        # Empty pointer drives the initial unwrap (descent_value) but does no
        # token-step work, so the success criterion is "resolve returns".
        p = resolve(doc, JsonPointer(""))
        assert p.is_root is True
        assert p.get() is doc
    finally:
        _REGISTRY.pop(_CountDownBox, None)


def test_unwrap_fixed_point_fails_past_depth_cap() -> None:
    from pydantic_jsonpointer.errors import PointerError
    from pydantic_jsonpointer.traversal import _MAX_UNWRAP_DEPTH

    _register(_CountDownBox, _CountDownBoxAdapter())
    try:
        # One unwrap iteration past the cap raises the bounded-loop guard.
        doc = _CountDownBox(_MAX_UNWRAP_DEPTH + 1)
        with pytest.raises(PointerError, match="unwrap chain exceeded"):
            resolve(doc, JsonPointer(""))
    finally:
        _REGISTRY.pop(_CountDownBox, None)


def test_package_import_is_reload_safe() -> None:
    """Reloading the package must not raise ``ValueError`` from a duplicate
    ``register`` of ``BaseModelAdapter`` against ``BaseModel``.
    """
    import importlib

    import pydantic_jsonpointer

    # Should not raise — the BaseModel registration is now idempotent
    # (``override=True``), so a reload re-registers cleanly.
    importlib.reload(pydantic_jsonpointer)


# ---------- Legacy 8-method adapter compatibility -------------------------


class _LegacyBox:
    """A container used only to host a legacy adapter (no ``is_value_frozen``)."""

    def __init__(self, slot: str, value: Any) -> None:
        self.slot = slot
        self.value = value


class _LegacyBoxAdapter:
    """An adapter implementing only the original 8-method ``ContainerAdapter``
    contract — deliberately missing ``is_value_frozen``. The walker must
    tolerate this and treat the omission as "not whole-value frozen".
    """

    def resolve_token(self, parent: Any, raw_token: str) -> str:
        return raw_token

    def has(self, parent: Any, key: int | str) -> bool:
        return bool(key == parent.slot)

    def get(self, parent: Any, key: int | str) -> Any:
        if key != parent.slot:
            raise PointerNotFoundError(repr(key))
        return parent.value

    def set(self, parent: Any, key: int | str, value: Any) -> None:
        if key != parent.slot:
            raise PointerNotFoundError(repr(key))
        parent.value = value

    def add(self, parent: Any, key: int | str, value: Any) -> None:
        self.set(parent, key, value)

    def remove(self, parent: Any, key: int | str) -> Any:
        prior = self.get(parent, key)
        parent.value = None
        return prior

    def unwrap(self, value: Any) -> Any:
        return ...

    def is_step_frozen(self, parent: Any, key: int | str) -> bool:
        return False


def test_legacy_adapter_without_is_value_frozen_still_resolves() -> None:
    """A third-party adapter written against the canonical 8-method Protocol
    must keep working: ``is_value_frozen`` is an opt-in hook outside the
    required Protocol surface, and omitting it is equivalent to ``return False``.
    """
    _register(_LegacyBox, _LegacyBoxAdapter())
    try:
        doc = {"holder": _LegacyBox("slot", 42)}
        p = resolve(doc, JsonPointer("/holder/slot"))
        assert p.is_frozen is False
        assert p.get() == 42

        p.set(99)
        assert doc["holder"].value == 99

        # All four convenience helpers must also tolerate the legacy adapter.
        assert get_value(doc, JsonPointer("/holder/slot")) == 99
        set_value(doc, JsonPointer("/holder/slot"), 7)
        assert doc["holder"].value == 7
        add_value(doc, JsonPointer("/holder/slot"), 5)
        assert doc["holder"].value == 5
        assert remove_value(doc, JsonPointer("/holder/slot")) == 5
    finally:
        _REGISTRY.pop(_LegacyBox, None)


class _LegacyWrap:
    """A transparent wrapper whose legacy adapter actually unwraps to a dict."""

    def __init__(self, inner: dict[str, Any]) -> None:
        self.inner = inner


class _LegacyWrapAdapter:
    """Legacy 8-method adapter with a non-trivial ``unwrap``. Deliberately
    omits ``is_value_frozen`` so the walker must guard the ``getattr`` probe
    on every iteration of the unwrap loop, not just when the first
    ``unwrap`` returns ``...`` immediately.
    """

    def resolve_token(self, parent: Any, raw_token: str) -> str:
        raise AssertionError("walker must unwrap before tokenizing")

    def has(self, parent: Any, key: int | str) -> bool:
        raise AssertionError("walker must unwrap before reading")

    def get(self, parent: Any, key: int | str) -> Any:
        raise AssertionError("walker must unwrap before reading")

    def set(self, parent: Any, key: int | str, value: Any) -> None:
        raise AssertionError("walker must unwrap before writing")

    def add(self, parent: Any, key: int | str, value: Any) -> None:
        raise AssertionError("walker must unwrap before adding")

    def remove(self, parent: Any, key: int | str) -> Any:
        raise AssertionError("walker must unwrap before removing")

    def unwrap(self, value: Any) -> Any:
        return value.inner

    def is_step_frozen(self, parent: Any, key: int | str) -> bool:
        return False


def test_legacy_adapter_real_unwrap_skips_is_value_frozen_probe() -> None:
    # A legacy adapter whose ``unwrap`` actually descends must not crash with
    # ``AttributeError`` during the unwrap loop's ``getattr`` probe. Catches a
    # regression that reorders the ``is_value_frozen`` check to depend on the
    # adapter type rather than ``getattr(..., None)``.
    _register(_LegacyWrap, _LegacyWrapAdapter())
    try:
        doc = _LegacyWrap({"x": 1, "y": 2})
        p = resolve(doc, JsonPointer("/x"))
        assert p.is_frozen is False
        assert p.get() == 1
        p.set(99)
        assert doc.inner == {"x": 99, "y": 2}
    finally:
        _REGISTRY.pop(_LegacyWrap, None)


# ---------------------------------------------------------------------------
# TupleAdapter integration tests
# ---------------------------------------------------------------------------


def test_get_value_from_tuple() -> None:
    doc = (10, 20, 30)
    assert get_value(doc, JsonPointer("/0")) == 10
    assert get_value(doc, JsonPointer("/2")) == 30


def test_get_value_from_nested_tuple() -> None:
    doc = {"items": (1, 2, 3)}
    assert get_value(doc, JsonPointer("/items/1")) == 2


def test_resolve_tuple_root() -> None:
    doc = (1, 2, 3)
    p = resolve(doc, JsonPointer(""))
    assert p.get() is doc


def test_get_value_tuple_out_of_range_raises() -> None:
    doc = (10, 20)
    with pytest.raises(PointerNotFoundError):
        get_value(doc, JsonPointer("/5"))


def test_set_value_tuple_raises_immutable() -> None:
    doc = (1, 2, 3)
    with pytest.raises(ImmutableTargetError):
        set_value(doc, JsonPointer("/0"), 99)


def test_add_value_tuple_raises_immutable() -> None:
    doc = (1, 2, 3)
    with pytest.raises(ImmutableTargetError):
        add_value(doc, JsonPointer("/0"), 99)


def test_remove_value_tuple_raises_immutable() -> None:
    doc = (1, 2, 3)
    with pytest.raises(ImmutableTargetError):
        remove_value(doc, JsonPointer("/0"))

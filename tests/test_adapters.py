from __future__ import annotations

from typing import Any, Iterator

import pytest

from pydantic_jsonpointer.adapters import (
    ContainerAdapter,
    DictAdapter,
    ListAdapter,
    TupleAdapter,
    adapter_for,
    register,
)
from pydantic_jsonpointer.errors import (
    AdapterNotFoundError,
    ImmutableTargetError,
    InvalidTokenError,
    PointerNotFoundError,
)


class _StubAdapter:
    """Minimal adapter for registry tests — every method is a no-op."""

    def resolve_token(self, parent: Any, raw_token: str) -> int | str:
        return raw_token

    def has(self, parent: Any, key: int | str) -> bool:
        return False

    def get(self, parent: Any, key: int | str) -> Any:
        raise NotImplementedError

    def set(self, parent: Any, key: int | str, value: Any) -> None:
        raise NotImplementedError

    def add(self, parent: Any, key: int | str, value: Any) -> None:
        raise NotImplementedError

    def remove(self, parent: Any, key: int | str) -> Any:
        raise NotImplementedError

    def unwrap(self, value: Any) -> Any:
        return ...

    def is_step_frozen(self, parent: Any, key: int | str) -> bool:
        return False

    def is_value_frozen(self, value: Any) -> bool:
        return False


class _CustomContainer:
    pass


class _CustomChild(_CustomContainer):
    pass


@pytest.fixture(autouse=True)
def _clean_registry() -> Iterator[None]:
    """Snapshot and restore the adapter registry around every test in this file."""
    from pydantic_jsonpointer import adapters as _ad

    saved = dict(_ad._REGISTRY)
    yield
    _ad._REGISTRY.clear()
    _ad._REGISTRY.update(saved)


def test_stub_satisfies_protocol() -> None:
    assert isinstance(_StubAdapter(), ContainerAdapter)


def test_register_and_lookup_exact_type() -> None:
    adapter = _StubAdapter()
    register(_CustomContainer, adapter)
    assert adapter_for(_CustomContainer()) is adapter


def test_lookup_via_mro() -> None:
    adapter = _StubAdapter()
    register(_CustomContainer, adapter)
    assert adapter_for(_CustomChild()) is adapter


def test_unknown_type_raises() -> None:
    with pytest.raises(AdapterNotFoundError, match="no adapter"):
        adapter_for(object())


def test_duplicate_register_without_override_raises() -> None:
    register(_CustomContainer, _StubAdapter())
    with pytest.raises(ValueError, match="already registered"):
        register(_CustomContainer, _StubAdapter())


def test_duplicate_register_with_override_succeeds() -> None:
    register(_CustomContainer, _StubAdapter())
    new_adapter = _StubAdapter()
    register(_CustomContainer, new_adapter, override=True)
    assert adapter_for(_CustomContainer()) is new_adapter


def test_adapter_for_accepts_resolver_kwarg() -> None:
    """`resolver=` kwarg is accepted from Task 2 (semantics added in Task 11)."""
    adapter = _StubAdapter()
    register(_CustomContainer, adapter)
    assert adapter_for(_CustomContainer(), resolver=None) is adapter


def test_mro_prefers_closest_ancestor() -> None:
    parent_adapter = _StubAdapter()
    child_adapter = _StubAdapter()
    register(_CustomContainer, parent_adapter)
    register(_CustomChild, child_adapter)
    assert adapter_for(_CustomChild()) is child_adapter
    assert adapter_for(_CustomContainer()) is parent_adapter


def test_dict_adapter_auto_registered() -> None:
    assert isinstance(adapter_for({}), DictAdapter)


def test_dict_adapter_satisfies_protocol() -> None:
    assert isinstance(DictAdapter(), ContainerAdapter)


@pytest.mark.parametrize(
    "token,expected",
    [
        ("foo", "foo"),
        ("a/b", "a/b"),  # JsonPointer.tokens already unescaped this upstream
        ("~0~1", "~0~1"),
        ("", ""),
        ("0", "0"),
    ],
)
def test_dict_resolve_token_passthrough(token: str, expected: str) -> None:
    assert DictAdapter().resolve_token({}, token) == expected


def test_dict_has_present_and_absent() -> None:
    a = DictAdapter()
    d = {"x": 1}
    assert a.has(d, "x") is True
    assert a.has(d, "missing") is False


def test_dict_get_present() -> None:
    assert DictAdapter().get({"x": 1}, "x") == 1


def test_dict_get_missing_raises_pointer_not_found() -> None:
    a = DictAdapter()
    with pytest.raises(PointerNotFoundError):
        a.get({"x": 1}, "missing")


def test_dict_set_replaces_existing_key() -> None:
    a = DictAdapter()
    d = {"x": 1}
    a.set(d, "x", 2)
    assert d == {"x": 2}


def test_dict_set_missing_key_raises() -> None:
    a = DictAdapter()
    with pytest.raises(PointerNotFoundError, match="cannot replace"):
        a.set({"x": 1}, "missing", 9)


def test_dict_add_creates_new_key() -> None:
    a = DictAdapter()
    d: dict[str, int] = {}
    a.add(d, "x", 1)
    assert d == {"x": 1}


def test_dict_add_replaces_existing_key() -> None:
    a = DictAdapter()
    d = {"x": 1}
    a.add(d, "x", 2)
    assert d == {"x": 2}


def test_dict_remove_pops_and_returns_value() -> None:
    a = DictAdapter()
    d = {"x": 1, "y": 2}
    assert a.remove(d, "x") == 1
    assert d == {"y": 2}


def test_dict_remove_missing_raises() -> None:
    a = DictAdapter()
    with pytest.raises(PointerNotFoundError):
        a.remove({}, "missing")


def test_dict_unwrap_is_ellipsis_sentinel() -> None:
    assert DictAdapter().unwrap({"x": 1}) is ...


def test_dict_is_step_frozen_is_false() -> None:
    assert DictAdapter().is_step_frozen({"x": 1}, "x") is False


def test_list_adapter_auto_registered() -> None:
    assert isinstance(adapter_for([1, 2, 3]), ListAdapter)


def test_list_adapter_satisfies_protocol() -> None:
    assert isinstance(ListAdapter(), ContainerAdapter)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("0", 0),
        ("1", 1),
        ("42", 42),
        ("-", "-"),
    ],
)
def test_list_resolve_token_valid(raw: str, expected: int | str) -> None:
    assert ListAdapter().resolve_token([1, 2, 3], raw) == expected


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "01",
        "00",
        "-1",
        "foo",
        "1a",
        " 1",
        # RFC 6901 §4 restricts array-index tokens to ASCII digits; non-ASCII
        # decimals (Arabic-Indic, fullwidth, etc.) must be rejected even though
        # ``str.isdecimal`` accepts them.
        "١٢٣",  # Arabic-Indic digits ١٢٣
        "１２",  # Fullwidth digits １２
        "१",  # Devanagari digit १
    ],
)
def test_list_resolve_token_invalid(bad: str) -> None:
    with pytest.raises(InvalidTokenError):
        ListAdapter().resolve_token([1, 2, 3], bad)


def test_list_has_in_range() -> None:
    a = ListAdapter()
    lst = [10, 20, 30]
    assert a.has(lst, 0) is True
    assert a.has(lst, 2) is True


def test_list_has_out_of_range() -> None:
    a = ListAdapter()
    assert a.has([10, 20, 30], 3) is False


def test_list_has_dash_is_false() -> None:
    assert ListAdapter().has([10, 20], "-") is False


def test_list_get_in_range() -> None:
    assert ListAdapter().get([10, 20, 30], 1) == 20


def test_list_get_out_of_range_raises() -> None:
    with pytest.raises(PointerNotFoundError):
        ListAdapter().get([10, 20], 5)


def test_list_get_dash_raises_invalid() -> None:
    with pytest.raises(InvalidTokenError):
        ListAdapter().get([10, 20], "-")


def test_list_set_replaces() -> None:
    a = ListAdapter()
    lst = [10, 20]
    a.set(lst, 0, 99)
    assert lst == [99, 20]


def test_list_set_out_of_range_raises() -> None:
    with pytest.raises(PointerNotFoundError):
        ListAdapter().set([10], 5, 99)


def test_list_set_dash_raises_invalid() -> None:
    with pytest.raises(InvalidTokenError):
        ListAdapter().set([10], "-", 99)


def test_list_add_insert_in_range() -> None:
    a = ListAdapter()
    lst = [10, 30]
    a.add(lst, 1, 20)
    assert lst == [10, 20, 30]


def test_list_add_at_end() -> None:
    a = ListAdapter()
    lst = [10, 20]
    a.add(lst, 2, 30)
    assert lst == [10, 20, 30]


def test_list_add_dash_appends() -> None:
    a = ListAdapter()
    lst = [10, 20]
    a.add(lst, "-", 30)
    assert lst == [10, 20, 30]


def test_list_add_at_zero_inserts_at_head() -> None:
    a = ListAdapter()
    lst = [20, 30]
    a.add(lst, 0, 10)
    assert lst == [10, 20, 30]


def test_list_add_out_of_range_raises() -> None:
    with pytest.raises(InvalidTokenError):
        ListAdapter().add([10, 20], 5, 99)


def test_list_add_negative_raises() -> None:
    with pytest.raises(InvalidTokenError):
        ListAdapter().add([10, 20], -1, 99)


def test_list_remove_pops_and_returns() -> None:
    a = ListAdapter()
    lst = [10, 20, 30]
    assert a.remove(lst, 1) == 20
    assert lst == [10, 30]


def test_list_remove_out_of_range_raises() -> None:
    with pytest.raises(PointerNotFoundError):
        ListAdapter().remove([10], 5)


def test_list_remove_dash_raises_invalid() -> None:
    with pytest.raises(InvalidTokenError):
        ListAdapter().remove([10], "-")


def test_list_unwrap_is_ellipsis_sentinel() -> None:
    assert ListAdapter().unwrap([1, 2]) is ...


def test_list_is_step_frozen_is_false() -> None:
    assert ListAdapter().is_step_frozen([1, 2], 0) is False


@pytest.mark.parametrize("key", [True, False])
def test_list_has_rejects_bool_key(key: bool) -> None:
    # bool is a subclass of int but is never produced by resolve_token; treat
    # it as an invalid index rather than silently coercing True->1 / False->0.
    assert ListAdapter().has([10, 20, 30], key) is False


@pytest.mark.parametrize(
    "op",
    [
        lambda a, k: a.get([10, 20], k),
        lambda a, k: a.set([10, 20], k, 99),
        lambda a, k: a.add([10, 20], k, 99),
        lambda a, k: a.remove([10, 20], k),
    ],
)
@pytest.mark.parametrize("key", [True, False])
def test_list_mutations_reject_bool_key(op: Any, key: bool) -> None:
    with pytest.raises(InvalidTokenError):
        op(ListAdapter(), key)


def test_adapter_for_resolver_preserves_basemodel_adapter_subclass() -> None:
    """A custom subclass of ``BaseModelAdapter`` must survive the per-call
    resolver substitution so user overrides still apply when callers pass
    ``resolver=...``."""
    from pydantic import BaseModel

    from pydantic_jsonpointer.pydantic_adapter import (
        BaseModelAdapter,
        ByAttribute,
    )

    class _M(BaseModel):
        x: int = 1

    class _Override(BaseModelAdapter):
        pass

    register(_M, _Override(), override=True)
    a = adapter_for(_M(), resolver=ByAttribute())
    assert isinstance(a, _Override)


def test_tuple_adapter_auto_registered() -> None:
    assert isinstance(adapter_for((1, 2, 3)), TupleAdapter)


def test_tuple_adapter_satisfies_protocol() -> None:
    assert isinstance(TupleAdapter(), ContainerAdapter)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("0", 0),
        ("1", 1),
        ("42", 42),
    ],
)
def test_tuple_resolve_token_valid(raw: str, expected: int) -> None:
    assert TupleAdapter().resolve_token((10, 20, 30), raw) == expected


@pytest.mark.parametrize(
    "bad",
    ["", "01", "-", "-1", "foo", "١٢٣"],
)
def test_tuple_resolve_token_invalid(bad: str) -> None:
    with pytest.raises(InvalidTokenError):
        TupleAdapter().resolve_token((1, 2), bad)


def test_tuple_has_in_range() -> None:
    a = TupleAdapter()
    t = (10, 20, 30)
    assert a.has(t, 0) is True
    assert a.has(t, 2) is True


def test_tuple_has_out_of_range() -> None:
    assert TupleAdapter().has((10, 20), 3) is False


def test_tuple_get_in_range() -> None:
    assert TupleAdapter().get((10, 20, 30), 1) == 20


def test_tuple_get_out_of_range_raises() -> None:
    with pytest.raises(PointerNotFoundError):
        TupleAdapter().get((10, 20), 5)


def test_tuple_set_raises_immutable() -> None:
    with pytest.raises(ImmutableTargetError):
        TupleAdapter().set((10, 20), 0, 99)


def test_tuple_set_missing_slot_raises_immutable() -> None:
    with pytest.raises(ImmutableTargetError):
        TupleAdapter().set((10, 20), 5, 99)


def test_tuple_add_raises_immutable() -> None:
    with pytest.raises(ImmutableTargetError):
        TupleAdapter().add((10, 20), 0, 99)


def test_tuple_remove_raises_immutable() -> None:
    with pytest.raises(ImmutableTargetError):
        TupleAdapter().remove((10, 20), 0)


def test_tuple_remove_missing_slot_raises_immutable() -> None:
    with pytest.raises(ImmutableTargetError):
        TupleAdapter().remove((10, 20), 5)


def test_tuple_unwrap_is_ellipsis_sentinel() -> None:
    assert TupleAdapter().unwrap((1, 2)) is ...


def test_tuple_is_step_frozen_is_false() -> None:
    assert TupleAdapter().is_step_frozen((1, 2), 0) is False


def test_adapter_for_resolver_preserves_subclass_state_and_custom_init() -> None:
    """``with_resolver`` clones via ``copy.copy``, so a subclass whose
    ``__init__`` takes extra required arguments — and which carries that state
    on the instance — survives the per-call resolver substitution. The
    registered instance must not be mutated."""
    from pydantic import BaseModel

    from pydantic_jsonpointer.pydantic_adapter import (
        BaseModelAdapter,
        ByAttribute,
        BySerializationAlias,
    )

    class _M(BaseModel):
        x: int = 1

    class _ConfiguredOverride(BaseModelAdapter):
        def __init__(self, label: str, resolver: Any = None) -> None:
            super().__init__(resolver=resolver)
            self.label = label

    registered = _ConfiguredOverride(label="custom")
    register(_M, registered, override=True)

    a = adapter_for(_M(), resolver=ByAttribute())
    assert isinstance(a, _ConfiguredOverride)
    assert a.label == "custom"
    assert a is not registered  # per-call clone, not the registered instance
    # Registered adapter still carries its original resolver.
    assert isinstance(registered._resolver, BySerializationAlias)
    # The clone uses the per-call resolver.
    assert isinstance(a._resolver, ByAttribute)

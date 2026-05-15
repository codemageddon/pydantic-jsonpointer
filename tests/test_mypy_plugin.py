"""Tests for the pydantic-jsonpointer mypy plugin.

Uses mypy.api.run() to verify that the plugin reports errors for invalid
field access and passes for valid field access.
"""

from __future__ import annotations

import os
import tempfile

import mypy.api


def _run_mypy(code: str) -> tuple[str, str, int]:
    """Run mypy on the given code with the plugin loaded and strict mode.

    Creates a temporary mypy.ini that enables the plugin, since the
    plugin is opt-in for downstream users and not enabled in this project's
    own config.
    """
    config = """\
[mypy]
plugins = pydantic_jsonpointer.mypy_plugin
strict = true
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = os.path.join(tmpdir, "mypy.ini")
        with open(config_path, "w") as f:
            f.write(config)
        result = mypy.api.run(
            [
                f"--config-file={config_path}",
                "--show-error-codes",
                "-c",
                code,
            ]
        )
        return result[0], result[1], result[2]


_PREAMBLE = """\
from pydantic import BaseModel
from pydantic_jsonpointer import pointer_from_model
"""


def test_valid_field_access() -> None:
    code = (
        _PREAMBLE
        + """
class User(BaseModel):
    name: str

p = pointer_from_model(User).name
"""
    )
    stdout, stderr, exit_code = _run_mypy(code)
    assert exit_code == 0, f"mypy errors: {stdout}"


def test_invalid_field_access() -> None:
    code = (
        _PREAMBLE
        + """
class User(BaseModel):
    name: str

p = pointer_from_model(User).typo
"""
    )
    stdout, stderr, exit_code = _run_mypy(code)
    assert exit_code != 0, f"mypy should have failed: {stdout}"
    assert "has no field 'typo'" in stdout


def test_chained_valid() -> None:
    code = (
        _PREAMBLE
        + """
class Address(BaseModel):
    city: str

class Profile(BaseModel):
    address: Address

p = pointer_from_model(Profile).address.city
"""
    )
    stdout, stderr, exit_code = _run_mypy(code)
    assert exit_code == 0, f"mypy errors: {stdout}"


def test_chained_invalid() -> None:
    code = (
        _PREAMBLE
        + """
class Address(BaseModel):
    city: str

class Profile(BaseModel):
    address: Address

p = pointer_from_model(Profile).address.typo
"""
    )
    stdout, stderr, exit_code = _run_mypy(code)
    assert exit_code != 0, f"mypy should have failed: {stdout}"
    assert "'Address' has no field 'typo'" in stdout, stdout


def test_list_field_and_index() -> None:
    code = (
        _PREAMBLE
        + """
class Address(BaseModel):
    city: str

class Order(BaseModel):
    items: list[Address]

p = pointer_from_model(Order).items[0].city
"""
    )
    stdout, stderr, exit_code = _run_mypy(code)
    assert exit_code == 0, f"mypy errors: {stdout}"


def test_index_on_non_list() -> None:
    code = (
        _PREAMBLE
        + """
class User(BaseModel):
    name: str

p = pointer_from_model(User).name[0]
"""
    )
    stdout, stderr, exit_code = _run_mypy(code)
    assert exit_code != 0, f"mypy should have failed: {stdout}"
    assert "non-list" in stdout, stdout


def test_rootmodel_entry() -> None:
    code = (
        _PREAMBLE
        + """
from pydantic import RootModel

class Item(BaseModel):
    label: str

class TagList(RootModel[list[Item]]):
    pass

p = pointer_from_model(TagList)[0].label
"""
    )
    stdout, stderr, exit_code = _run_mypy(code)
    assert exit_code == 0, f"mypy errors: {stdout}"


def test_rootmodel_attr_access_rejected() -> None:
    """Attribute access on a bare transparent RootModel must be rejected.

    pointer_from_model(TagList).root raises at runtime; the plugin must
    emit an error rather than silently accepting 'root' because it exists
    on the RootModel class.
    """
    code = (
        _PREAMBLE
        + """
from pydantic import RootModel

class Item(BaseModel):
    label: str

class TagList(RootModel[list[Item]]):
    pass

p = pointer_from_model(TagList).root
"""
    )
    stdout, stderr, exit_code = _run_mypy(code)
    assert exit_code != 0, f"mypy should have failed: {stdout}"
    assert "RootModel" in stdout and "transparent" in stdout


def test_basemodel_with_root_field_accepted() -> None:
    """A plain BaseModel with a field named 'root' must be accepted by the plugin.

    Only RootModel transparent access to '.root' is rejected; a plain BaseModel
    field named 'root' is a legitimate pointer target.
    """
    code = (
        _PREAMBLE
        + """
class Node(BaseModel):
    root: str
    value: int

p = pointer_from_model(Node).root
"""
    )
    stdout, stderr, exit_code = _run_mypy(code)
    assert exit_code == 0, f"mypy errors: {stdout}"


def test_union_ambiguous() -> None:
    """Ambiguous BaseModel Union is a hard error; the message guides isinstance narrowing."""
    code = (
        _PREAMBLE
        + """
class JsonBody(BaseModel):
    body: str

class XmlBody(BaseModel):
    root: str

class Event(BaseModel):
    payload: JsonBody | XmlBody

p = pointer_from_model(Event).payload.body
"""
    )
    stdout, stderr, exit_code = _run_mypy(code)
    assert exit_code != 0, f"mypy should have failed for ambiguous union: {stdout}"
    assert "ambiguous BaseModel Union" in stdout, stdout
    assert "isinstance" in stdout, stdout


def test_optional_field() -> None:
    code = (
        _PREAMBLE
        + """
class Inner(BaseModel):
    thing: str

class Outer(BaseModel):
    opt_inner: Inner | None = None

p = pointer_from_model(Outer).opt_inner.thing
"""
    )
    stdout, stderr, exit_code = _run_mypy(code)
    assert exit_code == 0, f"mypy errors: {stdout}"


def test_double_rootmodel() -> None:
    code = (
        _PREAMBLE
        + """
from pydantic import RootModel

class Item(BaseModel):
    label: str

class TagList(RootModel[list[Item]]):
    pass

class DoubleWrap(RootModel[TagList]):
    pass

p = pointer_from_model(DoubleWrap)[0].label
"""
    )
    stdout, stderr, exit_code = _run_mypy(code)
    assert exit_code == 0, f"mypy errors: {stdout}"


def test_field_named_build_no_error() -> None:
    """Field named 'build' must not cause a type error; runtime fields win."""
    code = (
        _PREAMBLE
        + """
class Widget(BaseModel):
    build: str
    version: int

p = pointer_from_model(Widget).build
"""
    )
    stdout, stderr, exit_code = _run_mypy(code)
    assert exit_code == 0, f"mypy errors: {stdout}"


def test_field_named_build_callable_via_call() -> None:
    """pointer_from_model(Widget).build() returns JsonPointer via __call__."""
    code = (
        _PREAMBLE
        + """
from pydantic_jsonpointer import JsonPointer

class Widget(BaseModel):
    build: str

result: JsonPointer = pointer_from_model(Widget).build()
"""
    )
    stdout, stderr, exit_code = _run_mypy(code)
    assert exit_code == 0, f"mypy errors: {stdout}"


def test_method_access_rejected() -> None:
    """Plugin must reject method access — methods are not model fields."""
    code = (
        _PREAMBLE
        + """
class User(BaseModel):
    name: str

    def helper(self) -> str:
        return self.name

p = pointer_from_model(User).helper
"""
    )
    stdout, stderr, exit_code = _run_mypy(code)
    assert exit_code != 0, f"mypy should have failed: {stdout}"
    assert "has no field 'helper'" in stdout


def test_field_named_build_nested_model_no_false_field_error() -> None:
    """build field that is a nested model must not report 'has no field' for it.

    Limitation: mypy resolves .build as the _ModelPath.build() method (a
    class-defined member) without firing get_attribute_hook, so chained
    access like .build.name produces a Callable-vs-attribute error rather
    than a model-field error.  The important guarantee is that accessing
    .build itself does not report 'Parent has no field build'.
    """
    code = (
        _PREAMBLE
        + """
class City(BaseModel):
    name: str

class Parent(BaseModel):
    build: City

p = pointer_from_model(Parent).build
"""
    )
    stdout, stderr, exit_code = _run_mypy(code)
    assert exit_code == 0, f"mypy errors: {stdout}"
    assert "has no field" not in stdout


def test_classvar_access_rejected() -> None:
    """ClassVar attributes are excluded from model_fields; plugin must reject them."""
    code = (
        _PREAMBLE
        + """
from typing import ClassVar

class User(BaseModel):
    name: str
    helper: ClassVar[str] = "shared"

p = pointer_from_model(User).helper
"""
    )
    stdout, stderr, exit_code = _run_mypy(code)
    assert exit_code != 0, f"mypy should have failed: {stdout}"
    assert "has no field 'helper'" in stdout


def test_rootmodel_wrapping_basemodel_attr_access() -> None:
    """pointer_from_model(Wrap).field where Wrap=RootModel[Inner] must not
    report 'Wrap has no field field'; plugin must unwrap to Inner."""
    code = (
        _PREAMBLE
        + """
from pydantic import RootModel

class Inner(BaseModel):
    field: str

class Wrap(RootModel[Inner]):
    pass

p = pointer_from_model(Wrap).field
"""
    )
    stdout, stderr, exit_code = _run_mypy(code)
    assert exit_code == 0, f"mypy errors: {stdout}"
    assert "has no field" not in stdout


def test_rootmodel_wrapping_basemodel_invalid_attr() -> None:
    """Attributes not on Inner must still be rejected even when entry is RootModel."""
    code = (
        _PREAMBLE
        + """
from pydantic import RootModel

class Inner(BaseModel):
    field: str

class Wrap(RootModel[Inner]):
    pass

p = pointer_from_model(Wrap).typo
"""
    )
    stdout, stderr, exit_code = _run_mypy(code)
    assert exit_code != 0, f"mypy should have failed: {stdout}"
    assert "has no field 'typo'" in stdout


def test_rootmodel_optional_inner_attr_access() -> None:
    """pointer_from_model(Wrap).field where Wrap=RootModel[Inner | None] must not
    false-positive; plugin must unwrap Optional to Inner."""
    code = (
        _PREAMBLE
        + """
from pydantic import RootModel
from typing import Optional

class Inner(BaseModel):
    field: str

class Wrap(RootModel[Optional[Inner]]):
    pass

p = pointer_from_model(Wrap).field
"""
    )
    stdout, stderr, exit_code = _run_mypy(code)
    assert exit_code == 0, f"mypy errors: {stdout}"
    assert "has no field" not in stdout


def test_rootmodel_list_inner_rejects_invalid_attr() -> None:
    """pointer_from_model(TagList).label where TagList=RootModel[list[Item]] must
    be rejected: the transparent RootModel wrapper forbids any attr access."""
    code = (
        _PREAMBLE
        + """
from pydantic import RootModel

class Item(BaseModel):
    label: str

class TagList(RootModel[list[Item]]):
    pass

p = pointer_from_model(TagList).label
"""
    )
    stdout, stderr, exit_code = _run_mypy(code)
    assert exit_code != 0, f"mypy should have failed: {stdout}"
    assert "RootModel" in stdout and "transparent" in stdout


def test_rootmodel_ambiguous_union_attr_rejected() -> None:
    """pointer_from_model(Wrap).body where Wrap=RootModel[A | B] must be rejected
    because A|B is ambiguous and the RootModel wrapper is transparent."""
    code = (
        _PREAMBLE
        + """
from pydantic import RootModel

class A(BaseModel):
    body: str

class B(BaseModel):
    other: str

class Wrap(RootModel[A | B]):
    pass

p = pointer_from_model(Wrap).body
"""
    )
    stdout, stderr, exit_code = _run_mypy(code)
    assert exit_code != 0, f"mypy should have failed: {stdout}"
    assert "RootModel" in stdout and "transparent" in stdout


def test_rootmodel_wrapping_basemodel_rejects_index() -> None:
    """pointer_from_model(Wrap).__getitem__(0) where Wrap=RootModel[Inner] (non-list)
    must be rejected: Inner is not a list so indexing is invalid.
    """
    code = (
        _PREAMBLE
        + """
from pydantic import RootModel

class Inner(BaseModel):
    field: str

class Wrap(RootModel[Inner]):
    pass

p = pointer_from_model(Wrap).__getitem__(0)
"""
    )
    stdout, stderr, exit_code = _run_mypy(code)
    assert exit_code != 0, f"mypy should have failed: {stdout}"
    assert "non-list" in stdout


def test_union_instance_requires_narrowing() -> None:
    """Ambiguous BaseModel Union is a hard error even on instance entry.

    Instance-based Union disambiguation is no longer a runtime feature.
    The plugin emits a hard error with a note suggesting isinstance() narrowing.
    """
    code = (
        _PREAMBLE
        + """
class JsonBody(BaseModel):
    body: str

class XmlBody(BaseModel):
    root: str

class Event(BaseModel):
    payload: JsonBody | XmlBody

event = Event(payload=JsonBody(body="hello"))
p = pointer_from_model(event).payload.body
"""
    )
    stdout, stderr, exit_code = _run_mypy(code)
    assert exit_code != 0, f"mypy should have failed for ambiguous union: {stdout}"
    assert "ambiguous BaseModel Union" in stdout, stdout
    assert "isinstance" in stdout, stdout


def test_chain_three_deep_invalid_target_class_in_message() -> None:
    """Three-deep chained access reports the typo against the correct nested model."""
    code = (
        _PREAMBLE
        + """
class City(BaseModel):
    name: str

class Address(BaseModel):
    city: City

class Profile(BaseModel):
    address: Address

p = pointer_from_model(Profile).address.city.typo
"""
    )
    stdout, stderr, exit_code = _run_mypy(code)
    assert exit_code != 0, f"mypy should have failed: {stdout}"
    assert "has no field 'typo'" in stdout, f"unexpected error text: {stdout}"
    assert "'City'" in stdout, (
        f"error should point at City (the leaf model), got: {stdout}"
    )


def test_explicit_getitem_then_invalid_attr() -> None:
    """orders.items.__getitem__(0).typo must error against the item model."""
    code = (
        _PREAMBLE
        + """
class Item(BaseModel):
    label: str

class Order(BaseModel):
    items: list[Item]

p = pointer_from_model(Order).items.__getitem__(0).typo
"""
    )
    stdout, stderr, exit_code = _run_mypy(code)
    assert exit_code != 0, f"mypy should have failed: {stdout}"
    assert "'Item' has no field 'typo'" in stdout, stdout


def test_explicit_getitem_then_valid_attr() -> None:
    """orders.items.__getitem__(0).label must pass — explicit form, valid field."""
    code = (
        _PREAMBLE
        + """
class Item(BaseModel):
    label: str

class Order(BaseModel):
    items: list[Item]

p = pointer_from_model(Order).items.__getitem__(0).label
"""
    )
    stdout, stderr, exit_code = _run_mypy(code)
    assert exit_code == 0, f"mypy errors: {stdout}"


def test_implicit_getitem_then_invalid_attr() -> None:
    """Implicit [0] syntax must also enable chained validation via get_method_signature_hook."""
    code = (
        _PREAMBLE
        + """
class Item(BaseModel):
    label: str

class Order(BaseModel):
    items: list[Item]

p = pointer_from_model(Order).items[0].typo
"""
    )
    stdout, stderr, exit_code = _run_mypy(code)
    assert exit_code != 0, f"mypy should have failed: {stdout}"
    assert "'Item' has no field 'typo'" in stdout, stdout


def test_chain_three_deep_valid() -> None:
    code = (
        _PREAMBLE
        + """
class City(BaseModel):
    name: str

class Address(BaseModel):
    city: City

class Profile(BaseModel):
    address: Address

p = pointer_from_model(Profile).address.city.name
"""
    )
    stdout, stderr, exit_code = _run_mypy(code)
    assert exit_code == 0, f"mypy errors: {stdout}"


def test_chain_three_deep_invalid_middle() -> None:
    """Typo at the middle of a deep chain points at the middle model."""
    code = (
        _PREAMBLE
        + """
class City(BaseModel):
    name: str

class Address(BaseModel):
    city: City

class Profile(BaseModel):
    address: Address

p = pointer_from_model(Profile).address.typo.name
"""
    )
    stdout, stderr, exit_code = _run_mypy(code)
    assert exit_code != 0, f"mypy should have failed: {stdout}"
    assert "'Address' has no field 'typo'" in stdout, stdout


def test_union_of_lists_indexable_no_error() -> None:
    """list[A] | list[B] field is valid for indexing at runtime; plugin must not false-positive."""
    code = (
        _PREAMBLE
        + """
class A(BaseModel):
    x: str

class B(BaseModel):
    y: str

class Event(BaseModel):
    payload: list[A] | list[B]

p = pointer_from_model(Event).payload[0]
"""
    )
    stdout, stderr, exit_code = _run_mypy(code)
    assert exit_code == 0, f"mypy errors: {stdout}"
    assert "non-list" not in stdout, stdout


def test_union_of_lists_chained_attr_error() -> None:
    """list[A] | list[B] field loses model context after [index]; chained .attr must error."""
    code = (
        _PREAMBLE
        + """
class A(BaseModel):
    x: str

class B(BaseModel):
    y: str

class Event(BaseModel):
    payload: list[A] | list[B]

p = pointer_from_model(Event).payload[0].x
"""
    )
    stdout, stderr, exit_code = _run_mypy(code)
    assert exit_code != 0, f"mypy should have failed: {stdout}"
    assert "model type context was lost" in stdout, stdout
    assert "'A' has no field 'x'" not in stdout, stdout


def test_tuple_leaf_element_chained_attr_error() -> None:
    """tuple[str, str][0].attr must emit a context-lost error for a leaf-type element."""
    code = (
        _PREAMBLE
        + """
class Model(BaseModel):
    pair: tuple[str, str]

p = pointer_from_model(Model).pair[0].typo
"""
    )
    stdout, stderr, exit_code = _run_mypy(code)
    assert exit_code != 0, f"mypy should have failed: {stdout}"
    assert "model type context was lost" in stdout, stdout


def test_tuple_field_indexable_no_error() -> None:
    """tuple[A, B] field is valid for indexing at runtime; plugin must not false-positive."""
    code = (
        _PREAMBLE
        + """
class Address(BaseModel):
    city: str

class Model(BaseModel):
    pair: tuple[Address, Address]

p = pointer_from_model(Model).pair[0]
"""
    )
    stdout, stderr, exit_code = _run_mypy(code)
    assert exit_code == 0, f"mypy errors: {stdout}"
    assert "non-list" not in stdout, stdout


def test_tuple_field_index_validates_element() -> None:
    """tuple[A, B][literal_index] must advance to the element model so .attr is validated."""
    code = (
        _PREAMBLE
        + """
class Address(BaseModel):
    city: str

class Model(BaseModel):
    pair: tuple[Address, Address]

p_ok = pointer_from_model(Model).pair[0].city
p_bad = pointer_from_model(Model).pair[0].typo
"""
    )
    stdout, stderr, exit_code = _run_mypy(code)
    assert exit_code != 0, f"mypy should have failed on typo: {stdout}"
    assert "'Address' has no field 'typo'" in stdout, stdout
    assert "'Address' has no field 'city'" not in stdout, (
        f"city should be valid: {stdout}"
    )


def test_tuple_fixed_out_of_range_index_error() -> None:
    """tuple[A, B][2] must emit a mypy error — index 2 is out of range for a 2-element tuple.

    Without this check the plugin would silently return _ModelPath[Any, Any] and
    allow chained .attr access that the runtime rejects with AttributeError.
    """
    code = (
        _PREAMBLE
        + """
class Address(BaseModel):
    city: str

class Model(BaseModel):
    pair: tuple[Address, Address]

p = pointer_from_model(Model).pair[2].city
"""
    )
    stdout, _stderr, exit_code = _run_mypy(code)
    assert exit_code != 0, f"mypy should have failed on out-of-range index: {stdout}"
    assert "out of range" in stdout, stdout


def test_rootmodel_tuple_inner_indexable_no_false_positive() -> None:
    """RootModel[tuple[A, B]] field must accept [0] without a false-positive error."""
    code = (
        _PREAMBLE
        + """
from pydantic import RootModel

class Address(BaseModel):
    city: str

class Holder(BaseModel):
    wrapped: RootModel[tuple[Address, Address]]

p = pointer_from_model(Holder).wrapped[0]
"""
    )
    stdout, stderr, exit_code = _run_mypy(code)
    assert exit_code == 0, f"mypy errors: {stdout}"
    assert "non-list" not in stdout, stdout


def test_rootmodel_union_of_lists_inner_indexable_no_false_positive() -> None:
    """RootModel[list[A] | list[B]] field must accept [0] without a false-positive error."""
    code = (
        _PREAMBLE
        + """
from pydantic import RootModel

class A(BaseModel):
    x: str

class B(BaseModel):
    y: str

class Holder(BaseModel):
    wrapped: RootModel[list[A] | list[B]]

p = pointer_from_model(Holder).wrapped[0]
"""
    )
    stdout, stderr, exit_code = _run_mypy(code)
    assert exit_code == 0, f"mypy errors: {stdout}"
    assert "non-list" not in stdout, stdout


def test_nested_list_chained_index_validates() -> None:
    """Chained [0][0] on list[list[Item]] validates the final attribute against Item."""
    code = (
        _PREAMBLE
        + """
class Item(BaseModel):
    name: str

class Grid(BaseModel):
    rows: list[list[Item]]

p_ok = pointer_from_model(Grid).rows[0][0].name
p_bad = pointer_from_model(Grid).rows[0][0].typo
"""
    )
    stdout, stderr, exit_code = _run_mypy(code)
    assert exit_code != 0, f"mypy should have failed on typo: {stdout}"
    assert "'Item' has no field 'typo'" in stdout, stdout
    assert "'Item' has no field 'name'" not in stdout, f"name should be valid: {stdout}"


def test_tuple_nested_list_chained_index_validates() -> None:
    """tuple[list[Item], list[Item]][0][0].attr must validate against Item."""
    code = (
        _PREAMBLE
        + """
class Item(BaseModel):
    name: str

class Model(BaseModel):
    grid: tuple[list[Item], list[Item]]

p_ok = pointer_from_model(Model).grid[0][0].name
p_bad = pointer_from_model(Model).grid[0][0].typo
"""
    )
    stdout, stderr, exit_code = _run_mypy(code)
    assert exit_code != 0, f"mypy should have failed on typo: {stdout}"
    assert "'Item' has no field 'typo'" in stdout, stdout
    assert "'Item' has no field 'name'" not in stdout, f"name should be valid: {stdout}"


def test_tuple_optional_element_validates() -> None:
    """tuple[Address | None, Address][0].attr must validate against Address."""
    code = (
        _PREAMBLE
        + """
class Address(BaseModel):
    city: str

class Model(BaseModel):
    pair: tuple[Address | None, Address]

p_ok = pointer_from_model(Model).pair[0].city
p_bad = pointer_from_model(Model).pair[0].typo
"""
    )
    stdout, stderr, exit_code = _run_mypy(code)
    assert exit_code != 0, f"mypy should have failed on typo: {stdout}"
    assert "'Address' has no field 'typo'" in stdout, stdout
    assert "'Address' has no field 'city'" not in stdout, (
        f"city should be valid: {stdout}"
    )


def test_optional_chain_validates() -> None:
    """Optional[Inner] is peeled and chained access validates against Inner."""
    code = (
        _PREAMBLE
        + """
class Inner(BaseModel):
    thing: str

class Outer(BaseModel):
    opt_inner: Inner | None = None

p_ok = pointer_from_model(Outer).opt_inner.thing
p_bad = pointer_from_model(Outer).opt_inner.typo
"""
    )
    stdout, stderr, exit_code = _run_mypy(code)
    assert exit_code != 0, f"mypy should have failed: {stdout}"
    assert "'Inner' has no field 'typo'" in stdout, stdout
    assert "'Inner' has no field 'thing'" not in stdout, (
        f"thing should be valid: {stdout}"
    )


def test_nested_tuple_chained_index_validates() -> None:
    """tuple[tuple[Item, Item], ...][0][0].attr must validate against Item."""
    code = (
        _PREAMBLE
        + """
class Item(BaseModel):
    name: str

class Model(BaseModel):
    grid: tuple[tuple[Item, Item], tuple[Item, Item]]

p_ok = pointer_from_model(Model).grid[0][0].name
p_bad = pointer_from_model(Model).grid[0][0].typo
"""
    )
    stdout, stderr, exit_code = _run_mypy(code)
    assert exit_code != 0, f"mypy should have failed on typo: {stdout}"
    assert "'Item' has no field 'typo'" in stdout, stdout
    assert "'Item' has no field 'name'" not in stdout, f"name should be valid: {stdout}"


def test_tuple_string_index_validates_element() -> None:
    """tuple[A, B]['0'].attr must validate the same as tuple[A, B][0].attr."""
    code = (
        _PREAMBLE
        + """
class Address(BaseModel):
    city: str

class Model(BaseModel):
    pair: tuple[Address, Address]

p_ok = pointer_from_model(Model).pair["0"].city
p_bad = pointer_from_model(Model).pair["0"].typo
"""
    )
    stdout, stderr, exit_code = _run_mypy(code)
    assert exit_code != 0, f"mypy should have failed on typo: {stdout}"
    assert "'Address' has no field 'typo'" in stdout, stdout
    assert "'Address' has no field 'city'" not in stdout, (
        f"city should be valid: {stdout}"
    )


def test_inherited_field_validates() -> None:
    """Fields inherited from a parent BaseModel are still resolvable."""
    code = (
        _PREAMBLE
        + """
class Parent(BaseModel):
    parent_field: str

class Child(Parent):
    child_field: int

p_ok = pointer_from_model(Child).parent_field
p_bad = pointer_from_model(Child).typo
"""
    )
    stdout, stderr, exit_code = _run_mypy(code)
    assert exit_code != 0, f"mypy should have failed: {stdout}"
    assert "'Child' has no field 'typo'" in stdout, stdout
    # The first line is valid — must not error
    assert "'Child' has no field 'parent_field'" not in stdout, (
        f"inherited field must resolve: {stdout}"
    )


def test_invalid_index_negative_int() -> None:
    """Negative integer indices are not valid RFC 6901 array tokens."""
    code = (
        _PREAMBLE
        + """
class Address(BaseModel):
    city: str

class Order(BaseModel):
    items: list[Address]

p = pointer_from_model(Order).items[-1].city
"""
    )
    stdout, stderr, exit_code = _run_mypy(code)
    assert exit_code != 0, f"mypy should have failed: {stdout}"
    assert "negative integers are not valid RFC 6901 array tokens" in stdout, stdout


def test_invalid_index_non_digit_string() -> None:
    """String indices that are not valid RFC 6901 array tokens are rejected."""
    code = (
        _PREAMBLE
        + """
class Address(BaseModel):
    city: str

class Order(BaseModel):
    items: list[Address]

p = pointer_from_model(Order).items["abc"].city
"""
    )
    stdout, stderr, exit_code = _run_mypy(code)
    assert exit_code != 0, f"mypy should have failed: {stdout}"
    assert "invalid array token" in stdout, stdout


def test_invalid_index_leading_zero_string() -> None:
    """String indices with leading zeros (except '0') are not valid RFC 6901 tokens."""
    code = (
        _PREAMBLE
        + """
class Address(BaseModel):
    city: str

class Order(BaseModel):
    items: list[Address]

p = pointer_from_model(Order).items["00"].city
"""
    )
    stdout, stderr, exit_code = _run_mypy(code)
    assert exit_code != 0, f"mypy should have failed: {stdout}"
    assert "invalid array token" in stdout, stdout


def test_valid_index_dash_string() -> None:
    """The '-' tail marker is a valid RFC 6901 array token and must not be rejected."""
    code = (
        _PREAMBLE
        + """
class Address(BaseModel):
    city: str

class Order(BaseModel):
    items: list[Address]

p = pointer_from_model(Order).items["-"]
"""
    )
    stdout, stderr, exit_code = _run_mypy(code)
    assert exit_code == 0, f"mypy errors: {stdout}"


def test_list_tail_marker_chained_attr_context_lost_error() -> None:
    """list[Address]['-'].city must be a static error: context is lost after ['-'].

    '-' loses model context for list fields. The plugin preserves the item type
    as pending so the attr hook emits "context was lost" rather than a false
    "has no field" error. This matches the runtime AttributeError.
    """
    code = (
        _PREAMBLE
        + """
class Address(BaseModel):
    city: str

class Order(BaseModel):
    items: list[Address]

q = pointer_from_model(Order).items["-"].city
"""
    )
    stdout, stderr, exit_code = _run_mypy(code)
    assert exit_code != 0, (
        f"mypy should have failed (context lost after ['-']): {stdout}"
    )
    assert "'Address' has no field 'city'" not in stdout, stdout
    assert "'Address' has no field" not in stdout, stdout
    assert "context" in stdout.lower(), stdout


def test_list_tail_marker_nested_reindex_context_lost_error() -> None:
    """rows['-'][0] on list[list[Item]] must be a static error at the [0] step.

    After ['-'], the plugin stores NoneType() as a sentinel in args[1] (not
    the item type list[Item]).  The subsequent [0] detects the NoneType sentinel
    and emits a "context was lost after '-' token" error rather than recovering
    model context from list[Item].  This matches the runtime AttributeError that
    rows['-'][0].name raises.
    """
    code = (
        _PREAMBLE
        + """
class Item(BaseModel):
    name: str

class Grid(BaseModel):
    rows: list[list[Item]]

q = pointer_from_model(Grid).rows["-"][0].name
"""
    )
    stdout, stderr, exit_code = _run_mypy(code)
    assert exit_code != 0, (
        f"mypy should have failed (context lost after ['-'][0]): {stdout}"
    )
    assert "'Item' has no field 'name'" not in stdout, stdout
    assert "'Item' has no field" not in stdout, stdout
    assert "context" in stdout.lower(), stdout


def test_tuple_homogeneous_tail_marker_error_on_index_step() -> None:
    """tuple[T, ...]['-'] must produce a type error at the indexing step.

    TupleAdapter ALWAYS rejects '-' at traversal time for both homogeneous and
    fixed-length tuples, so the plugin catches it immediately rather than
    deferring to a later .attr step (which would allow [0] to falsely recover
    model context before the error fires).
    """
    code = (
        _PREAMBLE
        + """
class Address(BaseModel):
    city: str

class Order(BaseModel):
    items: tuple[Address, ...]

p = pointer_from_model(Order).items["-"]
"""
    )
    stdout, stderr, exit_code = _run_mypy(code)
    assert exit_code != 0, f"mypy should have failed: {stdout}"
    assert "TupleAdapter" in stdout or "not valid for tuple" in stdout, stdout
    assert "has no field" not in stdout, stdout


def test_tuple_homogeneous_tail_marker_chained_attr_error() -> None:
    """tuple[T, ...]['-'].attr must emit an error.

    The error must come from the '-' indexing step itself (TupleAdapter always
    rejects '-' for tuples) and must not falsely report 'has no field city'.
    """
    code = (
        _PREAMBLE
        + """
class Address(BaseModel):
    city: str

class Order(BaseModel):
    items: tuple[Address, ...]

q = pointer_from_model(Order).items["-"].city
"""
    )
    stdout, stderr, exit_code = _run_mypy(code)
    assert exit_code != 0, f"mypy should have failed: {stdout}"
    assert "TupleAdapter" in stdout or "not valid for tuple" in stdout, stdout
    assert "'Address' has no field 'city'" not in stdout, stdout


def test_tuple_homogeneous_int_index_preserves_model_context() -> None:
    """tuple[T, ...][int_index].attr must still validate against T after the fix."""
    code = (
        _PREAMBLE
        + """
class Address(BaseModel):
    city: str

class Order(BaseModel):
    items: tuple[Address, ...]

p = pointer_from_model(Order).items[0].typo
"""
    )
    stdout, stderr, exit_code = _run_mypy(code)
    assert exit_code != 0, f"mypy should have failed on typo: {stdout}"
    assert "'Address' has no field 'typo'" in stdout, stdout


def test_tuple_fixed_tail_marker_error_on_index_step() -> None:
    """tuple[A, B]['-'] must produce a type error at the indexing step.

    TupleAdapter ALWAYS rejects '-' for fixed-length tuples; the plugin catches it
    immediately so a subsequent [i] cannot falsely recover model context.
    """
    code = (
        _PREAMBLE
        + """
class Address(BaseModel):
    city: str

class Model(BaseModel):
    pair: tuple[Address, Address]

p = pointer_from_model(Model).pair["-"]
"""
    )
    stdout, stderr, exit_code = _run_mypy(code)
    assert exit_code != 0, f"mypy should have failed: {stdout}"
    assert "TupleAdapter" in stdout or "not valid for tuple" in stdout, stdout
    assert "has no field" not in stdout, stdout


def test_tuple_fixed_tail_marker_chained_attr_error() -> None:
    """tuple[A, B]['-'].attr must emit an error.

    The error comes from the '-' indexing step and must not falsely report
    'has no field city' (which would indicate a false model-context recovery).
    """
    code = (
        _PREAMBLE
        + """
class Address(BaseModel):
    city: str

class Model(BaseModel):
    pair: tuple[Address, Address]

q = pointer_from_model(Model).pair["-"].city
"""
    )
    stdout, stderr, exit_code = _run_mypy(code)
    assert exit_code != 0, f"mypy should have failed: {stdout}"
    assert "TupleAdapter" in stdout or "not valid for tuple" in stdout, stdout
    assert "'Address' has no field 'city'" not in stdout, stdout


def test_tuple_fixed_tail_marker_re_index_no_false_positive() -> None:
    """tuple[A, B]['-'][i].attr must not falsely type-check as a model field access.

    After ['-'] emits an error, the chain collapses to _ModelPath[Any, Any] so that
    a subsequent [i].attr does not recover a specific model and falsely validate.
    """
    code = (
        _PREAMBLE
        + """
class Address(BaseModel):
    city: str

class Model(BaseModel):
    pair: tuple[Address, Address]

q = pointer_from_model(Model).pair["-"][0].city
"""
    )
    stdout, stderr, exit_code = _run_mypy(code)
    # The error is on the ["-"] step; subsequent accesses must not claim city is
    # invalid on Address (which would indicate false model-context recovery).
    assert "'Address' has no field 'city'" not in stdout, stdout


def test_tuple_homogeneous_literal_var_tail_marker_error_on_index_step() -> None:
    """tuple[T, ...][TOKEN] where TOKEN: Literal['-'] must produce a type error.

    The plugin detects Literal['-'] via type inference even when the value comes
    from a named variable, and must reject it for tuple fields at the indexing step.
    """
    code = (
        _PREAMBLE
        + """
from typing import Literal

class Address(BaseModel):
    city: str

class Order(BaseModel):
    items: tuple[Address, ...]

TOKEN: Literal["-"] = "-"
p = pointer_from_model(Order).items[TOKEN]
"""
    )
    stdout, stderr, exit_code = _run_mypy(code)
    assert exit_code != 0, f"mypy should have failed: {stdout}"
    assert "TupleAdapter" in stdout or "not valid for tuple" in stdout, stdout
    assert "has no field" not in stdout, stdout


def test_tuple_homogeneous_literal_var_tail_marker_chained_attr_error() -> None:
    """tuple[T, ...][TOKEN].attr where TOKEN: Literal['-'] must emit an error.

    The plugin detects Literal['-'] via type inference (not just inline StrExpr)
    and emits the error at the indexing step, matching the inline-literal behavior.
    """
    code = (
        _PREAMBLE
        + """
from typing import Literal

class Address(BaseModel):
    city: str

class Order(BaseModel):
    items: tuple[Address, ...]

TOKEN: Literal["-"] = "-"
q = pointer_from_model(Order).items[TOKEN].city
"""
    )
    stdout, stderr, exit_code = _run_mypy(code)
    assert exit_code != 0, f"mypy should have failed: {stdout}"
    assert "TupleAdapter" in stdout or "not valid for tuple" in stdout, stdout
    assert "'Address' has no field 'city'" not in stdout, stdout


def test_field_direct_rootmodel_wrapping_basemodel_attr_access() -> None:
    """pointer_from_model(Holder).wrapped.field where wrapped: RootModel[Inner]
    must succeed — plugin must peel the direct generic RootModel[Inner] annotation."""
    code = (
        _PREAMBLE
        + """
from pydantic import RootModel

class Inner(BaseModel):
    field: str

class Holder(BaseModel):
    wrapped: RootModel[Inner]

p = pointer_from_model(Holder).wrapped.field
"""
    )
    stdout, stderr, exit_code = _run_mypy(code)
    assert exit_code == 0, f"mypy errors: {stdout}"
    assert "has no field" not in stdout


def test_field_direct_rootmodel_wrapping_basemodel_invalid_attr() -> None:
    """Typos on Inner must be caught even when field type is direct RootModel[Inner]."""
    code = (
        _PREAMBLE
        + """
from pydantic import RootModel

class Inner(BaseModel):
    field: str

class Holder(BaseModel):
    wrapped: RootModel[Inner]

p = pointer_from_model(Holder).wrapped.typo
"""
    )
    stdout, stderr, exit_code = _run_mypy(code)
    assert exit_code != 0, f"mypy should have failed: {stdout}"
    assert "has no field 'typo'" in stdout


def test_invalid_index_bool_literal() -> None:
    """Boolean literals True/False are not valid RFC 6901 array tokens."""
    code = (
        _PREAMBLE
        + """
class Address(BaseModel):
    city: str

class Order(BaseModel):
    items: list[Address]

p = pointer_from_model(Order).items[True].city
"""
    )
    stdout, stderr, exit_code = _run_mypy(code)
    assert exit_code != 0, f"mypy should have failed: {stdout}"
    assert "invalid array index" in stdout and "bool" in stdout.lower(), stdout


def test_invalid_index_bool_typed_expression() -> None:
    """Bool-typed variable must be rejected even though it's not a literal True/False."""
    code = (
        _PREAMBLE
        + """
class Address(BaseModel):
    city: str

class Order(BaseModel):
    items: list[Address]

flag: bool = True
p = pointer_from_model(Order).items[flag].city
"""
    )
    stdout, stderr, exit_code = _run_mypy(code)
    assert exit_code != 0, f"mypy should have failed: {stdout}"
    assert "invalid array index" in stdout and "bool" in stdout.lower(), stdout


def test_invalid_index_bool_attr_access() -> None:
    """Bool attribute access (obj.flag) must be rejected as an array index."""
    code = (
        _PREAMBLE
        + """
class Address(BaseModel):
    city: str

class Order(BaseModel):
    items: list[Address]

class Flags:
    active: bool = True

flags = Flags()
p = pointer_from_model(Order).items[flags.active].city
"""
    )
    stdout, stderr, exit_code = _run_mypy(code)
    assert exit_code != 0, f"mypy should have failed: {stdout}"
    assert "invalid array index" in stdout and "bool" in stdout.lower(), stdout


def test_invalid_index_bool_call() -> None:
    """Bool-returning function call must be rejected as an array index."""
    code = (
        _PREAMBLE
        + """
class Address(BaseModel):
    city: str

class Order(BaseModel):
    items: list[Address]

def is_active() -> bool:
    return True

p = pointer_from_model(Order).items[is_active()].city
"""
    )
    stdout, stderr, exit_code = _run_mypy(code)
    assert exit_code != 0, f"mypy should have failed: {stdout}"
    assert "invalid array index" in stdout and "bool" in stdout.lower(), stdout


def test_invalid_index_bool_comparison() -> None:
    """Comparison expression (always bool) must be rejected as an array index."""
    code = (
        _PREAMBLE
        + """
class Address(BaseModel):
    city: str

class Order(BaseModel):
    items: list[Address]

p = pointer_from_model(Order).items[1 == 1].city
"""
    )
    stdout, stderr, exit_code = _run_mypy(code)
    assert exit_code != 0, f"mypy should have failed: {stdout}"
    assert "invalid array index" in stdout and "bool" in stdout.lower(), stdout


def test_invalid_index_after_context_loss_bool() -> None:
    """RFC 6901 token validation applies even after model context is lost (AnyType pending).

    After an ambiguous-union field collapses context, bad tokens like True must
    still be rejected by the plugin rather than silently accepted.
    """
    code = (
        _PREAMBLE
        + """
class A(BaseModel):
    x: str

class B(BaseModel):
    y: str

class Event(BaseModel):
    payload: list[A] | list[B]

p = pointer_from_model(Event).payload[True]
"""
    )
    stdout, stderr, exit_code = _run_mypy(code)
    assert exit_code != 0, f"mypy should have failed: {stdout}"
    assert "invalid array index" in stdout and "bool" in stdout.lower(), stdout


def test_invalid_index_after_context_loss_negative() -> None:
    """Negative indices are rejected even after model context loss."""
    code = (
        _PREAMBLE
        + """
class A(BaseModel):
    x: str

class B(BaseModel):
    y: str

class Event(BaseModel):
    payload: list[A] | list[B]

p = pointer_from_model(Event).payload[-1]
"""
    )
    stdout, stderr, exit_code = _run_mypy(code)
    assert exit_code != 0, f"mypy should have failed: {stdout}"
    assert "negative integers are not valid RFC 6901 array tokens" in stdout, stdout


def test_invalid_index_after_context_loss_bad_string() -> None:
    """Non-RFC-6901 string tokens are rejected even after model context loss."""
    code = (
        _PREAMBLE
        + """
class A(BaseModel):
    x: str

class B(BaseModel):
    y: str

class Event(BaseModel):
    payload: list[A] | list[B]

p = pointer_from_model(Event).payload["abc"]
"""
    )
    stdout, stderr, exit_code = _run_mypy(code)
    assert exit_code != 0, f"mypy should have failed: {stdout}"
    assert "invalid array token" in stdout, stdout


def test_rootmodel_list_union_int_indexable_no_false_positive() -> None:
    """RootModel[list[Item]] | int field must accept [0] without a false-positive error.

    _has_any_indexable_branch must peel the RootModel wrapper to find the inner
    list so that fields typed as RootModel[list[X]] | int are not rejected.
    """
    code = (
        _PREAMBLE
        + """
from pydantic import RootModel

class Item(BaseModel):
    value: str

class Holder(BaseModel):
    data: RootModel[list[Item]] | int

p = pointer_from_model(Holder).data[0]
"""
    )
    stdout, stderr, exit_code = _run_mypy(code)
    assert exit_code == 0, f"mypy errors: {stdout}"
    assert "non-list" not in stdout, stdout


def test_leaf_field_attr_chain_rejected() -> None:
    """Chaining .attr after a leaf field must be a type error matching runtime AttributeError.

    pointer_from_model(User).name.city fails at runtime with AttributeError because
    _model_ctx_lost is set after a leaf type; the plugin must report the same statically.
    """
    code = (
        _PREAMBLE
        + """
class User(BaseModel):
    name: str

p = pointer_from_model(User).name.city
"""
    )
    stdout, stderr, exit_code = _run_mypy(code)
    assert exit_code != 0, f"mypy should have failed: {stdout}"
    assert "cannot chain .city" in stdout, stdout
    assert "model type context was lost" in stdout, stdout


def test_leaf_field_attr_chain_no_cascade() -> None:
    """After the first error on a leaf-field chain, further accesses must not cascade.

    Runtime stops at the first bad step; the plugin must suppress follow-on errors.
    """
    code = (
        _PREAMBLE
        + """
class User(BaseModel):
    name: str

p = pointer_from_model(User).name.city.zip
"""
    )
    stdout, stderr, exit_code = _run_mypy(code)
    assert exit_code != 0, f"mypy should have failed: {stdout}"
    assert "cannot chain .city" in stdout, stdout
    assert "cannot chain .zip" not in stdout, f"cascade error on .zip: {stdout}"


def test_list_field_direct_attr_chain_rejected() -> None:
    """Chaining .attr directly on a list field (without [index]) must be rejected.

    pointer_from_model(Order).items.city fails at runtime (_model_ctx_lost); plugin must agree.
    """
    code = (
        _PREAMBLE
        + """
class Item(BaseModel):
    label: str

class Order(BaseModel):
    items: list[Item]

p = pointer_from_model(Order).items.label
"""
    )
    stdout, stderr, exit_code = _run_mypy(code)
    assert exit_code != 0, f"mypy should have failed: {stdout}"
    assert "cannot chain .label" in stdout, stdout
    assert "model type context was lost" in stdout, stdout


def test_tuple_literal_var_index_validates_element() -> None:
    """tuple[A, B][IDX] where IDX: Literal[0] must validate .attr against the element model.

    _extract_int_index must resolve Literal[int] named variables so that type-checking
    is not silently lost when the index is stored in a variable instead of an inline literal.
    """
    code = (
        _PREAMBLE
        + """
from typing import Literal

class Address(BaseModel):
    city: str

class Model(BaseModel):
    pair: tuple[Address, Address]

IDX: Literal[0] = 0
p_ok = pointer_from_model(Model).pair[IDX].city
p_bad = pointer_from_model(Model).pair[IDX].typo
"""
    )
    stdout, stderr, exit_code = _run_mypy(code)
    assert exit_code != 0, f"mypy should have failed on typo: {stdout}"
    assert "'Address' has no field 'typo'" in stdout, stdout
    assert "'Address' has no field 'city'" not in stdout, (
        f"city should be valid: {stdout}"
    )


def test_literal_str_var_index_validates_element() -> None:
    """tuple[A, B][IDX] where IDX: Literal['0'] must validate .attr against the element model.

    _extract_int_index must convert a named Literal[str] digit-string to an int
    so that tuple-element type-checking is not silently lost.
    """
    code = (
        _PREAMBLE
        + """
from typing import Literal

class Address(BaseModel):
    city: str

class Model(BaseModel):
    pair: tuple[Address, Address]

IDX: Literal["0"] = "0"
p_ok = pointer_from_model(Model).pair[IDX].city
p_bad = pointer_from_model(Model).pair[IDX].typo
"""
    )
    stdout, stderr, exit_code = _run_mypy(code)
    assert exit_code != 0, f"mypy should have failed on typo: {stdout}"
    assert "'Address' has no field 'typo'" in stdout, stdout
    assert "'Address' has no field 'city'" not in stdout, (
        f"city should be valid: {stdout}"
    )


def test_literal_var_negative_index_rejected() -> None:
    """A named Literal[-1] variable used as index must be rejected as RFC 6901 invalid."""
    code = (
        _PREAMBLE
        + """
from typing import Literal

class Item(BaseModel):
    value: str

class Order(BaseModel):
    items: list[Item]

BAD: Literal[-1] = -1
p = pointer_from_model(Order).items[BAD]
"""
    )
    stdout, stderr, exit_code = _run_mypy(code)
    assert exit_code != 0, f"mypy should have failed: {stdout}"
    assert "negative integers are not valid RFC 6901 array tokens" in stdout, stdout


def test_literal_var_invalid_string_token_rejected() -> None:
    """A named Literal['abc'] variable used as index must be rejected as RFC 6901 invalid."""
    code = (
        _PREAMBLE
        + """
from typing import Literal

class Item(BaseModel):
    value: str

class Order(BaseModel):
    items: list[Item]

TOKEN: Literal["abc"] = "abc"
p = pointer_from_model(Order).items[TOKEN]
"""
    )
    stdout, stderr, exit_code = _run_mypy(code)
    assert exit_code != 0, f"mypy should have failed: {stdout}"
    assert "invalid array token" in stdout, stdout


def test_invalid_field_no_cascade_errors() -> None:
    """After one invalid field access, subsequent accesses must not emit cascade errors.

    Runtime stops at the first bad token; the plugin must collapse the chain to
    Any after the first error so that follow-on .attr checks are suppressed.
    """
    code = (
        _PREAMBLE
        + """
class Address(BaseModel):
    city: str

class Profile(BaseModel):
    address: Address

p = pointer_from_model(Profile).address.typo.city
"""
    )
    stdout, stderr, exit_code = _run_mypy(code)
    assert exit_code != 0, f"mypy should have failed: {stdout}"
    assert "'Address' has no field 'typo'" in stdout, stdout
    # After the invalid field the chain collapses to Any; .city must not produce
    # a second 'Address has no field city' error (city IS a valid Address field).
    assert "'Address' has no field 'city'" not in stdout, f"cascade error: {stdout}"


def test_optional_fixed_tuple_index_validates_element() -> None:
    """Optional[tuple[A, B]][literal_index].attr must advance to A/B and validate.

    When the field type is tuple[Address, Address] | None, indexing must peel the
    Optional wrapper and advance into the element model, not lose context.
    """
    code = (
        _PREAMBLE
        + """
from typing import Optional

class Address(BaseModel):
    city: str

class Model(BaseModel):
    pair: Optional[tuple[Address, Address]]

p_ok = pointer_from_model(Model).pair[0].city
p_bad = pointer_from_model(Model).pair[0].typo
"""
    )
    stdout, stderr, exit_code = _run_mypy(code)
    assert exit_code != 0, f"mypy should have failed: {stdout}"
    assert "'Address' has no field 'typo'" in stdout, stdout
    assert "'Address' has no field 'city'" not in stdout, stdout


def test_optional_fixed_tuple_tail_marker_error() -> None:
    """Optional[tuple[A, B]]['-'] must produce a type error.

    The '-' tail-pointer is rejected by TupleAdapter regardless of Optional wrapping;
    the plugin must peel Optional before checking for TupleType.
    """
    code = (
        _PREAMBLE
        + """
from typing import Optional

class Address(BaseModel):
    city: str

class Model(BaseModel):
    pair: Optional[tuple[Address, Address]]

p = pointer_from_model(Model).pair["-"]
"""
    )
    stdout, stderr, exit_code = _run_mypy(code)
    assert exit_code != 0, f"mypy should have failed: {stdout}"
    assert "TupleAdapter" in stdout or "not valid for tuple" in stdout, stdout


def test_optional_fixed_tuple_out_of_range_error() -> None:
    """Optional[tuple[A, B]][2] must emit an out-of-range error.

    The index-range diagnostic must work through the Optional wrapper.
    """
    code = (
        _PREAMBLE
        + """
from typing import Optional

class Address(BaseModel):
    city: str

class Model(BaseModel):
    pair: Optional[tuple[Address, Address]]

p = pointer_from_model(Model).pair[2].city
"""
    )
    stdout, stderr, exit_code = _run_mypy(code)
    assert exit_code != 0, f"mypy should have failed: {stdout}"
    assert "out of range" in stdout, stdout


def test_optional_rootmodel_tuple_tail_marker_error() -> None:
    """Optional[RootModel[tuple[A, B]]]['-'] must produce a type error.

    The plugin must peel Optional then retry the RootModel peel before checking
    for TupleType. Without the retry, the code stops at the RootModel Instance
    and misses the tuple-tail diagnostic entirely.
    """
    code = (
        _PREAMBLE
        + """
from typing import Optional
from pydantic import RootModel

class Address(BaseModel):
    city: str

class Pair(RootModel[tuple[Address, Address]]):
    pass

class Holder(BaseModel):
    wrapped: Optional[Pair]

p = pointer_from_model(Holder).wrapped["-"]
"""
    )
    stdout, stderr, exit_code = _run_mypy(code)
    assert exit_code != 0, f"mypy should have failed: {stdout}"
    assert "TupleAdapter" in stdout or "not valid for tuple" in stdout, stdout


def test_optional_rootmodel_tuple_index_no_false_positive() -> None:
    """Optional[RootModel[tuple[A, B]]][0].city must pass without 'non-list' error.

    The plugin must peel Optional then retry RootModel to reach the TupleType
    and handle concrete integer indexing correctly.
    """
    code = (
        _PREAMBLE
        + """
from typing import Optional
from pydantic import RootModel

class Address(BaseModel):
    city: str

class Pair(RootModel[tuple[Address, Address]]):
    pass

class Holder(BaseModel):
    wrapped: Optional[Pair]

p = pointer_from_model(Holder).wrapped[0].city
"""
    )
    stdout, stderr, exit_code = _run_mypy(code)
    assert exit_code == 0, f"mypy errors: {stdout}"
    assert "non-list" not in stdout, stdout

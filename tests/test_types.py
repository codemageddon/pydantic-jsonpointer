from __future__ import annotations

import pytest
from pydantic import BaseModel

from pydantic_jsonpointer import JsonPointer


@pytest.mark.parametrize(
    "value",
    [
        "",
        "/",
        "/foo",
        "/foo/0",
        "/a~1b",
        "/m~0n",
    ],
)
def test_valid_pointer(value: str) -> None:
    ptr = JsonPointer(value)
    assert str(ptr) == value


@pytest.mark.parametrize(
    "value, match",
    [
        ("foo", r"must be empty or start with '/'"),
        ("~", r"must be empty or start with '/'"),
        ("/foo/~2", r"Invalid escape in JSON Pointer"),
        ("/~", r"Invalid escape in JSON Pointer"),
        ("/foo~", r"Invalid escape in JSON Pointer"),
        ("/a/b~", r"Invalid escape in JSON Pointer"),
        ("/~0/~", r"Invalid escape in JSON Pointer"),
    ],
)
def test_invalid_pointer_raises(value: str, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        JsonPointer(value)


@pytest.mark.parametrize("value", [123, None, b"/x", 1.5, ["/x"]])
def test_constructor_rejects_non_string_with_type_error(value: object) -> None:
    # The direct constructor is public; non-str inputs must surface a clear
    # TypeError rather than leak implementation-detail AttributeError from
    # ``startswith`` or similar string-only methods.
    with pytest.raises(TypeError, match="JsonPointer requires a str"):
        JsonPointer(value)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "pointer_str, expected_tokens",
    [
        ("", ()),
        ("/foo", ("foo",)),
        ("/foo/0", ("foo", "0")),
        ("/", ("",)),
        ("/a~1b", ("a/b",)),
        ("/c%d", ("c%d",)),
        ("/e^f", ("e^f",)),
        ("/g|h", ("g|h",)),
        ("/i\\j", ("i\\j",)),
        ('/k"l', ('k"l',)),
        ("/ ", (" ",)),
        ("/m~0n", ("m~n",)),
    ],
)
def test_tokens_rfc6901_examples(
    pointer_str: str, expected_tokens: tuple[str, ...]
) -> None:
    ptr = JsonPointer(pointer_str)
    assert ptr.tokens == expected_tokens


def test_tokens_return_type_is_tuple() -> None:
    assert isinstance(JsonPointer("/foo/0").tokens, tuple)


def test_tokens_empty_pointer_is_empty_tuple() -> None:
    assert JsonPointer("").tokens == ()


def test_tokens_property_returns_same_object_as_internal_attribute() -> None:
    ptr = JsonPointer("/foo/0")
    assert ptr.tokens is ptr._tokens


@pytest.mark.parametrize(
    "tokens, expected_str",
    [
        (("foo",), "/foo"),
        (("0",), "/0"),
        (("foo", "a/b", "~"), "/foo/a~1b/~0"),
    ],
)
def test_construction_equivalence(tokens: tuple[str, ...], expected_str: str) -> None:
    from_tokens_ptr = JsonPointer.from_tokens(*tokens)
    chained_ptr: JsonPointer = JsonPointer()
    for t in tokens:
        chained_ptr = chained_ptr / t
    parsed_ptr = JsonPointer(expected_str)

    assert str(from_tokens_ptr) == expected_str
    assert str(chained_ptr) == expected_str
    assert str(parsed_ptr) == expected_str

    assert from_tokens_ptr.tokens == tokens
    assert chained_ptr.tokens == tokens
    assert parsed_ptr.tokens == tokens


@pytest.mark.parametrize(
    "tokens, expected_str",
    [
        (("a/b", "~", "c"), "/a~1b/~0/c"),
        (("x~y", "p/q"), "/x~0y/p~1q"),
        (("foo", "a/b", "~"), "/foo/a~1b/~0"),
    ],
)
def test_fast_path_construction_consistency(
    tokens: tuple[str, ...], expected_str: str
) -> None:
    from_tokens_ptr = JsonPointer.from_tokens(*tokens)
    assert str(from_tokens_ptr) == expected_str
    assert from_tokens_ptr.tokens == tokens

    chained: JsonPointer = JsonPointer()
    for t in tokens:
        chained = chained / t
    assert str(chained) == expected_str
    assert chained.tokens == tokens


class M(BaseModel):
    p: JsonPointer


def test_pydantic_validate_tokens() -> None:
    m = M.model_validate({"p": "/foo/0"})
    assert m.p.tokens == ("foo", "0")


def test_pydantic_model_dump_json() -> None:
    m = M(p=JsonPointer("/x"))
    assert m.model_dump_json() == '{"p":"/x"}'


def test_pydantic_json_schema_is_string_type() -> None:
    schema = M.model_json_schema()
    assert schema["properties"]["p"]["type"] == "string"


def test_pydantic_validate_existing_jsonpointer_preserves_value() -> None:
    ptr = JsonPointer("/foo/0")
    m = M.model_validate({"p": ptr})
    assert m.p == ptr
    assert m.p.tokens == ptr.tokens


def test_pydantic_validate_repairs_mutated_tokens() -> None:
    ptr = JsonPointer("/foo")
    ptr._tokens = ("bar",)  # intentionally corrupt internal state
    m = M.model_validate({"p": ptr})
    assert str(m.p) == "/foo"
    assert m.p.tokens == ("foo",)


def test_from_tokens_no_args_returns_root_pointer() -> None:
    ptr = JsonPointer.from_tokens()
    assert str(ptr) == ""
    assert ptr.tokens == ()


def test_from_tokens_integer_tokens() -> None:
    ptr = JsonPointer.from_tokens("foo", 0, 1)
    assert str(ptr) == "/foo/0/1"
    assert ptr.tokens == ("foo", "0", "1")


def test_truediv_with_integer_token() -> None:
    ptr = JsonPointer("/foo") / 0
    assert str(ptr) == "/foo/0"
    assert ptr.tokens == ("foo", "0")


def test_public_import_is_same_type() -> None:
    from pydantic_jsonpointer.types import JsonPointer as _JsonPointerDirect

    assert JsonPointer is _JsonPointerDirect


def test_pydantic_validate_reconstructs_broken_instance() -> None:
    broken: JsonPointer = str.__new__(JsonPointer, "/foo/0")
    assert not hasattr(broken, "_tokens")
    m = M.model_validate({"p": broken})
    assert m.p.tokens == ("foo", "0")

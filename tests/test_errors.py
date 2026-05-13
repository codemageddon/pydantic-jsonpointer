from __future__ import annotations

import pytest

from pydantic_jsonpointer.errors import (
    AdapterNotFoundError,
    ImmutableTargetError,
    InvalidTokenError,
    PointerError,
    PointerNotFoundError,
    RootRebindError,
)


def test_pointer_error_is_exception() -> None:
    assert issubclass(PointerError, Exception)


@pytest.mark.parametrize(
    "cls, extra_bases",
    [
        (PointerNotFoundError, (KeyError,)),
        (AdapterNotFoundError, (TypeError,)),
        (InvalidTokenError, (ValueError,)),
        (RootRebindError, ()),
        (ImmutableTargetError, ()),
    ],
)
def test_subclass_hierarchy(cls: type[Exception], extra_bases: tuple[type, ...]) -> None:
    assert issubclass(cls, PointerError)
    for base in extra_bases:
        assert issubclass(cls, base)


@pytest.mark.parametrize(
    "cls",
    [
        PointerError,
        PointerNotFoundError,
        AdapterNotFoundError,
        InvalidTokenError,
        RootRebindError,
        ImmutableTargetError,
    ],
)
def test_instances_are_exceptions(cls: type[Exception]) -> None:
    instance = cls("boom")
    assert isinstance(instance, Exception)
    assert isinstance(instance, PointerError)


def test_pointer_not_found_str_does_not_apply_keyerror_repr_wrapping() -> None:
    # ``KeyError.__str__`` calls ``repr()`` on the single arg, which would
    # surface as e.g. ``"'missing key'"`` (double-quoted). The override on
    # ``PointerNotFoundError`` must restore plain ``str``-style formatting so
    # log/CLI consumers see clean messages.
    err = PointerNotFoundError("missing key")
    assert str(err) == "missing key"

    # The KeyError API surface (args, isinstance) is preserved.
    assert err.args == ("missing key",)
    assert isinstance(err, KeyError)

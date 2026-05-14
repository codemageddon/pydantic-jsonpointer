from __future__ import annotations

import re
import sys
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    if sys.version_info >= (3, 11):
        from typing import Self
    else:
        from typing_extensions import Self

from pydantic import GetCoreSchemaHandler, GetJsonSchemaHandler
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import CoreSchema, core_schema

_INVALID_TILDE_RE = re.compile(r"~(?![01])")


def _escape_token(token: str) -> str:
    """Escape a reference token per RFC 6901 section 3."""
    return token.replace("~", "~0").replace("/", "~1")


def _unescape_token(token: str) -> str:
    """Unescape a reference token per RFC 6901 section 3."""
    return token.replace("~1", "/").replace("~0", "~")


class JsonPointer(str):
    """RFC 6901 JSON Pointer.

    A JSON Pointer is either the empty string (referencing the whole document)
    or a sequence of reference tokens each prefixed by ``/``.

    Construct from a raw string, from individual tokens, or by chaining
    the ``/`` operator::

        ptr = JsonPointer("/foo/0")
        ptr = JsonPointer.from_tokens("foo", 0)
        ptr = JsonPointer() / "foo" / 0
    """

    __slots__ = ("_tokens",)
    _tokens: tuple[str, ...]

    def __new__(cls, value: str = "") -> Self:
        if not isinstance(value, str):
            msg = f"JsonPointer requires a str, got {type(value).__name__}"
            raise TypeError(msg)
        if value != "" and not value.startswith("/"):
            msg = f"JSON Pointer must be empty or start with '/': {value!r}"
            raise ValueError(msg)
        if _INVALID_TILDE_RE.search(value):
            msg = f"Invalid escape in JSON Pointer (~ must be followed by 0 or 1): {value!r}"
            raise ValueError(msg)
        tokens: tuple[str, ...] = (
            ()
            if value == ""
            else tuple(_unescape_token(t) for t in value[1:].split("/"))
        )
        return cls.__with_tokens(value, tokens)

    @classmethod
    def __with_tokens(cls, value: str, tokens: tuple[str, ...]) -> Self:
        instance = str.__new__(cls, value)
        instance._tokens = tokens
        return instance

    @classmethod
    def __get_pydantic_core_schema__(
        cls,
        _source_type: type[Any],
        _handler: GetCoreSchemaHandler,
    ) -> CoreSchema:
        return core_schema.no_info_wrap_validator_function(
            cls._pydantic_validate,
            core_schema.str_schema(),
            serialization=core_schema.to_string_ser_schema(),
        )

    @classmethod
    def __get_pydantic_json_schema__(
        cls,
        _core_schema: CoreSchema,
        handler: GetJsonSchemaHandler,
    ) -> JsonSchemaValue:
        return handler(core_schema.str_schema())

    @classmethod
    def _pydantic_validate(cls, value: Any, handler: Any) -> Self:
        raw = handler(value)
        return cls(raw)

    @classmethod
    def from_tokens(cls, *tokens: str | int) -> Self:
        """Build a pointer from unescaped reference tokens.

        Tokens are escaped per RFC 6901 (``~`` -> ``~0``, ``/`` -> ``~1``).
        """
        if not tokens:
            return cls.__with_tokens("", ())
        str_tokens = tuple(str(t) for t in tokens)
        value = "/" + "/".join(_escape_token(t) for t in str_tokens)
        return cls.__with_tokens(value, str_tokens)

    def __truediv__(self, token: str | int) -> Self:
        """Append a reference token: ``ptr / "key" / 0``."""
        str_token = str(token)
        new_value = str(self) + "/" + _escape_token(str_token)
        new_tokens = self._tokens + (str_token,)
        return type(self).__with_tokens(new_value, new_tokens)

    @property
    def tokens(self) -> tuple[str, ...]:
        """Decompose into unescaped reference tokens."""
        return self._tokens

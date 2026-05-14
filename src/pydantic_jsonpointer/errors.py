"""Error types for pointer-traversal APIs.

Kept in a dedicated module so that the adapter layer (which must raise these)
can import them without depending on the traversal layer, which would create
an import cycle.
"""

from __future__ import annotations


class PointerError(Exception):
    """Base class for all pointer-traversal errors."""


class PointerNotFoundError(PointerError, KeyError):
    """Raised when a path step expects a value to exist and it does not.

    Inherits from ``KeyError`` so callers can ``except KeyError``. ``__str__``
    is overridden because ``KeyError.__str__`` calls ``repr`` on its single
    arg, which would wrap our already human-readable messages in stray quotes
    (e.g. ``"'missing key'"`` instead of ``missing key``).
    """

    def __str__(self) -> str:
        return Exception.__str__(self)


class AdapterNotFoundError(PointerError, TypeError):
    """Raised when no ContainerAdapter is registered for a value's type."""


class InvalidTokenError(PointerError, ValueError):
    """Raised when a token cannot be resolved against the current container
    (e.g. non-decimal token for a list, unknown field name for a model)."""


class RootRebindError(PointerError):
    """Raised when set/add/remove is attempted on the root Ptr.

    Python functions cannot rebind a caller's variable; callers must replace
    the document themselves.
    """


class ImmutableTargetError(PointerError):
    """Raised when set/add/remove is attempted on a target that is under a
    frozen binding (transitive). See BaseModelAdapter.is_step_frozen."""

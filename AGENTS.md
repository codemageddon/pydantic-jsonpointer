# AGENTS.md

## Commands

Prefer `mise run <task>` where available, otherwise use `uv run`:

| Task | mise | Direct |
|------|------|--------|
| sync deps | `mise run sync` | `uv sync --frozen` |
| lint+format check | `mise run ruff` | `uv run ruff check . && uv run ruff format --check .` |
| typecheck (strict) | `mise run mypy` | `uv run mypy src tests` |
| test suite | `mise run pytest` | `uv run pytest` |
| full CI | `mise run ci` | — |
| single test | — | `uv run pytest tests/test_<file>.py::test_<name>` |
| build | — | `uv build` |

## Version

Bump `VERSION` in `src/pydantic_jsonpointer/__version__.py` — never in `pyproject.toml`.

## Critical invariants

- **`__init__.py` line 36** (`register(_BaseModel, BaseModelAdapter(), override=True)`) — must be preserved. It's a side-effect registration on import that makes pydantic traversal work out of the box.

- **Never construct `Ptr` outside `_iter_resolve`.** The function is the single allocation point. Tests use private helpers (`_dict_ptr`, `_list_ptr`) for unit isolation but production code must go through `resolve()`.

- **`...` (Ellipsis) is the project-wide sentinel** for both "no unwrap" (`ContainerAdapter.unwrap`) and "no default" (`Ptr.try_get`). Do not add new sentinel concepts — reuse `...`.

- **Token escaping** must go through `_escape_token` / `_unescape_token` in `types.py`. Never hand-roll `~0`/`~1` escapes.

- **Frozen taint is transitive** — once set at any step, all descendant `Ptr` slots inherit it.

- **`pointer_from_model()`** constructs pointers by chaining model attribute access with automatic alias resolution. Accepts classes or instances; for Union-typed fields, narrow with `isinstance` and pass the narrowed value. The `_ModelPath` proxy is private; always go through `pointer_from_model()`.

- **`_advance`** (in `_model_path.py`) walks type annotations to determine model class advancement for `_ModelPath`. Uses `model_fields["root"].annotation` for RootModel inner types, not `typing.get_args` (pydantic RootModels return bare classes, not generic aliases).

## Repository layout

- `src/pydantic_jsonpointer/` — eight modules: `types.py`, `adapters.py`, `pydantic_adapter.py`, `traversal.py`, `errors.py`, `__init__.py`, `_model_path.py`, `mypy_plugin.py`
- `tests/` — mirrors with `test_types.py`, `test_adapters.py`, `test_pydantic_adapter.py`, `test_traversal.py`, `test_errors.py`, `test_model_path.py`, `test_mypy_plugin.py`
- `docs/` — MkDocs source; `mise run docs:serve` for live preview

## Design docs

- Spec: `docs/superpowers/specs/2026-05-13-pointer-traversal-design.md`
- Plan: `docs/superpowers/plans/2026-05-14-pointer-traversal.md`

Full architecture details in `CLAUDE.md`.

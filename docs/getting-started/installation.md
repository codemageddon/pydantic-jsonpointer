# Installation

`pydantic-jsonpointer` requires **Python 3.10–3.14** and **Pydantic 2.x**. The only runtime dependency is `pydantic>=2.0,<3`.

## Install

=== "uv"

    ```shell
    uv add pydantic-jsonpointer
    ```

=== "pip"

    ```shell
    pip install pydantic-jsonpointer
    ```

=== "poetry"

    ```shell
    poetry add pydantic-jsonpointer
    ```

=== "pdm"

    ```shell
    pdm add pydantic-jsonpointer
    ```

## What's imported

Importing the package side-effect-registers `BaseModelAdapter` against `pydantic.BaseModel`, so traversal of any `BaseModel` subclass works out of the box without explicit setup:

```python
import pydantic_jsonpointer  # registration happens here
```

The registration uses `override=True`, so `importlib.reload(pydantic_jsonpointer)` is safe.

## Python version support

`pydantic-jsonpointer` is tested on Python 3.10 through 3.14.

## Next steps

Continue to the [Quickstart](quickstart.md) to walk and mutate your first document.

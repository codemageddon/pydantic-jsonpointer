# Contributing

This page covers local documentation preview, strict builds, and how publishing works.

## Prerequisites

Install the docs dependency group:

```bash
uv sync --group docs
```

This installs `mkdocs`, `mkdocs-material`, `mkdocstrings[python]`, and `pymdown-extensions` into your project virtualenv.

## Local preview

Start a live-reload server:

```bash
mise run docs:serve
```

The site is served at `http://127.0.0.1:8000/`. Changes to any file under `docs/`, to `mkdocs.yml`, or to the source under `src/pydantic_jsonpointer/` (the latter through mkdocstrings) are reflected immediately without restarting.

## Strict build

Validate the entire site with `--strict` mode (warnings become errors):

```bash
mise run docs:build
```

This is the same command CI runs. It catches broken internal links, unresolved `mkdocstrings` references, and misconfigured nav entries. The output is written to `site/` (git-ignored).

**Run this before opening a PR** — a clean strict build is required to merge docs changes.

## Writing docs

- Pages live under `docs/` and are plain Markdown with [Material for MkDocs](https://squidfunk.github.io/mkdocs-material/) extensions.
- Code blocks use triple-backtick fences with a language tag (`python`, `bash`, `yaml`, …).
- Admonitions use the `!!! note` / `!!! warning` / `!!! tip` syntax.
- Tabbed blocks use `=== "Tab"` syntax from `pymdownx.tabbed`.
- API reference pages under `docs/reference/` are stubs that defer to `:::module.path` directives rendered by `mkdocstrings`. Update the source docstrings (Google style) rather than the reference page itself when the public API changes.

## Publishing

Publishing is fully GitHub-Actions-driven — there is no `gh-pages` branch. `.github/workflows/docs.yaml` runs on every push to `main` (and on `workflow_dispatch`):

1. **Build job** — checks out the repo, installs the `docs` dependency group, runs `mkdocs build --strict`, and uploads `site/` as a GitHub Pages artifact via `actions/upload-pages-artifact`.
2. **Deploy job** — downloads the artifact and publishes it with `actions/deploy-pages` to the `github-pages` environment.

Concurrency is grouped under `pages` so two pushes in flight don't race; `cancel-in-progress: false` lets each push complete its deploy.

### Required repository settings

1. **Settings → Pages → Build and deployment → Source = "GitHub Actions"**. This is the only valid source for the `actions/deploy-pages` flow; "Deploy from a branch" will not work.
2. **Settings → Pages → Custom domain = `pydantic-jsonpointer.codemageddon.me`**. The `docs/CNAME` file is copied to the site root by mkdocs on every build, so the custom domain survives every deploy. Tick **Enforce HTTPS** once the certificate has provisioned.

### One version, always latest

Unlike a mike-based setup, this pipeline publishes exactly one version — whatever is on `main` at the time of the last push. There is no version selector. If you need versioned docs later, the cleanest options are (a) reintroduce `mike` and switch back to gh-pages branch publishing, or (b) deploy from tags into per-version subdirectories of the same artifact.

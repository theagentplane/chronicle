# Releasing

Chronicle publishes to PyPI as **`agent-chronicle`**. Releases are published by the `Release`
workflow when a `v*` tag is pushed. It uses PyPI Trusted Publishing (OIDC), so no API token is
stored anywhere.

## One-time setup

1. On PyPI, add a **publisher** for the project `agent-chronicle`:
   owner `theagentplane`, repository `chronicle`, workflow `release.yml`, environment `pypi`.
2. In the GitHub repository settings, create an environment named `pypi` and add **required
   reviewers** so a human approves each publish.
3. (Recommended) Do a dry run against TestPyPI the first time:
   ```bash
   uv build
   uv run twine upload --repository testpypi dist/*
   ```

## Cutting a release

1. Bump `__version__` in `src/chronicle/_version.py`. This is the only place the version lives.
2. Move the `[Unreleased]` entries in `CHANGELOG.md` under the new version and date. Each entry is
   classified **compatible** or **breaking** and names the migration each consumer needs.
3. Merge that change to `main` through a pull request.
4. Tag and push: `git tag v<version> && git push origin v<version>`.
5. Approve the `pypi` environment deployment when prompted.

The workflow refuses to publish if the tag does not match `_version.py`.

## Version choice

Follow [docs/versioning.md](docs/versioning.md). While pre-1.0, a breaking change is a new minor
version and consumers pin the exact minor. Check that the `agentplane-primitives` pin in
`pyproject.toml` is the minor you tested against.

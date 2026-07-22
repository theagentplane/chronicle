# Releasing

Chronicle publishes to PyPI as **`agent-chronicle`** using GitHub Actions with
**Trusted Publishing (OIDC)** — no API tokens are stored anywhere.

## One-time setup

1. Create the project on PyPI by configuring a **pending publisher**:
   PyPI → *Your projects* → *Publishing* → add a GitHub Actions publisher with:
   - PyPI project name: `agent-chronicle`
   - Owner: `theagentplane`
   - Repository: `chronicle`
   - Workflow filename: `release.yml`
   - Environment name: `pypi`
2. In the GitHub repo, create an **Environment** named `pypi`
   (Settings → Environments). Optionally add required reviewers.
3. (Recommended) Do a dry run against **TestPyPI** first:
   ```bash
   python -m build
   twine upload --repository testpypi dist/*
   pip install --index-url https://test.pypi.org/simple/ agent-chronicle
   ```

## Cutting a release

1. Move the `CHANGELOG.md` `[Unreleased]` items under a new version heading with
   today's date; start a fresh empty `[Unreleased]`.
2. Bump `version` in `pyproject.toml` following SemVer
   (`0.1.0` → `0.1.1` patch, `0.2.0` minor, `1.0.0` first stable API).
3. Commit and tag:
   ```bash
   git commit -am "Release vX.Y.Z"
   git tag vX.Y.Z
   git push && git push --tags
   ```
4. Create a **GitHub Release** from the tag. Publishing the release triggers
   `release.yml`, which builds and uploads to PyPI automatically.
5. Verify:
   ```bash
   pip install agent-chronicle==X.Y.Z
   ```

## Versioning notes

- Stay in `0.x` while the Envelope schema may still change; signal instability.
- Any change to the Envelope schema is at least a **minor** bump and must ship
  with a fixture migration path (see `CONTRIBUTING.md`).

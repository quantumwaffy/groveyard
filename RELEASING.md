# Releasing

Notes for maintainers cutting a groveyard release. Ordinary contributors do
not need this file — see [CONTRIBUTING.md](CONTRIBUTING.md) instead.

## Versioning

groveyard follows [Semantic Versioning](https://semver.org/). While the major
version is `0`, treat a minor bump (`0.1.0` → `0.2.0`) as the breaking-change
boundary and a patch bump (`0.1.0` → `0.1.1`) as backwards compatible.

## One-time setup (already done, kept here for reference)

1. The PyPI project `groveyard` is configured with a
   [trusted publisher](https://docs.pypi.org/trusted-publishers/) pointing at
   `quantumwaffy/groveyard`, workflow `release.yml`, environment `pypi`. This
   is what lets CI publish without a long-lived API token stored as a secret.
2. GitHub Pages is configured to deploy from the `gh-pages` branch, which
   `docs.yml` pushes to.

## Cutting a release

1. **Make sure `master` is green:** `uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest` and the CI workflow both pass.
2. **Update [`CHANGELOG.md`](CHANGELOG.md):** move the `[Unreleased]` entries
   under a new `## [X.Y.Z] - YYYY-MM-DD` heading, and add a fresh empty
   `[Unreleased]` section above it. Update the comparison links at the bottom
   of the file.
3. **Bump the version** in `pyproject.toml` (`[project].version`) to match.
4. **Commit** both changes together:
   ```bash
   git commit -am "Release vX.Y.Z"
   ```
5. **Tag and push:**
   ```bash
   git tag -a vX.Y.Z -m "vX.Y.Z"
   git push origin master vX.Y.Z
   ```
6. Pushing the `v*` tag triggers `.github/workflows/release.yml`, which
   builds the sdist and wheel, runs `twine check`, and publishes to PyPI via
   trusted publishing. Watch the
   [Actions tab](https://github.com/quantumwaffy/groveyard/actions) for the
   run.
7. **Draft the GitHub release** from the pushed tag, pasting the relevant
   `CHANGELOG.md` section as the release notes.
8. **Verify:** `pip install groveyard==X.Y.Z` in a clean environment, and
   check that <https://quantumwaffy.github.io/groveyard/changelog/> reflects
   the new version (the docs site redeploys automatically on every push to
   `master`, including the release commit).

## If a release goes wrong

PyPI releases cannot be overwritten — a bad upload must be
[yanked](https://pypi.org/help/#yanked) (which keeps it installable for
projects already pinned to it, but hides it from resolution otherwise) and
followed by a new patch version. Never delete and re-upload the same version
number.

# Python packaging and PyPI publishing

## Package and verify

Preserve the existing build backend, supported Python versions, package layout, and version source. Add missing `pyproject.toml` metadata, runtime dependencies, package data, and public entrypoints. Resolve the intended distribution name and ownership; do not silently rename an existing package. Use the project's release tag convention, defaulting to `v<version>` only when none exists.

Build wheel and sdist with the project toolchain. Check metadata and archive contents for missing runtime files and unwanted secrets or local artifacts. Run `twine check` or an equivalent artifact metadata check. In clean environments outside the source checkout, install the wheel and build/install from the sdist; verify imports, package data, and public CLI behavior. This catches accidental reliance on local source files or development dependencies.

## Configure releases

Adapt existing release CI rather than adding a competing publisher. Run quality gates and verify that the release tag resolves to the intended package version. Respect existing version formats; do not require semantic versioning when the project uses another valid Python version convention.

Separate building/testing from publication. Upload the verified distributions as workflow artifacts, then download those same artifacts in a dedicated publishing job. Give only that job `id-token: write`; it should retrieve artifacts and publish, without checking out or executing project source. Restrict the release workflow and publishing environment to the intended release tags. Pin actions to current verified commit SHAs with readable version comments.

Use PyPI Trusted Publishing instead of a long-lived upload token. Match the PyPI publisher's GitHub owner, repository, workflow filename, and environment exactly. For an absent distribution, configure a pending publisher through the authenticated PyPI account. Request login/account access when missing; never ask for a password, token, or recovery code in chat. Verify the publisher settings were actually saved.

Set up TestPyPI only when selected or needed for an agreed upload rehearsal; it requires separate publisher configuration. A successful TestPyPI upload does not prove production PyPI settings are correct.

## Completion and reruns

Configure publication without creating a release tag unless a release is authorized. Report any account setup that remains blocked precisely. When a first publication is authorized, confirm the registry version and test installation from the intended index in a clean environment.

Versions cannot be overwritten on PyPI. After an interrupted upload, inspect the version and its files before retrying; distinguish identical published artifacts from a partial or conflicting release. Reuse existing publishers and environments on reruns, preserving their protections.

Sources: [packaging tutorial](https://packaging.python.org/en/latest/tutorials/packaging-projects/), [Trusted Publishing](https://docs.pypi.org/trusted-publishers/using-a-publisher/), [pending publishers](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/), [publisher security](https://docs.pypi.org/trusted-publishers/security-model/).

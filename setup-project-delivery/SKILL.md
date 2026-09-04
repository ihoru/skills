---
name: setup-project-delivery
description: Set up Docker delivery for a project, with optional Python packaging and PyPI publishing, and optional GitHub Actions deployment to a server using docker run or Compose. Invoke explicitly with $setup-project-delivery.
---

# Set up project delivery

Turn the selected delivery capabilities into working project configuration and verified setup. Docker is the default path; PyPI and server deployment are independent options. Adapt existing setup instead of replacing it with a preferred stack.

## Establish the delivery contract

1. Read repository instructions, inspect the worktree and remote, and locate existing build commands, lockfiles, CI, packaging, and deployment configuration. Follow any required specification process before implementation. Preserve unrelated edits.
2. Determine the actual runtime: entrypoint, target architecture, services, ports, configuration sources, persistent data, shutdown behavior, and an observable readiness check. Reuse the project's tools and version conventions.
3. Resolve only missing choices. For an invocation without options, ask whether to add PyPI publishing and server deployment. Offer PyPI only for Python distributions. Infer `docker run` versus Compose from the application and existing setup; ask when both remain plausible. For deployment, resolve registry visibility and whether the first replacement should happen now or on a later `main` push. Carry forward existing answers and authorization.
4. State the selected capabilities and acceptance checks. Distinguish repository preparation from external setup and the first live release. Honor explicit holds on commits, pushes, or publication; do all authorized preparation before reporting a remaining access requirement.

Use current official documentation for provider configuration and CLI syntax. Prefer Context7 when available, resolving the library first; otherwise use official documentation directly. Do not freeze action versions or runtime versions from an unrelated project into the result.

## Implement selected paths

- **Docker:** Read [Docker setup](references/docker.md). Finish with a production image that builds and passes the project's relevant checks and runtime smoke test.
- **PyPI, when selected:** Read [Python packaging and publishing](references/pypi.md). Finish with verified wheel/sdist artifacts and a configured release workflow; distinguish configuration from a completed upload.
- **Server deployment, when selected:** Read [GitHub and server setup](references/deployment.md), then the matching [docker run](references/docker-run.md) or [Compose](references/compose.md) reference. Finish with verified runner access and registry pulls before enabling replacement.

Keep implementation in the target project: build/runtime files, applicable CI, deployment helpers, and concise operator documentation. Generate helpers for its runtime contract; this skill supplies guidance, not a universal privileged deployment script. Use a server-supported interpreter and installed Docker/Compose versions.

## Verify and hand off

Run repository-required checks and validate changed workflows. Exercise new deployment command validation, readiness failure, and recovery with fake Docker/SSH calls before using live infrastructure. Verify the selected path end to end within the user's authorized scope.

Document exact build, run, release, deployment-disable, and recovery commands applicable to this project. Report what is configured, what was actually tested, and what remains awaiting access or the chosen release event. For a live deployment, include the running revision and an application-level acceptance result. For setup-only work, compare the original and final running container identities and start times.

Respect the user's current commit/push instructions. Invocation alone does not authorize publishing a release or replacing production when those actions were excluded or deferred. Do not describe a future deployment or PyPI upload as already verified.

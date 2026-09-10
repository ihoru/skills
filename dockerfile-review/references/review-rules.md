# Dockerfile review rules

Apply these rules as an evidence filter, not as a list of warnings to emit. A rule becomes a finding only when the repository or an authorized check establishes its premise.

## Finding confidence and severity

- **Confirmed:** the supplied files or an executed check prove the defect and its relevant context.
- **Contextual:** the improvement depends on a stated production, reproducibility, compatibility, or security requirement. Name that requirement and the evidence for it.
- **Not observable:** the property requires other files, image metadata, CI/registry state, runtime configuration, or host access. Mention it only when it materially limits a requested conclusion.

Use severity for impact rather than taste:

- `critical`: exposed credentials or a demonstrated path to immediate compromise or destructive failure;
- `high`: likely security boundary failure, unusable production image, or broken shutdown/readiness behavior;
- `medium`: material correctness, reproducibility, caching, patching, or operability defect;
- `low`: bounded maintainability or efficiency problem with a concrete cost.

## Dockerfile scope

### Base images and stages

- Resolve every `ARG` used by `FROM` from build configuration when possible. An omitted tag and `:latest` are mutable. Version tags are also mutable; present digest pinning as contextual unless repository policy or the user's reproducibility/supply-chain requirement calls for it.
- Pair digest pinning with controlled refreshes, vulnerability scans, and reviewable update proposals. Reproducible but stale images are not a complete security policy.
- Judge image size against required compatibility and operations. Alpine uses musl; distroless and `scratch` may lack a shell, CA certificates, users, time-zone data, dynamic libraries, or probe tools. Verify required runtime assets rather than prescribing one base family.
- In a multi-stage build, trace only artifacts actually copied into the final stage. Confirm dynamic libraries, certificates, ownership, and other runtime dependencies where the application requires them. Multi-stage builds are a means, not a mandatory shape for every image.
- Treat provenance and trust as unestablished unless repository policy, registry configuration, signatures, or attestations provide evidence. An official-looking image name alone does not prove approval.

### Build context, copying, and cache

- Inspect `.dockerignore` using Docker's matching semantics. With a broad `COPY . .` or `ADD . .`, flag sensitive or costly context inclusion only when the ignore rules and repository contents establish it. BuildKit's incremental context transfer does not remove the need to exclude irrelevant or secret files.
- Check that dependency manifests, lockfiles, workspace configuration, and package-manager settings are copied before dependency installation when source churn would otherwise invalidate the expensive layer.
- Recognize intentional `ADD`: local archive extraction, Git sources, and remote URLs with supported verification can be legitimate. Prefer `COPY` for ordinary local files. For remote artifacts, require a checksum or signature when integrity matters; `ADD --checksum` is valid for supported URL sources.
- Verify `COPY --from` names and paths. Do not assume a copied file exists, is executable, or has correct ownership.

### Packages, downloads, and shell behavior

- For apt-based images, keep `apt-get update`, installation with `--no-install-recommends` where appropriate, and removal of `/var/lib/apt/lists/*` in the same `RUN`. Separating update from install can reuse a stale index; cleanup in a later layer does not shrink the earlier layer.
- Apply equivalent cache cleanup according to the actual package manager. Do not recommend commands from another distribution.
- Require lockfile-enforcing or otherwise deterministic dependency installation when the project claims reproducible builds. Package pinning also needs a controlled update path.
- Verify downloaded artifacts with an expected digest or signature. A successful TLS request establishes transport, not artifact identity.
- In shell pipelines, ensure an early failure cannot be masked. Use a shell with `pipefail` or rewrite the command. Account for the shell actually present in the base image.
- A continuation backslash must be the final escape on its physical line. Detect comments or trailing characters that break the intended continuation. Confirm every shown build command includes required arguments such as the build context.

### Secrets

- Treat credentials placed in Dockerfile `ARG` or `ENV`, copied files, URLs, command arguments, or layer-producing `RUN` instructions as confirmed findings because image history or layers can retain them.
- Prefer BuildKit secret or SSH mounts for build-time access and the deployment platform's secret mechanism at runtime. Verify the secret is consumed only in the mounting instruction and is not copied into later layers or artifacts.
- A variable name that merely resembles a secret is evidence for investigation, not proof that a real credential is embedded. Distinguish an input declaration from a literal value.

### User, ownership, and privileges

- Determine the final effective user from the last stage and, when available, base-image metadata. Absence of `USER` in the Dockerfile does not prove root if the base declares a user.
- When the effective user is root and the workload has no demonstrated need for it, report least privilege as a contextual finding; raise severity when production policy or exposed attack surface establishes the impact.
- Verify that `COPY --chown`, created users, numeric IDs, file modes, writable directories, and privileged ports are mutually compatible. Suggest a stable numeric UID/GID only when mounted-volume ownership or cross-environment identity requires it.
- Flag `sudo`, SSH daemons, setuid/setgid files, capabilities, or privilege escalation only in the evidence scope where they are actually present. Some require built-image inspection.

### Startup, PID 1, and shutdown

- Shell-form `ENTRYPOINT` runs through a shell and does not provide exec-form signal behavior. Inspect wrapper scripts; a wrapper that ends with `exec "$@"` or the actual application can correctly hand over PID 1.
- Do not assume every application needs Tini. Recommend an init only when child reaping or signal forwarding requires it, and verify the binary is installed before referencing it.
- Inspect Compose or Kubernetes command/entrypoint overrides before concluding which process starts. Graceful shutdown must be runtime-tested to establish actual signal handling and timing.

### Health and ports

- Dockerfile `HEALTHCHECK` applies to Docker Engine and platforms that consume image health metadata. Kubernetes does not consume it; inspect Kubernetes startup, readiness, and liveness probes separately.
- Verify that a health command exists in the final image and tests meaningful application health. Minimal images may not contain a shell or `curl`; prefer an application-native probe or deliberately included probe binary.
- `EXPOSE` is metadata, not publication or an access-control rule. Compare it with documented listeners and deployment ports, but do not report its absence as a security defect.

### Syntax and native checks

- Check parser directives, stage names, variable expansion, quoting, JSON-array syntax, line continuations, and referenced paths. Distinguish a parse/build failure from a best-practice suggestion.
- Use Docker build checks or a repository-pinned linter as supporting evidence. Preserve justified exclusions and tool versions. A linter result still needs impact and context before it becomes a review finding.

## Other evidence scopes

### Built image

Image inspection can establish the effective user, included packages and tools, file ownership/modes, setuid/setgid files, architecture, labels, layer contents, and vulnerability results. It can also reveal whether a secret survived a build. Do not claim these properties from Dockerfile text when base metadata or generated layers are unknown.

### CI and registry

Look for controlled base/dependency updates, scheduled rebuilds with fresh bases, build and runtime tests, vulnerability gates, trusted registries, artifact verification, image signing, and SBOM/provenance attestations. These controls are not Dockerfile instructions. SBOM/provenance flags prove generation only when CI actually publishes the resulting attestations.

### Runtime and Compose

When runtime configuration is in scope, inspect user overrides, capabilities, `no-new-privileges`, privileged mode, Docker socket mounts, read-only root filesystems with explicit writable paths, secrets, resource limits, ports, networks, init behavior, and restart/health semantics. Report only configuration that is present or demonstrably required.

### Kubernetes

Inspect `securityContext`, `runAsNonRoot`, privilege escalation, capabilities, read-only filesystems, resource requests/limits, service-account-token mounting, image identity, probes, secret delivery, and NetworkPolicies. Absence becomes a finding only when the supplied workload and policy establish the requirement. Never describe Dockerfile `HEALTHCHECK` as a Kubernetes probe.

### Host and daemon

Host patching, rootless/user namespaces, daemon socket exposure, authorization, logging, seccomp/AppArmor/SELinux, and registry transport require host or policy evidence. Keep them outside a Dockerfile-only review.

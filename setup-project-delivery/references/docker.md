# Docker setup

## Build and runtime contract

Inspect the real startup command and dependency workflow before choosing a base image. Keep supported language versions and existing lockfiles. Use build stages when they meaningfully separate compilers, development dependencies, or asset generation from runtime. Run as a non-root user where the application supports it, with explicit ownership of writable paths.

Create or adapt `.dockerignore` so credentials, environment files, VCS metadata, local environments, caches, and generated private data cannot enter the build context. Keep required source, lockfiles, and public runtime assets available. Pass build credentials through secret mounts when needed, not build arguments or image layers. Supply runtime secrets externally and commit only examples with dummy values.

Make the entrypoint propagate signals; define the working directory and writable directories. Select shutdown timeouts, restart policy, logging limits, and any init process from the workload. Record the full source revision in `org.opencontainers.image.revision`; derive image source and version labels from the project. Preserve necessary architecture, GPU, device, and resource settings rather than copying another project's values.

## Runtime layout

For **docker run**, document a reproducible command covering environment sources, user, ports, mounts, networks, logging, restart policy, and graceful shutdown. Avoid exposing internal-only services merely to make a smoke test convenient.

For **Compose**, preserve the project name and volume identities when adapting a running stack. Define application and supporting services, named volumes, networks, and health checks. Separate development conveniences from production configuration; production application services consume prebuilt images. Gate startup dependencies on readiness where needed. Existing databases, proxies, and external networks may remain separately managed.

Choose readiness that means the application can serve its role: a health endpoint, an explicit worker-ready signal, or a safe local probe. A running PID alone is insufficient. Keep probes free of secrets and user content. Record limitations when an external acceptance check is still needed.

## Verification

Run existing checks, then build and test the actual production target on the intended platform. Verify entrypoint behavior, required assets, revision label, readiness, and graceful termination. Use fake credentials and isolated dependencies for smoke tests; do not accidentally start a second consumer of production work.

For Compose, validate the resolved configuration privately, then test the relevant services and dependency readiness in an isolated project. Do not print rendered configuration if it contains secrets.

CI must publish the image it verified, without rebuilding it between verification and push. With multiple architectures, verify each deployed platform and retain the relationship to the published manifest. Obtain the digest from the build/push result for that artifact rather than a shared mutable tag. Hand immutable image references to deployment.

Sources: [Docker build practices](https://docs.docker.com/build/building/best-practices/), [build secrets](https://docs.docker.com/build/building/secrets/), [Compose in production](https://docs.docker.com/compose/how-tos/production/).

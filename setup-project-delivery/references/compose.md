# Deploy a Compose application

Read alongside [server setup](deployment.md). Use installed Docker Compose capabilities; verify support for required flags instead of assuming a plugin version.

## Preserve topology and restrict deployment input

Identify the existing Compose project name, service names, networks, volume identities, environment sources, and separately managed dependencies. Classify services into deployable application images and infrastructure such as databases. Establish readiness, graceful shutdown, migrations, and recovery requirements before enabling deployment.

Keep production Compose files and their referenced configuration root-owned. CI sends only a bounded release manifest mapping the allowlisted application services to validated SHA-256 digests. The helper maps services to fixed image repositories and generates a root-owned image override. Reject unknown/duplicate services, missing required services, invalid digests, extra fields, and arbitrary paths or Compose directives. Several services may intentionally share one application digest.

Record the commit-to-digest mapping for the entire release. Pin infrastructure images in administrator-controlled configuration. Do not let CI replace the base Compose file, choose a project name, set mounts, change privileges, or inject environment values. Topology changes require a separately reviewed administrator update before application deployment.

## Replacement and recovery

Under one server lock, snapshot the prior release mapping and required non-secret configuration, validate the resolved candidate configuration without logging secrets, and pull all candidate images before disrupting running services. Use explicit project/file/environment arguments with trusted paths and a controlled process environment.

Recreate the selected application services using the pinned images, with builds and additional pulls disabled. Preserve existing volumes and networks. Update infrastructure only when it is part of the agreed change. Use `up --wait` with a bounded timeout and meaningful service health checks, plus the application acceptance probe. Services without health checks are only observed as running by `--wait`.

Compose does not make a multi-service rollout atomic. Define singleton-worker sequencing and any tolerated mixed-version interval. When a candidate fails, restore the prior application digest mapping and reconcile the affected services, then verify recovery. Preserve the prior mapping until the new release succeeds; handle interrupted and repeated deployments under the same lock.

Image rollback does not reverse data writes or migrations. Use an agreed backward-compatible migration procedure or a tested backup/restore and maintenance procedure before changing a database schema. Keep migration execution in a fixed administrator-approved command, not arbitrary CI input. If compatibility or recovery is unresolved, complete image/SSH setup but leave deployment disabled and identify the missing decision.

Never use `down --volumes` or volume pruning for deployment or rollback. Preserve named volume identities when changing configuration. Recovery must also account for external storage and databases, not just Docker-managed volumes.

## Verification

Validate Compose syntax privately. In an isolated project with synthetic data, exercise readiness failure, a partial service update, recovery of the prior mapping, and a second invocation. Verify persistent data survives both a successful replacement and failed candidate recovery. Test manifest validation with fake Docker calls so rejected input cannot reach the engine.

On a live acceptance run, verify each application service's expected digest/revision and health plus a user-level operation. Report database backup or migration checks separately; a restored application image is not evidence of restored data.

Sources: [Compose up](https://docs.docker.com/reference/cli/docker/compose/up/), [startup order](https://docs.docker.com/compose/how-tos/startup-order/), [production configuration](https://docs.docker.com/compose/how-tos/production/).

# GitHub Actions and server setup

Use this path for a GitHub repository deploying to one Linux Docker host. Resolve an incompatible provider or orchestration requirement before generating provider-specific configuration.

## Inspect and bootstrap the host

Use existing trusted administrator access. If root SSH is unavailable, request the host, port, and a usable root SSH connection or authorized key setup; credentials stay in the local SSH agent or protected files. Root access is for bootstrap, never the identity stored in Actions.

Record current container identities, start times, image revisions, runtime flags, Compose project/service identities, and persistent storage. Inspect secrets only within protected processing. Reuse existing environment files when possible. If recovery is necessary, compare container configuration with image defaults and write overrides directly into a root-owned mode-600 file without printing values. Preserve explicit overrides and validate serialization: Docker env files and Compose interpolation have different rules, and arbitrary multiline values may require another secret delivery mechanism.

Install project-specific helpers and configuration into root-owned paths with non-writable parent directories. Create a dedicated unprivileged deploy user with no Docker group membership or other sudo grants. Reuse an existing identity only after verifying these constraints. Keep its home, `.ssh`, and `authorized_keys` root-owned while allowing SSH to read the public key file.

Generate a dedicated key outside the repository in a protected directory. Upload the private key directly to Actions secrets through stdin or a secure file interface; install the public key with a forced command, no PTY, and no forwarding. Grant sudo only to the root-owned deployment helper, and validate the sudoers file. Fetch the server's host public key through the trusted administrator connection; pin the exact hostname and port in known_hosts. An unverified `ssh-keyscan` is not a trust source.

The forced command must parse `SSH_ORIGINAL_COMMAND` as data, accepting only a harmless `check` operation and the documented deployment input. Use fixed executable paths and argument arrays, never shell evaluation. Validate digests, image repositories, and service allowlists before any Docker operation. Store lock files under a root-controlled directory such as `/run/<project>/`. Return bounded diagnostics without raw environment or application logs. Changes to privileged configuration use administrator access, not CI-controlled file uploads.

After installation, test the valid check, arbitrary commands, empty/interactive shell requests, malformed deployment inputs, and SSH restrictions. The rejected paths must not invoke Docker or change state. Manage the private key's retained or temporary lifecycle explicitly after verification; never delete an unrelated administrator key.

## GitHub workflow contract

Reuse project CI and registry ownership. Create or adapt a `production` environment restricted to `main`; automatic deployment has no required reviewers unless an existing policy or user instruction requires them. Preserve existing protections and resolve conflicts rather than silently weakening them.

Use these configuration names unless the project already has equivalents:

| Kind | Name | Purpose |
| --- | --- | --- |
| Variable | `DEPLOY_HOST` | Server hostname or IP |
| Variable | `DEPLOY_USER` | Restricted deployment user |
| Variable | `DEPLOY_PORT` | SSH port, default 22 |
| Variable | `DEPLOY_ENABLED` | Deployment switch; false during first bootstrap |
| Secret | `DEPLOY_SSH_KEY` | Dedicated private key |
| Secret | `DEPLOY_KNOWN_HOSTS` | Trusted host-key entries |

Keep deployment secrets in the production environment where supported by the workflow. Use `GITHUB_TOKEN` with `packages: write` only in the publishing job. Use strict SSH host checking and a temporary mode-600 key on runners, cleaning it up at job end. Check port reachability from a runner rather than assuming local SSH success proves it.

The event behavior is explicit:

| Event | Checks | Publish verified image | Deploy |
| --- | --- | --- | --- |
| Push to `main` | Yes | Yes after success | Only when enabled |
| Manual invocation on `main` | Yes | Yes after success | Never; harmless SSH check only |
| PR or other branch | Existing CI checks | No production publication | Never |
| Release tag | Existing release checks | Only existing release policy | Never through this deployment path |

Serialize deployment jobs using a production concurrency group with `cancel-in-progress: false`, and a server-side lock. Ensure workflow-level cancellation cannot interrupt an active replacement. Recheck that the candidate SHA is still the `main` head immediately before SSH; skip stale candidates. Treat failure to determine the head as a deployment failure. Pin deployable images to the verified digest and retain their revision labels; no mutable `latest` deployment or server-side build.

## Registry bootstrap and enablement

1. Keep deployment disabled during first setup. Publish repository changes only when authorized; an explicit commit/push hold leaves this stage pending.
2. Run the manual publish-only workflow on `main` to create an absent GHCR package and verify restricted SSH from a runner. It must never replace services, even if the switch is later enabled.
3. Inspect the actual package visibility. Make it public only when selected; verify anonymous pulls on the host using an empty temporary Docker credential config. For private packages, configure the minimum supported read-only registry access privately on the host and verify a pull. Do not broaden an account token solely to avoid an available authenticated settings UI.
4. Verify every candidate digest is pullable and its revision matches the checked commit. Pulling must not change running containers. Compare recorded identities/start times and inspect any unexpected change before continuing.
5. Wait for or safely cancel redundant setup runs before enabling: a queued push job may observe the switch later. Check active runs, the current `main` SHA, and server state. Then set `DEPLOY_ENABLED=true` for the chosen rollout timing. On reruns, preserve existing settings and keys unless a verified repair or rotation is needed.
6. For a deferred first replacement, report that the next eligible `main` push is the acceptance event. When immediate first deployment is authorized, recheck the candidate against `main` and invoke the same restricted deployment command with the verified digest or release manifest, then run acceptance checks. Keep manual workflow dispatch publish-only; no dummy feature commit is needed.

If a deployment response is interrupted or recovery fails, inspect server state before retrying. Report the original error and recovery result separately. Preserve images and persistent data needed for recovery; do not add automated pruning.

Sources: [Actions concurrency](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency), [deployment environments](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments), [GHCR access](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry), [OpenSSH key restrictions](https://man.openbsd.org/sshd.8#AUTHORIZED_KEYS_FILE_FORMAT).

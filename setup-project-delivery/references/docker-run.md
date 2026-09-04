# Deploy one container with docker run

Read alongside [server setup](deployment.md). Derive the complete runtime contract from the running container and project configuration before generating the helper.

## Command and replacement

Accept `deploy sha256:<64 lowercase hexadecimal characters>` for one fixed image repository, plus the read-only `check` operation. Names, ports, mounts, environment-file locations, network, resources, devices, restart behavior, and shutdown timeout come from root-owned configuration. The deploy key cannot select these flags.

Under the server lock:

1. Validate input and configuration, inspect current/previous state, and pull the candidate before stopping anything. Detect an interrupted prior deployment and recover deliberately rather than overwriting its only rollback container.
2. Stop the current container gracefully and retain it under a previous name. A restart alone does not adopt a new image. Never overlap singleton workers using the same production credentials.
3. Start the candidate by digest with the preserved runtime contract. Check application readiness within a bounded deadline and observe a stability interval without restarts. If using logs for readiness, inspect both stdout and stderr privately.
4. On success, retain the previous container and image for recovery and return the running revision. On failure, stop and remove the failed candidate before restoring the previous name and starting the original container. Verify recovery readiness and report deployment failure even if recovery succeeds.

If no previous container existed, failed initial deployment has no rollback target; leave a clear failed state. A repeated request for an already healthy deployed digest may return success without replacement after confirming the runtime contract still matches.

## Verification and operator instructions

Use fake Docker calls to exercise input rejection, pull failure before downtime, readiness failure, rollback ordering, first deployment failure, and interrupted state. Verify concurrent requests cannot interleave replacement. Preserve the old container's actual configuration during rollback instead of reconstructing it from possibly changed defaults.

Document disabling deployment and waiting for active jobs before manual recovery. After a live replacement, compare the image revision with the intended commit and perform an application-level check. Readiness alone may not verify external message delivery, scheduled work, or end-user behavior.

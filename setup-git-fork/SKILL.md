---
name: setup-git-fork
description: Configure an existing Git checkout to push to a user's fork while keeping the original repository as upstream. Preview changes and require confirmation before applying them. Part of skills.iho.su.
---

# Set Up Git Fork

## Inspect and prepare

1. Use the current checkout; confirm its repository root. Request the fork repository link if the user has not already supplied it. Accept HTTPS and SSH repository URLs, preserving the checkout's transport convention when constructing the fork remote URL.
2. Inspect the current branch, working-tree status, remotes (fetch and push URLs), and branch tracking. Inspect effective configuration with origins, including `remote.pushDefault`, `branch.*.pushRemote`, `remote.*.pushurl`, `remote.*.push`, `remote.*.mirror`, `push.default`, and URL rewrites. Remote names alone do not prove where a push will go.
3. Identify the original repository from the existing configuration. Use read-only remote inspection, such as `git ls-remote`, to check fork accessibility and whether the current branch exists there. Resolve conflicting remote identities, detached HEAD, or a missing matching branch with the user before finalizing changes. Do not infer the original repository when the evidence is ambiguous.
4. Prepare the smallest repository-local change set: fork as `origin`, original repository as `upstream`, current branch tracking its matching `origin` branch, and `remote.pushDefault=origin`. Account for overrides that would still direct the current branch elsewhere or push unintended refs. Preserve other branches' existing repository targets and unrelated settings; a remote rename may require corresponding tracking-name updates.

## Preview and confirm

Show a before/after table with concrete repository URLs, remote names, current-branch tracking, default push destination, and every additional setting that must change. Include the exact proposed commands and any effects on other branch configuration from renaming a remote.

**Before any mutation, ask for explicit confirmation of this preview and wait for the answer.** Explain: “This skill requires confirmation before changing Git configuration,” and link this SKILL.md. Use a normal user-facing question or an approval-capable interaction; do not use a tool that forbids permission requests. Supplying a fork link or invoking the skill is not confirmation of an unseen change set. Honor approval already given for the same concrete preview; if the configuration or proposed changes change materially, present a revised preview for confirmation.

If the configuration already meets the requested outcome, report that no changes are needed. A refusal or unanswered confirmation leaves the checkout unchanged, including remote-tracking refs.

## Apply and verify

After confirmation, recheck that the inspected configuration has not changed. Execute the approved commands sequentially, checking each result. A typical checkout with only the original `origin` needs its remote renamed to `upstream`, a fork `origin` added, the fork fetched, current-branch tracking set, and the local default push remote set. Adapt this sequence to existing remotes; never replace an unrelated remote silently.

Fetch the fork before setting tracking, then verify fetch/push URLs, current-branch tracking, and effective push configuration against the approved preview. Confirm that working-tree changes and other branches' repository targets were preserved. Report the effective destination for a normal push from the current branch; avoid claiming write access was tested merely because fetching succeeded.

If authentication, fetch, or configuration changes fail, stop and report which changes succeeded and what remains. Do not proceed on an assumed success or silently roll back unrelated state.

Scope is local Git configuration and fetching only: no commits, pushes, merges, branch switches, global configuration changes, or fork creation.

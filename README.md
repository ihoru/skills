# Agent Skills

Reusable skills for Codex that turn common development tasks into repeatable workflows.

## Available skills

| Skill | Description | Typical use cases |
| --- | --- | --- |
| [glab-address-discussions](glab-address-discussions/SKILL.md) | Fetch unresolved GitLab merge-request discussions, implement actionable feedback, and validate changes. | Address reviewer feedback; track unresolved comments through implementation. |
| [setup-project-delivery](setup-project-delivery/SKILL.md) | Configure Docker or Compose, optional PyPI publishing, and optional GitHub Actions deployment to a server. | Containerize an application; publish a Python package; deploy automatically after successful `main` checks. |

## Getting started

Clone this repository, then run the following from its root to install a selected skill. Set `skill` to a name from the table above.

```sh
skill=setup-project-delivery
mkdir -p "$HOME/.agents/skills"
ln -s "$PWD/$skill" "$HOME/.agents/skills/$skill"
```

The symlink keeps the repository as the source of truth: pulling updates also updates the installed skill. Keep the checkout in place. Existing installations do not need another symlink.

Invoke an installed skill in Codex while working in the target project:

```text
Use $glab-address-discussions to address the unresolved feedback on GitLab MR !123 in this repository.
```

```text
Use $setup-project-delivery to add Docker Compose and automatic deployment on main pushes. Skip PyPI publishing and keep the running services unchanged until the next feature deployment.
```

`setup-project-delivery` is manually invoked; Codex will not select it automatically.

### Prerequisites

- **GitLab discussions:** Python 3 and `glab`, authenticated to the relevant GitLab host, plus a local checkout of the merge request's source branch. Posting replies and resolving discussions require an explicit request.
- **Project delivery:** The project's build tools and Docker for container verification. Optional server deployment needs GitHub access and root SSH access for bootstrap; Actions uses a separate restricted deployment identity. Optional PyPI publishing needs access to the intended PyPI account or project.

Each skill's linked instructions describe its workflow and validation in detail. When adding or changing a skill, keep its catalog entry and invocation example up to date.

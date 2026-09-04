# Agent Skills

A directory of my reusable skills for Codex, including skills maintained here and skills packaged with other tools.

## Skills in this repository

| Skill | Description | Typical use cases |
| --- | --- | --- |
| [glab-address-discussions](glab-address-discussions/SKILL.md) | Fetch unresolved GitLab merge-request discussions, implement actionable feedback, and validate changes. | Address reviewer feedback; track unresolved comments through implementation. |
| [setup-project-delivery](setup-project-delivery/SKILL.md) | Configure Docker or Compose, optional PyPI publishing, and optional GitHub Actions deployment to a server. | Containerize an application; publish a Python package; deploy automatically after successful `main` checks. |

## Skills packaged with tools

These skills are maintained in their tool repositories. Follow the links for installation and usage; this directory contains only a brief catalog entry.

| Skill | Description | Typical use cases |
| --- | --- | --- |
| [local-transcription](https://github.com/ihoru/local-transcription/tree/main/skills/local-transcription) | Transcribe local audio or video into speaker-labeled TXT and SRT, then proofread the results. | Transcribe recordings; generate subtitles; review transcription errors. |

## Getting started

### Install through your coding agent

Pass the repository link to your coding agent with the skills you want. For a skill packaged with a tool, pass its linked skill directory so the agent installs from the owning repository. For Codex, copy one of these prompts.

**Install one skill:**

```text
Install setup-project-delivery from https://github.com/ihoru/skills for use in Codex. Use the repository's default branch.
```

**Install several named skills:**

```text
Install glab-address-discussions and setup-project-delivery from https://github.com/ihoru/skills for use in Codex. Use the repository's default branch.
```

**Browse first and choose:**

```text
Read the skill directory in https://github.com/ihoru/skills and list all skills, including those linked from other tool repositories, with a short description and use cases for each. Ask me to choose one or more, then install only my selected skills for use in Codex from their owning repositories. Follow linked skill paths and use the default branch for repository-only links.
```

These prompts install the skills; invoke them separately to perform a task.

### Install manually

For a skill listed under **Skills in this repository**, clone this repository and run the following from its root. Set `skill` to the selected name.

```sh
skill=setup-project-delivery
mkdir -p "$HOME/.agents/skills"
ln -s "$PWD/$skill" "$HOME/.agents/skills/$skill"
```

The symlink keeps the repository as the source of truth: pulling updates also updates the installed skill. Keep the checkout in place. Existing installations do not need another symlink.

### Use an installed skill

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

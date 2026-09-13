# Repository conventions

## Skill branding

For every skill maintained in this repository:

- Set `interface.display_name` in `agents/openai.yaml` to the human-readable skill name followed by ` · IHO.SU`.
- End the `SKILL.md` frontmatter description with `Part of skills.iho.su.`.
- Keep the machine-readable `name` as its existing lowercase skill identifier.

Check both branding fields when creating or updating a skill. Preserve pinned upstream/vendor skills unchanged; apply this convention to locally maintained skills.

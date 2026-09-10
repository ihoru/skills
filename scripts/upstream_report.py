#!/usr/bin/env python3
"""Render check --json output as a reviewable PR body (also on validation failure)."""

import json
import sys
from pathlib import Path


def render(report):
    lines = [
        "## Selected upstream updates",
        "",
        "Review the vendored diffs and plugin comparison before merging. Local activation is a separate post-merge step.",
        "",
    ]
    for source in report["sources"]:
        if not source["changed"] and "error" not in source:
            continue
        url = source["repository"].removesuffix(".git")
        old, new = source["old"], source["new"]
        lines += [
            f"### {source['id']}",
            "",
            f"- Previous: [{old[:12]}]({url}/commit/{old})",
        ]
        if new:
            lines += [
                f"- Candidate: [{new[:12]}]({url}/commit/{new})",
                f"- [Full upstream comparison]({url}/compare/{old}...{new})",
            ]
        lines += [
            f"- Validation: {source.get('error', 'passed (paths, frontmatter, licenses, symlinks, plugin structure)')}",
            "- License changes: "
            + ("; ".join(source["license_changes"]) or "none detected"),
            "",
        ]
    lines += [
        "## Activation",
        "",
        "After merging, fast-forward the clean installed checkout and run `python3 scripts/manage_upstreams.py install`. CI never installs skills or plugins on your machine.",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    print(render(json.loads(Path(sys.argv[1]).read_text())))

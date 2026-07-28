#!/usr/bin/env python3
"""Fetch unresolved resolvable discussions from a GitLab merge request."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote


MR_URL_RE = re.compile(
    r"^https?://(?P<hostname>[^/]+)/(?P<repo>.+?)/-/merge_requests/"
    r"(?P<iid>\d+)(?:[/?#].*)?$"
)


class FetchError(RuntimeError):
    """Raised when MR discussions cannot be fetched or parsed."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch unresolved resolvable GitLab MR discussions and render JSON "
            "and Markdown artifacts."
        )
    )
    parser.add_argument("mr", help="Merge request IID or full GitLab MR URL")
    parser.add_argument(
        "--repo",
        help="GitLab project path (group/project); defaults to the current repository",
    )
    parser.add_argument(
        "--hostname",
        help="GitLab hostname; defaults to the MR URL host or current repository host",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        type=Path,
        help="Directory in which to create the output artifacts",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing output artifacts",
    )
    return parser.parse_args()


def resolve_reference(
    mr_reference: str,
    repo_override: str | None,
    hostname_override: str | None,
) -> tuple[int, str | None, str | None]:
    match = MR_URL_RE.fullmatch(mr_reference)
    if match:
        return (
            int(match.group("iid")),
            repo_override or match.group("repo"),
            hostname_override or match.group("hostname"),
        )

    if not mr_reference.isdigit() or int(mr_reference) <= 0:
        raise FetchError(
            "MR must be a positive IID or a full URL ending in "
            "/-/merge_requests/<iid>."
        )

    return int(mr_reference), repo_override, hostname_override


def project_endpoint(repo: str | None) -> str:
    return f"projects/{quote(repo, safe='')}" if repo else "projects/:fullpath"


def run_glab_api(
    endpoint: str,
    *,
    hostname: str | None,
    paginate: bool = False,
    output: str = "json",
) -> str:
    command = ["glab", "api", endpoint, "--output", output]
    if hostname:
        command.extend(["--hostname", hostname])
    if paginate:
        command.append("--paginate")

    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown error"
        raise FetchError(f"glab API request failed: {detail}")
    return result.stdout


def parse_ndjson(payload: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for line_number, line in enumerate(payload.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise FetchError(
                f"Invalid glab NDJSON on line {line_number}: {exc}"
            ) from exc
        if not isinstance(item, dict):
            raise FetchError(
                f"Expected a discussion object on NDJSON line {line_number}."
            )
        items.append(item)
    return items


def is_unresolved_thread(discussion: dict[str, Any]) -> bool:
    notes = discussion.get("notes")
    if not isinstance(notes, list) or not notes:
        return False
    root = notes[0]
    return (
        isinstance(root, dict)
        and root.get("resolvable") is True
        and root.get("resolved") is not True
    )


def keep_human_notes(discussion: dict[str, Any]) -> dict[str, Any]:
    filtered = dict(discussion)
    filtered["notes"] = [
        note
        for note in discussion.get("notes", [])
        if isinstance(note, dict) and note.get("system") is not True
    ]
    return filtered


def compact_mr_metadata(mr: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "id",
        "iid",
        "title",
        "state",
        "draft",
        "source_branch",
        "target_branch",
        "sha",
        "web_url",
        "references",
    )
    return {key: mr.get(key) for key in keys}


def location_for(discussion: dict[str, Any]) -> tuple[str | None, Any]:
    for note in discussion.get("notes", []):
        position = note.get("position") if isinstance(note, dict) else None
        if not isinstance(position, dict):
            continue
        path = position.get("new_path") or position.get("old_path")
        line = position.get("new_line") or position.get("old_line")
        return path, line
    return None, None


def render_markdown(
    mr: dict[str, Any],
    discussions: list[dict[str, Any]],
) -> str:
    iid = mr.get("iid", "?")
    title = mr.get("title") or "(untitled)"
    web_url = mr.get("web_url") or ""
    source = mr.get("source_branch") or "?"
    target = mr.get("target_branch") or "?"
    lines = [
        f"# Unresolved discussions for MR !{iid}",
        "",
        f"- Title: {title}",
        f"- URL: {web_url}",
        f"- Branch: `{source}` -> `{target}`",
        f"- Unresolved resolvable discussions: {len(discussions)}",
        "",
    ]

    for index, discussion in enumerate(discussions, start=1):
        discussion_id = discussion.get("id", "?")
        path, line = location_for(discussion)
        location = f"`{path}:{line}`" if path and line else (f"`{path}`" if path else "general")
        lines.extend(
            [
                f"## {index}. Discussion `{discussion_id}`",
                "",
                f"- Location: {location}",
                "",
            ]
        )

        for note in discussion.get("notes", []):
            author = note.get("author") or {}
            username = author.get("username") or author.get("name") or "unknown"
            created_at = note.get("created_at") or "unknown time"
            note_id = note.get("id", "?")
            body = note.get("body") or ""
            lines.extend(
                [
                    f"### @{username} (note `{note_id}`, {created_at})",
                    "",
                    body,
                    "",
                ]
            )

    return "\n".join(lines).rstrip() + "\n"


def write_artifact(path: Path, content: str, *, force: bool) -> None:
    if path.exists() and not force:
        raise FetchError(f"Refusing to overwrite existing artifact: {path}")
    path.write_text(content, encoding="utf-8")


def artifact_paths(output_dir: Path, *, force: bool) -> tuple[Path, Path]:
    resolved_dir = output_dir.expanduser().resolve()
    resolved_dir.mkdir(parents=True, exist_ok=True)
    json_path = resolved_dir / "unresolved-discussions.json"
    markdown_path = resolved_dir / "unresolved-discussions.md"
    if not force:
        existing = [path for path in (json_path, markdown_path) if path.exists()]
        if existing:
            paths = ", ".join(str(path) for path in existing)
            raise FetchError(f"Refusing to overwrite existing artifacts: {paths}")
    return json_path, markdown_path


def main() -> int:
    args = parse_args()
    if shutil.which("glab") is None:
        raise FetchError("glab is not installed or is not on PATH.")

    iid, repo, hostname = resolve_reference(args.mr, args.repo, args.hostname)
    json_path, markdown_path = artifact_paths(args.output_dir, force=args.force)
    project = project_endpoint(repo)
    mr_endpoint = f"{project}/merge_requests/{iid}"
    discussions_endpoint = f"{mr_endpoint}/discussions?per_page=100"

    try:
        mr_payload = run_glab_api(mr_endpoint, hostname=hostname)
        mr = json.loads(mr_payload)
    except json.JSONDecodeError as exc:
        raise FetchError(f"Invalid merge request JSON: {exc}") from exc
    if not isinstance(mr, dict):
        raise FetchError("Expected the merge request API to return an object.")

    discussion_payload = run_glab_api(
        discussions_endpoint,
        hostname=hostname,
        paginate=True,
        output="ndjson",
    )
    all_discussions = parse_ndjson(discussion_payload)
    unresolved = [
        keep_human_notes(discussion)
        for discussion in all_discussions
        if is_unresolved_thread(discussion)
    ]

    result = {
        "merge_request": compact_mr_metadata(mr),
        "unresolved_count": len(unresolved),
        "discussions": unresolved,
    }

    write_artifact(
        json_path,
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        force=args.force,
    )
    write_artifact(
        markdown_path,
        render_markdown(result["merge_request"], unresolved),
        force=args.force,
    )

    summary = {
        "mr_iid": iid,
        "mr_url": mr.get("web_url"),
        "source_branch": mr.get("source_branch"),
        "target_branch": mr.get("target_branch"),
        "unresolved_count": len(unresolved),
        "json_path": str(json_path),
        "markdown_path": str(markdown_path),
    }
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except FetchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)

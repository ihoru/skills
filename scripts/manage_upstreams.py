#!/usr/bin/env python3
"""Review upstream snapshots separately from activating local skills."""

import argparse
import copy
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath

import yaml


class Invalid(ValueError):
    pass


class UniqueLoader(yaml.SafeLoader):
    def construct_mapping(self, node, deep=False):
        result = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if key in result:
                raise Invalid(f"Duplicate frontmatter key: {key}")
            result[key] = self.construct_object(value_node, deep=deep)
        return result


def run(*args, cwd=None):
    result = subprocess.run(
        args, cwd=cwd, capture_output=True, timeout=180, check=False
    )
    if result.returncode:
        raise Invalid(
            f"{args[0]} failed: {result.stderr.decode(errors='replace').strip()}"
        )
    return result.stdout


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_manifest(root):
    data = json.loads((root / "upstreams.json").read_text())
    if (
        data.get("version") != 1
        or not isinstance(data.get("sources"), list)
        or not data["sources"]
    ):
        raise Invalid("Expected manifest version 1 and nonempty sources")
    ids, names = set(), set()
    for source in data["sources"]:
        ident = source["id"]
        if (
            not isinstance(ident, str)
            or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", ident)
            or ident in ids
        ):
            raise Invalid("Invalid or duplicate source ID")
        ids.add(ident)
        if source["kind"] not in ("skills", "plugin"):
            raise Invalid("Invalid source kind")
        if not re.fullmatch(r"[0-9a-f]{40}", source["commit"]):
            raise Invalid("Commit must be a full SHA")
        if (
            not source["ref"]
            or source["ref"].startswith("-")
            or any(c.isspace() for c in source["ref"])
        ):
            raise Invalid("Invalid tracked ref")
        repository = source["repository"]
        if not (
            repository.startswith("https://github.com/")
            or Path(repository).is_absolute()
        ):
            raise Invalid(
                "Repository must be a GitHub HTTPS URL or absolute local fixture path"
            )
        if (
            not source["attribution"]
            or not source["license"]["spdx"]
            or not source["license"]["evidence"]
        ):
            raise Invalid("Missing attribution or license evidence")
        for evidence in source["license"]["evidence"]:
            safe_path(evidence["path"])
            if not re.fullmatch(r"[0-9a-f]{64}", evidence["sha256"]):
                raise Invalid("Invalid license hash")
            if evidence.get("field") not in (None, "license"):
                raise Invalid("Unsupported license evidence field")
        if not source["selections"]:
            raise Invalid("Empty selections")
        for item in source["selections"]:
            safe_path(item["path"])
            name = item["name"]
            if (
                not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name)
                or name in names
                or name == "provenance"
            ):
                raise Invalid("Invalid or duplicate skill name")
            names.add(name)
            if item["destination"] != f"vendor/{ident}/{name}":
                raise Invalid("Destination must be vendor/<source>/<name>")
            if not re.fullmatch(r"[0-9a-f]{40}", item["tree"]):
                raise Invalid("Invalid selected tree hash")
        if source["kind"] == "plugin":
            safe_path(source["marketplace_path"])
            if not re.fullmatch(r"[a-z0-9-]+", source["marketplace"]):
                raise Invalid("Invalid marketplace name")
            if len(source["selections"]) != 1:
                raise Invalid("Plugin sources require one complete plugin selection")
    return data


def safe_path(value):
    path = PurePosixPath(value)
    if (
        not value
        or path.is_absolute()
        or ".." in path.parts
        or ".git" in path.parts
        or str(path) != value
    ):
        raise Invalid(f"Unsafe relative path: {value}")


def frontmatter(content):
    lines = content.decode().splitlines()
    if not lines or lines[0] != "---" or "---" not in lines[1:]:
        raise Invalid("Missing SKILL.md frontmatter")
    try:
        metadata = yaml.load(
            "\n".join(lines[1 : lines.index("---", 1)]), Loader=UniqueLoader
        )
    except yaml.YAMLError as error:
        raise Invalid(f"Malformed SKILL.md frontmatter: {error}") from error
    if not isinstance(metadata, dict):
        raise Invalid("Frontmatter must be a mapping")
    return metadata


def fetch(source, directory):
    run("git", "init", "-q", str(directory))
    run(
        "git",
        "-C",
        str(directory),
        "fetch",
        "-q",
        "--depth=1",
        "--no-tags",
        "--",
        source["repository"],
        source["ref"],
    )
    return run("git", "-C", str(directory), "rev-parse", "FETCH_HEAD").decode().strip()


def blob(repo, sha, path):
    return run("git", "-C", str(repo), "show", f"{sha}:{path}")


def snapshot(repo, sha, path, target):
    # Read Git blobs directly: archive export-ignore/export-subst would alter snapshots.
    entries = run("git", "-C", str(repo), "ls-tree", "-rz", f"{sha}:{path}").split(
        b"\0"
    )
    target.mkdir(parents=True)
    links = []
    for entry in filter(None, entries):
        header, name = entry.split(b"\t", 1)
        mode, kind, oid = header.decode().split()
        name = name.decode()
        safe_path(name)
        if kind != "blob" or mode not in ("100644", "100755", "120000"):
            raise Invalid(f"Unsupported Git entry: {name}")
        content = run("git", "-C", str(repo), "cat-file", "blob", oid)
        dest = target / name
        if mode == "120000":
            links.append((dest, content.decode()))
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(content)
            dest.chmod(0o755 if mode == "100755" else 0o644)
    for dest, link in links:
        if Path(link).is_absolute():
            raise Invalid(f"Unsafe symlink: {dest.name}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.symlink_to(link)
    for dest, _ in links:
        try:
            resolved = dest.resolve(strict=True)
        except (OSError, RuntimeError) as error:
            raise Invalid(f"Broken or cyclic symlink: {dest.name}") from error
        if not resolved.is_relative_to(target.resolve()):
            raise Invalid(f"Escaping symlink: {dest.name}")


def directory_hash(directory):
    records = []
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            records.append(
                [str(path.relative_to(directory)), "link", os.readlink(path)]
            )
        elif path.is_file():
            records.append(
                [
                    str(path.relative_to(directory)),
                    "executable" if path.stat().st_mode & 0o111 else "file",
                    digest(path.read_bytes()),
                ]
            )
    return digest(json.dumps(records, ensure_ascii=True).encode())


def inspect(source, repo, sha, stage):
    candidate = copy.deepcopy(source)
    candidate["commit"] = sha
    changed = False
    paths = (
        run("git", "-C", str(repo), "ls-tree", "-rz", "--name-only", sha)
        .decode()
        .split("\0")
    )
    license_paths = {
        p
        for p in paths
        if p
        and re.fullmatch(
            r"(?:licen[sc]e|copying|notice)(?:[._-].*)?",
            PurePosixPath(p).name,
            re.IGNORECASE,
        )
        and (
            "/" not in p
            or any(p.startswith(s["path"] + "/") for s in source["selections"])
        )
    }
    declared = {e["path"] for e in source["license"]["evidence"] if not e.get("field")}
    if license_paths != declared:
        raise Invalid(
            f"{source['id']}: license evidence paths changed: {sorted(license_paths ^ declared)}"
        )
    for evidence in source["license"]["evidence"]:
        content = blob(repo, sha, evidence["path"])
        if evidence.get("field"):
            content = str(frontmatter(content).get(evidence["field"], "")).encode()
        if digest(content) != evidence["sha256"]:
            raise Invalid(
                f"{source['id']}: license change detected at {evidence['path']}; review evidence before updating"
            )
        evidence_dest = (
            stage / "vendor" / source["id"] / "provenance" / evidence["path"]
        )
        if evidence.get("field"):
            evidence_dest = evidence_dest.with_name(evidence_dest.name + ".license")
        evidence_dest.parent.mkdir(parents=True, exist_ok=True)
        evidence_dest.write_bytes(content)
    for selection in candidate["selections"]:
        tree = (
            run("git", "-C", str(repo), "rev-parse", f"{sha}:{selection['path']}")
            .decode()
            .strip()
        )
        changed |= tree != selection["tree"]
        selection["tree"] = tree
        snapshot(repo, sha, selection["path"], stage / selection["destination"])
        if source["kind"] == "skills":
            metadata = frontmatter(
                (stage / selection["destination"] / "SKILL.md").read_bytes()
            )
            if (
                metadata.get("name") != selection["name"]
                or not isinstance(metadata.get("description"), str)
                or not metadata["description"].strip()
            ):
                raise Invalid(
                    f"Missing/renamed skill or invalid description: {selection['path']}"
                )
            if (
                metadata.get("license", source["license"]["spdx"])
                != source["license"]["spdx"]
            ):
                raise Invalid(f"{source['id']}: skill license changed")
        else:
            plugin = stage / selection["destination"]
            manifest = json.loads((plugin / ".claude-plugin/plugin.json").read_text())
            if manifest.get("name") != selection["name"]:
                raise Invalid("Plugin name changed")
            for folder in ("agents", "commands", "skills"):
                if not any((plugin / folder).rglob("*.md")):
                    raise Invalid(f"Incomplete plugin: missing {folder}")
            skill_files = list((plugin / "skills").rglob("SKILL.md"))
            if not skill_files:
                raise Invalid("Plugin has no skills")
            for skill_file in skill_files:
                metadata = frontmatter(skill_file.read_bytes())
                if not metadata.get("name") or not metadata.get("description"):
                    raise Invalid("Malformed plugin skill")
            catalog = json.loads(blob(repo, sha, source["marketplace_path"]))
            entries = [p for p in catalog["plugins"] if p["name"] == selection["name"]]
            if (
                catalog["name"] != source["marketplace"]
                or len(entries) != 1
                or entries[0]["source"] != "./" + selection["path"]
            ):
                raise Invalid("Plugin marketplace name or selected path changed")
            entry_hash = digest(json.dumps(entries[0], sort_keys=True).encode())
            changed |= entry_hash != source["marketplace_entry_sha256"]
            candidate["marketplace_entry_sha256"] = entry_hash
            # The complete plugin is installed by Codex; only license evidence is vendored.
            shutil.rmtree(plugin)
    candidate["snapshot_sha256"] = directory_hash(stage / "vendor" / source["id"])
    changed |= candidate["snapshot_sha256"] != source.get("snapshot_sha256")
    return candidate, changed


def preflight(root, sources):
    if (root / "vendor").is_symlink():
        raise Invalid("vendor must be a real directory")
    for source in sources:
        directory = root / "vendor" / source["id"]
        if directory.is_symlink():
            raise Invalid(f"Refusing symlink snapshot directory: {directory}")
        if directory.exists() and directory_hash(directory) != source.get(
            "snapshot_sha256"
        ):
            raise Invalid(f"Local snapshot modified or unowned: {directory}")
        if source["kind"] == "skills":
            for item in source["selections"]:
                link = root / item["name"]
                if link.is_symlink():
                    if os.readlink(link) != item["destination"]:
                        raise Invalid(f"Unrelated top-level symlink: {link}")
                elif link.exists():
                    raise Invalid(f"Unrelated top-level target: {link}")


def update(root, manifest, staged, candidates):
    preflight(root, manifest["sources"])
    # Stage every source before replacing anything; rollback on filesystem errors.
    original_manifest = (root / "upstreams.json").read_bytes()
    replaced, created_links = [], []
    backup = staged.parent / "backups"
    backup.mkdir()
    try:
        apply_update(
            root, manifest, staged, candidates, backup, replaced, created_links
        )
    except Exception:
        for link in reversed(created_links):
            link.unlink()
        for directory, saved in reversed(replaced):
            if directory.exists():
                shutil.rmtree(directory)
            if saved.exists():
                shutil.move(str(saved), directory)
        (root / "upstreams.json").write_bytes(original_manifest)
        raise


def apply_update(root, manifest, staged, candidates, backup, replaced, created_links):
    for candidate in candidates:
        source_dir = root / "vendor" / candidate["id"]
        source_dir.parent.mkdir(exist_ok=True)
        saved = backup / candidate["id"]
        if source_dir.exists():
            shutil.move(str(source_dir), saved)
        replaced.append((source_dir, saved))
        shutil.copytree(staged / "vendor" / candidate["id"], source_dir, symlinks=True)
        for item in candidate["selections"] if candidate["kind"] == "skills" else []:
            link = root / item["name"]
            if not link.is_symlink():
                link.symlink_to(item["destination"])
                created_links.append(link)
        manifest["sources"] = [
            candidate if s["id"] == candidate["id"] else s for s in manifest["sources"]
        ]
    (root / "upstreams.json").write_text(json.dumps(manifest, indent=2) + "\n")


def verify(root, manifest):
    preflight(root, manifest["sources"])
    for source in manifest["sources"]:
        directory = root / "vendor" / source["id"]
        if not directory.is_dir() or not source.get("snapshot_sha256"):
            raise Invalid(f"Missing snapshot provenance: {source['id']}")
        if source["kind"] == "skills":
            for item in source["selections"]:
                link = root / item["name"]
                if not link.is_symlink() or not (link / "SKILL.md").is_file():
                    raise Invalid(f"Missing skill link: {link}")
                metadata = frontmatter((link / "SKILL.md").read_bytes())
                if metadata.get("name") != item["name"]:
                    raise Invalid(f"Skill name mismatch: {link}")


def install(root, manifest, skills_dir):
    verify(root, manifest)
    links = []
    for source in manifest["sources"]:
        if source["kind"] != "skills":
            continue
        for item in source["selections"]:
            target = root / item["name"]
            if not (target / "SKILL.md").is_file():
                raise Invalid(f"Missing snapshot: {target}")
            link = skills_dir / item["name"]
            if link.is_symlink():
                if Path(os.path.abspath(link.parent / os.readlink(link))) != target:
                    raise Invalid(f"Refusing unrelated installed symlink: {link}")
            elif link.exists():
                raise Invalid(f"Refusing unrelated installed target: {link}")
            else:
                links.append((link, target))
    plugins = [s for s in manifest["sources"] if s["kind"] == "plugin"]
    for source in plugins:
        marketplaces = json.loads(
            run("codex", "plugin", "marketplace", "list", "--json")
        )["marketplaces"]
        for market in marketplaces:
            if market["name"] == source["marketplace"]:
                configured = market.get("marketplaceSource", {})
                if configured.get("sourceType") != "git" or configured.get(
                    "source", ""
                ).removesuffix(".git") != source["repository"].removesuffix(".git"):
                    raise Invalid(
                        f"Unrelated configured marketplace: {source['marketplace']}"
                    )
    for source in plugins:
        run(
            "codex",
            "plugin",
            "marketplace",
            "add",
            source["repository"],
            "--ref",
            source["commit"],
            "--sparse",
            source["selections"][0]["path"],
            "--sparse",
            str(PurePosixPath(source["marketplace_path"]).parent),
            "--json",
        )
        markets = json.loads(run("codex", "plugin", "marketplace", "list", "--json"))[
            "marketplaces"
        ]
        market = next((m for m in markets if m["name"] == source["marketplace"]), None)
        if market is None:
            raise Invalid("Codex did not register the expected marketplace")
        actual = run("git", "-C", market["root"], "rev-parse", "HEAD").decode().strip()
        if actual != source["commit"]:
            raise Invalid("Codex marketplace commit does not match the lock")
        item = source["selections"][0]
        tree = (
            run("git", "-C", market["root"], "rev-parse", f"HEAD:{item['path']}")
            .decode()
            .strip()
        )
        if tree != item["tree"]:
            raise Invalid("Codex marketplace plugin tree does not match the lock")
        selector = f"{item['name']}@{source['marketplace']}"
        run("codex", "plugin", "add", selector, "--json")
        installed = json.loads(
            run(
                "codex",
                "plugin",
                "list",
                "--marketplace",
                source["marketplace"],
                "--json",
            )
        )["installed"]
        plugin = next((p for p in installed if p["pluginId"] == selector), None)
        if not plugin or not plugin.get("installed") or not plugin.get("enabled"):
            raise Invalid(f"Codex did not enable {selector}")
        installed_path = plugin.get("source", {}).get("path")
        expected_path = Path(market["root"]) / item["path"]
        if (
            not installed_path
            or not Path(installed_path).is_dir()
            or directory_hash(Path(installed_path)) != directory_hash(expected_path)
        ):
            raise Invalid(
                f"Installed plugin content does not match the pinned marketplace: {selector}"
            )
    skills_dir.mkdir(parents=True, exist_ok=True)
    for link, target in links:
        link.symlink_to(target)
    print(
        f"Verified {sum(len(s['selections']) for s in manifest['sources'] if s['kind'] == 'skills')} standalone skills"
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("check", "update"):
        command = sub.add_parser(name)
        command.add_argument("--source")
        command.add_argument("--json", action="store_true")
    sub.add_parser(
        "verify", help="Validate local snapshots and links without network access"
    )
    command = sub.add_parser("install")
    command.add_argument(
        "--skills-dir", type=Path, default=Path.home() / ".agents/skills"
    )
    args = parser.parse_args(argv)
    try:
        root = Path.cwd()
        manifest = read_manifest(root)
        if args.command == "verify":
            verify(root, manifest)
            print("Local snapshots, provenance, and skill links verified")
            return 0
        if args.command == "install":
            install(root, manifest, args.skills_dir.expanduser().absolute())
            return 0
        selected = [
            s for s in manifest["sources"] if not args.source or s["id"] == args.source
        ]
        if not selected:
            raise Invalid(f"Unknown source: {args.source}")
        reports, candidates = [], []
        with tempfile.TemporaryDirectory(prefix="upstreams-") as tmp:
            stage = Path(tmp) / "stage"
            for source in selected:
                repo = Path(tmp) / source["id"]
                report = {
                    "id": source["id"],
                    "repository": source["repository"],
                    "old": source["commit"],
                    "new": None,
                    "changed": False,
                    "license_changes": [],
                }
                try:
                    sha = fetch(source, repo)
                    report["new"] = sha
                    candidate, changed = inspect(source, repo, sha, stage)
                    if args.command == "update":
                        changed |= not (root / "vendor" / source["id"]).is_dir()
                        if source["kind"] == "skills":
                            changed |= any(
                                not (root / s["name"]).is_symlink()
                                for s in source["selections"]
                            )
                    report["changed"] = changed
                    if changed:
                        candidates.append(candidate)
                except (
                    Invalid,
                    OSError,
                    ValueError,
                    KeyError,
                    TypeError,
                    subprocess.TimeoutExpired,
                ) as error:
                    report["error"] = str(error)
                    if "license" in str(error).lower():
                        report["license_changes"].append(str(error))
                    print(f"{source['id']}: {error}", file=sys.stderr)
                reports.append(report)
            failed = any("error" in report for report in reports)
            if args.command == "update" and candidates and not failed:
                update(root, manifest, stage, candidates)
        if getattr(args, "json", False):
            print(json.dumps({"sources": reports}, indent=2))
        else:
            for report in reports:
                print(
                    f"{report['id']}: {'ERROR' if 'error' in report else 'updated' if args.command == 'update' and report['changed'] and not failed else 'update available' if report['changed'] else 'current'}"
                )
        if failed:
            return 1
        return 2 if args.command == "check" and candidates else 0
    except (
        Invalid,
        OSError,
        ValueError,
        KeyError,
        TypeError,
        subprocess.TimeoutExpired,
    ) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

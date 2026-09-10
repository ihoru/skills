"""CLI contract tests using disposable local Git repositories, never the network."""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/manage_upstreams.py"


class UpstreamTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.repo = self.base / "upstream"
        self.root = self.base / "consumer"
        self.root.mkdir()
        self.repo.mkdir()
        self.git("init", "-b", "main")
        self.git("config", "user.email", "test@example.com")
        self.git("config", "user.name", "Test")
        self.skill = self.repo / "skills/example"
        self.skill.mkdir(parents=True)
        (self.skill / "SKILL.md").write_text(
            "---\nname: example\ndescription: A fixture skill.\n---\n\nOriginal\n"
        )
        (self.repo / "LICENSE").write_text("MIT fixture\n")
        sha = self.commit()
        self.manifest = {
            "version": 1,
            "sources": [
                {
                    "id": "example",
                    "repository": str(self.repo),
                    "ref": "main",
                    "commit": sha,
                    "kind": "skills",
                    "attribution": "Fixture author",
                    "license": {
                        "spdx": "MIT",
                        "evidence": [
                            {
                                "path": "LICENSE",
                                "sha256": hashlib.sha256(b"MIT fixture\n").hexdigest(),
                            }
                        ],
                    },
                    "selections": [
                        {
                            "path": "skills/example",
                            "name": "example",
                            "destination": "vendor/example/example",
                            "tree": "0" * 40,
                        }
                    ],
                }
            ],
        }
        self.save()

    def git(self, *args):
        return subprocess.check_output(
            ["git", "-C", str(self.repo), *args], stderr=subprocess.DEVNULL, text=True
        ).strip()

    def commit(self):
        self.git("add", ".")
        self.git("commit", "-qm", "fixture", "--allow-empty")
        return self.git("rev-parse", "HEAD")

    def save(self):
        (self.root / "upstreams.json").write_text(json.dumps(self.manifest))

    def cli(self, *args, env=None):
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            cwd=self.root,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_check_reports_selected_updates_and_update_is_idempotent(self):
        result = self.cli("check", "--json")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertTrue(json.loads(result.stdout)["sources"][0]["changed"])
        result = self.cli("update")
        self.assertEqual(result.returncode, 0, result.stderr)
        installed = self.root / "example/SKILL.md"
        self.assertEqual(installed.read_bytes(), (self.skill / "SKILL.md").read_bytes())
        first = (self.root / "upstreams.json").read_bytes()
        self.assertEqual(self.cli("update").returncode, 0)
        self.assertEqual(first, (self.root / "upstreams.json").read_bytes())
        self.assertEqual(self.cli("check").returncode, 0)
        (self.repo / "unselected.txt").write_text("unrelated change")
        self.commit()
        self.assertEqual(self.cli("check").returncode, 0)

    def test_rejects_invalid_manifest_and_unknown_source(self):
        self.assertEqual(self.cli("check", "--source", "missing").returncode, 1)
        for field, value in (
            ("id", "../escape"),
            ("commit", "main"),
            ("kind", "other"),
            ("ref", "--upload-pack=bad"),
        ):
            with self.subTest(field=field):
                original = self.manifest["sources"][0][field]
                self.manifest["sources"][0][field] = value
                self.save()
                self.assertEqual(self.cli("check").returncode, 1)
                self.manifest["sources"][0][field] = original

    def test_license_and_skill_validation_precedes_writes(self):
        self.assertEqual(self.cli("update").returncode, 0)
        before = (self.root / "upstreams.json").read_bytes()
        (self.repo / "LICENSE").write_text("Different license\n")
        self.commit()
        result = self.cli("check", "--json")
        self.assertEqual(result.returncode, 1)
        self.assertIn("license", result.stderr.lower())
        self.assertEqual(self.cli("update").returncode, 1)
        self.assertEqual(before, (self.root / "upstreams.json").read_bytes())
        (self.repo / "LICENSE").write_text("MIT fixture\n")
        for content in (
            "---\nname: renamed\ndescription: valid\n---\n",
            "---\nname: [broken\n---\n",
            "# no frontmatter",
        ):
            (self.skill / "SKILL.md").write_text(content)
            self.commit()
            self.assertEqual(self.cli("update").returncode, 1)
        (self.skill / "SKILL.md").unlink()
        self.commit()
        self.assertEqual(self.cli("update").returncode, 1)

    def test_snapshot_links_are_internal_and_unrelated_local_paths_are_preserved(self):
        (self.skill / "alias.md").symlink_to("SKILL.md")
        self.commit()
        result = self.cli("update")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.root / "example/alias.md").is_symlink())
        (self.skill / "alias.md").unlink()
        (self.skill / "alias.md").symlink_to("../../outside")
        self.commit()
        self.assertEqual(self.cli("update").returncode, 1)
        self.assertEqual(os.readlink(self.root / "example/alias.md"), "SKILL.md")

    def test_install_is_idempotent_and_refuses_unrelated_targets(self):
        self.assertEqual(self.cli("update").returncode, 0)
        agent_dir = self.base / "agents"
        command = ("install", "--skills-dir", str(agent_dir))
        result = self.cli(*command)
        self.assertEqual(result.returncode, 0, result.stderr)
        link = agent_dir / "example"
        self.assertEqual(link.resolve(), (self.root / "example").resolve())
        self.assertEqual(self.cli(*command).returncode, 0)
        link.unlink()
        link.write_text("user data")
        self.assertEqual(self.cli(*command).returncode, 1)
        self.assertEqual(link.read_text(), "user data")
        link.unlink()
        link.symlink_to(self.base / "unrelated")
        self.assertEqual(self.cli(*command).returncode, 1)
        self.assertEqual(os.readlink(link), str(self.base / "unrelated"))

    def test_update_preserves_conflicting_top_level_directory(self):
        (self.root / "example").mkdir()
        (self.root / "example/user.txt").write_text("mine")
        result = self.cli("update")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual((self.root / "example/user.txt").read_text(), "mine")
        self.assertFalse((self.root / "vendor").exists())

    def plugin_fixture(self):
        plugin = self.repo / "plugins/differential-review"
        (plugin / ".claude-plugin").mkdir(parents=True)
        (plugin / ".claude-plugin/plugin.json").write_text(
            json.dumps({"name": "differential-review", "version": "1.0.0"})
        )
        for relative in (
            "agents/reviewer.md",
            "commands/review.md",
            "skills/differential-review/reference.md",
        ):
            path = plugin / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixture")
        (plugin / "skills/differential-review/SKILL.md").write_text(
            "---\nname: differential-review\ndescription: Review fixture.\n---\n"
        )
        (self.repo / ".claude-plugin").mkdir()
        catalog = {
            "name": "fixture-market",
            "plugins": [
                {
                    "name": "differential-review",
                    "source": "./plugins/differential-review",
                }
            ],
        }
        (self.repo / ".claude-plugin/marketplace.json").write_text(json.dumps(catalog))
        source = self.manifest["sources"][0]
        source.update(
            kind="plugin",
            marketplace="fixture-market",
            marketplace_path=".claude-plugin/marketplace.json",
            marketplace_entry_sha256="0" * 64,
        )
        source["selections"] = [
            {
                "name": "differential-review",
                "path": "plugins/differential-review",
                "destination": "vendor/example/differential-review",
                "tree": "0" * 40,
            }
        ]
        source["commit"] = self.commit()
        self.save()
        return plugin

    def test_plugin_tracks_complete_tree_and_only_selected_catalog_entry(self):
        plugin = self.plugin_fixture()
        result = self.cli("update")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.root / "differential-review").exists())
        self.assertFalse((self.root / "vendor/example/differential-review").exists())
        catalog_path = self.repo / ".claude-plugin/marketplace.json"
        catalog = json.loads(catalog_path.read_text())
        catalog["plugins"].append(
            {"name": "unselected", "source": "./plugins/unselected"}
        )
        catalog_path.write_text(json.dumps(catalog))
        self.commit()
        self.assertEqual(self.cli("check").returncode, 0)
        (plugin / "agents/reviewer.md").write_text("changed agent")
        self.commit()
        self.assertEqual(self.cli("check").returncode, 2)
        self.assertEqual(self.cli("update").returncode, 0)
        (plugin / "commands/review.md").unlink()
        self.commit()
        self.assertEqual(self.cli("check").returncode, 1)

    def test_verify_is_offline_and_detects_modified_snapshot_and_missing_link(self):
        self.assertEqual(self.cli("update").returncode, 0)
        self.assertEqual(self.cli("verify").returncode, 0)
        (self.root / "example").unlink()
        self.assertEqual(self.cli("verify").returncode, 1)
        (self.root / "example").symlink_to("vendor/example/example")
        (self.root / "example/SKILL.md").write_text("local edit")
        self.assertEqual(self.cli("verify").returncode, 1)
        self.assertEqual(
            self.cli("install", "--skills-dir", str(self.base / "agents")).returncode, 1
        )

    def test_plugin_install_pins_native_marketplace_and_preserves_complete_content(
        self,
    ):
        self.plugin_fixture()
        self.assertEqual(self.cli("update").returncode, 0)
        bin_dir = self.base / "bin"
        bin_dir.mkdir()
        fake = bin_dir / "codex"
        fake.write_text("""#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
root = os.environ['FIXTURE_UPSTREAM']
with open(os.environ['FIXTURE_CALLS'], 'a') as stream:
    stream.write(json.dumps(args) + '\\n')
if args[:3] == ['plugin', 'marketplace', 'list']:
    print(json.dumps({'marketplaces': [{'name': 'fixture-market', 'root': root,
        'marketplaceSource': {'sourceType': 'git', 'source': root}}]}))
elif args[:2] == ['plugin', 'list']:
    print(json.dumps({'installed': [{'pluginId': 'differential-review@fixture-market',
        'installed': True, 'enabled': True,
        'source': {'path': root + '/plugins/differential-review'}}]}))
else:
    print('{}')
""")
        fake.chmod(0o755)
        calls = self.base / "calls.jsonl"
        env = dict(
            os.environ,
            PATH=str(bin_dir) + os.pathsep + os.environ["PATH"],
            FIXTURE_UPSTREAM=str(self.repo),
            FIXTURE_CALLS=str(calls),
        )
        result = self.cli("install", "--skills-dir", str(self.base / "agents"), env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        commands = [json.loads(line) for line in calls.read_text().splitlines()]
        pin = json.loads((self.root / "upstreams.json").read_text())["sources"][0][
            "commit"
        ]
        self.assertIn(
            [
                "plugin",
                "marketplace",
                "add",
                str(self.repo),
                "--ref",
                pin,
                "--sparse",
                "plugins/differential-review",
                "--sparse",
                ".claude-plugin",
                "--json",
            ],
            commands,
        )
        self.assertIn(
            ["plugin", "add", "differential-review@fixture-market", "--json"], commands
        )
        self.assertIn(
            ["plugin", "list", "--marketplace", "fixture-market", "--json"], commands
        )

    def test_exact_git_snapshot_ignores_export_attributes_and_removes_stale_files(self):
        (self.skill / ".gitattributes").write_text("retained.md export-ignore\n")
        (self.skill / "retained.md").write_text("must be retained")
        (self.skill / "obsolete.md").write_text("removed next update")
        self.commit()
        result = self.cli("update")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            (self.root / "example/retained.md").read_text(), "must be retained"
        )
        (self.skill / "obsolete.md").unlink()
        self.commit()
        self.assertEqual(self.cli("update").returncode, 0)
        self.assertFalse((self.root / "example/obsolete.md").exists())

    def test_new_license_file_requires_review(self):
        self.assertEqual(self.cli("update").returncode, 0)
        (self.skill / "LICENSE.txt").write_text("Additional terms")
        self.commit()
        result = self.cli("check", "--json")
        self.assertEqual(result.returncode, 1)
        self.assertTrue(json.loads(result.stdout)["sources"][0]["license_changes"])

    def test_update_repairs_missing_catalog_link_without_upstream_change(self):
        self.assertEqual(self.cli("update").returncode, 0)
        (self.root / "example").unlink()
        self.assertEqual(self.cli("update").returncode, 0)
        self.assertTrue((self.root / "example/SKILL.md").is_file())

    def test_duplicate_frontmatter_fields_are_rejected(self):
        (self.skill / "SKILL.md").write_text(
            "---\nname: unexpected\nname: example\ndescription: fixture\n---\n"
        )
        self.commit()
        self.assertEqual(self.cli("check").returncode, 1)

    def test_approved_license_change_updates_provenance_without_skill_change(self):
        self.assertEqual(self.cli("update").returncode, 0)
        (self.repo / "LICENSE").write_text("Reviewed MIT fixture\n")
        self.commit()
        self.manifest = json.loads((self.root / "upstreams.json").read_text())
        self.manifest["sources"][0]["license"]["evidence"][0]["sha256"] = (
            hashlib.sha256(b"Reviewed MIT fixture\n").hexdigest()
        )
        self.save()
        self.assertEqual(self.cli("update").returncode, 0)
        self.assertEqual(
            (self.root / "vendor/example/provenance/LICENSE").read_text(),
            "Reviewed MIT fixture\n",
        )


if __name__ == "__main__":
    unittest.main()

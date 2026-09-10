# Upstream maintenance

Run commands from the repository root with Python 3.10+ and Git. Install the maintenance dependency in a virtual environment:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-upstreams.txt
```

## Review repository updates

```sh
python scripts/manage_upstreams.py check
python scripts/manage_upstreams.py check --source redis --json
python scripts/manage_upstreams.py update
python scripts/manage_upstreams.py verify
python -m unittest discover -s tests -v
```

`check` returns 0 when the selected content is current, 2 when updates are available, and 1 on validation or operational errors. `update` accepts the same source filter and optional JSON output. `verify` validates local snapshots and catalog links offline. Tests use temporary local Git repositories and a fake Codex executable; they need no network or active installation.

`upstreams.json` records each repository, tracked ref, locked commit, selected Git tree, destination, expected skill name, attribution, and SHA-256 license evidence. `vendor/<source>/provenance/` preserves the evidence. Standalone directories contain exact Git blobs and executable modes, including safe internal symlinks. Updates ignore unrelated upstream commits and preserve a lock until selected content changes. The plugin's complete tree and its individual marketplace entry are tracked; changes to other marketplace entries do not trigger updates.

All candidate sources validate before any snapshot is replaced. The updater refuses local snapshot edits and unrelated catalog targets. Filesystem failures roll back replacements; an abrupt process kill or disk failure may still require recovery through Git. Run only one local update/install process at a time.

### License changes

License hashes, additional or removed LICENSE/NOTICE/COPYING files, and skill license metadata are checked. A change fails closed and appears in the JSON report. Review the exact upstream revision and terms, then explicitly edit the evidence paths/hashes and SPDX identifier in `upstreams.json` before retrying. Do not edit the vendored skill text to resolve a validation error.

- Timescale: Apache-2.0; upstream LICENSE and NOTICE retained.
- Vercel: MIT as declared in the selected skill's frontmatter. At the locked revision the repository has no root license file; preserve its declaration and author metadata without inventing a copyright notice.
- Redis: MIT; upstream LICENSE retained.
- Trail of Bits: CC-BY-SA-4.0; upstream LICENSE retained, with attribution to Trail of Bits and plugin author Omar Inuwa. The complete plugin remains in its native marketplace.

These identifiers document upstream declarations, rather than replacing their license texts. The original skill snapshots are unmodified.

## Weekly review PR

The workflow runs Mondays at 05:00 UTC (09:00 Asia/Tbilisi, currently UTC+4 with no daylight saving changes) and supports manual dispatch. GitHub schedules default to UTC and may run late; they run from the default branch, which is `master` in this repository. GitHub also supports explicit timezone schedules, but this workflow uses the approved UTC form. See [GitHub schedule documentation](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).

It opens or refreshes `automation/upstream-skills` with old/new commit links, upstream comparisons, full standalone diffs, validation results, and license-change results. Validation failures are reported in the run summary and commented on an existing review PR; they never replace snapshots. It neither merges PRs nor activates local skills. Review the source content, not just passing validation: the validator checks structure and provenance, not the correctness of upstream advice.

Repository setup prerequisite: in **Settings → Actions → General → Workflow permissions**, enable **Allow GitHub Actions to create and approve pull requests**. This was disabled when the initial setup was prepared. The workflow declares `contents: write` and `pull-requests: write`; it contains no approval or merge step. No repository permission setting is changed by this setup. GitHub may require a maintainer to approve CI runs originating from automated PRs, and may disable schedules after prolonged public-repository inactivity.

## Activate after the initial setup PR merges

Keep the active skills on a dedicated clean checkout so development branches and dirty files cannot change them. After the initial PR has merged, create this checkout once (the destination must not already exist):

```sh
git clone --branch master --single-branch ssh://git@github.com/ihoru/skills.git /home/ihoru/projects/my/skills-installed
cd /home/ihoru/projects/my/skills-installed
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-upstreams.txt
python scripts/manage_upstreams.py verify
python scripts/manage_upstreams.py install
```

`install` creates only the six declared `~/.agents/skills/<name>` links, pointing at this checkout's top-level links. Already-correct links are idempotent; unrelated files, directories, and links are refused. Broken links with the same intended target become valid once `update` restores the repository snapshot. `--skills-dir PATH` is available for isolated standalone fixture installs; it does **not** isolate Codex plugin configuration.

The installer registers the Trail of Bits Git marketplace at the locked SHA with sparse paths for the marketplace manifest and entire plugin, then installs `differential-review@trailofbits`. It checks the marketplace commit/tree, enabled plugin entry, and complete installed content. It refuses a same-named marketplace from another source. Native commands were inspected with Codex CLI 0.154.0; actual native installation and Codex discovery are deliberately deferred until post-merge activation. See [OpenAI plugin documentation](https://learn.chatgpt.com/docs/plugins).

For later merged updates, first ensure the installed checkout is clean:

```sh
cd /home/ihoru/projects/my/skills-installed
git status --short
git pull --ff-only origin master
. .venv/bin/activate
python -m pip install -r requirements-upstreams.txt
python scripts/manage_upstreams.py install
```

After activation, verify all six links resolve into `skills-installed`, check `codex plugin list --marketplace trailofbits --json`, and start a new Codex task to confirm skill/plugin discovery. If native Codex installation fails, keep its error for diagnosis and rerun after resolving it; standalone links are created only after plugin verification passes. Never run a blanket marketplace upgrade to activate these pins.

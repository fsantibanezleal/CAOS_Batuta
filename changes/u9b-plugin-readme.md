## Area `init`, `fragments` and `reserve`: adopt, check, update and remove; shared files and numbers

One command adopts Batuta on a device or in a project. Every write is a dry run unless `--apply`, atomic, and reversible:
what is replaced is backed up next to it as `<name>.bak-<stamp>`, and what `init` wrote is recorded in an install manifest.

```
python scripts/batuta.py init user [--home DIR] [--deploy-root DIR] [--python PATH] [--var user_name=...] [--apply]
python scripts/batuta.py init project [--target DIR] [--var project_name=...] [--apply]
python scripts/batuta.py init doctor [--project DIR] [--channel auto|device|plugin]
python scripts/batuta.py init update [--scope project|user] [--target DIR] [--apply]
python scripts/batuta.py init uninstall [--scope project|user] [--target DIR] [--apply]
python scripts/batuta.py fragments changelog REPO_DIR [--apply]
python scripts/batuta.py fragments i18n DICTIONARY.csv FRAGMENT_DIR [--apply]
python scripts/batuta.py reserve next REPO KIND [--from N] [--root DIR] [--apply]
python scripts/batuta.py reserve list [--root DIR]
npx github:fsantibanezleal/CAOS_Batuta <area> <verb> ...
copier copy gh:fsantibanezleal/CAOS_Batuta <destination>
```

- `init user` writes `<BATUTA_HOME>/batuta.json` only when it is missing (roots from `BATUTA_*` variables, the user core
  template and its values), then runs the device area's deploy and restore and installs the agent files into
  `~/.claude/agents/`. The manifest is `<deploy root>/installed.json`.
- `init project` renders `templates/project/` of the plugin with five variables (`project_name`, `python_version`,
  `test_command`, `default_branch`, `batuta_ref`, the release tag of the installed version that the CI checks are fetched
  from, moved by `init update`; the defaults are the target folder's name, `3.12`, `python -m unittest discover -s tests -t . -v`
  and `main`). An existing `CLAUDE.md` or `AGENTS.md` is backed up with a stamp before it is replaced;
  `.claude/settings.json` is merged append-only (the permission rules of the template are added, nothing is removed or
  reordered) after a backup; a file the template does not own is never touched. No git repository at the target is a
  WARN (the workflow is still written); a target inside another repository is a WARN that GitHub reads the workflow at
  the repository root only. The manifest is `<project>/.batuta/installed.json` and carries no machine path.
- Ownership: a seed file (`.batuta/batuta.json`, the constitution, thresholds, the example feature, the foundation test) is
  written once and is yours afterwards; `init` and `init update` never overwrite it. A managed file (AGENTS.md, the
  workflow, the agent files) is rewritten only while it is an unchanged installed copy; a hand-edited one is kept and
  reported DIFFERENT (exit 2) unless `--force` replaces it after a backup. An existing CLAUDE.md, in a project or the user
  core, keeps its content and gains one block between `<!-- batuta:begin ... -->` and `<!-- batuta:end -->`, rewritten in
  place by `init update`. `init uninstall` refuses a manifest whose bases, paths or links leave the project or the Batuta
  home, deleting nothing.
- The workflow `.github/workflows/batuta-gates.yml` has one job, `batuta-gates`: full history, Python from
  `python_version`, the base revision from `github.event.pull_request.base.sha` (pull request) or `github.event.before` (a
  push, or the merge base with the default branch on a new branch or a force push), the test step `id: tests` running
  exactly `tdd.test_command`, then the Batuta checks. A WARN (exit 2) of a check is reported and does not fail the job; a
  FAIL fails it, and every check runs even after a failure.
- `init doctor` reports each probe OK, WARN or FAIL with its fix, without writing and in a few seconds, and compares the
  workflow's test step with `tdd.test_command` (a difference is a FAIL naming both strings). Git Bash on Windows is a FAIL
  for the plugin channel and not needed by the device channel; Node (npx channel only) and the `claude` CLI are WARN.
- `init uninstall` restores the backup of each file init replaced and removes each installed file whose hash (line
  endings ignored) is unchanged; an edited file is kept and reported DIFFERENT with exit 2, and the manifest keeps it for
  a later run. Folders init created are removed when empty. `init update` renders again from the current templates and
  backs up every file it changes.
- `fragments changelog` merges `changes/*.md` bullets under `## [Unreleased]` (file-name order, no duplicates, line
  endings kept) and `fragments i18n` merges `*.csv` rows into a dictionary (sorted dictionaries stay sorted, duplicate keys
  are refused with the file names); both delete the fragments only with `--apply` and change nothing on a refusal.
  `reserve next` gives the next number of a `repo:kind` sequence, recorded under an exclusive lock with `--apply`.
- The npx entry finds Python in this order: `BATUTA_PYTHON`, `py -3` (Windows), `python3`, `python`; one older than 3.10
  is skipped. Without a suitable Python it exits 1 and names every candidate it tried.

# Changelog

All notable changes to this project are recorded here, in the
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) form. Versions are `X.XX.XXX` (ADR-0068); `VERSION` is
the single source and every release is tagged `vX.XX.XXX`.

## [Unreleased]

Pre-release, under construction toward 0.01.000.

### Added

- Repository skeleton: the layout of the architecture (ADR-0001), `plugins/harness` plugin, `bin/harness.mjs` npx
  entry and a docs wiki index.
- Community files: README, Apache-2.0 LICENSE, CODE_OF_CONDUCT, CONTRIBUTING, SECURITY, `LESSONS.md`,
  `.editorconfig`, `.gitattributes`, `.gitignore`.
- Versioning: `VERSION` 0.01.000 with the semver form 0.1.0 in `package.json` and `plugin.json`.
- Plugin manifest (`plugins/harness/.claude-plugin/plugin.json`) and marketplace listing
  (`.claude-plugin/marketplace.json`).
- Command dispatcher `plugins/harness/scripts/harness.py`: discovers area modules in `harness_lib/areas/`,
  global options `--config`, `--json`, `--version`, and reports a module that fails to load as a warning.
- Area `version` (`harness.py version show`).
- `scripts/check_content_standards.py`: no em-dash, no emoji, no absolute user path in repository text.
- CI (`.github/workflows/ci.yml`): unit tests on Python 3.10 and 3.13 on Linux and Windows, and the content
  standards check; push to `develop` and `main` and manual dispatch only.
- Tests for the dispatcher, the version area, the manifests, the root files, the workflow and the content
  standards script.
- Contracts aligned with the dimensioned contract-first method (ADR-0002): C23 inventory, C25 evaluations, C26 availability (declaration and runtime block), C27 readiness, C28 model registry and C21 units, `contract graph --inventory`, one-level maps in the front matter, and the contracts moved into `plugins/harness/contracts/`.
- Contracts revised after the adversarial review (ADR-0003): the product is named Batuta (plugin, CLI, package, `batuta.json`, `.batuta/`); C23 is the contract of `sizing.md` and C22 of the contract catalog, C21 and C25 re-keyed, `contract graph --catalog --sizing --tasks` with one wave numbering; availability states `available`, `partial`, `stale`, `provider`, `training`, `missing`; lifecycle gate names `L0-understand` to `L10-lessons`; C02 and C03 describe the briefs and reports the tools write; new contracts C30 (dispatch), C31 (hooks) and C32 (commit grammar); shared helpers `batuta_lib/config.py` and `batuta_lib/output.py`; a stricter validator (whole-text patterns, no NaN or duplicate keys, sections files checked, `$ref` cycles refused) and every finding F01 to F31 covered by a test.

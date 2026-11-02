# Contributing

Thanks for your interest in this project. It is maintained by Felipe Santibanez-Leal. Contributions,
issues, and suggestions are welcome.

## Reporting issues

Please open a GitHub issue before starting non-trivial work, so intent is visible and effort is not
duplicated. A good issue states:

- What you observed (or want), with steps to reproduce for a bug.
- The environment (OS, Python and Node versions) when relevant.
- One logical topic per issue.

## Development flow

This project uses a three-level branch flow:

1. Branch from `develop` as `task/<short-slug>`.
2. Commit in small, focused units (one logical change per commit).
3. Open a pull request from your `task/<slug>` branch **into `develop`** (never straight into `main`).
4. `develop` is promoted to `main` via its own pull request when a change is release-ready.

`main` is the released branch; it is never committed to directly.

## Pull requests

- Reference the issue it addresses (for example `Fixes #123`).
- Describe what changed and how you verified it.
- Keep pull requests small and frequent rather than large and batched.
- Do not disable commit hooks or force-push shared branches.

## Code and content conventions

- Code, identifiers, comments, documentation and commit messages are written in **English**.
- No em-dash and no emoji in any tracked text; no absolute user path (a drive-letter users folder or a home
  folder). `python scripts/check_content_standards.py` enforces this and runs in CI.
- Python is stdlib only and supports 3.10 and newer; Node code has no dependencies.
- Match the style of the surrounding code (naming, formatting, comment density).
- Tests come first: add or update tests alongside the change, and keep the suite green.
- Versions follow `X.XX.XXX` (see `CHANGELOG.md`); a change that alters behaviour adds a changelog entry.

## Local setup

Run the tests from the repository root:

```
python -m unittest discover -s tests -p "test_*.py"
python scripts/check_content_standards.py
```

No dependencies are installed: Batuta is stdlib Python and dependency-free Node.

## License of contributions

By contributing, you agree that your contributions are licensed under the same license as this repository
(see `LICENSE`).

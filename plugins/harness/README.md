# harness (plugin)

The Claude Code plugin of CAOS_AGENTIC_HARNESS. Status: pre-release, under construction toward 0.01.000.

## What ships today

- `.claude-plugin/plugin.json`, the plugin manifest (name `harness`, version in semver form).
- `scripts/harness.py`, the single command line entry (stdlib Python 3.10 or newer).
  `python scripts/harness.py version show` prints the version; no other area ships yet.
- `scripts/harness_lib/areas/`, the folder the dispatcher scans: one module per area, each defining `AREA`,
  `HELP` and `register(subparsers)`.

## What is planned

Agents, skills, hooks and the other command areas are added by later units and are not part of this plugin yet.
The plugin declares none of them, so enabling it today adds nothing to a session's context.

## Adding an area

Create `scripts/harness_lib/areas/<name>.py`:

```python
AREA = "example"
HELP = "one line shown in `harness.py --help`"

def _run(args):
    print("hello")
    return 0  # exit code: 0 ok, 1 failure or refusal, 2 warnings or honest partial

def register(subparsers):
    parser = subparsers.add_parser("run", help="say hello")
    parser.set_defaults(func=_run)
```

The dispatcher imports every module in that folder in sorted order. A module that raises on import is reported as
`WARN area <name> failed to load: <error>` and skipped; the others keep working. Global options `--config PATH`,
`--json` and `--version` are available to every handler as `args.config` and `args.json`.

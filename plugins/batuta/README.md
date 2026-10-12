# batuta (plugin)

The Claude Code plugin of CAOS_Batuta. Status: pre-release, under construction toward 0.01.000.

## What ships today

- `.claude-plugin/plugin.json`, the plugin manifest (name `batuta`, version in semver form).
- `scripts/batuta.py`, the single command line entry (stdlib Python 3.10 or newer).
  `python scripts/batuta.py version show` prints the version; `python scripts/batuta.py contract lint` checks the
  contracts; the other areas ship in later units.
- `scripts/batuta_lib/areas/`, the folder the dispatcher scans: one module per area, each defining `AREA`,
  `HELP` and `register(subparsers)`. Shipped: `version` and `contract` (lint, validate, graph).
- `scripts/batuta_lib/config.py` and `output.py`, the helpers every area uses: the configuration (`--config`,
  `BATUTA_CONFIG`, project `.batuta/batuta.json`, user `<BATUTA_HOME>/batuta.json`, defaults) and the tag lines, the
  C20 object and the exit codes.
- `contracts/`, the data contracts C01 to C32 with their fixtures (see `contracts/README.md`).

## What is planned

Agents, skills, hooks and the other command areas are added by later units and are not part of this plugin yet.
The plugin declares none of them, so enabling it today adds nothing to a session's context.

## Adding an area

Create `scripts/batuta_lib/areas/<name>.py`:

```python
from batuta_lib.output import emit, item

AREA = "example"
HELP = "one line shown in `batuta.py --help`"

def _run(args):
    items = [item("OK", "hello")]
    return emit(AREA, "run", items, "run: 1 ok", getattr(args, "json", False))  # 0 ok, 1 failure, 2 warnings

def register(subparsers):
    parser = subparsers.add_parser("run", help="say hello")
    parser.set_defaults(func=_run)
```

The dispatcher imports every module in that folder in sorted order. A module that raises on import is reported as
`WARN area <name> failed to load: <error>` and skipped; the others keep working. Global options `--config PATH`,
`--json` and `--version` are available to every handler as `args.config` and `args.json`.

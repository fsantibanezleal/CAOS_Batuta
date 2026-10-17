#!/usr/bin/env python3
"""CAOS_Batuta command line: `batuta.py <area> <verb>`.

The dispatcher knows no area by name. It imports every module in `batuta_lib/areas/` (sorted) and, for each
module that defines `AREA`, `HELP` and `register(subparsers)`, adds the subcommand `batuta.py <AREA> <verb>`.
A verb handler is set with `parser.set_defaults(func=handler)` and is called as `handler(args) -> int`; the
return value is the exit code (0 ok, 1 failure or refusal, 2 warnings or honest partial).

Global options (`--config PATH`, `--json`, `--version`) are accepted before or after the area and verb.
A module that fails to load is reported as `WARN area <name> failed to load: <error>` on stderr and skipped,
so the CLI keeps working.
"""
from __future__ import annotations

import argparse
import importlib
import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

DEFAULT_AREAS_DIR = HERE / "batuta_lib" / "areas"


def load_areas(areas_dir: Path | None = None):
    """Import every area module in `areas_dir` (sorted). Returns (modules, warnings)."""
    areas_dir = Path(areas_dir) if areas_dir else DEFAULT_AREAS_DIR
    modules, warnings = [], []
    for path in sorted(areas_dir.glob("*.py")):
        name = path.stem
        if name.startswith("_"):
            continue
        try:
            module = _import_area(name, path, areas_dir)
            if not hasattr(module, "AREA"):
                continue  # a helper module, not an area
            for attr in ("HELP", "register"):
                if not hasattr(module, attr):
                    raise AttributeError(f"module defines AREA but not {attr}")
            modules.append(module)
        except Exception as exc:  # noqa: BLE001 (any failure must degrade to a warning)
            warnings.append(f"WARN area {name} failed to load: {exc}")
    return modules, warnings


def _import_area(name: str, path: Path, areas_dir: Path):
    if areas_dir.resolve() == DEFAULT_AREAS_DIR.resolve():
        return importlib.import_module(f"batuta_lib.areas.{name}")
    spec = importlib.util.spec_from_file_location(f"batuta_area_{name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _hoist_global_options(argv: list[str]) -> list[str]:
    """Move --json, --config PATH and --version to the front so they work after the verb too."""
    front, rest = [], []
    items = iter(range(len(argv)))
    for i in items:
        arg = argv[i]
        if arg in ("--json", "--version"):
            front.append(arg)
        elif arg == "--config" and i + 1 < len(argv):
            front.extend([arg, argv[i + 1]])
            next(items)
        elif arg.startswith("--config="):
            front.append(arg)
        else:
            rest.append(arg)
    return front + rest


class _Parser(argparse.ArgumentParser):
    """argparse exits with 2 on a usage error; here 2 means WARN only (exit codes: 0 ok, 1 failure, 2 warnings), so a usage
    error prints the usage and exits 1, and a CI step cannot take a gate that failed to start for a warning."""

    def error(self, message):
        self.print_usage(sys.stderr)
        print(f"{self.prog}: error: {message}", file=sys.stderr)
        sys.exit(1)


def build_parser(areas, version_text: str) -> argparse.ArgumentParser:
    parser = _Parser(prog="batuta.py", description="CAOS_Batuta command line.")
    parser.add_argument("--config", metavar="PATH", default=None, help="path to batuta.json")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--version", action="version", version=f"batuta {version_text}")
    subparsers = parser.add_subparsers(dest="area", metavar="<area>")
    for module in areas:
        area_parser = subparsers.add_parser(module.AREA, help=module.HELP, description=module.HELP)
        module.register(area_parser.add_subparsers(dest="verb", metavar="<verb>", required=True))
    return parser


def main(argv: list[str] | None = None, areas_dir: Path | None = None) -> int:
    argv = _hoist_global_options(list(sys.argv[1:] if argv is None else argv))
    areas, warnings = load_areas(areas_dir)
    for line in warnings:
        print(line, file=sys.stderr)
    from batuta_lib.areas import version as version_area  # always shipped; version text for --version

    parser = build_parser(areas, version_area.read_version())
    args = parser.parse_args(argv)
    if getattr(args, "func", None) is None:
        parser.print_help()
        return 0
    return int(args.func(args) or 0)


if __name__ == "__main__":
    sys.exit(main())

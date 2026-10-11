"""Area `version`: print the harness version (`harness.py version show`)."""
from __future__ import annotations

import json
from pathlib import Path

AREA = "version"
HELP = "show the harness version"

PLUGIN_ROOT = Path(__file__).resolve().parents[3]  # plugins/harness
SCRIPTS_DIR = Path(__file__).resolve().parents[2]


def _semver_to_display(semver: str) -> str:
    major, minor, patch = semver.strip().split(".")[:3]
    return f"{int(major)}.{int(minor):02d}.{int(patch):03d}"


def read_version(search_from: Path | None = None, plugin_root: Path | None = None) -> str:
    """VERSION file (display form) found above `search_from`, else the plugin manifest converted."""
    start = Path(search_from) if search_from else SCRIPTS_DIR
    for folder in [start, *start.parents]:
        candidate = folder / "VERSION"
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8").strip()
    manifest = Path(plugin_root or PLUGIN_ROOT) / ".claude-plugin" / "plugin.json"
    try:
        return _semver_to_display(json.loads(manifest.read_text(encoding="utf-8"))["version"])
    except (OSError, KeyError, ValueError) as exc:
        raise RuntimeError(f"cannot determine the version: {exc}") from exc


def _show(args) -> int:
    value = read_version()
    print(json.dumps({"version": value}) if args.json else value)
    return 0


def register(subparsers) -> None:
    show = subparsers.add_parser("show", help="print the version in display form (X.XX.XXX)")
    show.set_defaults(func=_show)

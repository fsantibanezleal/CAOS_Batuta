"""Shared helpers for the skeleton tests (stdlib only)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "plugins" / "harness" / "scripts"


def load_module(name: str, path: Path):
    """Import a module from a file path under a given name."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_harness():
    """Import the dispatcher module with its folder on sys.path, as the CLI does."""
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    return load_module("harness_cli_under_test", SCRIPTS / "harness.py")


def display_to_semver(display: str) -> str:
    major, minor, patch = display.strip().split(".")
    return f"{int(major)}.{int(minor)}.{int(patch)}"

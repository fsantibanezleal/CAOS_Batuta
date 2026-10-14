"""Area `preflight`: measured machine limits and owner-prerequisite probes, before a build or a long job.

Verbs:
    limits   CPU count, memory, free disk on each root, GPU (optional, `nvidia-smi` when on PATH), Python and Node
    prereqs  run each owner-prerequisite probe of a register and report present or missing

A machine without a GPU, or without Node, is reported absent (SKIP) and is not an error; Node is only needed by the
`npx` entry of the plugin. A prerequisite whose probe fails, times out or cannot be run is reported missing with its
owner action and the probe text, and the verb exits 1. A probe's output is discarded and never printed.
Exit codes: 0 ok, 1 failure or missing prerequisite, 2 warnings.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

from batuta_lib import config
from batuta_lib import device_profile as dp
from batuta_lib.output import emit, item

try:   # optional: a YAML register needs it, a JSON register does not
    import yaml as _yaml
except ImportError:  # pragma: no cover - depends on the interpreter
    _yaml = None

AREA = "preflight"
HELP = "Preflight: machine limits (CPU, memory, disk, GPU, Python, Node) and owner-prerequisite probes."

GB = 1024 ** 3
DEFAULT_TIMEOUT = 60
REQUIRED = ("name", "why", "owner_action", "probe")


def parse_nvidia_smi(text):
    """Parse `--query-gpu=name,memory.total,memory.free --format=csv,noheader,nounits`; None when no GPU line."""
    gpus = []
    for line in (text or "").splitlines():
        cols = [c.strip() for c in line.split(",")]
        if len(cols) < 3:
            continue
        try:
            gpus.append({"name": cols[0], "mem_total_mib": int(float(cols[1])), "mem_free_mib": int(float(cols[2]))})
        except ValueError:
            continue
    return gpus or None


class RealSystem:
    """Readings from this machine; a reading that is unavailable is None."""

    @staticmethod
    def _run(args, timeout=10):
        try:
            p = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", timeout=timeout,
                               stdin=subprocess.DEVNULL)
        except (OSError, subprocess.TimeoutExpired):
            return None
        return p.stdout if p.returncode == 0 else None

    def cpu_count(self):
        return os.cpu_count() or 1

    def memory(self):
        if sys.platform == "win32":
            return self._memory_windows()
        if sys.platform == "darwin":
            out = self._run(["sysctl", "-n", "hw.memsize"])
            try:
                return {"total": int(out.strip()), "free": None}
            except (AttributeError, ValueError):
                return None
        try:
            kb = {}
            for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
                name, _, rest = line.partition(":")
                parts = rest.split()
                if parts and parts[0].isdigit():
                    kb[name] = int(parts[0]) * 1024
            return {"total": kb["MemTotal"], "free": kb.get("MemAvailable")}
        except (OSError, KeyError):
            return None

    @staticmethod
    def _memory_windows():
        import ctypes

        class Status(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

        st = Status()
        st.dwLength = ctypes.sizeof(Status)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
            return None
        return {"total": st.ullTotalPhys, "free": st.ullAvailPhys}

    def disk_free(self, path):
        try:
            return shutil.disk_usage(path).free
        except OSError:
            return None

    def gpus(self):
        if not shutil.which("nvidia-smi"):
            return None
        out = self._run(["nvidia-smi", "--query-gpu=name,memory.total,memory.free", "--format=csv,noheader,nounits"])
        return parse_nvidia_smi(out)

    def node_version(self):
        if not shutil.which("node"):
            return None
        out = self._run(["node", "--version"])
        return out.strip() if out else None

    def python_version(self):
        return platform.python_version()


SYSTEM = RealSystem()   # replaceable by tests


def _gb(n):
    return f"{n / GB:.1f} GB"


def _flag_json(args):
    return bool(getattr(args, "json", False))


def _existing(path):
    """The nearest folder at or above `path` that exists (a root that is not created yet is measured on its drive)."""
    p = Path(path)
    for folder in [p, *p.parents]:
        if folder.exists():
            return folder
    return p


# ------------------------------------------------------------------ limits


def _limits(args):
    items, as_json = [], _flag_json(args)
    system = SYSTEM
    items.append(item("OK", f"cpu: {system.cpu_count()} logical CPU(s)"))
    mem = system.memory()
    if not mem or not mem.get("total"):
        items.append(item("WARN", "memory: not readable on this platform"))
    elif mem.get("free") is None:
        items.append(item("OK", f"memory: {_gb(mem['total'])} total, free memory not reported on this platform"))
    else:
        items.append(item("OK", f"memory: {_gb(mem['total'])} total, {_gb(mem['free'])} free"))

    try:
        cfg = config.load(getattr(args, "config", None)).config
        home = Path(args.home) if args.home else Path.home()
        deploy = dp.deploy_root(args.deploy_root)
        roots = {"deploy": deploy, **{k[:-5]: Path(v) for k, v in dp.resolve_roots(cfg, None, home).items()}}
    except (config.ConfigError, dp.ProfileError) as exc:
        items.append(item("FAIL", f"roots: {exc}"))
        roots = {}
    for name, folder in roots.items():
        free = system.disk_free(_existing(folder))
        if free is None:
            items.append(item("WARN", f"disk {name}: free space not readable", Path(folder).as_posix()))
        else:
            items.append(item("OK", f"disk {name}: {_gb(free)} free", Path(folder).as_posix()))

    gpus = system.gpus()
    if not gpus:
        items.append(item("SKIP", "gpu: no GPU detected (optional; nvidia-smi not on PATH or no device)"))
    for i, g in enumerate(gpus or []):
        items.append(item("OK", f"gpu {i}: {g['name']}, {g['mem_free_mib']} MiB free of {g['mem_total_mib']} MiB"))
    items.append(item("OK", f"python: {system.python_version()}"))
    node = system.node_version()
    if node:
        items.append(item("OK", f"node: {node}"))
    else:
        items.append(item("SKIP", "node: not found; only the npx entry of the plugin needs it"))
    return emit(AREA, "limits", items, "preflight limits: measured", as_json)


# ------------------------------------------------------------------ prereqs


def load_register(path):
    """The list of prerequisites in a JSON (or, with PyYAML, YAML) register: a `prerequisites` list or a list."""
    p = Path(path)
    text = p.read_text(encoding="utf-8-sig")
    if p.suffix.lower() in (".yaml", ".yml") and _yaml is not None:
        data = _yaml.safe_load(text)
    else:
        try:
            data = json.loads(text)
        except ValueError as exc:
            hint = "; install PyYAML or write the register as JSON" if p.suffix.lower() in (".yaml", ".yml") else ""
            raise ValueError(f"not valid JSON ({exc}){hint}") from exc
    rows = data.get("prerequisites") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        raise ValueError("the register needs a 'prerequisites' list")
    return rows


def _probe_text(probe):
    return probe if isinstance(probe, str) else " ".join(str(x) for x in probe)


def run_probe(entry, timeout=DEFAULT_TIMEOUT):
    """(present, reason) for one prerequisite; a probe that cannot run is missing. Its output is discarded."""
    absent = [k for k in REQUIRED if not entry.get(k)]
    if absent:
        return False, f"invalid item, missing field(s): {', '.join(absent)}"
    probe = entry["probe"]
    try:
        proc = subprocess.run(probe, shell=isinstance(probe, str), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              stdin=subprocess.DEVNULL, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, f"the probe timed out after {timeout} s"
    except (OSError, ValueError) as exc:
        return False, f"the probe cannot be run ({type(exc).__name__})"
    return (True, "") if proc.returncode == 0 else (False, f"the probe exited {proc.returncode}")


def _prereqs(args):
    items, as_json = [], _flag_json(args)
    try:
        rows = load_register(args.register)
    except (OSError, ValueError) as exc:
        items.append(item("FAIL", f"cannot read the register {Path(args.register).as_posix()}: {exc}"))
        return emit(AREA, "prereqs", items, "preflight prereqs: failed", as_json)
    for row in rows:
        entry = row if isinstance(row, dict) else {}
        name, why = str(entry.get("name", "?")), str(entry.get("why", ""))
        ok, reason = run_probe(entry, args.timeout)
        if ok:
            items.append(item("OK", f"{name}: {why}"))
        else:
            probe = f"; probe: {_probe_text(entry['probe'])}" if entry.get("probe") else ""
            items.append(item("FAIL", f"{name} is missing: {why}; {reason}; owner action: {entry.get('owner_action', '?')}{probe}"))
    missing = sum(1 for i in items if i["tag"] == "FAIL")
    return emit(AREA, "prereqs", items, f"preflight prereqs: {len(items) - missing} present, {missing} missing", as_json)


def register(subparsers):
    p = subparsers.add_parser("limits", help="print CPU, memory, free disk per root, GPU, Python and Node")
    p.add_argument("--home", help="home folder (default: the user's home)")
    p.add_argument("--deploy-root", help="the device copy's folder (default: BATUTA_HOME, else ~/.batuta)")
    p.set_defaults(func=_limits)

    p = subparsers.add_parser("prereqs", help="run each owner-prerequisite probe and report present or missing")
    p.add_argument("--register", required=True, help="the register: a JSON (or YAML) file with a prerequisites list")
    p.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="seconds per probe (default 60)")
    p.set_defaults(func=_prereqs)

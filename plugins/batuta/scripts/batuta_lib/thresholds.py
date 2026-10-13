"""Ratcheting thresholds (C11): a value only goes up.

The file keeps the current `values` and an append-only `history` of every change. A raise is recorded in the history. A
decrease needs a history entry and a C10 waiver of the same date for gate L9-promote written by a human; without both it is
refused. `check` replays the history and compares it with the values (and, with a git reference, with the committed
baseline), so a value lowered by editing the file is found even when nothing else records it.
"""
import json
from pathlib import Path

from batuta_lib import config, evidence, frontmatter as fm
from batuta_lib import contract as core
from batuta_lib import gate_model
from batuta_lib.output import item

DEFAULT_PATH = "specs/000-foundation/thresholds.json"
WAIVER_GATE = "L9-promote"


def _schema():
    sp = core.find_schema(config.contracts_dir(), "C11")
    return core.load_schema(sp)


def schema_errors(doc):
    return core.validate_instance("C11", doc, _schema())


def load(path):
    """(doc, errors)."""
    try:
        doc = core.loads_strict(Path(path).read_text(encoding="utf-8-sig"))
    except OSError as exc:
        return None, [f"cannot read {path}: {exc}"]
    except ValueError as exc:
        return None, [f"{path}: invalid JSON ({exc})"]
    errs = schema_errors(doc)
    return (None, errs) if errs else (doc, [])


def waiver_dates(root, roles):
    """Dates of the human waivers of L9-promote found in any specs/*/status.md."""
    dates = set()
    for p in sorted((Path(root) / "specs").glob("*/status.md")):
        try:
            meta, _ = fm.parse(evidence.strip_comments(gate_model.read(p)))
        except (OSError, ValueError):
            continue
        for w in meta.get("waivers", []) if isinstance(meta.get("waivers"), list) else []:
            if (isinstance(w, dict) and w.get("gate") == WAIVER_GATE and str(w.get("reason", "")).strip()
                    and not gate_model.is_agent_name(w.get("by", ""), roles)):
                dates.add(str(w.get("date")))
    return dates


def replay(doc, waivers):
    """Problems of a document's history against its values. The history of each name must chain (every `from` is the previous
    `to`), never go back in time, end at the current value, and every decrease must have a waiver dated that day."""
    problems, last, dates = [], {}, {}
    for i, e in enumerate(doc["history"]):
        name = e["name"]
        if name in last and e["from"] != last[name]:
            problems.append(f"history entry {i} of '{name}' goes from {e['from']} but the chain was at {last[name]}: the history chain is broken")
        if name in dates and e["date"] < dates[name]:
            problems.append(f"history entry {i} of '{name}' is dated {e['date']}, before the previous entry ({dates[name]})")
        if e["to"] < e["from"] and e["date"] not in waivers:
            problems.append(f"'{name}' was lowered from {e['from']} to {e['to']} on {e['date']} without a human waiver of "
                            f"{WAIVER_GATE} dated {e['date']} in any specs/*/status.md")
        last[name], dates[name] = e["to"], e["date"]
    for name, end in sorted(last.items()):
        if name not in doc["values"]:
            problems.append(f"'{name}' has history but is missing from values")
        elif doc["values"][name] != end:
            problems.append(f"'{name}' is {doc['values'][name]} but its history ends at {end}: a value changed without a history entry")
    return problems


def baseline_problems(doc, old):
    """Problems of `doc` against the committed baseline `old` (both valid C11 documents)."""
    problems = []
    if doc["history"][:len(old["history"])] != old["history"]:
        problems.append("the history is append-only: entries of the baseline were changed or removed")
    for name, was in sorted(old["values"].items()):
        now = doc["values"].get(name)
        if now is None:
            problems.append(f"threshold '{name}' was removed (it was {was})")
        elif now < was and not any(e["name"] == name and e["to"] < e["from"] and e["from"] <= was for e in doc["history"][len(old["history"]):]):
            problems.append(f"threshold '{name}' was lowered from {was} to {now} with no history entry for the decrease")
    return problems


def check(root, path, cfg, *, against=None):
    root = Path(root)
    full = root / path
    rel = Path(path).as_posix()
    if not full.is_file():
        return [item("SKIP", f"no thresholds file at {rel}", rel)]
    doc, errs = load(full)
    if doc is None:
        return [item("FAIL", e, rel) for e in errs]
    problems = replay(doc, waiver_dates(root, cfg.get("roles", {})))
    if against:
        text = gate_model.GIT.show(root, against, rel)
        if text is None:
            problems.append(f"cannot read {rel} at {against}")
        else:
            try:
                old = core.loads_strict(text)
                old_errs = schema_errors(old)
            except ValueError as exc:
                old, old_errs = None, [str(exc)]
            if old_errs:
                problems.append(f"the baseline at {against} is not a valid C11 document: {old_errs[0]}")
            else:
                problems.extend(baseline_problems(doc, old))
    if problems:
        return [item("FAIL", p, rel) for p in problems]
    return [item("OK", f"{rel}: {len(doc['values'])} threshold(s), {len(doc['history'])} history entr{'y' if len(doc['history']) == 1 else 'ies'}, ratchet holds", rel)]


def parse_proposal(text):
    """(name, number) of `name=value`; ValueError with the reason otherwise."""
    name, sep, raw = str(text).partition("=")
    if not sep or not name.strip() or not raw.strip():
        raise ValueError(f"'{text}' is not name=value")
    try:
        value = core.loads_strict(raw.strip())
    except ValueError:
        raise ValueError(f"'{raw}' is not a number") from None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"'{raw}' is not a number")
    return name.strip(), value


def propose(root, path, cfg, proposal, *, reason=None, today=None, apply=False):
    root = Path(root)
    today = today or gate_model.today_iso()
    rel = Path(path).as_posix()
    try:
        name, value = parse_proposal(proposal)
    except ValueError as exc:
        return [item("REFUSED", str(exc))]
    full = root / path
    if full.is_file():
        doc, errs = load(full)
        if doc is None:
            return [item("FAIL", e, rel) for e in errs]
    else:
        doc = {"contract_version": "1.0", "values": {}, "history": []}
    old = doc["values"].get(name)
    if old is None:
        doc["values"][name] = value
        msg = f"threshold '{name}' set to {value}"
        tag = "NEW"
    elif value == old:
        return [item("SAME", f"threshold '{name}' is already {value}", rel)]
    else:
        if value < old:
            if today not in waiver_dates(root, cfg.get("roles", {})):
                return [item("REFUSED", f"threshold '{name}' cannot go from {old} to {value}: thresholds only ratchet up; a decrease needs "
                                        f"a human waiver of {WAIVER_GATE} dated {today} in a specs/*/status.md and a reason", rel)]
            if not (reason or "").strip():
                return [item("REFUSED", f"lowering '{name}' needs --reason (it is recorded in the history)", rel)]
        doc["history"].append({"date": today, "name": name, "from": old, "to": value, "reason": (reason or "ratchet up").strip()})
        doc["values"][name] = value
        msg = f"threshold '{name}' {'raised' if value > old else 'lowered'} from {old} to {value}"
        tag = "CHANGED"
    problems = replay(doc, waiver_dates(root, cfg.get("roles", {}))) + schema_errors(doc)
    if problems:
        return [item("REFUSED", p, rel) for p in problems]
    if apply:
        gate_model.write_atomic(full, json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
        return [item(tag, msg, rel)]
    return [item(tag, msg + " (dry run; use --apply to write)", rel)]

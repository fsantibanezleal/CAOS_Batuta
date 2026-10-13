"""Readiness, availability and previews: what is real in a build, and what each dependency does when it is absent.

The readiness document (C27) states, per catalog row, whether the real producer serves it or a labelled provider does. It is a
pure function of the repository, so it is current when its `catalog_sha256` is the hash of the catalog and when no code commit
has landed since it was committed (more than `lag` commits that changed files outside `specs/`). A release gate lists every
component that is still on a provider, missing, partial, stale or a training model answering from its baseline as a gap.
The catalog's missing-data behavior column (C22) declares the states of each boundary with the test that proves each one; the
runtime block of C26 is what a response carries, and `check_response` ties the two together.
"""
import hashlib
import json
import re
import urllib.error
import urllib.request
from pathlib import Path

from batuta_lib import config, gate_model
from batuta_lib import contract as core
from batuta_lib.output import item

READINESS_PATHS = ("data/derived/readiness.json", "docs/design/readiness.json")
CATALOG_PATH = "docs/contracts/catalog.md"
PREVIEWS_PATH = "docs/design/previews.json"
KINDS = ("stub", "simulator", "fixture", "baseline")
STATE_ITEM = re.compile(r"^(available|partial|stale|provider\((?:stub|simulator|fixture|baseline)\)|training|missing): "
                        r"(.+) \(test: ([^)]+)\)$")
NO_MODEL = {"", "-", "n/a", "na", "none", "no"}


def _validate(cid, doc):
    sp = core.find_schema(config.contracts_dir(), cid)
    return core.validate_instance(cid, doc, core.load_schema(sp))


def readiness_errors(doc):
    return _validate("C27", doc)


def block_errors(doc):
    return _validate("C26", doc)


def reason_text(reason):
    if isinstance(reason, dict):
        return str(reason.get("en", "")).strip()
    return str(reason or "").strip()


def sha256_lf(path):
    text = Path(path).read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _rel(root, path):
    try:
        return Path(path).resolve().relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        return Path(path).as_posix()


def _abs(root, path):
    p = Path(path)
    return p if p.is_absolute() else Path(root) / p


def find_readiness(root, explicit=None):
    """The readiness document: the named path (even when absent, so the check says so) or the first default that exists."""
    if explicit:
        return _abs(root, explicit)
    for rel in READINESS_PATHS:
        if (Path(root) / rel).is_file():
            return Path(root) / rel
    return None


# ------------------------------------------------------------------ the catalog

def catalog_rows(root, path):
    """(rows, errors): the C22 rows of a catalog file, validated against C22 first."""
    sp = core.find_schema(config.contracts_dir(), "C22")
    schema, spec = core.load_schema(sp), core.load_sections_spec(sp)
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
    except OSError as exc:
        return None, [f"cannot read {path}: {exc}"]
    try:
        errors = core.validate_markdown(text, schema, spec)
    except ValueError as exc:
        errors = [str(exc)]
    if errors:
        return None, [f"C22: {e}" for e in errors]
    hit = core.read_table(text, spec["tables"][0])
    return (hit[0] if hit else []), []


def declared_states(cell):
    """{state: (behavior, test token)} of a missing-data behavior cell."""
    out = {}
    for part in str(cell).split(";"):
        m = STATE_ITEM.match(part.strip())
        if m:
            out[m.group(1)] = (m.group(2), m.group(3).strip())
    return out


def _test_exists(root, token):
    path, _, name = token.partition("::")
    target = Path(root) / path
    if not target.is_file():
        return f"test file {path} does not exist"
    if name:
        text = target.read_text(encoding="utf-8", errors="replace")
        if path.endswith(".py"):
            if not re.search(rf"\b(def|class)\s+{re.escape(name)}\b", text):
                return f"test {name} is not defined in {path}"
        elif name not in text:
            return f"test {name} is not in {path}"
    return None


def lint_catalog(root, path, *, explicit, models=None):
    """Items of `provider lint`."""
    root = Path(root)
    full = _abs(root, path)
    rel = _rel(root, full)
    if not full.is_file():
        if explicit:
            return [item("FAIL", f"catalog not found: {rel}", rel)]
        return [item("SKIP", f"no catalog at {rel} (it is written at L3-contracts)", rel)]
    rows, errors = catalog_rows(root, full)
    if rows is None:
        return [item("FAIL", e, rel) for e in errors]
    items = []
    for row in rows:
        cid, bad = row["id"], []
        states = declared_states(row["missing-data behavior"])
        tests = [tok for _, tok in states.values()]
        for dup in sorted({t for t in tests if tests.count(t) > 1}):
            bad.append(f"test {dup} proves more than one state: each state has its own test")
        for state, (_, tok) in states.items():
            problem = _test_exists(root, tok)
            if problem:
                bad.append(f"state {state}: {problem}")
        provider = str(row.get("provider", "")).strip().strip("`")
        m = re.match(r"(stub|simulator|fixture|baseline):", provider)
        if m:
            want = f"provider({m.group(1)})"
            if want not in states:
                bad.append(f"the provider is {m.group(1)} but no {want} state is declared (what the consumer sees while it answers)")
            for state in states:
                if state.startswith("provider(") and state != want:
                    bad.append(f"state {state} does not match the provider column ({m.group(1)})")
            ppath = core.cell_path(provider)
            if ppath and not (root / ppath).exists():
                bad.append(f"the provider path {ppath} does not exist")
        elif provider not in ("", "-"):
            bad.append(f"provider {provider!r} is not kind:path with kind one of {', '.join(KINDS)}")
        slot = str(row.get("model io", "")).strip().strip("`").lower() not in NO_MODEL
        if slot and "training" not in states:
            items.append(item("WARN", f"{cid}: a model slot declares no 'training' state (what answers while a version trains)", rel))
        if bad:
            items.extend(item("FAIL", f"{cid}: {b}", rel) for b in bad)
        else:
            items.append(item("OK", f"{cid}: {len(states)} state(s) declared, each with its own test ({', '.join(states)})", rel))
    if models:
        folder = _abs(root, models)
        cards = sorted(folder.glob("*/card.json")) if folder.is_dir() else []
        if not cards:
            items.append(item("WARN", f"no model cards under {_rel(root, folder)}", _rel(root, folder)))
        sp = core.find_schema(config.contracts_dir(), "C28")
        for card in cards:
            errs = core.validate_file(card, sp, "C28")
            crel = _rel(root, card)
            if errs:
                items.extend(item("FAIL", f"model card {card.parent.name}: {e}", crel) for e in errs)
            else:
                items.append(item("OK", f"model card {card.parent.name} satisfies C28", crel))
    return items


def check_response(path, *, root, catalog=None, row_id=None):
    """Items of `provider check`: the runtime block validates (C26) and its state is one the catalog row declares."""
    path = Path(path)
    rel = path.as_posix()
    try:
        doc = core.loads_strict(path.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        return [item("FAIL", f"cannot read {rel}: {exc}", rel)]
    except ValueError as exc:
        return [item("FAIL", f"{rel}: invalid JSON ({exc})", rel)]
    block = None
    if isinstance(doc, dict):
        block = doc if "state" in doc else doc.get("availability")
    if not isinstance(block, dict):
        return [item("FAIL", "the response carries no availability block (an object with state, reason, source, age, or an "
                             "`availability` key holding it)", rel)]
    errs = block_errors(block)
    if errs:
        return [item("FAIL", f"availability block: {e}", rel) for e in errs]
    state, prov = block["state"], block.get("provenance")
    label = f"provider({prov})" if state == "provider" else state
    if row_id is None:
        return [item("OK", f"availability block is valid (state {label}); the states a row declares were not checked (give --id)", rel)]
    rows, errors = catalog_rows(root, catalog)
    if rows is None:
        return [item("FAIL", e, rel) for e in errors]
    row = next((r for r in rows if r["id"] == row_id), None)
    if row is None:
        return [item("FAIL", f"catalog has no row '{row_id}'", rel)]
    declared = declared_states(row["missing-data behavior"])
    if label not in declared:
        return [item("FAIL", f"row '{row_id}' declares {', '.join(declared)}; the response says {label}", rel)]
    return [item("OK", f"availability block is valid and row '{row_id}' declares {label}", rel)]


# ------------------------------------------------------------------ readiness check

def is_gap(entry):
    """A component a release cannot ship on: a provider serves it, it is missing, partial or stale, or a model that is
    still training answers from its baseline."""
    state = entry["state"]
    return state in ("provider", "missing", "partial", "stale") or (state == "training" and entry["provenance"] != "real")


def _gap_line(e):
    extra = f"; missing: {', '.join(e['missing'])}" if e["missing"] else ""
    served = f" served by {e['provenance']}" if e["provenance"] else ""
    return f"release gap: {e['id']} is {e['state']}{served}: {reason_text(e['reason'])}{extra}"


def check_tests(root, rows, record_path, rel):
    items = []
    results, recorded = {}, False
    if record_path:
        try:
            doc = core.loads_strict(_abs(root, record_path).read_text(encoding="utf-8-sig"))
            results, recorded = doc.get("results", {}), True
        except (OSError, ValueError, AttributeError) as exc:
            items.append(item("FAIL", f"contract test record {record_path}: {exc}", rel))
    for row in rows:
        for tok in list(row["producer test"]) + list(row["consumer test"]):
            tpath = core.cell_path(tok)
            if not tpath:
                continue
            if not (Path(root) / tpath).is_file():
                items.append(item("FAIL", f"{row['id']}: contract test {tpath} does not exist", rel))
            elif recorded:
                got = results.get(tpath)
                if got == "pass":
                    continue
                if got is None:
                    items.append(item("WARN", f"{row['id']}: no recorded result for contract test {tpath}", rel))
                else:
                    items.append(item("FAIL", f"{row['id']}: contract test {tpath} is recorded as {got}", rel))
    if not recorded and not record_path:
        items.append(item("WARN", "no contract test status recorded (give --tests-record: a JSON file with results per test path)", rel))
    elif recorded and not any(i["tag"] in ("FAIL", "WARN") for i in items):
        items.append(item("OK", "every contract test the catalog names exists and is recorded as passing", rel))
    return items


def check_readiness(root, path, *, catalog=None, head=None, lag=0, release=False, tests=True, tests_record=None, age=True):
    """Items of `skeleton check` for the readiness document at `path`."""
    root, path = Path(root), Path(path)
    rel = _rel(root, path)
    try:
        doc = core.loads_strict(path.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        return [item("FAIL", f"cannot read {rel}: {exc}", rel)]
    except ValueError as exc:
        return [item("FAIL", f"{rel}: invalid JSON ({exc})", rel)]
    errs = readiness_errors(doc)
    if errs:
        return [item("FAIL", f"{rel} does not satisfy C27: {e}", rel) for e in errs]
    items = []
    cat = _abs(root, catalog or CATALOG_PATH)
    rows = None
    if cat.is_file():
        if doc["catalog_sha256"] != sha256_lf(cat):
            items.append(item("FAIL", f"{rel} is stale: its catalog_sha256 is not the hash of {_rel(root, cat)}; compute it again", rel))
        rows, errors = catalog_rows(root, cat)
        if rows is None:
            items.extend(item("FAIL", e, _rel(root, cat)) for e in errors)
        else:
            by_id = {r["id"]: r for r in rows}
            have = {e["id"]: e for e in doc["contracts"]}
            for cid in sorted(set(by_id) - set(have)):
                items.append(item("FAIL", f"catalog row '{cid}' has no readiness entry: a component the document does not label", rel))
            for cid in sorted(set(have) - set(by_id)):
                items.append(item("FAIL", f"readiness entry '{cid}' is not a row of the catalog", rel))
            for cid in sorted(set(have) & set(by_id)):
                if have[cid]["version"] != by_id[cid]["version"]:
                    items.append(item("FAIL", f"'{cid}': readiness version {have[cid]['version']} differs from the catalog's {by_id[cid]['version']}", rel))
    else:
        items.append(item("WARN", f"catalog not found at {_rel(root, cat)}: coverage and freshness were not checked", rel))
    info = gate_model.GIT.info(root) if age else None
    if not age:
        pass
    elif info is None:
        items.append(item("WARN", "not a git repository with a commit: the age of the readiness document was not checked", rel))
    else:
        dirty = gate_model.GIT.dirty(root) or []
        if rel in dirty:
            items.append(item("WARN", f"{rel} has uncommitted changes: its age cannot be measured until it is committed", rel))
        else:
            asof = gate_model.GIT.last_commit(root, rel)
            if asof is None:
                items.append(item("WARN", f"{rel} is not committed: its age was not checked", rel))
            else:
                behind = gate_model.GIT.count_since(root, asof, head or info[1], "specs")
                if behind > lag:
                    items.append(item("FAIL", f"{rel} is {behind} commit(s) behind the head (as of {asof[:12]}) that changed files outside "
                                              f"specs/; allowed {lag}: regenerate it", rel))
    for e in doc["contracts"]:
        why = reason_text(e["reason"])
        if e["state"] == "available":
            items.append(item("OK", f"{e['id']} {e['version']}: real", rel))
        else:
            tail = f" served by {e['provenance']}" if e["provenance"] else ""
            items.append(item("OK", f"{e['id']} {e['version']}: {e['state']}{tail} ({why})", rel))
    gaps = [e for e in doc["contracts"] if is_gap(e)]
    if release:
        items.extend(item("FAIL", _gap_line(e), rel) for e in gaps)
    elif gaps:
        items.append(item("OK", f"{len(gaps)} component(s) are not real yet (allowed before release): {', '.join(e['id'] for e in gaps)}", rel))
    if tests and rows is not None:
        items.extend(check_tests(root, rows, tests_record, rel))
    return items


# ------------------------------------------------------------------ previews

def fetch_status(url, timeout=10):
    """HTTP status of a GET, or None when nothing answered. Only called for http and https URLs."""
    try:
        req = urllib.request.Request(url, method="GET", headers={"User-Agent": "batuta-skeleton-check"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:   # noqa: S310 (scheme checked by the caller)
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except (urllib.error.URLError, OSError, ValueError):
        return None


def _check_url(url, network, label):
    if not re.match(r"https?://[^\s/]+", url):
        return [item("FAIL", f"{label}: {url!r} is not an http or https URL")]
    if not network:
        return [item("OK", f"{label}: {url} (reachability not checked; use --check-network)")]
    status = fetch_status(url)
    if status is not None and 200 <= status < 400:
        return [item("OK", f"{label}: {url} answered {status}")]
    return [item("FAIL", f"{label}: {url} is unreachable ({'no answer' if status is None else 'status ' + str(status)})")]


def check_previews(root, path, urls, *, head, network, explicit):
    """Items for the preview record (C29) and any URL given directly."""
    root, items = Path(root), []
    full = _abs(root, path or PREVIEWS_PATH)
    rel = _rel(root, full)
    if full.is_file():
        try:
            doc = core.loads_strict(full.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as exc:
            return [item("FAIL", f"{rel}: {exc}", rel)]
        errs = _validate("C29", doc)
        if errs:
            return [item("FAIL", f"{rel} does not satisfy C29: {e}", rel) for e in errs]
        if not doc["entries"]:
            items.append(item("WARN", f"{rel} records no preview: the walking skeleton is deployed to one", rel))
        for e in doc["entries"]:
            label = f"preview {e['env']}"
            c = str(e["commit"]).lower()
            if head and not (head.startswith(c) or c.startswith(head)):
                items.append(item("WARN", f"{label} serves commit {c[:12]} but the head is {head[:12]}", rel))
            items.extend(_check_url(e["url"], network, label))
    elif explicit:
        items.append(item("FAIL", f"preview record not found: {rel}", rel))
    elif not urls:
        items.append(item("SKIP", f"no preview record at {rel}", rel))
    for url in urls:
        items.extend(_check_url(url, network, "preview url"))
    return items

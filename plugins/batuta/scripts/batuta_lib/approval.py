"""The freeze approval (C06): the typed phrase, what the approval hashes, the record, and the VALID or VOID check.

The human types `approve <spec id> <first 12 hex of the spec's sha256>` (the keyword and the hex in any case, the phrase at
the start of the prompt, decisions 11, 16 and 28). The prefix binds the approval to the version the human read. The record
hashes the spec, every contract the spec's Interfaces section references (catalog ids resolved to their schema files), every
accepted ADR the spec references and every test file a Gate cell names, LF-normalized (decision 4). Any later change,
deletion or addition among those files voids the approval; the newest schema-valid record of a spec is the one that counts.

Only two paths write a record: the typed prompt (the `spec-approval` hook handler) and `spec approve` (the manual fallback
for devices where hooks do not run). Both go through `write_record`.
"""
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from batuta_lib import contract as core
from batuta_lib import config
from batuta_lib import spec_model as sm

PREFIX_LEN = 12
_PHRASE = re.compile(r"(?i:approve)[ \t]+(\d{3}-[a-z0-9-]+)(?:[ \t]+(\S+))?")
_HEX12 = re.compile(r"[0-9a-f]{12}\Z")


def phrase(spec_id, spec_sha):
    return f"approve {spec_id} {spec_sha[:PREFIX_LEN]}"


def parse_phrase(text):
    """(spec id, prefix as typed in lower case) when the prompt STARTS with the phrase, after leading whitespace; else None.
    The prefix is `''` when the id is not followed by one. A sentence that merely contains the phrase never matches."""
    if not text or not text.strip():
        return None
    first = text.lstrip().splitlines()[0]
    m = _PHRASE.match(first)
    if not m:
        return None
    return m.group(1), (m.group(2) or "").lower()


def valid_prefix(token):
    return bool(_HEX12.match((token or "").lower()))


def approvals_dir(root, spec_id):
    return Path(root) / sm.SPECS_DIR / spec_id / "approvals"


@dataclass
class Gathered:
    spec_id: str
    spec_rel: str = ""
    spec_sha: str = ""
    contracts: dict = field(default_factory=dict)
    adrs: dict = field(default_factory=dict)
    tests: dict = field(default_factory=dict)
    problems: list = field(default_factory=list)      # reasons that refuse a freeze
    unfrozen: list = field(default_factory=list)      # catalog ids that are referenced but not frozen
    missing: list = field(default_factory=list)       # referenced files that do not exist
    warnings: list = field(default_factory=list)
    spec: object = None

    @property
    def prefix(self):
        return self.spec_sha[:PREFIX_LEN]

    def refusals(self):
        return self.problems + self.missing_reasons() + self.unfrozen_reasons()

    def missing_reasons(self):
        return [f"{m} is missing" for m in self.missing]

    def unfrozen_reasons(self):
        return [f"contract '{c}' is not frozen (its catalog row must say frozen: yes)" for c in self.unfrozen]

    def hashed(self):
        out = {self.spec_rel: self.spec_sha}
        for group in (self.contracts, self.adrs, self.tests):
            out.update(group)
        return out


def gather(root, spec_id, catalog=None):
    """Resolve and hash everything the freeze of `spec_id` covers. Problems are collected, never raised."""
    root = Path(root)
    g = Gathered(spec_id)
    path = sm.spec_path(root, spec_id)
    g.spec_rel = sm.rel(path, root)
    if not path.is_file():
        g.problems.append(f"no spec {spec_id}: {g.spec_rel} does not exist")
        return g
    spec = sm.read_spec(path)
    g.spec = spec
    g.spec_sha = sm.sha256_lf(path)
    ids = sm.interface_ids(spec)
    if ids:
        rows, items = sm.read_catalog_rows(root, catalog)
        if rows is None:
            where = sm.rel(sm.catalog_file(root, catalog), root)
            g.problems.append(f"the interfaces cannot be resolved: no valid catalog at {where}" if not items else
                              "the catalog is invalid: " + "; ".join(i["message"] for i in items))
        else:
            by_id = {r["id"]: r for r in rows}
            for cid in ids:
                row = by_id.get(cid)
                if row is None:
                    g.problems.append(f"interface '{cid}' is not a row of the catalog")
                    continue
                if str(row.get("frozen", "no")).lower() != "yes":
                    g.unfrozen.append(cid)
                    continue
                file = core.cell_path(row["schema file"])
                if not file or not (root / file).is_file():
                    g.missing.append(file or f"the schema file of '{cid}'")
                else:
                    g.contracts[file] = sm.sha256_lf(root / file)
    for aid in sm.adr_references(spec):
        found = sm.find_adr(root, aid)
        if found is None:
            g.warnings.append(f"{aid} is referenced but not found under {sm.ADR_DIR}/; it is not hashed")
        elif sm.adr_status(found) == "Accepted":
            g.adrs[sm.rel(found, root)] = sm.sha256_lf(found)
        else:
            g.warnings.append(f"{aid} is {sm.adr_status(found) or 'of unknown status'}, not Accepted; it is not hashed")
    for rid, kind, detail in sm.gate_findings(root, spec):
        if kind == "escape":
            g.problems.append(f"{rid}: the Gate names {detail}, outside the repository")
        elif kind == "outside":
            g.problems.append(f"{rid}: the Gate names {detail}, which resolves outside the repository")
        elif kind == "none":
            g.problems.append(f"{rid}: the Gate names no test file or folder of tests the freeze can hash (configuration and documentation files never count)")
        elif detail not in g.missing:
            g.missing.append(detail)
    files, _, _ = sm.expand_tests(root, sm.spec_test_tokens(spec))
    for f in files:
        g.tests[f] = sm.sha256_lf(root / f)
    return g


# ------------------------------------------------------------------ the record


def _stamp(now):
    return now.strftime("%Y%m%dT%H%M%S%f") + "Z"


def build_record(g, typed, approved_by, tool_version, now=None):
    now = now or datetime.now(timezone.utc)
    return {
        "contract_version": "1.0",
        "spec_id": g.spec_id,
        "spec_sha256": g.spec_sha,
        "approved_spec_sha256_prefix": g.prefix,
        "contracts_sha256": dict(sorted(g.contracts.items())),
        "adrs_sha256": dict(sorted(g.adrs.items())),
        "named_tests_sha256": dict(sorted(g.tests.items())),
        "approved_by": approved_by,
        "prompt_excerpt": (typed.lstrip().splitlines() or [""])[0][:200],
        "approved_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tool_version": tool_version,
    }


def write_record(root, g, typed, approved_by, tool_version, now=None):
    """Validate the record against C06 and write it under approvals/ (a new file; older records stay as history).
    Returns the record path. Raises ValueError when the record would not satisfy C06."""
    now = now or datetime.now(timezone.utc)
    record = build_record(g, typed, approved_by, tool_version, now)
    schema = core.load_schema(core.find_schema(config.contracts_dir(), "C06"))
    errors = core.validate_instance("C06", record, schema)
    if errors:
        raise ValueError("the approval record does not satisfy C06: " + "; ".join(errors))
    folder = approvals_dir(root, g.spec_id)
    folder.mkdir(parents=True, exist_ok=True)
    text = json.dumps(record, indent=2) + "\n"
    n = 0
    while True:
        name = _stamp(now) + (f"-{n}" if n else "") + ".json"
        try:
            with open(folder / name, "x", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
            return folder / name
        except FileExistsError:
            n += 1


def _utcnow():
    return datetime.now(timezone.utc)


def _instant(text):
    """The UTC instant of an ISO 8601 `approved_at` (the C06 pattern allows Z and numeric offsets), or None."""
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def read_records(root, spec_id):
    """[(path, record or None, errors)] for every file under approvals/, oldest first by the instant in `approved_at`
    (not by its text), then by name. A record dated in the future never counts (a forged date must not outrank a real one)."""
    folder = approvals_dir(root, spec_id)
    out = []
    schema = core.load_schema(core.find_schema(config.contracts_dir(), "C06"))
    now = _utcnow()
    for f in sorted(folder.glob("*.json")) if folder.is_dir() else []:
        try:
            doc = core.loads_strict(f.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as exc:
            out.append((f, None, [f"invalid JSON ({exc})"]))
            continue
        errors = core.validate_instance("C06", doc, schema) if isinstance(doc, dict) else ["the record is not an object"]
        if not errors and doc.get("spec_id") != spec_id:
            errors = [f"the record is for spec {doc.get('spec_id')}, not {spec_id}"]
        if not errors:
            at = _instant(doc["approved_at"])
            if at is None:
                errors = ["approved_at is not a valid instant"]
            elif at > now + timedelta(minutes=5):
                errors = [f"approved_at {doc['approved_at']} is in the future"]
        out.append((f, None if errors else doc, errors))
    zero = datetime.min.replace(tzinfo=timezone.utc)
    out.sort(key=lambda r: (_instant(r[1]["approved_at"]) if r[1] else zero, r[0].name))
    return out


def newest_valid(records):
    valid = [r for r in records if r[1] is not None]
    return valid[-1] if valid else None


def check(root, spec_id, catalog=None):
    """(state, reasons, record path): VALID when the newest schema-valid record matches every file now, VOID with the reasons
    (the files that changed, were deleted or are no longer covered) otherwise; NONE when no valid record exists."""
    root = Path(root)
    records = read_records(root, spec_id)
    best = newest_valid(records)
    if best is None:
        return "NONE", [f"no approval record under {sm.SPECS_DIR}/{spec_id}/approvals/"], None, records
    path, rec, _ = best
    g = gather(root, spec_id, catalog)
    recorded = {rec_path: sha for group in ("contracts_sha256", "adrs_sha256", "named_tests_sha256") for rec_path, sha in rec[group].items()}
    recorded[g.spec_rel] = rec["spec_sha256"]
    current = g.hashed()
    reasons = []
    for p, sha in sorted(recorded.items()):
        if not (root / p).is_file():
            reasons.append(f"{p} was deleted or is missing since the approval")
        elif p not in current:
            reasons.append(f"{p} is no longer referenced by the spec")
        elif current[p] != sha:
            reasons.append(f"{p} changed since the approval")
    for p in sorted(set(current) - set(recorded)):
        reasons.append(f"{p} is referenced now but the approval does not cover it")
    reasons.extend(g.unfrozen_reasons())
    reasons.extend(g.problems)
    return ("VOID" if reasons else "VALID"), reasons, path, records


def tool_version():
    from batuta_lib.areas import version
    try:
        return version.read_version()
    except RuntimeError:
        return "0.00.000"


def current_user():
    import getpass
    try:
        return getpass.getuser() or "human"
    except Exception:  # noqa: BLE001 (no user database on some CI images)
        return os.environ.get("USER") or os.environ.get("USERNAME") or "human"

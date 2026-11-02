"""Gate evidence (C09): comment stripping, linting, and the adversary routing a gate requires.

An evidence file is the independent check of one lifecycle gate. It is valid when it satisfies C09 and the rules the
contract cannot say: every finding that is open or fixed carries a real reproduction, finding ids are unique, the
`gate` and `feature` fields match the file's place, the date is not in the future, and the role and model match the
routing of C01 (critical gates use the reviewer role on the critical model, every other gate the adversary role on the
routine model). HTML comments are stripped before anything is read, so an example left in a template can never count.
"""
import datetime
import re

from batuta_lib import config
from batuta_lib import contract as core
from batuta_lib import frontmatter as fm
from batuta_lib.output import item

FENCE = re.compile(r"^\s*(```|~~~)")
NO_REPRODUCTION = {"", "-", "--", "n/a", "na", "none", "todo", "tbd", "unknown", "?", "no", "nil"}
FINDING_HEADERS = ["Id", "Severity", "Claim", "Reproduction", "Status"]


def strip_comments(text):
    """The text without HTML comments (single or multi line) outside fenced code. Line numbers are kept: a removed
    comment leaves the newlines it spanned."""
    out, fence, in_comment = [], None, False
    for line in text.lstrip("﻿").split("\n"):
        m = FENCE.match(line)
        if not in_comment and m:
            fence = None if fence == m.group(1) else (fence or m.group(1))
            out.append(line)
            continue
        if fence is not None and not in_comment:
            out.append(line)
            continue
        kept, rest = [], line
        while True:
            if in_comment:
                end = rest.find("-->")
                if end < 0:
                    rest = ""
                    break
                rest, in_comment = rest[end + 3:], False
                continue
            start = rest.find("<!--")
            if start < 0:
                kept.append(rest)
                break
            kept.append(rest[:start])
            rest, in_comment = rest[start + 4:], True
        out.append("".join(kept))
    return "\n".join(out)


def is_critical(cfg, gate, feature):
    """A gate is critical when C01 lists it, or it is L7-build of a unit listed in `gates.critical_units` (the unit
    id equals the feature or the slug of the feature, `NNN-slug`)."""
    gates = cfg.get("gates", {})
    if gate in gates.get("critical", []):
        return True
    slug = re.sub(r"^\d{3}-", "", feature or "")
    return gate == "L7-build" and (feature in gates.get("critical_units", []) or slug in gates.get("critical_units", []))


def routing(cfg, gate, feature):
    """(role, model) the evidence of a gate must carry."""
    gates = cfg.get("gates", {})
    if is_critical(cfg, gate, feature):
        return "reviewer", gates.get("adversary_model_critical", "opus")
    return "adversary", gates.get("adversary_model_routine", "sonnet")


def model_matches(model, expected):
    """The evidence model is the routed model by its whole name: `sonnet`, `claude-sonnet-5-5`, `Claude Sonnet 5.5` and
    `claude-sonnet-5-5[1m]` match `sonnet`; `haiku-not-sonnet` and `sonnet-lite` do not. An `inherit` routing cannot be
    checked and accepts any model."""
    if expected == "inherit":
        return True
    name = re.sub(r"[\s_]+", "-", str(model).strip().lower())
    return re.fullmatch(rf"(claude-)?{re.escape(expected.lower())}(-\d+(?:[.-]\d+)*)?(\[[^\]]*\])?", name) is not None


def _schema_and_spec():
    sp = core.find_schema(config.contracts_dir(), "C09")
    if sp is None:
        raise ValueError(f"the C09 schema is not found in {config.contracts_dir()}")
    return core.load_schema(sp), core.load_sections_spec(sp)


def findings(text):
    """The rows of the Findings table of a (comment-stripped) evidence text, as dicts."""
    hit = core.read_table(text, {"headers": FINDING_HEADERS, "section": "Findings"})
    return hit[0] if hit else []


def lint_text(text, cfg, *, expect_gate=None, expect_feature=None, path=None, today=None):
    """Lint an evidence text. Returns (items, meta); meta is None when the front matter cannot be read."""
    today = today or datetime.date.today().isoformat()
    stripped = strip_comments(text)
    schema, spec = _schema_and_spec()
    items = [item("FAIL", e, path) for e in core.validate_markdown(stripped, schema, spec)]
    try:
        meta, _ = fm.parse(stripped)
    except ValueError as exc:
        return items or [item("FAIL", f"front matter: {exc}", path)], None
    if not isinstance(meta, dict) or not {"gate", "feature", "verdict", "role", "model"} <= set(meta):
        return items, None
    if expect_gate and meta.get("gate") != expect_gate:
        items.append(item("FAIL", f"evidence is for gate {meta.get('gate')!r}, expected {expect_gate!r}", path))
    if expect_feature and meta.get("feature") != expect_feature:
        items.append(item("FAIL", f"evidence is for feature {meta.get('feature')!r}, expected {expect_feature!r}", path))
    date = str(meta.get("date", ""))
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", date) and date > today:
        items.append(item("FAIL", f"evidence is dated {date}, after today ({today})", path))
    gate = meta.get("gate")
    if gate in core_gates():
        role, model = routing(cfg, gate, meta.get("feature"))
        if meta.get("role") != role:
            why = (" (a script is not an independent check: a gate needs an adversary or reviewer agent that did not build the result)"
                   if meta.get("role") == "script" else "")
            items.append(item("FAIL", f"gate {gate} needs evidence from the {role} role, found role {meta.get('role')!r}{why}", path))
        if not model_matches(meta.get("model", ""), model):
            items.append(item("FAIL", f"gate {gate} routes to model {model!r}, the evidence names {meta.get('model')!r}", path))
    rows, seen = findings(stripped), set()
    for row in rows:
        fid = row.get("Id", "")
        if fid in seen:
            items.append(item("FAIL", f"finding id {fid!r} appears twice", path))
        seen.add(fid)
        if row.get("Status") in ("open", "fixed") and str(row.get("Reproduction", "")).strip().lower() in NO_REPRODUCTION:
            items.append(item("FAIL", f"finding {fid} has no reproduction (a finding without one is dropped, status dropped-no-repro)", path))
    return items, meta


def core_gates():
    return ("L0-understand", "L1-size", "L2-decide", "L3-contracts", "L4-boundaries", "L5-freeze", "L6-skeleton",
            "L7-build", "L8-integrate", "L9-promote", "L10-lessons")

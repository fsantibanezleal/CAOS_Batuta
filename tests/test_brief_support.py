"""Helpers shared by the route, brief and report tests (unit U2), plus the checks of the helpers themselves."""
from __future__ import annotations

import contextlib
import io
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from _support import SCRIPTS, load_batuta  # noqa: E402

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

PLUGIN = ROOT / "plugins" / "batuta"
CONTRACTS = PLUGIN / "contracts"
FIXTURES = ROOT / "tests" / "fixtures"

# the answers for every slot of the shipped template (regex of the slot -> text)
FILLED = {
    r"\(<fill: why this model[^>]*>\)": "(locating files is a lookup without judgment)",
    r"<fill: absolute path of the worktree[^\n]*": "/work/repo",
    r"<fill: read-only[^>]*>": "src/area/, tests/area/",
    r"<fill: expected size[^>]*>": "about 20 turns",
    r"<fill: the task or issue[^>]*>": "issue 12",
    r"<fill: one sentence[^>]*>": "Count the scripts.",
    r"<fill: why this unit exists[^>]*>": "Evidence for the finding.",
    r"<fill: terms, data shapes[^>]*>": "None.",
    r"<fill: for implement and docs[^>]*>": "List each family.",
    r"<fill: what the agent must not[^>]*>": "Do not run any script.",
    r"<fill: one checkable outcome>": "a table of script families with member counts",
    r"<fill: an acceptance criterion[^>]*>": "every file appears once",
    r"<fill: ADR ids[^>]*>": "ADR-001 constrains the storage; no amendment proposed.",
    r"<fill: the unit id[^>]*>": "Unit U1 of the sizing document.",
    r"<fill: consumed and produced[^>]*>": "Consumed: alert v1 (alert.schema.json). Produced: report v1 (report.schema.json).",
    r"<fill: empty sets[^>]*>": "Empty input returns an empty list.",
    r"<fill: what this unit does[^>]*>": "An absent input yields an empty report.",
    r"<fill: versions verified[^>]*>": "Python 3.12 verified 2026-10-11 on python.org.",
    r"<fill: none, or each item[^>]*>": "None.",
    r"<fill: none, or the fragment[^>]*>": "None.",
    r"<fill: claims the reviewer[^>]*>": "An empty input must not crash the unit.",
    r"<fill: the exact command[^>]*>": "`python run.py --real` exits 0 on the real path.",
    r"<fill: a backticked command[^>]*>": "`python -m unittest` exits 0",
}


def write_config(root, **override):
    """Write `<root>/.batuta/batuta.json`: the C01 defaults with the given top-level keys replaced."""
    from batuta_lib import config
    doc = config.default_config({"BATUTA_HOME": str(Path(root) / "home")})
    doc.update(override)
    folder = Path(root) / ".batuta"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "batuta.json").write_text(json.dumps(doc), encoding="utf-8")
    return doc


def run(*argv, env=None, stdin=None):
    """Run the CLI in process: (exit code, stdout, stderr). No user configuration is ever read."""
    batuta = load_batuta()
    out, err = io.StringIO(), io.StringIO()
    environ = {"BATUTA_HOME": str(ROOT / "no-such-home")}
    environ.update(env or {})
    with mock.patch.dict(os.environ, environ), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        if stdin is not None:
            with mock.patch.object(sys, "stdin", io.StringIO(stdin)):
                code = batuta.main([str(a) for a in argv])
        else:
            code = batuta.main([str(a) for a in argv])
    return code, out.getvalue(), err.getvalue()


def run_json(*argv, **kw):
    code, out, err = run(*argv, "--json", **kw)
    return code, json.loads(out), err


def fill(text):
    for pattern, value in FILLED.items():
        text = re.sub(pattern, lambda _m, v=value: v, text)
    return text


class TempCase(unittest.TestCase):
    """A temporary project root per test."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()

    def new_brief(self, topic="alpha", agent="implementer", *extra, date="2026-10-10", title="Inventory"):
        code, data, err = run_json("brief", "new", "--slug", "demo", "--topic", topic, "--agent", agent, "--title", title,
                                   "--root", self.root, "--date", date, *extra)
        self.assertEqual(code, 0, (data, err))
        path = next(i["path"] for i in data["items"] if i["tag"] == "NEW" and i["path"].endswith(".brief.md"))
        return Path(path)

    def filled_brief(self, topic="alpha", agent="implementer", *extra, **kw):
        brief = self.new_brief(topic, agent, *extra, **kw)
        brief.write_text(fill(brief.read_text(encoding="utf-8")), encoding="utf-8", newline="\n")
        return brief

    @property
    def ledger(self):
        return self.root / ".batuta" / "delegation" / "ledger.md"


def report_text(rows, extra="", crlf=False):
    """A report with a Completeness table; rows is a list of (id, status, evidence)."""
    lines = ["# Report", "", "## Summary", "Short summary.", ""]
    for ident, _s, _e in rows:
        lines += [f"## {ident} outcome", "evidence in `path:1`", ""]
    lines += ["## Completeness", "", "| ID | Status | Evidence |", "|---|---|---|"]
    lines += [f"| {i} | {s} | {e} |" for i, s, e in rows]
    text = "\n".join(lines) + "\n" + extra
    return text.replace("\n", "\r\n") if crlf else text


class SupportTests(unittest.TestCase):
    def test_every_slot_of_the_template_has_an_answer(self):
        from batuta_lib import delegation
        for kind in ("implement", "lookup"):
            text = delegation.render_template(kind, {"title": "T", "id": "t-2026-10-10", "agent": "searcher", "kind": kind,
                                                      "model": "haiku", "report": "/r.md", "brief": "/b.md", "sizing": ""})
            self.assertEqual(delegation.SLOT.findall(fill(text)), [], kind)


if __name__ == "__main__":
    unittest.main()

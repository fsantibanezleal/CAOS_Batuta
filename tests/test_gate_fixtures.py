"""Shared builders for the gate, skeleton, provider and lessons tests, and the contract tests of the consumed contracts.

`Project` builds a scratch project in a temp folder: a git repository with a spec, a contract, evidence files, a status
file, a hash-bound approval, a catalog and a readiness document. Nothing here touches a real repository.
This module also holds the contract conformance tests of this unit (ADR-0080 section 6: contract tests come first):
every consumed contract fixture is read by the gate code and the invalid ones are rejected for their stated reason.
"""
import contextlib
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "plugins" / "batuta" / "scripts"))
from _support import load_batuta  # noqa: E402

CONTRACTS = ROOT / "plugins" / "batuta" / "contracts"
TODAY = "2026-10-12"
GATES = ("L0-understand", "L1-size", "L2-decide", "L3-contracts", "L4-boundaries", "L5-freeze", "L6-skeleton",
         "L7-build", "L8-integrate", "L9-promote", "L10-lessons")
CRITICAL = ("L2-decide", "L5-freeze", "L9-promote")
FEATURE = "001-widget"


def run(*argv, cwd=None, stdin=None):
    """Run the CLI in-process; returns (exit code, stdout)."""
    batuta = load_batuta()
    out, err = io.StringIO(), io.StringIO()
    env = {"BATUTA_HOME": str(ROOT / "no-such-home"), "BATUTA_CONFIG": ""}
    old = os.getcwd()
    with mock.patch.dict(os.environ, env), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        if cwd:
            os.chdir(cwd)
        try:
            if stdin is not None:
                with mock.patch("sys.stdin", io.StringIO(stdin)):
                    code = batuta.main(list(argv))
            else:
                code = batuta.main(list(argv))
        finally:
            os.chdir(old)
    return code, out.getvalue() + err.getvalue()


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def evidence_text(gate, feature=FEATURE, *, verdict="PASS", role=None, model=None, commit="abc1234", date=TODAY,
                  findings=None, extra_body="", comment=""):
    if role is None:
        role = "reviewer" if gate in CRITICAL else "adversary"
    if model is None:
        model = "opus" if gate in CRITICAL else "sonnet"
    rows = findings if findings is not None else []
    table = "| Id | Severity | Claim | Reproduction | Status |\n|---|---|---|---|---|\n" + "".join(
        f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} | {r[4]} |\n" for r in rows)
    return (f"{comment}---\ngate: {gate}\nfeature: {feature}\nverdict: {verdict}\nrole: {role}\nmodel: {model}\n"
            f"commit: {commit}\ndate: {date}\n---\n\n## Definition of done restated\n\nAll tests pass.\n\n"
            f"## Commands and output\n\n`python -m unittest`: OK\n\n## Findings\n\n{table}{extra_body}\n"
            f"## Waivers requested\n\nNone.\n")


class FakeGit:
    """An in-memory stand-in for `gate_model.Git`. A real git process costs seconds on a loaded machine, so the suite
    models the repository (commits, parents, changed files, the working tree's pending paths, branches) and runs real git
    only in `test_gate_git_real.py`. It answers exactly the questions the gate code asks through the Git interface."""

    def __init__(self, enabled=True):
        self.enabled = enabled
        self.commits = {}        # sha -> {"parents": [...], "files": set, "snap": {path: text}}
        self.order = []          # shas in creation order
        self.branches = {"develop": None}
        self.current = "develop"
        self.pending = set()     # paths changed in the working tree since the last commit
        self.tracked = {}        # path -> text, as of the last commit
        self.merges = []
        self.counter = 0

    # ---- model
    def head_sha(self):
        return self.branches[self.current]

    def add_commit(self, parents, files, snap, branch=None):
        self.counter += 1
        import hashlib as _h
        sha = _h.sha1(f"fake-{self.counter}".encode()).hexdigest()
        self.commits[sha] = {"parents": list(parents), "files": set(files), "snap": dict(snap)}
        self.order.append(sha)
        if branch:
            self.branches[branch] = sha
        return sha

    def _ancestors(self, sha):
        seen, stack, out = set(), [sha], []
        while stack:
            cur = stack.pop()
            if cur is None or cur in seen:
                continue
            seen.add(cur)
            out.append(cur)
            stack.extend(reversed(self.commits[cur]["parents"]))
        return sorted(out, key=self.order.index, reverse=True)

    def _full(self, ref):
        if ref in self.commits:
            return ref
        if ref == "HEAD":
            return self.head_sha()
        if ref in self.branches:
            return self.branches[ref]
        hits = [s for s in self.commits if s.startswith(ref)] if len(ref) >= 4 else []
        return hits[0] if len(hits) == 1 else None

    # ---- the Git interface
    def info(self, root):
        return ("", self.head_sha()) if self.enabled else None

    def history(self, root, head):
        return self._ancestors(head)

    def is_ancestor(self, root, a, b):
        return a in self._ancestors(b)

    def changed(self, root, a, b):
        keep = set(self._ancestors(b)) - set(self._ancestors(a))
        names = set()
        for sha in keep:
            names |= self.commits[sha]["files"]
        return sorted(names)

    def dirty(self, root):
        return sorted(self.pending) if self.enabled else None

    def last_commit(self, root, relpath):
        for sha in self._ancestors(self.head_sha()):
            if relpath in self.commits[sha]["files"]:
                return sha
        return None

    def count_since(self, root, since, head, exclude_prefix):
        skip = set(self._ancestors(since))
        n = 0
        for sha in self._ancestors(head):
            if sha in skip:
                continue
            if any(not f.startswith(exclude_prefix + "/") for f in self.commits[sha]["files"]):
                n += 1
        return n

    def show(self, root, ref, relpath):
        sha = self._full(ref)
        return self.commits[sha]["snap"].get(relpath) if sha else None

    def branch(self, root):
        return self.current

    def rev(self, root, ref):
        return self._full(ref)

    def checkout(self, name, create=False):
        if create:
            self.branches[name] = self.head_sha()
        self.current = name

    def merge(self, root, sha, message):
        parents = [self.head_sha(), sha]
        merged = self.add_commit(parents, self.changed(root, self.head_sha(), sha), self.commits[sha]["snap"], self.current)
        self.merges.append((sha, message, merged))
        return 0, "merged"


class Project:
    """A scratch project under a temp folder; its git repository is a `FakeGit` installed as `gate_model.GIT`."""

    def __init__(self, tmp, feature=FEATURE, git=True):
        self.root = Path(tmp) / "proj"
        self.root.mkdir(parents=True)
        self.feature = feature
        self.git_enabled = git
        self.fake = FakeGit(enabled=git)
        self.install()

    def install(self):
        from batuta_lib import gate_model
        gate_model.GIT = self.fake

    def write(self, rel, text):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(text.encode("utf-8"))
        self.fake.pending.add(rel)
        return p

    def remove(self, rel):
        (self.root / rel).unlink()
        self.fake.pending.add(rel)

    def commit(self, message="work"):
        f = self.fake
        for rel in f.pending:
            path = self.root / rel
            if path.exists():
                f.tracked[rel] = path.read_bytes().decode("utf-8", "replace")
            else:
                f.tracked.pop(rel, None)
        parents = [f.head_sha()] if f.head_sha() else []
        sha = f.add_commit(parents, f.pending, f.tracked, f.current)
        f.pending = set()
        return sha

    def orphan_commit(self):
        """A commit on another line of history (not an ancestor of HEAD); HEAD does not move."""
        self.fake.add_commit([], {"other.txt"}, {"other.txt": "x\n"})
        return self.fake.order[-1]

    def first(self):
        return self.fake.order[0]

    def head(self):
        return self.fake.head_sha() or "abc1234"

    # ---- artifacts
    def spec_dir(self):
        return f"specs/{self.feature}"

    def evidence(self, gate, **kw):
        kw.setdefault("commit", self.head() if self.git_enabled else "abc1234")
        return self.write(f"{self.spec_dir()}/evidence/{gate}.md", evidence_text(gate, self.feature, **kw))

    def status(self, gates, phase=None, waivers=None, extra=""):
        """gates: dict gate -> state. phase defaults to the first incomplete gate (or done)."""
        full = {g: gates.get(g, "pending") for g in GATES}
        if phase is None:
            phase = next((g for g in GATES if full[g] not in ("passed", "waived")), "done")
        lines = ["---", f"feature: {self.feature}", f"phase: {phase}", "gates:"]
        lines += [f"  {g}: {full[g]}" for g in GATES]
        if waivers:
            lines.append("waivers:")
            for w in waivers:
                lines.append(f"  - {{gate: {w['gate']}, reason: \"{w['reason']}\", by: {w['by']}, date: {w['date']}}}")
        lines.append("blocked: false")
        if extra:
            lines.append(extra)
        lines += ["---", "", "## Notes", "", "Body of the status file.", ""]
        return self.write(f"{self.spec_dir()}/status.md", "\n".join(lines))

    def contract_file(self):
        return self.write("contracts/C01-widget.schema.json", '{"title": "widget"}\n')

    def spec(self, text="# Spec\n\nrequirements\n"):
        return self.write(f"{self.spec_dir()}/spec.md", text)

    def approval(self, *, tamper=None, by="alex", excerpt=None, stamp="20261010T100000"):
        """A hash-bound approval of the current spec and contract (call after writing them)."""
        spec = self.root / self.spec_dir() / "spec.md"
        contract = self.root / "contracts/C01-widget.schema.json"
        spec_sha = sha256_file(spec)
        prefix = spec_sha[:12]
        doc = {
            "contract_version": "1.0", "spec_id": self.feature, "spec_sha256": spec_sha,
            "approved_spec_sha256_prefix": prefix,
            "contracts_sha256": {"contracts/C01-widget.schema.json": sha256_file(contract)},
            "named_tests_sha256": {}, "adrs_sha256": {}, "approved_by": by,
            "prompt_excerpt": excerpt or f"approve {self.feature} {prefix}",
            "approved_at": "2026-10-10T10:00:00Z", "tool_version": "0.01.000",
        }
        if tamper:
            doc.update(tamper)
        return self.write(f"{self.spec_dir()}/approvals/{stamp}.json", json.dumps(doc, indent=2) + "\n")

    def catalog(self, rows=None):
        """The catalog (C22) with one real row by default, and the test files its rows name."""
        rows = rows or [catalog_row("widget-event")]
        head = ("| id | version | owner | schema file | example | producer test | consumer test | missing-data behavior | "
                "provider | swap test | status |\n|---|---|---|---|---|---|---|---|---|---|---|\n")
        self.write("docs/contracts/catalog.md", "# Catalog\n\n" + head + "".join(r + "\n" for r in rows))
        for name in ("producer", "consumer", "swap"):
            self.write(f"tests/test_widget_{name}.py",
                       "def test_available(): pass\ndef test_provider(): pass\ndef test_missing(): pass\n"
                       "def test_partial(): pass\ndef test_training(): pass\n")
        self.write("docs/contracts/examples/widget.json", "{}\n")
        return self.root / "docs/contracts/catalog.md"

    def catalog_sha(self):
        text = (self.root / "docs/contracts/catalog.md").read_text(encoding="utf-8-sig").replace("\r\n", "\n")
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def readiness(self, entries=None, *, sha=None, path="data/derived/readiness.json"):
        entries = entries or [readiness_entry("widget-event")]
        doc = {"schema": "widget.readiness/v1", "product_version": "0.01.000",
               "catalog_sha256": sha or self.catalog_sha(), "contracts": entries}
        return self.write(path, json.dumps(doc, indent=2) + "\n")

    def full(self, gates=GATES, *, states=None, readiness_entries=None):
        """A compliant project: spec, contract, approval, catalog, readiness and tests committed once; evidence for each
        gate in `gates` (all naming that commit) and the status committed second."""
        self.spec()
        self.contract_file()
        self.approval()
        self.catalog()
        self.readiness(readiness_entries)
        base = self.commit("spec, contracts, catalog, readiness")
        passed = {}
        for g in gates:
            self.evidence(g, commit=base)
            passed[g] = "passed"
        passed.update(states or {})
        self.status(passed)
        self.commit("evidence and status")
        return self


def catalog_row(cid, *, version="1.0.0", status="real", kind="fixture", behavior=None, model_io="", provider=None):
    behavior = behavior or ("available: normal answer (test: tests/test_widget_consumer.py::test_available); "
                            f"provider({kind}): labelled degraded (test: tests/test_widget_consumer.py::test_provider); "
                            "missing: empty result with a reason (test: tests/test_widget_consumer.py::test_missing)")
    provider = provider or f"{kind}:docs/contracts/examples/widget.json"
    cells = [cid, version, "core", "contracts/C01-widget.schema.json", "docs/contracts/examples/widget.json",
             "tests/test_widget_producer.py", "tests/test_widget_consumer.py", behavior, provider,
             "tests/test_widget_swap.py", status]
    return "| " + " | ".join(cells) + " |"


def readiness_entry(cid, *, state="available", status="real", provenance="real", reason=None, missing=None, version="1.0.0"):
    return {"id": cid, "version": version, "status": status, "provenance": provenance, "state": state,
            "reason": reason, "missing": missing or []}


_TEMPLATE = {}


def full_template():
    """One compliant project built once per process; tests copy it."""
    if "dir" not in _TEMPLATE:
        holder = tempfile.TemporaryDirectory()
        _TEMPLATE["holder"] = holder
        proj = Project(Path(holder.name))
        proj.full()
        _TEMPLATE["dir"] = proj.root
        _TEMPLATE["fake"] = proj.fake
    return _TEMPLATE["dir"]


class Case(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._restore_git)

    @staticmethod
    def _restore_git():
        from batuta_lib import gate_model
        gate_model.GIT = gate_model.Git()

    def project(self, **kw):
        return Project(self.tmp, **kw)

    def full_project(self):
        """A copy of the compliant project (git history included)."""
        import copy
        import shutil
        proj = Project.__new__(Project)
        proj.root = self.tmp / "proj"
        proj.feature = FEATURE
        proj.git_enabled = True
        shutil.copytree(full_template(), proj.root)
        proj.fake = copy.deepcopy(_TEMPLATE["fake"])
        proj.install()
        return proj

    def fails_with(self, out, fragment):
        self.assertIn(fragment, out, out)


# ------------------------------------------------------------------ contract conformance (consumed contracts)


class ConsumedContracts(unittest.TestCase):
    """Every invalid fixture of C09, C10, C11, C26 and C27 is rejected by the gate code for the stated reason, and the
    valid ones are accepted."""

    def _each(self, cid, pattern):
        return sorted((CONTRACTS / "fixtures" / cid).glob(pattern))

    def test_c09_valid_fixtures_pass_the_evidence_lint(self):
        from batuta_lib import config, evidence
        cfg = config.default_config()
        for path in self._each("C09", "valid-*.md"):
            text = path.read_text(encoding="utf-8")
            schema_errors = [i for i in evidence.lint_text(text, cfg)[0] if "routes to model" not in i["message"]
                             and "needs evidence from" not in i["message"]]
            self.assertEqual([], schema_errors, path.name)

    def test_c09_invalid_fixtures_are_rejected(self):
        from batuta_lib import config, evidence
        cfg = config.default_config()
        for path in self._each("C09", "invalid-*.md"):
            items, _ = evidence.lint_text(path.read_text(encoding="utf-8"), cfg)
            self.assertTrue(any(i["tag"] == "FAIL" for i in items), path.name)

    def test_c10_invalid_fixtures_are_rejected_by_gate_status_loading(self):
        from batuta_lib import gate_model
        for path in self._each("C10", "invalid-*.md"):
            errors = gate_model.status_errors(path.read_text(encoding="utf-8"))
            self.assertTrue(errors, path.name)

    def test_c10_valid_fixtures_are_accepted(self):
        from batuta_lib import gate_model
        for path in self._each("C10", "valid-*.md"):
            self.assertEqual([], gate_model.status_errors(path.read_text(encoding="utf-8")), path.name)

    def test_c11_fixtures(self):
        from batuta_lib import thresholds
        from batuta_lib import contract as core
        for path in self._each("C11", "valid-*.json"):
            self.assertEqual([], thresholds.schema_errors(core.loads_strict(path.read_text(encoding="utf-8"))), path.name)
        for path in self._each("C11", "invalid-*.json"):
            try:
                doc = core.loads_strict(path.read_text(encoding="utf-8"))
            except ValueError:
                continue          # refused while reading (strict JSON): the same rejection the gate code makes
            doc = {k: v for k, v in doc.items() if not k.startswith("_")}
            self.assertTrue(thresholds.schema_errors(doc), path.name)

    def test_c26_fixtures_through_provider_check(self):
        from batuta_lib import readiness
        for path in self._each("C26", "valid-*.json"):
            doc = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual([], readiness.block_errors(doc), path.name)
        for path in self._each("C26", "invalid-*.json"):
            doc = {k: v for k, v in json.loads(path.read_text(encoding="utf-8")).items() if not k.startswith("_")}
            self.assertTrue(readiness.block_errors(doc), path.name)

    def test_c27_fixtures_through_skeleton_check(self):
        from batuta_lib import readiness
        for path in self._each("C27", "valid-*.json"):
            self.assertEqual([], readiness.readiness_errors(json.loads(path.read_text(encoding="utf-8"))), path.name)
        for path in self._each("C27", "invalid-*.json"):
            doc = {k: v for k, v in json.loads(path.read_text(encoding="utf-8")).items() if not k.startswith("_")}
            self.assertTrue(readiness.readiness_errors(doc), path.name)


if __name__ == "__main__":
    unittest.main()

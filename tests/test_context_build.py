"""context build: C12 validation, the byte-stable index, path-scoped stubs and the always-loaded core."""
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from _support import load_batuta  # noqa: E402

FIXTURES = ROOT / "plugins" / "batuta" / "contracts" / "fixtures" / "C12"


def run(*argv):
    batuta = load_batuta()
    out, err = io.StringIO(), io.StringIO()
    with mock.patch.dict(os.environ, {"BATUTA_HOME": str(ROOT / "no-such-home")}), \
            contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = batuta.main(list(argv))
    return code, out.getvalue()


def unit(uid, kind="rule", load="always", **extra):
    base = {"id": uid, "title": uid.replace("-", " ").title(), "kind": kind, "file": f"units/{uid}.md",
            "summary": f"Summary of {uid}.", "load": load}
    base.update(extra)
    return base


class Case(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.out = self.dir / "rendered"

    def manifest(self, units, core=7000, index=4000, bodies=None):
        (self.dir / "units").mkdir(exist_ok=True)
        for u in units:
            body = (bodies or {}).get(u["id"], f"Body of {u['id']}.\n")
            (self.dir / u["file"]).write_bytes(body.encode("utf-8"))
        doc = {"contract_version": "1.0", "budget": {"core_bytes": core, "index_bytes": index}, "units": units}
        path = self.dir / "manifest.json"
        path.write_text(json.dumps(doc), encoding="utf-8")
        return path

    def build(self, path, *extra):
        return run("context", "build", "--manifest", str(path), "--out", str(self.out), *extra)

    def sample(self, **kw):
        return self.manifest([
            unit("never-stop", summary="Decide and act."),
            unit("deploy-vps", kind="procedure", load="trigger", triggers=["deploy", "vps"], requires=["never-stop"]),
            unit("ui-rules", kind="reference", load="path", paths=["web/**", 'a"b.css']),
        ], **kw)

    def tree(self):
        return {p.relative_to(self.out).as_posix(): p.read_bytes() for p in self.out.rglob("*") if p.is_file()}


class Build(Case):
    def test_dry_run_reports_and_writes_nothing(self):
        code, text = self.build(self.sample())
        self.assertEqual(code, 0, text)
        for name in ("INDEX.md", "CORE.md", "rules/ui-rules.md"):
            self.assertIn(f"NEW {name}", text.replace("\\", "/"))
        self.assertFalse(self.out.exists())

    def test_apply_writes_then_second_apply_is_same_and_bytes_equal(self):
        path = self.sample()
        self.assertEqual(self.build(path, "--apply")[0], 0)
        first = self.tree()
        self.assertEqual(sorted(first), ["CORE.md", "INDEX.md", "rules/ui-rules.md"])
        code, text = self.build(path, "--apply")
        self.assertEqual(code, 0)
        self.assertNotIn("NEW ", text)
        self.assertNotIn("CHANGED ", text)
        self.assertIn("SAME INDEX.md", text.replace("\\", "/"))
        self.assertEqual(first, self.tree())
        self.assertTrue(all(b"\r" not in v for v in first.values()))

    def test_output_is_independent_of_unit_order(self):
        a = self.sample()
        self.build(a, "--apply")
        one = self.tree()
        shutil.rmtree(self.out)
        units = json.loads(a.read_text(encoding="utf-8"))["units"]
        self.manifest(list(reversed(units)))
        self.build(self.dir / "manifest.json", "--apply")
        self.assertEqual(one, self.tree())

    def test_index_layout(self):
        self.build(self.sample(), "--apply")
        lines = (self.out / "INDEX.md").read_text(encoding="utf-8").splitlines()
        self.assertTrue(lines[0].startswith("# "))
        self.assertTrue(any(line.startswith("> ") for line in lines[:4]))
        self.assertIn("## Rules", lines)
        self.assertIn("## Procedures", lines)
        self.assertIn("## References", lines)
        self.assertNotIn("## Decisions", lines)
        deploy = next(line for line in lines if "units/deploy-vps.md" in line)
        self.assertIn("Triggers: deploy, vps", deploy)
        self.assertIn("Requires: never-stop", deploy)
        self.assertTrue(deploy.startswith("- ["))

    def test_stub_has_paths_front_matter_and_points_to_the_source(self):
        self.build(self.sample(), "--apply")
        text = (self.out / "rules" / "ui-rules.md").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\npaths:\n"))
        self.assertIn('  - "web/**"', text)
        self.assertIn('  - "a\\"b.css"', text)
        self.assertIn("units/ui-rules.md", text)
        self.assertNotIn("Body of ui-rules", text)

    def test_core_holds_only_always_units(self):
        self.build(self.sample(), "--apply")
        core = (self.out / "CORE.md").read_text(encoding="utf-8")
        self.assertIn("Body of never-stop.", core)
        self.assertNotIn("Body of deploy-vps", core)
        self.assertNotIn("Body of ui-rules", core)

    def test_empty_manifest_renders_empty_index_and_core(self):
        code, text = self.build(self.manifest([]), "--apply")
        self.assertEqual(code, 0, text)
        self.assertTrue((self.out / "INDEX.md").is_file())
        self.assertTrue((self.out / "CORE.md").is_file())
        self.assertFalse((self.out / "rules").exists())

    def test_requires_cycle_is_refused(self):
        path = self.manifest([unit("a", requires=["b"]), unit("b", requires=["a"])])
        code, text = self.build(path, "--apply")
        self.assertEqual(code, 1)
        self.assertIn("FAIL", text)
        self.assertIn("cycle", text)
        self.assertFalse(self.out.exists())

    def test_missing_unit_file_fails(self):
        path = self.sample()
        (self.dir / "units" / "deploy-vps.md").unlink()
        code, text = self.build(path, "--apply")
        self.assertEqual(code, 1)
        self.assertIn("deploy-vps.md", text)
        self.assertFalse(self.out.exists())

    def test_summary_over_160_chars_fails(self):
        code, text = self.build(self.manifest([unit("a", summary="x" * 161)]))
        self.assertEqual(code, 1)
        self.assertIn("FAIL", text)

    def test_unit_file_may_not_escape_the_manifest_folder(self):
        path = self.manifest([unit("a")])
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["units"][0]["file"] = "../outside.md"
        path.write_text(json.dumps(doc), encoding="utf-8")
        code, text = self.build(path)
        self.assertEqual(code, 1, text)

    def test_no_manifest_names_the_expected_path(self):
        missing = self.dir / "nowhere" / "manifest.json"
        code, text = run("context", "build", "--manifest", str(missing), "--out", str(self.out))
        self.assertEqual(code, 1)
        self.assertIn("nowhere", text)

    def test_json_output_is_c20(self):
        code, text = run("--json", "context", "build", "--manifest", str(self.sample()), "--out", str(self.out))
        data = json.loads(text)
        self.assertEqual((data["area"], data["verb"], data["exit_code"]), ("context", "build", code))


class Links(Case):
    def test_every_index_and_stub_link_resolves_in_the_default_layout(self):
        path = self.sample()
        code, text = run("context", "build", "--manifest", str(path), "--apply")
        self.assertEqual(code, 0, text)
        out = path.parent / "rendered"
        import re as _re
        for page in (out / "INDEX.md", out / "rules" / "ui-rules.md"):
            body = page.read_text(encoding="utf-8")
            links = _re.findall(r"\]\(([^)]+)\)", body) + _re.findall(r"`([^`]+\.md)`", body)
            self.assertTrue(links, page.name)
            for link in links:
                self.assertTrue((page.parent / link).resolve().is_file(), f"{page.name}: {link}")

    def test_links_do_not_depend_on_the_working_directory(self):
        path = self.sample()
        run("context", "build", "--manifest", str(path), "--out", str(self.out), "--apply")
        first = self.tree()
        cwd = os.getcwd()
        os.chdir(self.dir)
        try:
            run("context", "build", "--manifest", "manifest.json", "--out", "rendered", "--apply")
        finally:
            os.chdir(cwd)
        self.assertEqual(first, self.tree())


class CoreVersusUserBudget(Case):
    def test_core_over_the_c01_user_core_budget_warns_at_build(self):
        units = [unit("big")]
        path = self.manifest(units, core=100000, bodies={"big": "x" * 8000 + "\n"})
        code, text = self.build(path, "--apply")
        self.assertEqual(code, 2, text)
        self.assertIn("WARN", text)
        self.assertIn("user_core_bytes", text)
        self.assertTrue((self.out / "CORE.md").is_file())


class Stale(Case):
    def test_generated_stub_of_a_unit_that_left_the_path_load_is_removed_but_a_foreign_file_stays(self):
        path = self.sample()
        self.build(path, "--apply")
        (self.out / "rules" / "mine.md").write_text("my own rule\n", encoding="utf-8")
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["units"][2].update(load="manual")
        doc["units"][2].pop("paths")
        path.write_text(json.dumps(doc), encoding="utf-8")
        code, text = self.build(path, "--apply")
        self.assertEqual(code, 0, text)
        self.assertIn("REMOVED rules/ui-rules.md", text.replace("\\", "/"))
        self.assertFalse((self.out / "rules" / "ui-rules.md").exists())
        self.assertTrue((self.out / "rules" / "mine.md").exists())


class Template(Case):
    def test_the_shipped_sample_manifest_builds_and_lists_all_three_layers(self):
        sample = ROOT / "plugins" / "batuta" / "templates" / "knowledge" / "manifest.json"
        code, text = self.build(sample, "--apply")
        self.assertEqual(code, 0, text)
        self.assertEqual(sorted(self.tree()), ["CORE.md", "INDEX.md", "rules/web-ui-floor.md"])


class BuildBudgets(Case):
    def core_size(self, units, bodies=None):
        self.build(self.manifest(units, bodies=bodies), "--apply")
        size = len((self.out / "CORE.md").read_bytes())
        shutil.rmtree(self.out)
        return size

    def test_core_exactly_at_the_budget_passes_and_one_byte_under_refuses(self):
        units = [unit("a")]
        size = self.core_size(units)
        self.assertEqual(self.build(self.manifest(units, core=size))[0], 0)
        code, text = self.build(self.manifest(units, core=size - 1), "--apply")
        self.assertEqual(code, 1)
        self.assertIn("REFUSED", text)
        self.assertFalse(self.out.exists())

    def test_budget_counts_bytes_not_characters(self):
        units = [unit("a")]
        bodies = {"a": "café éééééé\n"}
        self.build(self.manifest(units, bodies=bodies), "--apply")
        data = (self.out / "CORE.md").read_bytes()
        shutil.rmtree(self.out)
        chars = len(data.decode("utf-8"))
        self.assertGreater(len(data), chars)
        self.assertEqual(self.build(self.manifest(units, core=len(data), bodies=bodies))[0], 0)
        self.assertEqual(self.build(self.manifest(units, core=chars, bodies=bodies))[0], 1)

    def test_index_over_budget_is_refused(self):
        code, text = self.build(self.manifest([unit("a")], index=10))
        self.assertEqual(code, 1)
        self.assertIn("REFUSED", text)
        self.assertIn("index", text)


class ContractFixtures(Case):
    def put_files(self, doc):
        for u in doc.get("units", []):
            if isinstance(u.get("file"), str):
                f = self.dir / u["file"]
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text("Body.\n", encoding="utf-8")

    def test_valid_c12_fixtures_build(self):
        for fx in sorted(FIXTURES.glob("valid-*.json")):
            with self.subTest(fx.name):
                doc = json.loads(fx.read_text(encoding="utf-8"))
                self.put_files(doc)
                path = self.dir / fx.name
                path.write_text(json.dumps(doc), encoding="utf-8")
                code, text = self.build(path)
                self.assertEqual(code, 0, text)

    def test_invalid_c12_fixtures_are_refused_with_the_stated_reason(self):
        for fx in sorted(FIXTURES.glob("invalid-*.json")):
            with self.subTest(fx.name):
                doc = json.loads(fx.read_text(encoding="utf-8"))
                self.put_files(doc)
                path = self.dir / fx.name
                path.write_text(json.dumps(doc), encoding="utf-8")
                code, text = self.build(path)
                self.assertEqual(code, 1, text)
                if doc.get("_expect"):
                    self.assertIn(doc["_expect"], text)


if __name__ == "__main__":
    unittest.main()

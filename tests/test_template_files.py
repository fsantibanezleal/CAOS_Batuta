"""The project template (`templates/project/`): every templated file that has a contract validates after rendering with the
fixture variable set, the placeholders are the five of the template and nothing else, no file carries a machine path, and
the example feature is what the spec area itself creates."""
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_init_support import (FIXTURE_VARS, ROOT, TEMPLATE_DIR, WORKFLOW, World, commit_all, make_repo, run,  # noqa: E402
                               snapshot)

from batuta_lib import config, render, thresholds  # noqa: E402
from batuta_lib.areas import init, spec  # noqa: E402

EXPECTED = [
    ".batuta/batuta.json",
    ".claude/settings.json",
    ".github/workflows/batuta-gates.yml",
    ".gitignore",
    "AGENTS.md",
    "CLAUDE.md",
    "specs/000-foundation/constitution.md",
    "specs/000-foundation/thresholds.json",
    "specs/001-example-feature/plan.md",
    "specs/001-example-feature/spec.md",
    "specs/001-example-feature/status.md",
    "specs/001-example-feature/tasks.md",
    "tests/__init__.py",
    "tests/test_foundation.py",
]
FIVE = set(FIXTURE_VARS)   # the five questions and the hidden sixth variable, the release tag of the checks
RAW = re.compile(r"\{%\s*raw\s*%\}(.*?)\{%\s*endraw\s*%\}", re.S)


def template_files():
    return {p.relative_to(TEMPLATE_DIR).as_posix(): p for p in sorted(TEMPLATE_DIR.rglob("*")) if p.is_file()}


class TemplateTree(unittest.TestCase):
    def test_template_folder_holds_exactly_the_expected_files(self):
        self.assertEqual(sorted(template_files()), EXPECTED)

    def test_only_the_five_placeholders_and_no_template_logic(self):
        for rel, path in template_files().items():
            text = path.read_text(encoding="utf-8")
            plain = RAW.sub("", text)   # only a GitHub expression inside a raw block may hold braces
            self.assertNotIn("{%", plain, rel)
            self.assertNotIn("{#", plain, rel)
            self.assertNotIn("${{", plain, f"{rel}: a GitHub expression outside a raw block would be read as a placeholder")
            for name in re.findall(r"\{\{\s*([^{}]*?)\s*\}\}", plain):
                self.assertIn(name, FIVE, f"{rel}: placeholder {name!r} is not one of the template variables")
            self.assertEqual(plain.count("{{"), plain.count("}}"), rel)

    def test_no_machine_path_in_any_template_file(self):
        bad = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]|/Users/|/home/[a-z]|\\Users\\|@[a-z0-9-]+\.(com|org|net)\b")
        for rel, path in template_files().items():
            self.assertIsNone(bad.search(path.read_text(encoding="utf-8")), rel)

    def test_files_are_lf_utf8_without_bom_and_end_with_a_newline(self):
        for rel, path in template_files().items():
            data = path.read_bytes()
            self.assertNotIn(b"\r", data, rel)
            self.assertFalse(data.startswith(b"\xef\xbb\xbf"), rel)
            data.decode("utf-8")
            if data:
                self.assertTrue(data.endswith(b"\n"), rel)

    def test_no_em_dash_or_emoji(self):
        for rel, path in template_files().items():
            text = path.read_text(encoding="utf-8")
            self.assertNotIn(chr(0x2014), text, rel)
            self.assertFalse(re.search("[\\u2190-\\u21ff\\U0001f300-\\U0001faff\\u2600-\\u27bf]", text), rel)


class RenderedContracts(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.out = Path(self._tmp.name) / "p"
        for rel, text in init.render_project(dict(FIXTURE_VARS)).items():
            render.write_atomic(self.out / rel, text)

    def test_rendering_returns_every_template_file_with_the_variables_filled(self):
        rendered = init.render_project(dict(FIXTURE_VARS))
        self.assertEqual(sorted(rendered), EXPECTED)
        for rel, text in rendered.items():
            self.assertNotRegex(text, r"(?<!\$)\{\{", rel)   # only a GitHub expression, `${{ ... }}`, keeps braces
        self.assertIn("Demo Project", rendered["AGENTS.md"])

    def test_batuta_json_validates_as_c01_and_names_the_test_command(self):
        doc = json.loads((self.out / ".batuta/batuta.json").read_text(encoding="utf-8"))
        self.assertEqual(config.validate(doc), [])
        self.assertEqual(doc["contract_version"], "1.1")
        self.assertEqual(doc["tdd"]["test_command"], FIXTURE_VARS["test_command"])
        resolved = config.load(None, project_root=self.out)
        self.assertEqual(resolved.source, "project")

    def test_thresholds_validate_as_c11(self):
        doc, errors = thresholds.load(self.out / "specs/000-foundation/thresholds.json")
        self.assertEqual(errors, [])
        self.assertIsNotNone(doc)

    def test_constitution_is_the_specs_own_template(self):
        template = Path(spec.TEMPLATES) / "constitution.md"
        self.assertEqual((self.out / "specs/000-foundation/constitution.md").read_text(encoding="utf-8"),
                         render.render_file(template, {}))

    def test_example_feature_is_what_the_spec_area_creates(self):
        with tempfile.TemporaryDirectory() as tmp:
            items = spec.new(tmp, init.EXAMPLE_TITLE, tier=init.EXAMPLE_TIER, owner=init.EXAMPLE_OWNER, apply=True,
                             today=init.EXAMPLE_DATE)
            self.assertFalse([i for i in items if i["tag"] == "FAIL"])
            created = {k: v for k, v in snapshot(Path(tmp)).items()
                       if k.startswith("specs/001-") and not k.endswith(".gitkeep")}
        ours = {k: v for k, v in snapshot(self.out).items() if k.startswith("specs/001-")}
        self.assertEqual(sorted(set(ours) - set(created)), ["specs/001-example-feature/status.md"],
                         "the template adds only the status file (C10) that `gate check` needs; the empty approvals and evidence "
                         "folders are left out (a guard scans for `specs/*/approvals` folders) and created on first use")
        for rel, data in created.items():
            if data is None:
                continue
            if rel.endswith(("spec.md", "tasks.md")):
                # the example rows (one requirement and its task, so the files satisfy C05 and C21) are the only addition
                lines = ours[rel].decode("utf-8").split("\n")
                kept = [ln for ln in lines if not ln.startswith(("| REQ-FOUND-001", "| T-001"))]
                self.assertEqual("\n".join(kept).encode("utf-8"), data, rel)
                self.assertNotEqual(ours[rel], data, f"{rel} carries its example row")
            else:
                self.assertEqual(ours[rel], data, rel)

    def test_every_rendered_file_validates_against_its_contract(self):
        contracts = {".batuta/batuta.json": "C01", "specs/000-foundation/thresholds.json": "C11",
                     "specs/001-example-feature/spec.md": "C05", "specs/001-example-feature/tasks.md": "C21",
                     "specs/001-example-feature/status.md": "C10"}
        for rel, cid in contracts.items():
            code, out, err = run("contract", "validate", cid, str(self.out / rel))
            self.assertEqual(code, 0, f"{rel} as {cid}: {out}{err}")
        preset = init._settings_preset((self.out / ".claude/settings.json").read_text(encoding="utf-8"))
        self.assertEqual(preset["contract_version"], "1.0")

    def test_status_file_is_the_gate_areas_template_for_the_example_feature(self):
        text = (self.out / "specs/001-example-feature/status.md").read_text(encoding="utf-8")
        template = (ROOT / "plugins/batuta/templates/gates/status.md").read_text(encoding="utf-8")
        self.assertIn("feature: 001-example-feature", text)
        lines = template.replace("\r\n", "\n").split("\n")[1:]   # the first line is the copy instruction of the template
        self.assertEqual(text, "\n".join(lines).replace("feature: 000-example", "feature: 001-example-feature"))
        code, out, err = run("gate", "status", "001-example-feature", "--root", str(self.out))
        self.assertEqual(code, 0, out + err)

    def test_spec_lint_and_trace_pass_on_the_rendered_project(self):
        code, out, err = run("spec", "lint", "--root", str(self.out))
        self.assertEqual(code, 0, out + err)
        code, out, err = run("spec", "trace", "001-example-feature", "--root", str(self.out))
        self.assertIn(code, (0, 2), out + err)
        self.assertNotIn("FAIL", out)

    def test_claude_md_is_a_short_core_within_the_project_core_budget(self):
        size = len((self.out / "CLAUDE.md").read_bytes())
        self.assertLessEqual(size, config.default_config()["budgets"]["project_core_bytes"])
        self.assertLess(size, 3500, "the project core stays short; detail goes to AGENTS.md and the docs")
        with tempfile.TemporaryDirectory() as home:
            code, out, err = run("context", "check", "--project", str(self.out), "--home", home, "--chain-root",
                                 str(self.out))
            self.assertNotEqual(code, 1, out + err)
            self.assertIn("project CLAUDE.md chain", out)

    def test_settings_json_is_valid_json_with_only_permission_rules(self):
        doc = json.loads((self.out / ".claude/settings.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(doc), ["permissions"])
        deny = doc["permissions"]["deny"]
        self.assertTrue(any("approvals" in d for d in deny))
        self.assertTrue(any("test-locks" in d for d in deny))

    def test_leaks_scan_is_clean_on_the_rendered_project(self):
        make_repo(self.out)
        commit_all(self.out, "init")
        code, out, err = run("leaks", "scan", "--root", str(self.out))
        self.assertEqual(code, 0, out + err)

    def test_the_foundation_test_runs_with_the_configured_command(self):
        import subprocess
        done = subprocess.run([sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-t", ".", "-v"],
                              cwd=self.out, capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertRegex(done.stderr, r"test_\w+ \(tests\.test_foundation\.\w+\.test_\w+\) \.\.\. ok")

    def test_render_refuses_a_missing_or_unsafe_variable(self):
        with self.assertRaises(init.InitError):
            init.render_project({k: v for k, v in FIXTURE_VARS.items() if k != "default_branch"})
        with self.assertRaises(init.InitError):   # the unused project_slug question is gone
            init.render_project({**FIXTURE_VARS, "project_slug": "x"})
        for key, bad in (("python_version", "three"), ("batuta_ref", "main"), ("test_command", 'run "x"'),
                         ("test_command", "line1\nline2"), ("default_branch", "-x"), ("project_name", 'a"b'),
                         ("project_name", "{{ x }}")):
            with self.assertRaises(init.InitError, msg=f"{key}={bad!r}"):
                init.render_project({**FIXTURE_VARS, key: bad})


class CopierEquivalence(unittest.TestCase):
    """The copier channel and `init project` render the same bytes (skipped where copier is not installed)."""

    def test_copier_and_init_project_produce_the_same_files(self):
        import shutil
        import subprocess
        copier = shutil.which("copier")
        if copier is None:
            try:
                import copier as _module  # noqa: F401
                copier = [sys.executable, "-m", "copier"]
            except ImportError:
                self.skipTest("copier is not installed (pip install copier); the equivalence is checked where it is")
        else:
            copier = [copier]
        self.assertTrue((ROOT / "copier.yml").is_file())
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            src = tmp / "src"
            shutil.copytree(ROOT / "plugins" / "batuta" / "templates", src / "plugins" / "batuta" / "templates")
            shutil.copy2(ROOT / "copier.yml", src / "copier.yml")
            dest = tmp / "copier-out"
            data = [a for k, v in FIXTURE_VARS.items() for a in ("--data", f"{k}={v}")]
            done = subprocess.run([*copier, "copy", "--defaults", "--trust", *data, str(src), str(dest)],
                                  capture_output=True, text=True, timeout=300)
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
            ours = {k: v for k, v in init.render_project(dict(FIXTURE_VARS)).items()}
            theirs = {k: v for k, v in snapshot(dest).items() if v is not None}
            self.assertEqual(sorted(theirs), sorted(ours))
            for rel, text in ours.items():
                self.assertEqual(theirs[rel], text.encode("utf-8"), rel)


class CopierFile(unittest.TestCase):
    def test_copier_yml_names_the_subdirectory_and_the_five_questions(self):
        text = (ROOT / "copier.yml").read_text(encoding="utf-8")
        self.assertRegex(text, r"(?m)^_subdirectory:\s*plugins/batuta/templates/project\s*$")
        for name in FIVE:
            self.assertRegex(text, rf"(?m)^{name}:\s*$", name)
        for key, value in init.DEFAULTS.items():
            if key == "project_name":
                continue   # derived from the target folder by `init project`; copier asks
            self.assertIn(str(value), text, f"default of {key} differs between copier.yml and init project")
        self.assertEqual(len(re.findall(r"(?m)^[a-z_]+:\s*$", text)), 5, "four questions and the hidden release tag")
        self.assertNotIn("project_slug", text)
        self.assertRegex(text, r"(?ms)^batuta_ref:.*?when:\s*false")
        tag = "v" + (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        self.assertEqual(init.DEFAULTS["batuta_ref"], tag, "init project pins the checks to the installed version")
        self.assertIn(tag, text, "copier.yml carries the same tag as its default")


class WorkflowFile(World):
    def test_workflow_is_in_the_template_and_has_the_required_job(self):
        text = (TEMPLATE_DIR / WORKFLOW).read_text(encoding="utf-8")
        self.assertRegex(text, r"(?m)^name: batuta-gates\s*$")
        self.assertRegex(text, r"(?m)^  batuta-gates:\s*$")
        self.assertRegex(text, r"(?m)^    name: batuta-gates\s*$")
        self.assertRegex(text, r"(?m)^  push:")
        self.assertRegex(text, r"(?m)^  pull_request:")
        rendered = init.render_project(dict(FIXTURE_VARS))[WORKFLOW]
        self.assertRegex(rendered, r"(?m)^concurrency:\s*\n\s+group: \$\{\{ github\.workflow \}\}-\$\{\{ github\.ref \}\}\s*$")
        self.assertIn("${{ github.event.pull_request.base.sha }}", rendered)
        self.assertIn("${{ github.event.before }}", rendered)
        self.assertRegex(rendered, r"(?m)^      BATUTA_REF: v0\.01\.000\s*$")
        self.assertNotIn("BATUTA_REF: main", rendered)
        self.assertNotIn("{%", rendered)
        self.assertRegex(text, r"(?m)^    timeout-minutes: \d+")
        self.assertRegex(text, r"fetch-depth: 0")
        self.assertIn('python-version: "{{ python_version }}"', text)
        self.assertNotIn("continue-on-error: true", text.split("steps:")[0], "the job itself must not be skippable")

    def test_every_batuta_verb_in_the_workflow_exists_in_the_dispatcher(self):
        import argparse
        sys.path.insert(0, str(ROOT / "plugins" / "batuta" / "scripts"))
        import importlib
        batuta = importlib.import_module("batuta")
        areas, _ = batuta.load_areas()
        parser = batuta.build_parser(areas, "test")
        known = {}
        for action in parser._subparsers._group_actions[0].choices.items():
            area, sub = action
            verbs = set()
            for a in sub._actions:
                if isinstance(a, argparse._SubParsersAction):
                    verbs |= set(a.choices)
            known[area] = verbs
        text = (TEMPLATE_DIR / WORKFLOW).read_text(encoding="utf-8")
        found = re.findall(r'batuta\.py"?\s+([a-z]+)\s+([a-z][a-z-]*)', text)
        self.assertTrue(found)
        for area, verb in found:
            self.assertIn(area, known, f"area {area} is not in the dispatcher")
            self.assertIn(verb, known[area], f"{area} {verb} is not a verb of the dispatcher")
        wanted = {("tdd", "check"), ("spec", "trace"), ("gate", "check"), ("gate", "thresholds"), ("guard", "scan"),
                  ("context", "check"), ("leaks", "scan")}
        self.assertTrue(wanted <= set(found), f"missing: {sorted(wanted - set(found))}")

    def test_gate_options_match_the_requirement(self):
        text = (TEMPLATE_DIR / WORKFLOW).read_text(encoding="utf-8")
        self.assertIn('tdd check --replay --range "$BATUTA_BASE..HEAD"', text)
        self.assertIn('gate check "$id" --against "$BATUTA_BASE"', text)
        self.assertIn('guard scan --diff "$BATUTA_BASE..HEAD"', text)
        self.assertIn("gate thresholds", text)
        self.assertIn("context check", text)
        self.assertIn("leaks scan", text)

    def test_test_step_runs_exactly_the_configured_test_command(self):
        rendered = init.render_project(dict(FIXTURE_VARS))[WORKFLOW]
        from test_init_support import run_block, step_block
        body = run_block(step_block(rendered, "tests")).strip()
        self.assertEqual(body, FIXTURE_VARS["test_command"])
        doc = json.loads(init.render_project(dict(FIXTURE_VARS))[".batuta/batuta.json"])
        self.assertEqual(body, doc["tdd"]["test_command"])


if __name__ == "__main__":
    unittest.main()

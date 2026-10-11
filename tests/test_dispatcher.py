"""The dispatcher discovers area modules, skips and reports broken ones, and serves `version show`."""
import contextlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from _support import ROOT, SCRIPTS, display_to_semver, load_harness

HARNESS = SCRIPTS / "harness.py"
GOOD_AREA = textwrap.dedent('''
    AREA = "fake"
    HELP = "a fake area for tests"

    def _ping(args):
        print("pong json=%s config=%s" % (args.json, args.config))
        return 0

    def register(subparsers):
        p = subparsers.add_parser("ping", help="say pong")
        p.set_defaults(func=_ping)
''')
BROKEN_AREA = 'raise RuntimeError("boom")\n'
HELPER_MODULE = "VALUE = 1\n"  # no AREA: a helper, skipped silently


def run_main(harness, argv, areas_dir=None):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = harness.main(argv, areas_dir=areas_dir)
        except SystemExit as exc:  # argparse exits for --version and errors
            code = exc.code
    return code, out.getvalue(), err.getvalue()


class DiscoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.harness = load_harness()

    def make_areas(self, **modules):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for name, source in modules.items():
            (Path(tmp.name) / f"{name}.py").write_text(source, encoding="utf-8")
        return Path(tmp.name)

    def test_discovers_a_fake_area(self):
        areas, warnings = self.harness.load_areas(self.make_areas(fake=GOOD_AREA))
        self.assertEqual([a.AREA for a in areas], ["fake"])
        self.assertEqual(warnings, [])

    def test_broken_area_is_reported_as_warn_and_skipped(self):
        areas, warnings = self.harness.load_areas(self.make_areas(fake=GOOD_AREA, broken=BROKEN_AREA))
        self.assertEqual([a.AREA for a in areas], ["fake"])
        self.assertEqual(warnings, ["WARN area broken failed to load: boom"])

    def test_helper_module_without_area_is_skipped_silently(self):
        areas, warnings = self.harness.load_areas(self.make_areas(helper=HELPER_MODULE))
        self.assertEqual((areas, warnings), ([], []))

    def test_modules_are_loaded_sorted(self):
        second = GOOD_AREA.replace('"fake"', '"zeta"')
        first = GOOD_AREA.replace('"fake"', '"alpha"')
        areas, _ = self.harness.load_areas(self.make_areas(b_zeta=second, a_alpha=first))
        self.assertEqual([a.AREA for a in areas], ["alpha", "zeta"])

    def test_module_missing_register_is_a_warning(self):
        areas, warnings = self.harness.load_areas(self.make_areas(half='AREA = "half"\nHELP = "x"\n'))
        self.assertEqual(areas, [])
        self.assertEqual(len(warnings), 1)
        self.assertTrue(warnings[0].startswith("WARN area half failed to load:"))

    def test_main_runs_fake_area_verb_and_keeps_working_with_a_broken_one(self):
        areas_dir = self.make_areas(fake=GOOD_AREA, broken=BROKEN_AREA)
        code, out, err = run_main(self.harness, ["fake", "ping"], areas_dir)
        self.assertEqual(code, 0)
        self.assertIn("pong json=False config=None", out)
        self.assertIn("WARN area broken failed to load: boom", err)

    def test_global_options_are_accepted_after_the_verb(self):
        areas_dir = self.make_areas(fake=GOOD_AREA)
        code, out, _ = run_main(self.harness, ["fake", "ping", "--json", "--config", "x.json"], areas_dir)
        self.assertEqual(code, 0)
        self.assertIn("pong json=True config=x.json", out)

    def test_unknown_area_exits_nonzero(self):
        code, _, _ = run_main(self.harness, ["nope", "x"], self.make_areas(fake=GOOD_AREA))
        self.assertNotEqual(code, 0)

    def test_no_arguments_prints_help_listing_areas(self):
        code, out, _ = run_main(self.harness, [], self.make_areas(fake=GOOD_AREA))
        self.assertEqual(code, 0)
        self.assertIn("fake", out)
        self.assertIn("a fake area for tests", out)


class VersionAreaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.harness = load_harness()
        cls.display = (ROOT / "VERSION").read_text(encoding="utf-8").strip()

    def test_version_show_prints_version_file(self):
        code, out, _ = run_main(self.harness, ["version", "show"])
        self.assertEqual((code, out.strip()), (0, self.display))

    def test_version_show_json(self):
        code, out, _ = run_main(self.harness, ["version", "show", "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), {"version": self.display})

    def test_global_version_flag(self):
        code, out, _ = run_main(self.harness, ["--version"])
        self.assertEqual(code, 0)
        self.assertIn(self.display, out)

    def test_fallback_to_plugin_manifest_when_version_file_is_absent(self):
        from harness_lib.areas import version  # sys.path is set by load_harness
        with tempfile.TemporaryDirectory() as tmp:
            plugin = Path(tmp) / ".claude-plugin"
            plugin.mkdir()
            (plugin / "plugin.json").write_text(json.dumps({"version": "1.2.3"}), encoding="utf-8")
            self.assertEqual(
                version.read_version(search_from=Path(tmp) / "scripts", plugin_root=Path(tmp)),
                "1.02.003",
            )

    def test_semver_roundtrip_helper(self):
        self.assertEqual(display_to_semver("0.01.000"), "0.1.0")


class SubprocessTests(unittest.TestCase):
    def test_script_runs_as_a_process(self):
        result = subprocess.run([sys.executable, str(HARNESS), "version", "show"],
                                capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), (ROOT / "VERSION").read_text(encoding="utf-8").strip())

    def test_node_entry_prints_the_same_version(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node is not installed")
        result = subprocess.run([node, str(ROOT / "bin" / "harness.mjs"), "version", "show"],
                                capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), (ROOT / "VERSION").read_text(encoding="utf-8").strip())

    def test_node_entry_propagates_exit_code(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node is not installed")
        result = subprocess.run([node, str(ROOT / "bin" / "harness.mjs"), "no-such-area"],
                                capture_output=True, text=True, encoding="utf-8")
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()

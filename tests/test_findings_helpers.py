"""F14: the shared helpers every area uses: configuration resolution (C01) and tag-line / C20 output."""
import contextlib
import io
import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins" / "batuta" / "scripts"))

from batuta_lib import config, contract, output  # noqa: E402

CONTRACTS = ROOT / "plugins" / "batuta" / "contracts"
VALID = json.loads((CONTRACTS / "fixtures" / "C01" / "valid-full.json").read_text(encoding="utf-8"))


def write_config(d, doc=None, name="batuta.json"):
    p = pathlib.Path(d) / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc if doc is not None else VALID), encoding="utf-8")
    return p


class ConfigResolutionOrder(unittest.TestCase):
    """--config, BATUTA_CONFIG, project .batuta/batuta.json, user <BATUTA_HOME>/batuta.json, then defaults."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        t = pathlib.Path(self.tmp.name)
        self.arg = write_config(t / "arg", dict(VALID, version=11))
        self.env_file = write_config(t / "env", dict(VALID, version=12))
        self.project = t / "project"
        write_config(self.project / ".batuta", dict(VALID, version=13))
        self.home = t / "home"
        write_config(self.home, dict(VALID, version=14))
        self.env = {"BATUTA_CONFIG": str(self.env_file), "BATUTA_HOME": str(self.home)}

    def version(self, **kw):
        return config.load(**kw).config["version"]

    def test_the_explicit_argument_wins(self):
        self.assertEqual(self.version(config_arg=str(self.arg), project_root=self.project, env=self.env), 11)

    def test_then_the_environment_variable(self):
        self.assertEqual(self.version(project_root=self.project, env=self.env), 12)

    def test_then_the_project_file(self):
        env = {"BATUTA_HOME": str(self.home)}
        self.assertEqual(self.version(project_root=self.project, env=env), 13)

    def test_then_the_user_file_under_batuta_home(self):
        env = {"BATUTA_HOME": str(self.home)}
        self.assertEqual(self.version(project_root=self.project / "nowhere", env=env), 14)

    def test_then_the_defaults_with_no_file_at_all(self):
        with tempfile.TemporaryDirectory() as empty:
            r = config.load(project_root=empty, env={"BATUTA_HOME": str(pathlib.Path(empty) / "h")})
        self.assertEqual(r.source, "defaults")
        self.assertIsNone(r.path)
        self.assertEqual(contract.validate(r.config, contract.load_schema(CONTRACTS / "C01-batuta-config.schema.json")), [])

    def test_the_source_names_where_the_file_came_from(self):
        env = {"BATUTA_HOME": str(self.home)}
        self.assertEqual(config.load(project_root=self.project, env=env).source, "project")
        self.assertEqual(config.load(project_root=self.project, env=self.env).source, "BATUTA_CONFIG")
        self.assertEqual(config.load(config_arg=str(self.arg), env=self.env).source, "--config")

    def test_a_named_file_that_does_not_exist_is_an_error_not_a_fallback(self):
        with self.assertRaises(config.ConfigError):
            config.load(config_arg=str(pathlib.Path(self.tmp.name) / "missing.json"), env=self.env)
        with self.assertRaises(config.ConfigError):
            config.load(env={"BATUTA_CONFIG": str(pathlib.Path(self.tmp.name) / "missing.json")})

    def test_home_defaults_to_dot_batuta_in_the_user_home(self):
        self.assertEqual(config.home_dir({}).name, ".batuta")
        self.assertEqual(config.home_dir({"BATUTA_HOME": "/x/y"}), pathlib.Path("/x/y"))


class ConfigValidationAndExpansion(unittest.TestCase):
    def test_an_invalid_file_is_refused_with_every_problem(self):
        with tempfile.TemporaryDirectory() as d:
            bad = json.loads(json.dumps(VALID))
            del bad["roots"]
            bad["caps"]["spawn_depth"] = -1
            p = write_config(d, bad)
            with self.assertRaises(config.ConfigError) as cm:
                config.load(config_arg=str(p), env={})
        self.assertIn("roots", str(cm.exception))
        self.assertIn("spawn_depth", str(cm.exception))

    def test_a_file_that_is_not_json_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "batuta.json"
            p.write_text("{not json", encoding="utf-8")
            with self.assertRaises(config.ConfigError):
                config.load(config_arg=str(p), env={})

    def test_variables_expand_from_the_environment(self):
        with tempfile.TemporaryDirectory() as d:
            doc = json.loads(json.dumps(VALID))
            doc["roots"] = {"temp": "$BATUTA_TEMP", "data": "${BATUTA_DATA}/x", "worktrees": "$BATUTA_WORKTREES"}
            p = write_config(d, doc)
            env = {"BATUTA_TEMP": "/t", "BATUTA_DATA": "/d", "BATUTA_WORKTREES": "/w", "BATUTA_HOME": "/h"}
            roots = config.load(config_arg=str(p), env=env).config["roots"]
        self.assertEqual(roots, {"temp": "/t", "data": "/d/x", "worktrees": "/w"})

    def test_an_unset_root_variable_falls_back_under_batuta_home(self):
        with tempfile.TemporaryDirectory() as d:
            p = write_config(d)
            roots = config.load(config_arg=str(p), env={"BATUTA_HOME": "/h"}).config["roots"]
        self.assertEqual(roots["temp"], str(pathlib.Path("/h") / "temp"))
        self.assertEqual(roots["data"], str(pathlib.Path("/h") / "data"))
        self.assertEqual(roots["worktrees"], str(pathlib.Path("/h") / "worktrees"))

    def test_an_unset_variable_elsewhere_is_kept_and_reported(self):
        with tempfile.TemporaryDirectory() as d:
            doc = json.loads(json.dumps(VALID))
            doc["dispatch"] = {"default_lane": "sdk", "lanes": ["sdk"], "sdk": {"key_file": "$NOPE/key"}}
            r = config.load(config_arg=str(write_config(d, doc)), env={"BATUTA_HOME": "/h"})
        self.assertEqual(r.config["dispatch"]["sdk"]["key_file"], "$NOPE/key")
        self.assertIn("NOPE", r.unresolved)

    def test_expand_handles_both_forms(self):
        self.assertEqual(config.expand("$A-${B}", {"A": "1", "B": "2"}), ("1-2", []))
        self.assertEqual(config.expand("$A-$B", {"A": "1"}), ("1-$B", ["B"]))

    def test_the_default_config_validates_as_c01(self):
        doc = config.default_config({"BATUTA_HOME": "/h"})
        self.assertEqual(contract.validate(doc, contract.load_schema(CONTRACTS / "C01-batuta-config.schema.json")), [])

    def test_the_default_critical_gates_are_the_lifecycle_names(self):
        doc = config.default_config({})
        self.assertEqual(doc["gates"]["critical"], ["L2-decide", "L5-freeze", "L9-promote"])


class OutputHelpers(unittest.TestCase):
    def test_item_refuses_an_unknown_tag(self):
        with self.assertRaises(ValueError):
            output.item("GOOD", "x")
        self.assertEqual(output.item("OK", "x"), {"tag": "OK", "message": "x"})
        self.assertEqual(output.item("OK", "x", "a/b"), {"tag": "OK", "message": "x", "path": "a/b"})

    def test_the_tags_are_the_c20_enum(self):
        schema = contract.load_schema(CONTRACTS / "C20-cli-output.schema.json")
        enum = schema["properties"]["items"]["items"]["properties"]["tag"]["enum"]
        self.assertEqual(list(output.TAGS), enum)

    def test_exit_codes(self):
        self.assertEqual(output.exit_code([]), 0)
        self.assertEqual(output.exit_code([output.item("OK", "a")]), 0)
        self.assertEqual(output.exit_code([output.item("OK", "a"), output.item("WARN", "b")]), 2)
        self.assertEqual(output.exit_code([output.item("WARN", "b"), output.item("FAIL", "c")]), 1)
        self.assertEqual(output.exit_code([output.item("REFUSED", "c")]), 1)

    def test_a_tag_line(self):
        self.assertEqual(output.render_line(output.item("OK", "done", "a/b")), "OK done (a/b)")
        self.assertEqual(output.render_line(output.item("WARN", "careful")), "WARN careful")

    def test_emit_prints_tag_lines_then_the_summary_and_returns_the_exit_code(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = output.emit("contract", "lint", [output.item("OK", "a"), output.item("WARN", "b")], "lint: 1 ok", False)
        self.assertEqual(code, 2)
        self.assertEqual(buf.getvalue().splitlines(), ["OK a", "WARN b", "lint: 1 ok"])

    def test_emit_json_is_a_valid_c20_object(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = output.emit("size", "lint", [output.item("FAIL", "bad", "p")], "1 failure", True)
        obj = json.loads(buf.getvalue())
        self.assertEqual(code, 1)
        self.assertEqual((obj["tool"], obj["area"], obj["verb"], obj["exit_code"]), ("batuta", "size", "lint", 1))
        self.assertEqual(contract.validate(obj, contract.load_schema(CONTRACTS / "C20-cli-output.schema.json")), [])


if __name__ == "__main__":
    unittest.main()

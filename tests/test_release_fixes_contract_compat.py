"""Release review fix F-02 (CONTRACT-5): `contract lint --against <ref>` fails a changed contract schema whose version does
not follow the version rule (a breaking change needs a higher major, an additive change a higher minor)."""
from __future__ import annotations

import copy
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_brief_support import CONTRACTS, ROOT, run  # noqa: E402

BASE = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "contract_id": "C99",
    "contract_version": "1.0",
    "title": "Demo",
    "type": "object",
    "required": ["a"],
    "additionalProperties": True,
    "properties": {
        "a": {"type": "string", "enum": ["x", "y"], "pattern": "^[a-z]+$", "minLength": 1, "maxLength": 9},
        "b": {"type": ["string", "null"], "description": "text"},
        "n": {"type": "integer", "minimum": 1, "maximum": 10},
        "l": {"type": "array", "items": {"type": "string", "enum": ["p"]}, "minItems": 1, "maxItems": 5},
        "r": {"$ref": "#/$defs/d"},
        "k": {"const": "one"},
    },
    "$defs": {"d": {"type": "object", "properties": {"z": {"type": "string"}}}},
}
GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false"]
DELETE = object()


def git(cwd, *args):
    p = subprocess.run([*GIT, *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert p.returncode == 0, (args, p.stdout, p.stderr)
    return p.stdout.strip()


def mutate(path, value):
    """A deep copy of BASE with the nested key path (a tuple) set to `value`; DELETE removes it."""
    doc = copy.deepcopy(BASE)
    node = doc
    for key in path[:-1]:
        node = node[key]
    if value is DELETE:
        del node[path[-1]]
    else:
        node[path[-1]] = value
    return doc


class Repo:
    def __init__(self, case):
        self.dir = Path(tempfile.mkdtemp(prefix="compat-"))
        case.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        git(self.dir, "init", "-q")
        self.cdir = self.dir / "contracts"
        self.cdir.mkdir()
        self.write(BASE)
        git(self.dir, "add", "-A")
        git(self.dir, "commit", "-q", "-m", "base")

    def write(self, doc, name="C99-demo.schema.json", text=None):
        (self.cdir / name).write_text(text if text is not None else json.dumps(doc, indent=2) + "\n", encoding="utf-8")

    def lint(self, doc, version, ref="HEAD"):
        from batuta_lib import contract_compat
        doc = copy.deepcopy(doc)
        doc["contract_version"] = version
        self.write(doc)
        return contract_compat.check_against(self.cdir, ref)


def fails(items):
    return [i for i in items if i["tag"] == "FAIL"]


class Classify(unittest.TestCase):
    def kinds(self, new):
        from batuta_lib import contract_compat
        return contract_compat.classify(BASE, new)

    def test_every_breaking_kind_is_found_with_its_path(self):
        cases = {
            "a property removed": mutate(("properties", "b"), DELETE),
            "a property added to required": mutate(("required",), ["a", "n"]),
            "an enum value removed": mutate(("properties", "a", "enum"), ["x"]),
            "an enum added where absent": mutate(("properties", "n", "enum"), [1, 2]),
            "a const changed": mutate(("properties", "k", "const"), "two"),
            "a type removed from a list": mutate(("properties", "b", "type"), ["string"]),
            "a type changed": mutate(("properties", "n", "type"), "string"),
            "a pattern changed": mutate(("properties", "a", "pattern"), "^[a-z0-9]+$"),
            "a pattern added": mutate(("properties", "b", "pattern"), "^x"),
            "a minLength raised": mutate(("properties", "a", "minLength"), 2),
            "a maxLength lowered": mutate(("properties", "a", "maxLength"), 5),
            "a minimum raised": mutate(("properties", "n", "minimum"), 2),
            "a maximum lowered": mutate(("properties", "n", "maximum"), 9),
            "a minLength added where absent": mutate(("properties", "b", "minLength"), 1),
            "a minItems raised": mutate(("properties", "l", "minItems"), 2),
            "a maxItems lowered": mutate(("properties", "l", "maxItems"), 4),
            "additionalProperties closed": mutate(("additionalProperties",), False),
            "additionalProperties made a schema": mutate(("additionalProperties",), {"type": "string"}),
            "a ref retargeted": mutate(("properties", "r", "$ref"), "#/$defs/e"),
            "a nested enum value removed": mutate(("properties", "l", "items", "enum"), []),
            "a def removed": mutate(("$defs", "d"), DELETE),
            "a nested def property removed": mutate(("$defs", "d", "properties", "z"), DELETE),
        }
        for label, doc in cases.items():
            with self.subTest(label):
                found = self.kinds(doc)
                self.assertTrue(found.breaking, (label, found))

    def test_a_breaking_change_names_the_json_path(self):
        found = self.kinds(mutate(("properties", "a", "enum"), ["x"]))
        self.assertTrue(any(p.startswith("/properties/a/enum") for p in found.breaking), found.breaking)

    def test_every_additive_kind_is_not_breaking(self):
        cases = {
            "a new optional property": mutate(("properties", "c"), {"type": "string"}),
            "an enum value added": mutate(("properties", "a", "enum"), ["x", "y", "z"]),
            "a description edited": mutate(("properties", "b", "description"), "other text"),
            "a type added to a list": mutate(("properties", "b", "type"), ["string", "null", "integer"]),
            "a pattern removed": mutate(("properties", "a", "pattern"), DELETE),
            "a minLength lowered": mutate(("properties", "a", "minLength"), 0),
            "a maxLength raised": mutate(("properties", "a", "maxLength"), 20),
            "a minimum removed": mutate(("properties", "n", "minimum"), DELETE),
            "a maximum raised": mutate(("properties", "n", "maximum"), 20),
            "a minItems removed": mutate(("properties", "l", "minItems"), DELETE),
            "a maxItems raised": mutate(("properties", "l", "maxItems"), 50),
            "a property dropped from required": mutate(("required",), []),
            "additionalProperties opened": mutate(("additionalProperties",), DELETE),
            "a def added": mutate(("$defs", "e"), {"type": "string"}),
            "a const removed": mutate(("properties", "k", "const"), DELETE),
        }
        for label, doc in cases.items():
            with self.subTest(label):
                found = self.kinds(doc)
                self.assertEqual(found.breaking, [], (label, found))
                self.assertTrue(found.additive, label)

    def test_a_reformatted_schema_has_no_change(self):
        from batuta_lib import contract_compat
        reordered = dict(reversed(list(BASE.items())))
        found = contract_compat.classify(BASE, reordered)
        self.assertEqual((found.breaking, found.additive), ([], []))
        self.assertFalse(contract_compat.changed(BASE, reordered))

    def test_a_version_change_alone_is_no_content_change(self):
        from batuta_lib import contract_compat
        self.assertFalse(contract_compat.changed(BASE, dict(BASE, contract_version="1.1")))


class AgainstARef(unittest.TestCase):
    def test_a_breaking_change_with_an_unchanged_version_fails(self):
        repo = Repo(self)
        items = repo.lint(mutate(("properties", "b"), DELETE), "1.0")
        bad = fails(items)
        self.assertEqual(len(bad), 1, items)
        self.assertIn("C99", bad[0]["message"])
        self.assertIn("/properties/b", bad[0]["message"])
        self.assertIn("2.0", bad[0]["message"])

    def test_a_breaking_change_with_only_a_minor_bump_fails(self):
        repo = Repo(self)
        self.assertEqual(len(fails(repo.lint(mutate(("required",), ["a", "n"]), "1.1"))), 1)

    def test_a_breaking_change_with_a_major_bump_passes(self):
        repo = Repo(self)
        self.assertEqual(fails(repo.lint(mutate(("properties", "b"), DELETE), "2.0")), [])

    def test_an_additive_change_with_a_minor_bump_passes(self):
        repo = Repo(self)
        self.assertEqual(fails(repo.lint(mutate(("properties", "c"), {"type": "string"}), "1.1")), [])

    def test_an_additive_change_with_a_major_bump_passes(self):
        repo = Repo(self)
        self.assertEqual(fails(repo.lint(mutate(("properties", "c"), {"type": "string"}), "2.0")), [])

    def test_an_additive_change_without_a_bump_fails_and_names_the_version_it_needs(self):
        repo = Repo(self)
        bad = fails(repo.lint(mutate(("properties", "c"), {"type": "string"}), "1.0"))
        self.assertEqual(len(bad), 1)
        self.assertIn("/properties/c", bad[0]["message"])
        self.assertIn("1.1", bad[0]["message"])

    def test_a_lower_version_for_a_changed_file_fails(self):
        repo = Repo(self)
        self.assertEqual(len(fails(repo.lint(mutate(("properties", "c"), {"type": "string"}), "0.9"))), 1)

    def test_a_reformatted_file_is_the_same(self):
        from batuta_lib import contract_compat
        repo = Repo(self)
        repo.write(None, text=json.dumps(BASE, indent=4, sort_keys=True) + "\n\n")
        items = contract_compat.check_against(repo.cdir, "HEAD")
        self.assertEqual(fails(items), [])
        self.assertTrue(any("C99" in i["message"] and "unchanged" in i["message"] for i in items), items)

    def test_a_byte_equal_file_is_the_same(self):
        from batuta_lib import contract_compat
        repo = Repo(self)
        items = contract_compat.check_against(repo.cdir, "HEAD")
        self.assertEqual([i["tag"] for i in items], ["OK"], items)

    def test_a_new_contract_file_passes(self):
        from batuta_lib import contract_compat
        repo = Repo(self)
        repo.write(dict(BASE, contract_id="C98"), name="C98-other.schema.json")
        items = contract_compat.check_against(repo.cdir, "HEAD")
        self.assertEqual(fails(items), [])
        self.assertTrue(any("C98" in i["message"] and "new" in i["message"] for i in items), items)

    def test_a_deleted_contract_file_fails(self):
        from batuta_lib import contract_compat
        repo = Repo(self)
        (repo.cdir / "C99-demo.schema.json").unlink()
        bad = fails(contract_compat.check_against(repo.cdir, "HEAD"))
        self.assertEqual(len(bad), 1)
        self.assertIn("C99", bad[0]["message"])
        self.assertIn("deleted", bad[0]["message"])

    def test_a_schema_without_a_version_fails_naming_the_file(self):
        from batuta_lib import contract_compat
        repo = Repo(self)
        doc = mutate(("properties", "c"), {"type": "string"})
        del doc["contract_version"]
        repo.write(doc)
        bad = fails(contract_compat.check_against(repo.cdir, "HEAD"))
        self.assertEqual(len(bad), 1)
        self.assertIn("C99-demo.schema.json", bad[0]["message"] + str(bad[0].get("path", "")))

    def test_an_unknown_ref_is_a_failure_with_the_reason(self):
        from batuta_lib import contract_compat
        repo = Repo(self)
        bad = fails(contract_compat.check_against(repo.cdir, "no-such-ref"))
        self.assertEqual(len(bad), 1)
        self.assertIn("no-such-ref", bad[0]["message"])

    def test_outside_a_git_repository_is_a_failure_naming_the_cause(self):
        from batuta_lib import contract_compat
        d = Path(tempfile.mkdtemp(prefix="compat-nogit-"))
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        (d / "contracts").mkdir()
        bad = fails(contract_compat.check_against(d / "contracts", "HEAD"))
        self.assertEqual(len(bad), 1)
        self.assertIn("git", bad[0]["message"])

    def test_a_contracts_folder_absent_at_the_ref_makes_every_contract_new(self):
        from batuta_lib import contract_compat
        repo = Repo(self)
        git(repo.dir, "rm", "-rq", "contracts")
        git(repo.dir, "commit", "-qm", "drop")
        repo.cdir.mkdir(exist_ok=True)
        repo.write(BASE)
        items = contract_compat.check_against(repo.cdir, "HEAD")
        self.assertEqual(fails(items), [])
        self.assertTrue(any("new" in i["message"] for i in items), items)


class Cli(unittest.TestCase):
    def scratch(self):
        repo = Repo(self)
        shutil.rmtree(repo.cdir)
        shutil.copytree(CONTRACTS, repo.cdir)
        git(repo.dir, "add", "-A")
        git(repo.dir, "commit", "-qm", "real contracts")
        return repo

    def test_the_repository_own_contracts_pass_against_head(self):
        code, out, err = run("contract", "lint", "--against", "HEAD")
        self.assertEqual(code, 0, (out, err))

    def test_the_repository_own_contracts_pass_against_the_release_candidate(self):
        probe = subprocess.run(["git", "-C", str(ROOT), "cat-file", "-e", "ad3fea8^{commit}"], capture_output=True)
        if probe.returncode != 0:
            self.skipTest("commit ad3fea8 is not in this clone")
        code, out, err = run("contract", "lint", "--against", "ad3fea8")
        self.assertEqual(code, 0, (out, err))

    def test_without_against_lint_is_unchanged(self):
        code, out, _ = run("contract", "lint")
        self.assertEqual(code, 0, out)
        self.assertNotIn("unchanged since", out)

    def test_a_required_property_removed_without_a_version_change_exits_one_naming_it(self):
        repo = self.scratch()
        path = repo.cdir / "C02-brief.schema.json"
        doc = json.loads(path.read_text(encoding="utf-8"))
        victim = next(iter(doc["properties"]))
        doc["properties"].pop(victim)
        path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
        code, out, _ = run("contract", "lint", "--root", repo.dir, "--against", "HEAD")
        self.assertEqual(code, 1, out)
        self.assertRegex(out, r"FAIL.*C02")
        self.assertIn(f"/properties/{victim}", out)

    def test_an_unknown_ref_exits_one_with_the_reason(self):
        repo = self.scratch()
        code, out, _ = run("contract", "lint", "--root", repo.dir, "--against", "no-such-ref")
        self.assertEqual(code, 1, out)
        self.assertIn("no-such-ref", out)


if __name__ == "__main__":
    unittest.main()

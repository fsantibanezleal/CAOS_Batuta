"""context check and context measure: budgets of the always-loaded context, memory index caps, missing data."""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "plugins" / "batuta" / "scripts"))
from _support import load_batuta  # noqa: E402
from batuta_lib.areas import context  # noqa: E402

# Default C01 budgets (batuta_lib.config.default_config): user 7000, project 7000, unscoped rules 2000,
# memory index 4000 bytes and 60 lines.


def run(*argv):
    batuta = load_batuta()
    out, err = io.StringIO(), io.StringIO()
    with mock.patch.dict(os.environ, {"BATUTA_HOME": str(ROOT / "no-such-home"), "BATUTA_CONFIG": ""}), \
            contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = batuta.main(list(argv))
    return code, out.getvalue()


def sized(n_bytes, heading="## Section"):
    """A markdown body of exactly n_bytes ASCII bytes: a heading line, then filler lines of 100 bytes."""
    text = heading + "\n"
    while len(text) < n_bytes:
        room = n_bytes - len(text)
        text += ("x" * min(99, room - 1) + "\n") if room > 1 else "x"
    return text[:n_bytes]


class Case(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.home = self.root / "home"
        self.proj = self.root / "work" / "proj"
        self.proj.mkdir(parents=True)
        (self.home / ".claude").mkdir(parents=True)

    def core(self, text):
        (self.home / ".claude" / "CLAUDE.md").write_bytes(text.encode("utf-8"))

    def rule(self, name, text):
        p = self.home / ".claude" / "rules" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(text.encode("utf-8"))

    def memory(self, text, project=None, raw=None):
        key = context.project_key(project or self.proj)
        d = self.home / ".claude" / "projects" / key / "memory"
        d.mkdir(parents=True, exist_ok=True)
        (d / "MEMORY.md").write_bytes(raw if raw is not None else text.encode("utf-8"))
        return d

    def check(self, *extra):
        return run("context", "check", "--project", str(self.proj), "--home", str(self.home),
                   "--chain-root", str(self.root), *extra)

    def measure(self, *extra):
        return run("context", "measure", "--project", str(self.proj), "--home", str(self.home),
                   "--chain-root", str(self.root), *extra)


class UserCore(Case):
    def test_at_the_limit_passes_and_one_byte_over_fails(self):
        self.core(sized(7000))
        code, text = self.check()
        self.assertEqual(code, 0, text)
        self.core(sized(7001))
        code, text = self.check()
        self.assertEqual(code, 1, text)
        self.assertIn("FAIL", text)
        self.assertIn("7001", text)

    def test_non_ascii_counts_bytes_not_characters(self):
        self.core("\u00e9" * 3500)
        self.assertEqual(self.check()[0], 0)
        self.core("\u00e9" * 3501)
        self.assertEqual(len("\u00e9" * 3501), 3501)
        self.assertEqual(self.check()[0], 1)

    def test_over_budget_names_the_largest_sections_and_the_layer(self):
        self.core("# Core\n\n## Small\nhi\n\n## Big section\n" + "y" * 7000 + "\n")
        code, text = self.check()
        self.assertEqual(code, 1)
        self.assertIn("Big section", text)
        self.assertRegex(text, r"L[12]")

    def test_missing_core_is_reported_not_a_crash(self):
        code, text = self.check()
        self.assertEqual(code, 0, text)
        self.assertIn("MISSING", text)

    def test_explicit_user_core_path(self):
        other = self.root / "rendered.md"
        other.write_bytes(sized(7001).encode())
        code, text = self.check("--user-core", str(other))
        self.assertEqual(code, 1, text)


class Rules(Case):
    def test_unscoped_rules_over_budget_fail_scoped_rules_are_free(self):
        self.rule("a.md", sized(1000))
        self.rule("b.md", sized(1000))
        self.assertEqual(self.check()[0], 0)
        self.rule("c.md", sized(1))
        code, text = self.check()
        self.assertEqual(code, 1, text)
        self.assertIn("rules", text)
        self.rule("scoped.md", '---\npaths:\n  - "web/**"\n---\n' + sized(5000))
        self.assertEqual(self.check()[0], 1)  # still over because of c.md only
        (self.home / ".claude" / "rules" / "c.md").unlink()
        self.assertEqual(self.check()[0], 0)


class ProjectChain(Case):
    def test_chain_is_summed_from_the_project_up_to_the_chain_root(self):
        (self.root / "work" / "CLAUDE.md").write_bytes(sized(4000).encode())
        (self.proj / "CLAUDE.md").write_bytes(sized(3000).encode())
        self.assertEqual(self.check()[0], 0)
        (self.proj / "CLAUDE.md").write_bytes(sized(3001).encode())
        code, text = self.check()
        self.assertEqual(code, 1, text)
        self.assertIn("project", text)

    def test_dot_claude_claude_md_counts(self):
        (self.proj / ".claude").mkdir()
        (self.proj / ".claude" / "CLAUDE.md").write_bytes(sized(7001).encode())
        self.assertEqual(self.check()[0], 1)

    def test_chain_to_the_filesystem_root_does_not_crash(self):
        code, text = run("context", "check", "--project", str(self.proj), "--home", str(self.home))
        self.assertIn(code, (0, 1, 2), text)

    def test_the_user_core_is_not_counted_twice_when_home_is_an_ancestor(self):
        self.core(sized(6000))
        proj = self.home / "work"
        proj.mkdir()
        (proj / "CLAUDE.md").write_bytes(sized(2000).encode())
        code, text = run("context", "check", "--project", str(proj), "--home", str(self.home),
                         "--chain-root", str(self.home))
        self.assertEqual(code, 0, text)


class MemoryIndex(Case):
    def test_lines_budget_exact_and_one_over(self):
        self.memory("".join(f"- [t{i}](t{i}.md)\n" for i in range(60)))
        self.assertEqual(self.check()[0], 0)
        self.memory("".join(f"- [t{i}](t{i}.md)\n" for i in range(61)))
        code, text = self.check()
        self.assertEqual(code, 1, text)
        self.assertIn("lines", text)

    def test_bytes_budget_exact_and_one_over(self):
        self.memory(sized(4000))
        self.assertEqual(self.check()[0], 0)
        self.memory(sized(4001))
        self.assertEqual(self.check()[0], 1)

    def test_crlf_lines_are_counted_once_each(self):
        self.memory("", raw=b"- [t](t.md)\r\n" * 60)
        self.assertEqual(self.check()[0], 0)
        self.memory("", raw=b"- [t](t.md)\r\n" * 61)
        self.assertEqual(self.check()[0], 1)

    def test_over_budget_advises_memory_index_topics(self):
        self.memory(sized(4100))
        _, text = self.check()
        self.assertIn("memory index", text)

    def test_other_project_hard_caps_200_lines_and_25_kb(self):
        other = self.root / "elsewhere" / "other"
        other.mkdir(parents=True)
        self.memory("", project=other, raw=b"x\n" * 200)
        code, text = self.check()
        self.assertEqual(code, 2, text)  # over the budget but under the cap: a warning only
        self.assertIn("WARN", text)
        self.memory("", project=other, raw=b"x\n" * 201)
        code, text = self.check()
        self.assertEqual(code, 1, text)
        self.assertIn("200", text)
        self.memory("", project=other, raw=b"x" * 25000)
        self.assertEqual(self.check()[0], 2)
        self.memory("", project=other, raw=b"x" * 25001)
        self.assertEqual(self.check()[0], 1)

    def test_no_memory_folder_is_skipped(self):
        code, text = self.check()
        self.assertEqual(code, 0)
        self.assertIn("SKIP", text)

    def test_memory_folder_without_an_index_is_skipped(self):
        d = self.memory("x")
        (d / "MEMORY.md").unlink()
        code, text = self.check()
        self.assertEqual(code, 0, text)
        self.assertIn("SKIP", text)

    def test_explicit_memory_dir(self):
        d = self.root / "mem"
        d.mkdir()
        (d / "MEMORY.md").write_bytes(sized(4001).encode())
        self.assertEqual(self.check("--memory-dir", str(d))[0], 1)


class Imports(Case):
    """`@path` imports load eagerly, relative to the importing file, up to 4 hops; cycles are reported."""

    def test_a_big_import_counts_against_the_user_core(self):
        (self.home / ".claude" / "big.md").write_bytes(sized(100000).encode())
        self.core("@big.md\n")
        code, text = self.check()
        self.assertEqual(code, 1, text)
        self.assertIn("import", text)
        self.assertIn("100008", text)

    def test_a_big_import_counts_against_the_project_chain(self):
        (self.proj / "big2.md").write_bytes(sized(100000).encode())
        (self.proj / "CLAUDE.md").write_bytes(b"See @big2.md for detail.\n")
        code, text = self.check()
        self.assertEqual(code, 1, text)
        self.assertIn("import", text)

    def test_imports_resolve_relative_to_the_importing_file_and_nest(self):
        sub = self.home / ".claude" / "sub"
        sub.mkdir()
        (sub / "a.md").write_bytes(b"@b.md\n" + b"a" * 100 + b"\n")
        (sub / "b.md").write_bytes(b"b" * 200 + b"\n")
        self.core("@sub/a.md\n")
        code, text = self.measure()
        self.assertEqual(code, 0, text)
        self.assertIn("import", text)
        self.assertIn("a.md", text)
        self.assertIn("b.md", text)
        self.assertIn(f"total at session start (L0): {10 + 107 + 201} bytes", text)

    def test_only_four_hops_load_and_the_rest_is_reported(self):
        d = self.home / ".claude"
        for i in range(1, 7):
            nxt = f"@h{i + 1}.md\n" if i < 6 else ""
            (d / f"h{i}.md").write_bytes((nxt + "x" * 100 + "\n").encode())
        self.core("@h1.md\n")
        code, text = self.measure()
        self.assertIn("h4.md", text)
        self.assertNotIn("h5.md)", text)
        self.assertIn("WARN", text)
        self.assertIn("hop", text)

    def test_cycles_are_reported_and_terminate(self):
        d = self.home / ".claude"
        (d / "x.md").write_bytes(b"@y.md\nxx\n")
        (d / "y.md").write_bytes(b"@x.md\nyy\n")
        self.core("@x.md\n")
        code, text = self.check()
        self.assertEqual(code, 2, text)
        self.assertIn("cycle", text)

    def test_code_spans_blocks_emails_and_missing_files_are_not_imports(self):
        (self.home / ".claude" / "big.md").write_bytes(sized(9000).encode())
        self.core("Use `@big.md` inline.\n\n```\n@big.md\n```\n\nMail me@big.md.example or @missing.md\n")
        code, text = self.check()
        self.assertEqual(code, 0, text)

    def test_home_relative_import(self):
        (self.home / "shared.md").write_bytes(sized(9000).encode())
        self.core("@~/shared.md\n")
        self.assertEqual(self.check()[0], 1)

    def test_imports_in_a_scoped_rule_are_not_session_start(self):
        (self.home / ".claude" / "big.md").write_bytes(sized(9000).encode())
        self.rule("scoped.md", '---\npaths:\n  - "web/**"\n---\n@big.md\n')
        self.assertEqual(self.check()[0], 0)


class LineCountAndAncestors(Case):
    def test_only_newlines_count_as_lines(self):
        other = self.root / "elsewhere" / "other"
        other.mkdir(parents=True)
        self.memory("", project=other, raw=("a b\n" * 101).encode("utf-8"))
        code, text = self.check()
        self.assertNotIn("FAIL", text)
        self.assertIn("101 lines", text)

    def test_unterminated_last_line_counts(self):
        self.memory("", raw=b"a\nb")
        _, text = self.check()
        self.assertIn("2 lines", text)

    def test_an_ancestor_folders_memory_is_a_warning_naming_the_uncertainty(self):
        parent = self.proj.parent
        self.memory("", project=parent, raw=b"x\n" * 100)
        code, text = self.check()
        self.assertEqual(code, 2, text)
        self.assertNotIn("FAIL", text)
        self.assertIn("UNVERIFIED", text)

    def test_an_ancestor_folders_memory_over_the_cap_still_fails(self):
        self.memory("", project=self.proj.parent, raw=b"x\n" * 201)
        self.assertEqual(self.check()[0], 1)


class Output(Case):
    def test_json_is_c20(self):
        self.core(sized(7001))
        code, text = run("--json", "context", "check", "--project", str(self.proj), "--home", str(self.home),
                         "--chain-root", str(self.root))
        data = json.loads(text)
        self.assertEqual((data["area"], data["verb"], data["exit_code"]), ("context", "check", 1))
        self.assertEqual(code, 1)

    def test_bad_config_fails_cleanly(self):
        bad = self.root / "bad.json"
        bad.write_text("{}", encoding="utf-8")
        code, text = run("--config", str(bad), "context", "check", "--project", str(self.proj),
                         "--home", str(self.home))
        self.assertEqual(code, 1)
        self.assertIn("FAIL", text)


class Measure(Case):
    def test_breakdown_and_total_exit_zero_even_over_budget(self):
        self.core(sized(7001))
        (self.proj / "CLAUDE.md").write_bytes(sized(300).encode())
        self.rule("a.md", sized(100))
        self.memory(sized(200))
        code, text = self.measure()
        self.assertEqual(code, 0, text)
        self.assertIn("7001", text)
        self.assertIn("estimate", text.lower())
        self.assertIn("total", text.lower())
        self.assertIn("L0", text)
        self.assertIn("MEMORY.md", text)

    def test_tokens_are_bytes_over_four_rounded_up(self):
        self.assertEqual(context.estimate_tokens(0), 0)
        self.assertEqual(context.estimate_tokens(4), 1)
        self.assertEqual(context.estimate_tokens(5), 2)

    def test_project_key_replaces_every_non_alphanumeric(self):
        self.assertEqual(context.sanitize("C:\\Users\\a.b\\Repos\\_x\\Y_Z"), "C--Users-a-b-Repos--x-Y-Z")


if __name__ == "__main__":
    unittest.main()

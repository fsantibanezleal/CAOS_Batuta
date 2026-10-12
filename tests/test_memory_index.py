"""memory index: the generated auto-memory index (library functions and the `memory index` verb)."""
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
sys.path.insert(0, str(ROOT / "plugins" / "batuta" / "scripts"))
from _support import load_batuta  # noqa: E402
from batuta_lib import memory_index as mi  # noqa: E402

FIXTURES = ROOT / "plugins" / "batuta" / "contracts" / "fixtures" / "C13"
DASH = "\u2014"

CFG = {"version": 1, "hook_max_chars": 40, "title_max_chars": 20}
PROJECT = {
    "pinned": ["feedback_pin", "feedback_gone_pin"],
    "topics": [
        {"id": "git", "title": "Git", "when": "committing", "match": ["git", "commit"]},
        {"id": "ui", "title": "UI", "when": "building UI", "match": ["^app_", "chart"]},
        {"id": "facts", "title": "Facts", "when": "project work", "match": ["^project_"]},
    ],
    "other": {"title": "Other", "when": "nothing fits"},
}
CLEAN = dict(PROJECT, pinned=["feedback_pin"])


def memory(name, description, kind="feedback"):
    return f"---\nname: {name}\ndescription: {description}\nmetadata:\n  node_type: memory\n  type: {kind}\n---\n\nBody.\n"


def run(*argv):
    batuta = load_batuta()
    out, err = io.StringIO(), io.StringIO()
    with mock.patch.dict(os.environ, {"BATUTA_HOME": str(ROOT / "no-such-home"), "BATUTA_CONFIG": ""}), \
            contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = batuta.main(list(argv))
    return code, out.getvalue()


class Frontmatter(unittest.TestCase):
    def test_plain_fields_and_nested_type(self):
        fm = mi.parse_frontmatter(memory("my-name", "A description"))
        self.assertEqual((fm["name"], fm["description"], fm["type"]), ("my-name", "A description", "feedback"))

    def test_quoted_description(self):
        text = '---\nname: "q-name"\ndescription: "Commit: often, \\"always\\""\nmetadata:\n  type: user\n---\n'
        fm = mi.parse_frontmatter(text)
        self.assertEqual(fm["name"], "q-name")
        self.assertTrue(fm["description"].startswith("Commit: often"))
        self.assertEqual(fm["type"], "user")

    def test_single_quoted(self):
        fm = mi.parse_frontmatter("---\nname: 'x'\ndescription: 'it''s fine'\n---\n")
        self.assertEqual(fm["description"], "it's fine")

    def test_missing_fields(self):
        fm = mi.parse_frontmatter("---\nname: only-name\n---\nbody")
        self.assertEqual(fm.get("name"), "only-name")
        self.assertNotIn("description", fm)
        self.assertNotIn("type", fm)

    def test_no_frontmatter(self):
        self.assertEqual(mi.parse_frontmatter("just text\n"), {})

    def test_empty_metadata_block_and_crlf(self):
        fm = mi.parse_frontmatter("---\r\nname: a\r\ndescription: b\r\nmetadata: \r\n  node_type: memory\r\n---\r\n")
        self.assertEqual((fm["name"], fm["description"]), ("a", "b"))


class IndexParsing(unittest.TestCase):
    def test_four_separators(self):
        text = "\n".join(["- [A](a.md) - hook a", "- [B](b.md) -- hook b", "- [C](c.md): hook c",
                          f"- [D](d.md) {DASH} hook d"])
        entries, other = mi.parse_index(text)
        self.assertEqual(entries["a"], ("A", "hook a"))
        self.assertEqual(entries["b"], ("B", "hook b"))
        self.assertEqual(entries["c"], ("C", "hook c"))
        self.assertEqual(entries["d"], ("D", "hook d"))
        self.assertEqual(other, [])

    def test_non_entry_lines(self):
        entries, other = mi.parse_index("# Title\n\nSome prose line\n- [A](a.md) - h\n- plain bullet\n")
        self.assertEqual(list(entries), ["a"])
        self.assertIn("Some prose line", other)
        self.assertIn("- plain bullet", other)

    def test_entry_without_hook(self):
        entries, _ = mi.parse_index("- [A](a.md)\n")
        self.assertEqual(entries["a"], ("A", ""))


class Classify(unittest.TestCase):
    def test_pinned_first(self):
        self.assertEqual(mi.classify("feedback_pin", PROJECT), "pinned")

    def test_pinned_beats_topic_match(self):
        self.assertEqual(mi.classify("feedback_git_pin", dict(PROJECT, pinned=["feedback_git_pin"])), "pinned")

    def test_first_topic_wins(self):
        self.assertEqual(mi.classify("feedback_git_chart", PROJECT), "git")

    def test_search_not_match(self):
        self.assertEqual(mi.classify("feedback_my_commit_x", PROJECT), "git")

    def test_anchored_regex(self):
        self.assertEqual(mi.classify("project_x", PROJECT), "facts")
        self.assertEqual(mi.classify("feedback_project_x", PROJECT), "other")

    def test_other(self):
        self.assertEqual(mi.classify("feedback_zzz", PROJECT), "other")


class Trim(unittest.TestCase):
    def test_short_unchanged(self):
        self.assertEqual(mi.trim("short", 20), "short")

    def test_word_boundary(self):
        out = mi.trim("one two three four five", 15)
        self.assertEqual(out, "one two...")
        self.assertLessEqual(len(out), 15)
        self.assertEqual(mi.trim("one two three four five", 16), "one two three...")

    def test_no_space_hard_cut(self):
        self.assertEqual(mi.trim("abcdefghijklmnop", 10), "abcdefg...")


class Fixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.mem = self.root / "memory"
        self.mem.mkdir()

    def put(self, stem, name=None, description="desc", raw=None):
        text = raw if raw is not None else memory(name or stem.replace("_", "-"), description)
        (self.mem / f"{stem}.md").write_text(text, encoding="utf-8")

    def index(self, text, raw=None):
        (self.mem / "MEMORY.md").write_bytes(raw if raw is not None else text.encode("utf-8"))

    def topics_file(self, projects=None, cfg=None):
        path = self.root / "topics.json"
        data = {"contract_version": "1.0", **(cfg or CFG), "projects": projects if projects is not None else {"P": CLEAN}}
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def budget_file(self, bytes_=4000, lines=60):
        path = self.root / "budget.json"
        path.write_text(json.dumps({"user_core_bytes": 7000, "project_core_bytes": 7000, "unscoped_rules_bytes": 2000,
                                    "memory_index_bytes": bytes_, "memory_index_lines": lines}), encoding="utf-8")
        return path

    def cli(self, *extra, project="P", budget=None, topics=None, mem=None):
        return run("memory", "index", "--memory-dir", str(mem or self.mem), "--project", project,
                   "--topics", str(topics or self.topics_file()), "--budget", str(budget or self.budget_file()), *extra)

    def snapshot(self):
        return {str(p.relative_to(self.mem)): p.read_bytes() for p in sorted(self.mem.rglob("*")) if p.is_file()}

    def standard(self):
        self.put("feedback_pin", description="Pinned rule")
        self.put("feedback_git_one", description="Git thing")
        self.put("feedback_commit_two", description="Commit thing")
        self.put("app_chart", description="Chart thing")
        self.put("project_alpha", description="Alpha facts")
        self.put("feedback_zzz", description="Unclassified")


class Build(Fixture):
    def test_layout(self):
        self.standard()
        text, pages, report = mi.build(self.mem, PROJECT, CFG)
        lines = text.splitlines()
        self.assertTrue(lines[0].startswith(mi.GENERATED_PREFIX))
        self.assertEqual(lines[1], "## Always relevant")
        self.assertEqual(lines[2], "- [Feedback pin](feedback_pin.md) - Pinned rule")
        self.assertEqual(lines[3], "## Topics (open the page when the task matches)")
        self.assertEqual(lines[4], "- [Git (2)](topics/git.md) - committing")
        self.assertIn("- [UI (1)](topics/ui.md) - building UI", lines)
        self.assertEqual(lines[-1], "- [Other (1)](topics/other.md) - nothing fits")
        self.assertNotIn("## Notes", text)
        self.assertTrue(text.endswith("\n"))
        self.assertEqual(set(pages), {"git", "ui", "facts", "other"})

    def test_topic_page_layout_sorted_by_stem(self):
        self.standard()
        _, pages, _ = mi.build(self.mem, PROJECT, CFG)
        self.assertEqual(pages["git"].splitlines(), [
            "# Git", mi.PAGE_MARK, "", "Read when: committing.", "",
            "- [Feedback commit two](../feedback_commit_two.md) - Commit thing",
            "- [Feedback git one](../feedback_git_one.md) - Git thing"])

    def test_empty_topic_omitted(self):
        self.put("feedback_pin")
        self.put("feedback_git_one")
        text, pages, _ = mi.build(self.mem, PROJECT, CFG)
        self.assertEqual(set(pages), {"git"})
        self.assertNotIn("topics/ui.md", text)
        self.assertNotIn("topics/other.md", text)

    def test_old_title_and_hook_preserved(self):
        self.standard()
        self.index("- [Hand title](feedback_git_one.md) - hand hook\n- [Pinned hand](feedback_pin.md) - pin hook\n")
        text, pages, _ = mi.build(self.mem, PROJECT, CFG)
        self.assertIn("- [Hand title](../feedback_git_one.md) - hand hook", pages["git"])
        self.assertIn("- [Pinned hand](feedback_pin.md) - pin hook", text)

    def test_old_title_and_hook_trimmed(self):
        self.put("feedback_git_one")
        self.index("- [A very long hand written title here](feedback_git_one.md) - " + "word " * 30 + "\n")
        _, pages, _ = mi.build(self.mem, PROJECT, CFG)
        line = [ln for ln in pages["git"].splitlines() if ln.startswith("- [")][0]
        title = line[3:line.index("](")]
        hook = line.split(" - ", 1)[1]
        self.assertLessEqual(len(title), CFG["title_max_chars"])
        self.assertLessEqual(len(hook), CFG["hook_max_chars"])
        self.assertTrue(title.endswith("..."))
        self.assertTrue(hook.endswith("..."))

    def test_title_and_hook_from_frontmatter_without_index(self):
        self.put("feedback_git_one", name="no-force-push", description="Never force push")
        _, pages, _ = mi.build(self.mem, PROJECT, CFG)
        self.assertIn("- [No force push](../feedback_git_one.md) - Never force push", pages["git"])

    def test_missing_frontmatter_falls_back_to_stem(self):
        self.put("feedback_git_one", raw="no frontmatter here\n")
        _, pages, _ = mi.build(self.mem, PROJECT, CFG)
        self.assertIn("- [Feedback git one](../feedback_git_one.md)", pages["git"])
        self.assertNotIn("md) - ", pages["git"])

    def test_dangling_and_missing_pin(self):
        self.standard()
        self.index("- [Ghost](ghost_file.md) - nothing here\n- [Git](feedback_git_one.md) - ok\n")
        text, pages, report = mi.build(self.mem, PROJECT, CFG)
        self.assertEqual(report["dangling"], ["ghost_file"])
        self.assertEqual(report["missing_pins"], ["feedback_gone_pin"])
        self.assertNotIn("ghost_file", text + "".join(pages.values()))
        rendered = mi.render_report(report)
        self.assertIn("DANGLING", rendered)
        self.assertIn("MISSING PIN", rendered)

    def test_notes_kept_verbatim(self):
        self.standard()
        self.index("# Memory Index\n\n## Read first\n\nRules live in `Rules/`.\n- [Git](feedback_git_one.md) - h\n- plain bullet\n")
        text, _, _ = mi.build(self.mem, PROJECT, CFG)
        lines = text.splitlines()
        at = lines.index("## Notes")
        self.assertEqual(lines[at + 1:], ["Rules live in `Rules/`.", "- plain bullet"])

    def test_regenerated_index_is_stable_and_notes_not_duplicated(self):
        self.standard()
        self.index("Rules live in `Rules/`.\n- [Git](feedback_git_one.md) - h\n")
        first, pages, _ = mi.build(self.mem, PROJECT, CFG)
        self.index(first)
        (self.mem / "topics").mkdir()
        for tid, body in pages.items():
            (self.mem / "topics" / f"{tid}.md").write_text(body, encoding="utf-8")
        second, pages2, _ = mi.build(self.mem, PROJECT, CFG)
        self.assertEqual(first, second)
        self.assertEqual(pages, pages2)

    def test_crlf_index_is_read_like_an_lf_one(self):
        self.standard()
        lf = "- [Hand title](feedback_git_one.md) - hand hook\nNote line\n"
        self.index(lf)
        a = mi.build(self.mem, PROJECT, CFG)
        self.index("", raw=lf.replace("\n", "\r\n").encode("utf-8"))
        b = mi.build(self.mem, PROJECT, CFG)
        self.assertEqual(a[:2], b[:2])
        self.assertNotIn("\r", b[0])

    def test_every_file_exactly_once(self):
        self.standard()
        text, pages, report = mi.build(self.mem, PROJECT, CFG)
        corpus = text + "".join(pages.values())
        for stem in [p.stem for p in self.mem.glob("*.md") if p.name != "MEMORY.md"]:
            self.assertEqual(corpus.count(f"{stem}.md)"), 1, stem)
        self.assertEqual(sum(report["counts"].values()), report["files"])
        self.assertEqual(report["files"], 6)

    def test_deterministic(self):
        self.standard()
        self.assertEqual(mi.build(self.mem, PROJECT, CFG), mi.build(self.mem, PROJECT, CFG))

    def test_report_sizes_count_bytes(self):
        self.put("feedback_git_one", description="café")
        text, _, report = mi.build(self.mem, PROJECT, CFG)
        self.assertEqual(report["index_bytes"], len(text.encode("utf-8")))
        self.assertEqual(report["index_lines"], len(text.splitlines()))

    def test_generated_header_names_batuta_and_carries_no_path(self):
        self.assertIn("batuta", mi.GENERATED_HEADER)
        self.assertIsNone(re.search(r"[\\/]|[A-Za-z]:", mi.GENERATED_HEADER))


class Verb(Fixture):
    def test_dry_run_writes_nothing(self):
        self.standard()
        before = self.snapshot()
        code, out = self.cli()
        self.assertEqual(code, 0, out)
        self.assertEqual(self.snapshot(), before)
        self.assertIn("NEW MEMORY.md", out)
        self.assertFalse((self.mem / "topics").exists())

    def test_apply_writes_and_second_apply_is_same(self):
        self.standard()
        code, out = self.cli("--apply")
        self.assertEqual(code, 0, out)
        self.assertTrue((self.mem / "MEMORY.md").exists())
        self.assertTrue((self.mem / "topics" / "git.md").exists())
        after = self.snapshot()
        code, out = self.cli("--apply")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.snapshot(), after)
        self.assertNotIn("CHANGED", out)
        self.assertNotIn("NEW", out)
        self.assertIn("SAME", out)

    def test_written_bytes_are_lf_utf8_with_trailing_newline(self):
        self.put("feedback_git_one", description="café rule")
        self.cli("--apply")
        raw = (self.mem / "topics" / "git.md").read_bytes()
        self.assertNotIn(b"\r", raw)
        self.assertTrue(raw.endswith(b"\n"))
        self.assertIn("café".encode("utf-8"), raw)

    def test_changed_reported_when_index_differs(self):
        self.standard()
        self.index("old\n")
        code, out = self.cli()
        self.assertEqual(code, 0, out)
        self.assertIn("CHANGED MEMORY.md", out)

    def test_stale_topic_page_removed_on_apply_reported_on_dry_run(self):
        self.standard()
        self.cli("--apply")
        (self.mem / "topics" / "retired.md").write_text("# Old\n" + mi.PAGE_MARK + "\n", encoding="utf-8")
        _, out = self.cli()
        self.assertIn("REMOVED topics/retired.md", out)
        self.assertTrue((self.mem / "topics" / "retired.md").exists())
        self.cli("--apply")
        self.assertFalse((self.mem / "topics" / "retired.md").exists())

    def test_hand_written_files_in_topics_are_never_deleted(self):
        self.standard()
        topics = self.mem / "topics"
        topics.mkdir()
        (topics / "handnotes.md").write_text("important hand-written content\n", encoding="utf-8")
        (topics / "scratch.txt").write_text("scratch\n", encoding="utf-8")
        _, out = self.cli("--apply")
        self.assertNotIn("REMOVED", out)
        self.assertEqual((topics / "handnotes.md").read_text(encoding="utf-8"), "important hand-written content\n")
        self.assertTrue((topics / "scratch.txt").exists())
        self.cli("--apply")
        self.assertTrue((topics / "handnotes.md").exists())

    def test_hand_written_page_named_like_a_topic_id_without_the_mark_is_replaced_not_orphaned(self):
        # a page of a configured topic id is regenerated (legacy pages carry no mark); an unknown name is kept
        self.standard()
        topics = self.mem / "topics"
        topics.mkdir()
        (topics / "git.md").write_text("legacy page\n", encoding="utf-8")
        self.cli("--apply")
        self.assertIn(mi.PAGE_MARK, (topics / "git.md").read_text(encoding="utf-8"))

    def test_legacy_page_of_an_emptied_topic_is_removed(self):
        self.standard()
        topics = self.mem / "topics"
        topics.mkdir()
        (topics / "ui.md").write_text("legacy page without a mark\n", encoding="utf-8")
        (self.mem / "app_chart.md").unlink()
        self.cli("--apply")
        self.assertFalse((topics / "ui.md").exists())

    def test_invalid_match_pattern_fails_cleanly(self):
        self.standard()
        bad = dict(CLEAN, topics=[{"id": "git", "title": "Git", "when": "w", "match": ["(unclosed"]}])
        code, out = self.cli(topics=self.topics_file({"P": bad}))
        self.assertEqual(code, 1, out)
        self.assertIn("FAIL", out)
        self.assertIn("pattern", out)

    def test_star_and_plus_bullets_keep_title_and_hook(self):
        entries, other = mi.parse_index("* [Star](a.md) - star hook\n+ [Plus](b.md): plus hook\n")
        self.assertEqual(entries["a"], ("Star", "star hook"))
        self.assertEqual(entries["b"], ("Plus", "plus hook"))
        self.assertEqual(other, [])

    def test_topic_page_removed_when_topic_empties(self):
        self.standard()
        self.cli("--apply")
        (self.mem / "app_chart.md").unlink()
        self.cli("--apply")
        self.assertFalse((self.mem / "topics" / "ui.md").exists())

    def test_folder_without_an_index_gets_one(self):
        self.standard()
        self.assertFalse((self.mem / "MEMORY.md").exists())
        self.assertEqual(self.cli("--apply")[0], 0)
        self.assertTrue((self.mem / "MEMORY.md").is_file())

    def test_index_exactly_at_the_budget_passes_one_under_refuses(self):
        self.standard()
        text, _, report = mi.build(self.mem, CLEAN, CFG)
        size, lines = report["index_bytes"], report["index_lines"]
        self.assertEqual(self.cli("--apply", budget=self.budget_file(size, lines))[0], 0)
        (self.mem / "MEMORY.md").unlink()
        shutil_topics = self.mem / "topics"
        for p in shutil_topics.iterdir():
            p.unlink()
        shutil_topics.rmdir()
        before = self.snapshot()
        code, out = self.cli("--apply", budget=self.budget_file(size - 1, lines))
        self.assertEqual(code, 1)
        self.assertIn("REFUSED", out)
        self.assertEqual(self.snapshot(), before)
        code, out = self.cli("--apply", budget=self.budget_file(size, lines - 1))
        self.assertEqual(code, 1)
        self.assertEqual(self.snapshot(), before)

    def test_default_budget_comes_from_the_c01_defaults(self):
        self.standard()
        topics = self.topics_file(cfg=dict(CFG, hook_max_chars=110, title_max_chars=60))
        for i in range(120):
            self.put(f"project_item_{i:03d}", description="d" * 60)
        code, out = run("memory", "index", "--memory-dir", str(self.mem), "--project", "P", "--topics", str(topics), "--apply")
        self.assertEqual(code, 0, out)  # topic pages absorb the lines, the index stays small
        self.assertLessEqual(len((self.mem / "MEMORY.md").read_bytes()), 4000)

    def test_not_opted_in_exit_2_and_nothing_written(self):
        self.standard()
        before = self.snapshot()
        code, out = self.cli("--apply", project="Unknown")
        self.assertEqual(code, 2)
        self.assertEqual(self.snapshot(), before)
        self.assertIn("not opted in", out)

    def test_missing_topics_file_is_not_opted_in(self):
        code, out = run("memory", "index", "--memory-dir", str(self.mem), "--project", "P",
                        "--topics", str(self.root / "nowhere.json"))
        self.assertEqual(code, 2)
        self.assertIn("nowhere.json", out)

    def test_missing_pin_is_reported_as_a_warning(self):
        self.standard()
        code, out = self.cli(topics=self.topics_file({"P": PROJECT}))
        self.assertEqual(code, 2, out)
        self.assertIn("MISSING PIN", out)
        self.assertIn("feedback_gone_pin", out)

    def test_dangling_entry_is_reported_then_gone(self):
        self.standard()
        self.index("- [Ghost](ghost_file.md) - nothing here\n")
        code, out = self.cli("--apply")
        self.assertEqual(code, 2, out)
        self.assertIn("DANGLING", out)
        code, out = self.cli("--apply")
        self.assertEqual(code, 0, out)

    def test_missing_memory_dir_fails(self):
        code, out = self.cli(mem=self.root / "nope")
        self.assertEqual(code, 1)
        self.assertIn("FAIL", out)

    def test_json_output_is_c20(self):
        self.standard()
        code, out = run("--json", "memory", "index", "--memory-dir", str(self.mem), "--project", "P",
                        "--topics", str(self.topics_file()), "--budget", str(self.budget_file()))
        data = json.loads(out)
        self.assertEqual((data["area"], data["verb"], data["exit_code"]), ("memory", "index", code))

    def test_bad_budget_file_fails_against_c14(self):
        bad = self.root / "badbudget.json"
        bad.write_text(json.dumps({"memory_index_bytes": "big"}), encoding="utf-8")
        code, out = self.cli(budget=bad)
        self.assertEqual(code, 1)
        self.assertIn("C14", out)


class ContractFixtures(Fixture):
    def test_valid_c13_fixtures_run(self):
        for fx in sorted(FIXTURES.glob("valid-*.json")):
            with self.subTest(fx.name):
                doc = json.loads(fx.read_text(encoding="utf-8"))
                project = next(iter(doc["projects"]), "None")
                code, out = self.cli(project=project, topics=fx)
                self.assertIn(code, (0, 2), out)
                self.assertNotIn("FAIL", out)
        code, out = self.cli(project="ExampleProject", topics=FIXTURES / "valid-one-project.json")
        self.assertEqual(code, 2, out)  # its pinned memory has no file: a MISSING PIN warning, not a failure
        self.assertIn("MISSING PIN", out)

    def test_invalid_c13_fixtures_are_refused(self):
        for fx in sorted(FIXTURES.glob("invalid-*.json")):
            with self.subTest(fx.name):
                doc = json.loads(fx.read_text(encoding="utf-8"))
                code, out = self.cli(project="ExampleProject", topics=fx)
                self.assertEqual(code, 1, out)
                self.assertIn("C13", out)
                if doc.get("_expect"):
                    self.assertIn(doc["_expect"], out)


if __name__ == "__main__":
    unittest.main()

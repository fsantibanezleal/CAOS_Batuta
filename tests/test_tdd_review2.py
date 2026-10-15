"""The second round of the Opus review of U4 (R2-01 to R2-07) and decisions 32 and 33 (typed-prompt decision, runtime comparison of
the locked tests), each reproduction as a test on scratch git repositories."""
import json
import os
import subprocess
from pathlib import Path
import sys
import unittest
from unittest import mock

from _support import SCRIPTS
from test_tdd_check import EDITED, REQUESTS, commit_request_open_first, requests
from test_tdd_fixtures import LOCK, SPEC, TEST_CALC, message, run_cli, write_config
from test_tdd_review import ReviewBase

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from batuta_lib import config  # noqa: E402
from batuta_lib import contract as core  # noqa: E402
from batuta_lib import tdd_history as hist  # noqa: E402
from batuta_lib import tdd_lock as lk  # noqa: E402
from batuta_lib.areas import tdd as tdd_area  # noqa: E402

CLI = str(SCRIPTS / "batuta.py")


class OpenRequestCase(ReviewBase):
    """A scratch repository with one open request, CR-001, for tests/test_calc.py."""

    def setUp(self):
        self.repo = self.fresh(self.id().rsplit(".", 1)[-1])
        self.repo.write("README.md", "x\n")
        self.repo.commit("init", "README.md")
        code, out = run_cli("--config", self.cfg, "tdd", "change-request", "new", "--repo", self.repo.root, "--test", "tests/test_calc.py",
                            "--requirement", "REQ-CALC-001", "--reason", "wrong oracle", "--proposed", "expect 6", "--feature", "calc", "--apply")
        self.assertEqual(code, 0, out)
        self.file = self.repo.root / REQUESTS

    def rows(self):
        sp = core.find_schema(config.contracts_dir(), "C33")
        return core.read_table(self.file.read_text(encoding="utf-8"), core.load_sections_spec(sp)["tables"][0])[0]


class R201Console(OpenRequestCase):
    """R2-01: the console must be a real interactive one, the wait is bounded and the decider is the account, not the environment."""

    def decide_in_a_subprocess(self, **kwargs):
        argv = [sys.executable, "-B", CLI, "--config", str(self.cfg), "tdd", "change-request", "decide", "--repo", str(self.repo.root),
                "CR-001", "approve", "--apply"]
        return subprocess.run(argv, capture_output=True, text=True, timeout=120, **kwargs)

    def test_a_null_standard_input_is_not_a_console(self):
        before = self.file.read_bytes()
        proc = self.decide_in_a_subprocess(stdin=subprocess.DEVNULL)
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("REFUSED", proc.stdout)
        self.assertEqual(self.file.read_bytes(), before)

    def test_a_piped_answer_is_not_a_console(self):
        before = self.file.read_bytes()
        proc = self.decide_in_a_subprocess(input="approve CR-001\n")
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("REFUSED", proc.stdout)
        self.assertEqual(self.file.read_bytes(), before)

    def test_an_interactive_check_that_fails_refuses(self):
        with mock.patch.object(tdd_area, "_console_interactive", return_value=(False, "standard input is not a console")):
            with self.assertRaises(tdd_area.ConsoleUnavailable) as caught:
                tdd_area.read_console("confirm: ")
        self.assertIn("standard input", str(caught.exception))

    def test_a_read_that_never_answers_times_out(self):
        import time
        with mock.patch.object(tdd_area, "_console_interactive", return_value=(True, "")), \
                mock.patch.object(tdd_area, "_ask_on_console", side_effect=lambda prompt: time.sleep(5) or "approve CR-001"):
            with self.assertRaises(tdd_area.ConsoleUnavailable) as caught:
                tdd_area.read_console("confirm: ", timeout=0.2)
        self.assertIn("timed out", str(caught.exception))

    def test_an_answer_on_an_interactive_console_is_returned(self):
        with mock.patch.object(tdd_area, "_console_interactive", return_value=(True, "")), \
                mock.patch.object(tdd_area, "_ask_on_console", return_value="approve CR-001"):
            self.assertEqual(tdd_area.read_console("confirm: "), "approve CR-001")

    def test_the_decision_names_the_account_not_the_environment(self):
        forged = {"USERNAME": "forged", "USER": "forged", "LOGNAME": "forged", "LNAME": "forged"}
        with mock.patch.dict(os.environ, forged), mock.patch.object(tdd_area, "read_console", return_value="approve CR-001"):
            code, out = run_cli("--config", self.cfg, "tdd", "change-request", "decide", "--repo", self.repo.root, "CR-001", "approve", "--apply")
        self.assertEqual(code, 0, out)
        by = self.rows()[0]["Decided by"]
        self.assertNotIn(by.strip(), ("", "-", "forged"))
        self.assertNotEqual(by, "forged")


class R205RequestHistory(ReviewBase):
    def test_a_row_born_approved_fails(self):
        repo = self.clone()
        repo.write(REQUESTS, requests())
        repo.commit("docs: change request", REQUESTS)
        self.failing(repo, "born")

    def test_a_decided_row_edited_in_place_fails(self):
        repo = self.clone()
        commit_request_open_first(repo, requests(path="tests/test_other.py"))
        repo.write(REQUESTS, requests(path="tests/test_calc.py"))
        repo.commit("docs: retarget the request", REQUESTS)
        self.failing(repo, "decided request")

    def test_a_row_opened_and_then_decided_in_its_own_commits_passes(self):
        repo = self.clone()
        commit_request_open_first(repo, requests())
        code, out = self.check(repo)
        self.assertEqual(code, 0, out)


class R206SettingsWarning(ReviewBase):
    def test_the_base_commits_own_configuration_is_not_a_change(self):
        repo = self.fresh("base-config-quiet")
        cfg = config.default_config({})
        cfg["roots"] = {"temp": str(self.tmp / "qtemp"), "data": str(self.tmp / "qdata"), "worktrees": str(self.tmp / "qwt")}
        cfg["tdd"] = {"markers": ["wip"]}
        repo.write("README.md", "x\n")
        repo.write(".batuta/batuta.json", json.dumps(cfg, indent=2) + "\n")
        repo.commit("init", "README.md", ".batuta/batuta.json")
        repo.write("tests/test_calc.py", TEST_CALC)
        code, out = self.plain("tdd", "lock", "--repo", repo.root, "--task", "T-001", "tests/test_calc.py", "--apply")
        self.assertEqual(code, 0, out)
        code, out = self.plain("tdd", "commit", "--repo", repo.root, "--red", "T-001", "-m", "calc", "tests/test_calc.py", "--apply")
        self.assertEqual(code, 0, out)
        code, out = self.plain("tdd", "check", "--repo", repo.root)
        self.assertEqual(code, 0, out)
        self.assertNotIn("tdd settings", out)


class Q2ShowAndTypedPrompt(OpenRequestCase):
    def hook(self, prompt, cwd=None):
        payload = {"session_id": "s1", "cwd": str(cwd or self.repo.root), "transcript_path": "t.jsonl",
                   "hook_event_name": "UserPromptSubmit", "prompt": prompt}
        return tdd_area.HOOKS["tdd-change-request"](payload)

    def phrases(self):
        code, out = run_cli("--config", self.cfg, "tdd", "change-request", "show", "--repo", self.repo.root, "CR-001")
        self.assertEqual(code, 0, out)
        digest = lk.row_hash(self.rows()[0])[:12]
        return out, digest

    def test_show_prints_both_phrases_with_the_hash_of_the_row(self):
        out, digest = self.phrases()
        self.assertIn(f"approve CR-001 {digest}", out)
        self.assertIn(f"reject CR-001 {digest}", out)
        self.assertRegex(digest, r"^[0-9a-f]{12}$")

    def test_show_refuses_an_unknown_request(self):
        code, out = run_cli("--config", self.cfg, "tdd", "change-request", "show", "--repo", self.repo.root, "CR-009")
        self.assertEqual(code, 1, out)

    def test_the_typed_phrase_records_the_decision(self):
        _, digest = self.phrases()
        result = self.hook(f"approve CR-001 {digest}")
        self.assertEqual(result["exit_code"], 0)
        row = self.rows()[0]
        self.assertEqual((row["Status"], row["Decided by"]), ("approved", "typed prompt"))
        self.assertEqual(core.validate_file(self.file, core.find_schema(config.contracts_dir(), "C33")), [])
        self.assertTrue(result["output"])

    def test_the_phrase_may_be_indented_and_followed_by_more_lines(self):
        _, digest = self.phrases()
        self.hook(f"  reject CR-001 {digest}  \nthe oracle is right after all")
        self.assertEqual(self.rows()[0]["Status"], "rejected")

    def test_words_after_the_phrase_on_its_line_decide_nothing(self):
        _, digest = self.phrases()
        before = self.file.read_bytes()
        for prompt in (f"approve CR-001 {digest} -- no wait, do not approve",
                       f"approve CR-001 {digest} reject CR-001 {digest}",
                       f"approve CR-001 {digest}x"):
            with self.subTest(prompt=prompt):
                self.hook(prompt)
                self.assertEqual(self.file.read_bytes(), before)

    def test_a_phrase_that_does_not_start_the_prompt_is_ignored(self):
        _, digest = self.phrases()
        before = self.file.read_bytes()
        result = self.hook(f"please approve CR-001 {digest}")
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(self.file.read_bytes(), before)

    def test_a_wrong_or_stale_hash_is_ignored_and_never_blocks(self):
        _, digest = self.phrases()
        before = self.file.read_bytes()
        result = self.hook("approve CR-001 " + "0" * 12)
        self.assertEqual(result["exit_code"], 0)
        self.assertNotIn("decision", result.get("output") or {})
        self.assertEqual(self.file.read_bytes(), before)
        self.file.write_text(self.file.read_text(encoding="utf-8").replace("wrong oracle", "another reason"), encoding="utf-8", newline="\n")
        stale = self.file.read_bytes()
        self.hook(f"approve CR-001 {digest}")
        self.assertEqual(self.file.read_bytes(), stale)

    def test_a_decided_request_is_not_decided_again(self):
        _, digest = self.phrases()
        self.hook(f"approve CR-001 {digest}")
        decided = self.file.read_bytes()
        self.hook(f"reject CR-001 {lk.row_hash(self.rows()[0])[:12]}")
        self.assertEqual(self.file.read_bytes(), decided)

    def test_the_handler_never_raises(self):
        for payload in ({}, {"prompt": None}, {"prompt": 7, "cwd": 3}, {"prompt": "approve CR-001 abcdef012345", "cwd": "no/such/folder"}):
            with self.subTest(payload=payload):
                result = tdd_area.HOOKS["tdd-change-request"](payload)
                self.assertEqual(result["exit_code"], 0)

    def test_the_result_satisfies_c31_with_a_userpromptsubmit_output(self):
        _, digest = self.phrases()
        result = self.hook(f"approve CR-001 {digest}")
        schema = core.load_schema(core.find_schema(config.contracts_dir(), "C31"))
        self.assertEqual(core.validate_instance("C31", result, schema), [])


class Q3RuntimeComparison(ReviewBase):
    HIDE = 'exec("import unittest\\ndef load_" + "tests(loader, tests, pattern):\\n    return unittest.TestSuite()\\n")\n'

    def test_a_locked_test_that_stops_being_collected_fails_the_replay(self):
        repo = self.clone()
        repo.write("tests/__init__.py", self.HIDE)
        repo.commit(message("refactor", "T-001", "hide the tests from the loader"), "tests/__init__.py")
        out = self.failing(repo, "disappears", "tests/test_calc.py", extra=("--replay",))
        self.assertIn("CalcTests", out)

    def test_the_same_history_passes_the_static_rules_alone(self):
        repo = self.clone()
        repo.write("tests/__init__.py", self.HIDE)
        repo.commit(message("refactor", "T-001", "hide the tests from the loader"), "tests/__init__.py")
        code, out = self.check(repo)
        self.assertEqual(code, 0, out)

    def test_static_ids_are_read_from_the_test_file(self):
        ids = hist.static_test_ids("tests/test_calc.py", TEST_CALC)
        self.assertEqual(sorted(ids), [("CalcTests", "test_add"), ("CalcTests", "test_add_negative")])
        self.assertEqual(hist.static_test_ids("tests/test_f.py", "def test_a():\n    pass\n\n\ndef helper():\n    pass\n"), [(None, "test_a")])

    def test_the_comparison_names_a_missing_and_a_skipped_test(self):
        base = [("CalcTests", "test_add"), ("CalcTests", "test_gone"), ("CalcTests", "test_skipped")]
        listing = [{"id": "test_calc.CalcTests.test_add", "skipped": False},
                   {"id": "test_calc.CalcTests.test_skipped", "skipped": True}]
        problems = hist.compare_listing("tests/test_calc.py", base, listing)
        self.assertEqual(len(problems), 2)
        self.assertTrue(any("test_gone" in p and "disappears" in p for p in problems))
        self.assertTrue(any("test_skipped" in p and "skipped" in p for p in problems))
        self.assertEqual(hist.compare_listing("tests/test_calc.py", [("CalcTests", "test_add")], listing[:1]), [])

    def test_a_pytest_listing_is_parsed(self):
        out = "tests/test_calc.py::CalcTests::test_add\ntests/test_f.py::test_a\n\n2 tests collected in 0.01s\n"
        self.assertEqual(hist.parse_pytest_listing(out), [{"id": "tests/test_calc.py::CalcTests::test_add", "skipped": False},
                                                          {"id": "tests/test_f.py::test_a", "skipped": False}])


class R301RuntimeOutcomes(ReviewBase):
    # patches TestCase.setUp through setattr and a SkipTest looked up by a computed name: nothing a static rule reads
    SKIPPER = ("import unittest\n\n\ndef _setup(self):\n    raise vars(unittest)['Skip' + 'Test']('environment')\n\n\n"
               "setattr(vars(unittest)['Test' + 'Case'], 'setUp', _setup)\n\n\nclass Z(unittest.TestCase):\n    def test_z(self):\n"
               "        self.assertTrue(True)\n")

    def test_a_runtime_skip_of_every_locked_test_fails_the_replay(self):
        repo = self.clone()
        repo.write("tests/test_zz_env.py", self.SKIPPER)
        repo.commit(message("refactor", "T-001", "environment"), "tests/test_zz_env.py")
        code, out = self.check(repo)
        self.assertEqual(code, 0, out)   # the static rules cannot see it
        out = self.failing(repo, "skipped at runtime", "tests/test_calc.py", extra=("--replay",))
        self.assertIn("CalcTests", out)

    def test_the_compliant_history_still_runs_clean(self):
        code, out = self.check(self.clone(), "--replay")
        self.assertEqual(code, 0, out)


class R401RuntimeAtEveryChange(ReviewBase):
    """U03, U04: the locked tests of every task are run at every later commit that changes a test, a test support file or the
    test configuration, whatever its tag or task, and at the head of the range."""

    PATCH = ("import unittest\n\nimport test_calc\n\n\ndef _setup(self):\n    raise vars(unittest)['Skip' + 'Test']('environment')\n\n\n"
             "setattr(test_calc.CalcTests, 'setUp', _setup)\n\n\nclass Z(unittest.TestCase):\n    def test_z(self):\n"
             "        self.assertTrue(True)\n")
    TWO = ("# REQ: REQ-CALC-002\nimport unittest\n\nimport calc\n\n\nclass TwoTests(unittest.TestCase):\n    def test_sub(self):\n"
           "        self.assertEqual(calc.sub(3, 1), 2)\n")

    def test_u03_a_skip_patch_in_an_untagged_commit_fails_the_replay(self):
        repo = self.clone()
        repo.write("tests/test_zz_env.py", self.PATCH)
        repo.commit("chore: helper", "tests/test_zz_env.py")
        sha = repo.head()[:7]
        out = self.failing(repo, "skipped at runtime", "tests/test_calc.py", extra=("--replay",))
        self.assertIn(sha, out)

    def test_u04_a_skip_patch_of_another_tasks_tests_in_a_green_fails_the_replay(self):
        repo = self.clone()
        repo.write("tests/test_two.py", self.TWO)
        code, out = self.lock(repo, "T-002", "tests/test_two.py")
        self.assertEqual(code, 0, out)
        code, out = run_cli("--config", self.cfg, "tdd", "commit", "--repo", repo.root, "--red", "T-002", "-m", "sub", "tests/test_two.py", "--apply")
        self.assertEqual(code, 0, out)
        repo.write("calc.py", "def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n")
        repo.write("tests/test_zz_env.py", self.PATCH)
        repo.commit(message("green", "T-002", "sub"), "calc.py", "tests/test_zz_env.py")
        sha = repo.head()[:7]
        out = self.failing(repo, "skipped at runtime", "tests/test_calc.py", extra=("--replay",))
        self.assertIn(sha, out)

    def test_u07_a_patch_that_changes_no_test_file_is_caught_at_the_head(self):
        repo = self.clone()
        repo.write("calc.py", "import unittest\n\n\ndef _setup(self):\n    raise vars(unittest)['Skip' + 'Test']('x')\n\n\n"
                              "setattr(vars(unittest)['Test' + 'Case'], 'setUp', _setup)\n\n\ndef add(a, b):\n    return a + b\n")
        repo.commit("chore: tidy", "calc.py")
        self.failing(repo, "skipped at runtime", "tests/test_calc.py", extra=("--replay",))

    def test_a_problem_is_named_at_the_first_commit_that_has_it(self):
        repo = self.clone()
        repo.write("tests/test_zz_env.py", self.PATCH)
        repo.commit("chore: helper", "tests/test_zz_env.py")
        first = repo.head()[:7]
        repo.write("README.md", "later\n")
        repo.commit("docs: later", "README.md")
        out = self.failing(repo, "skipped at runtime", extra=("--replay",))
        self.assertIn(first, out)
        self.assertEqual(out.count("test_add is skipped at runtime"), 1)


class R501TheHeadIsTheProjectsOwnRun(ReviewBase):
    """X13: product code must not be able to tell the replay from the project's own run. The head check point runs in the
    repository's own checkout; intermediate points run in worktrees with neutral names and an unchanged environment."""

    SKIP = "raise vars(unittest)['Skip' + 'Test']('environment')"

    def patched_calc(self, condition):
        return (f"import os\nimport unittest\n\n\ndef _setup(self):\n    {self.SKIP}\n\n\nif {condition}:\n"
                f"    setattr(vars(unittest)['Test' + 'Case'], 'setUp', _setup)\n\n\ndef add(a, b):\n    return a + b\n")

    def replay(self, repo, *extra):
        keys = ("BATUTA", "TDD", "REPLAY", "PYTHONDONTWRITEBYTECODE")
        env = {k: v for k, v in os.environ.items() if not any(w in k.upper() for w in keys)}
        with mock.patch.dict(os.environ, env, clear=True):
            return self.check(repo, "--replay", *extra)

    def test_x13_a_patch_that_acts_only_outside_a_replay_worktree_fails_at_the_head(self):
        repo = self.clone()
        repo.write("calc.py", self.patched_calc("'tdd-replay-' not in os.getcwd()"))
        repo.commit("chore: tidy", "calc.py")
        code, out = self.replay(repo)
        self.assertEqual(code, 1, out)
        self.assertIn("skipped at runtime", out)

    def test_a_patch_keyed_on_a_variable_the_replay_used_to_set_fails(self):
        repo = self.clone()
        repo.write("calc.py", self.patched_calc("os.environ.get('PYTHONDONTWRITEBYTECODE') is None"))
        repo.commit("chore: tidy", "calc.py")
        code, out = self.replay(repo)
        self.assertEqual(code, 1, out)
        self.assertIn("skipped at runtime", out)

    def test_a_working_tree_that_differs_from_head_fails_the_head_check(self):
        repo = self.clone()
        repo.write("README.md", "changed but not committed\n")
        code, out = self.replay(repo)
        self.assertEqual(code, 1, out)
        self.assertIn("the working tree differs from HEAD", out)

    def test_an_untracked_file_does_not(self):
        repo = self.clone()
        repo.write("notes.txt", "not tracked\n")
        code, out = self.replay(repo)
        self.assertEqual(code, 0, out)

    def test_a_range_that_ends_before_head_runs_its_end_in_a_worktree_and_ignores_the_dirty_tree(self):
        repo = self.clone()
        repo.write("README.md", "changed but not committed\n")
        code, out = self.replay(repo, "--range", "HEAD~3..HEAD~1")
        self.assertEqual(code, 2, out)   # the warning that the range ends before HEAD (R6-03); no dirty-tree failure
        self.assertNotIn("differs from HEAD", out)

    def test_the_head_runs_in_the_checkout_and_the_others_in_neutral_worktrees(self):
        repo = self.clone()
        log = self.tmp / "probe-log.jsonl"
        log.unlink(missing_ok=True)
        probe = ("import json\nimport os\nimport unittest\n\nLOG = " + repr(str(log)) + "\n\n\n"
                 "def _record():\n    keys = sorted(k for k in os.environ if any(w in k.upper() for w in ('BATUTA', 'TDD', 'REPLAY')))\n"
                 "    with open(LOG, 'a', encoding='utf-8') as handle:\n        handle.write(json.dumps({'cwd': os.getcwd(), 'env': keys}) + '\\n')\n\n\n"
                 "_record()\n\n\nclass P(unittest.TestCase):\n    def test_p(self):\n        self.assertTrue(True)\n")
        repo.write("tests/test_zz_probe.py", probe)
        repo.commit("chore: probe", "tests/test_zz_probe.py")
        repo.write("README.md", "later\n")
        repo.commit("docs: later", "README.md")
        code, out = self.replay(repo)
        self.assertEqual(code, 0, out)
        lines = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines() if x.strip()]
        self.assertGreaterEqual(len(lines), 2, lines)
        self.assertEqual(os.path.realpath(lines[-1]["cwd"]), os.path.realpath(repo.root))
        for line in lines[:-1]:
            below = os.path.relpath(os.path.realpath(line["cwd"]), os.path.realpath(self.temp_root)).lower()
            self.assertFalse(below.startswith(".."), below)
            for word in ("tdd", "replay", "batuta"):
                self.assertNotIn(word, below)
        for line in lines:
            self.assertEqual(line["env"], [])


class R601TheHeadRunIsTheRealRun(ReviewBase):
    """X16 and X16b: the head check and the real run are one process: the configured test command, verbatim, in the checkout, its
    own output read. No wrapper, no recording class, no added argument."""

    SKIP = "raise vars(unittest)['Skip' + 'Test']('environment')"

    def patched_calc(self, condition):
        return (f"import sys\nimport unittest\n\n\ndef _setup(self):\n    {self.SKIP}\n\n\nif {condition}:\n"
                f"    setattr(vars(unittest)['Test' + 'Case'], 'setUp', _setup)\n\n\ndef add(a, b):\n    return a + b\n")

    def replay(self, repo, *extra, cfg=None):
        env = {k: v for k, v in os.environ.items() if not any(w in k.upper() for w in ("BATUTA", "TDD", "REPLAY"))}
        with mock.patch.dict(os.environ, env, clear=True):
            return self.check(repo, "--replay", *extra, cfg=cfg)

    def test_x16_a_patch_keyed_on_argv_zero_of_the_recording_run_fails_at_the_head(self):
        repo = self.clone()
        repo.write("calc.py", self.patched_calc("sys.argv[0] != '-c'"))
        repo.commit("chore: tidy", "calc.py")
        code, out = self.replay(repo)
        self.assertEqual(code, 1, out)
        self.assertIn("skipped at runtime", out)

    def test_x16b_a_patch_keyed_on_the_recording_class_in_main_fails_at_the_head(self):
        repo = self.clone()
        repo.write("calc.py", self.patched_calc("not hasattr(sys.modules['__main__'], 'Rec')"))
        repo.commit("chore: tidy", "calc.py")
        code, out = self.replay(repo)
        self.assertEqual(code, 1, out)
        self.assertIn("skipped at runtime", out)

    def test_a_command_that_reports_no_per_test_outcome_fails_the_head_check(self):
        folder = self.tmp / "quiet"
        folder.mkdir(exist_ok=True)
        cfg = write_config(folder, self.temp_root, test_command='python -m unittest discover -s tests -p "test_*.py"')
        code, out = self.replay(self.clone(), cfg=cfg)
        self.assertEqual(code, 1, out)
        self.assertIn("configure tdd.test_command to report each test", out)

    def test_a_verbose_command_is_run_verbatim_and_passes(self):
        folder = self.tmp / "verbose"
        folder.mkdir(exist_ok=True)
        cfg = write_config(folder, self.temp_root, test_command='python -m unittest discover -s tests -p "test_*.py" -v')
        code, out = self.replay(self.clone(), cfg=cfg)
        self.assertEqual(code, 0, out)

    def test_r603_a_range_that_ends_before_head_warns_naming_both_commits(self):
        repo = self.clone()
        end = repo.git("rev-parse", "HEAD~1").strip()[:7]
        top = repo.head()[:7]
        code, out = self.replay(repo, "--range", "HEAD~3..HEAD~1")
        self.assertEqual(code, 2, out)
        self.assertIn("WARN", out)
        self.assertIn(end, out)
        self.assertIn(top, out)


class R601Parsers(unittest.TestCase):
    def test_every_spelling_of_a_verbose_unittest_outcome_is_read(self):
        text = ("test_a (test_m.C.test_a) ... ok\ntest_b (test_m.C.test_b) ... FAIL\ntest_c (test_m.C.test_c) ... ERROR\n"
                "test_d (test_m.C.test_d) ... skipped 'not on this machine ... really'\ntest_e (test_m.C.test_e) ... expected failure\n"
                "test_f (test_m.C.test_f) ... unexpected success\ntest_g (test_m.C.test_g)\nA docstring line ... ok\n"
                "test_h (test_m.C.test_h) (i=1) ... ok\n\n----------------------------------------------------------------------\nRan 8 tests\n")
        got = {e["id"]: e["outcome"] for e in hist.parse_unittest_verbose(text)}
        self.assertEqual(got, {"test_m.C.test_a": "passed", "test_m.C.test_b": "failed", "test_m.C.test_c": "error",
                               "test_m.C.test_d": "skipped", "test_m.C.test_e": "expected failure",
                               "test_m.C.test_f": "unexpected success", "test_m.C.test_g": "passed", "test_m.C.test_h": "passed"})

    def test_a_pytest_summary_of_rA_is_read(self):
        text = ("=== short test summary info ===\nPASSED tests/test_a.py::test_x[1]\nPASSED tests/test_a.py::T::test_y\n"
                "FAILED tests/test_a.py::test_z - assert 1 == 2\nERROR tests/test_a.py::test_e - boom\n"
                "XFAIL tests/test_a.py::test_x_fail - reason\nXPASS tests/test_a.py::test_x_pass\nSKIPPED tests/test_a.py::test_s - why\n")
        got = {e["id"]: e["outcome"] for e in hist.parse_pytest_summary(text)}
        self.assertEqual(got, {"tests/test_a.py::test_x[1]": "passed", "tests/test_a.py::T::test_y": "passed",
                               "tests/test_a.py::test_z": "failed", "tests/test_a.py::test_e": "error",
                               "tests/test_a.py::test_x_fail": "expected failure", "tests/test_a.py::test_x_pass": "unexpected success",
                               "tests/test_a.py::test_s": "skipped"})

    def test_a_junit_report_the_command_writes_is_read_from_the_path_it_was_given(self):
        import tempfile
        xml = '<testsuites><testsuite tests="1"><testcase classname="tests.test_a" name="test_x"/></testsuite></testsuites>'
        for flag in (["--junitxml=report.xml"], ["--junitxml", "report.xml"]):
            with self.subTest(flag=flag), tempfile.TemporaryDirectory() as folder:
                (Path(folder) / "report.xml").write_text(xml, encoding="utf-8")
                argv, parse = hist.head_run("pytest -q " + " ".join(flag), False, folder)
                self.assertEqual(argv[1:], ["-q"] + flag)
                self.assertEqual(parse("")[0]["outcome"], "passed")

    def test_the_command_is_run_verbatim(self):
        argv, _ = hist.head_run('python -m unittest discover -s tests -p "test_*.py" -v', False, ".")
        self.assertEqual(argv[1:], ["-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py", "-v"])
        argv, _ = hist.head_run("pytest -rA tests", False, ".")
        self.assertEqual(argv[1:], ["-rA", "tests"])

    def test_the_default_command_reports_each_test(self):
        argv, parse = hist.head_run(hist.DEFAULT_TEST_COMMAND, False, ".")
        self.assertIn("-v", argv)
        self.assertEqual(argv[1:4], ["-m", "unittest", "discover"])
        argv, _ = hist.head_run(hist.DEFAULT_TEST_COMMAND, True, ".")
        self.assertEqual(argv[-2:], ["-t", "."])

    def test_a_command_that_reports_no_per_test_outcome_is_refused(self):
        for command in ('python -m unittest discover -s tests', "pytest", "pytest -q tests", "make test", "python -m unittest {tests}",
                        "python -m unittest discover -v {tests}"):
            with self.subTest(command=command):
                with self.assertRaises(ValueError) as caught:
                    hist.head_run(command, False, ".")
                self.assertIn("configure tdd.test_command to report each test", str(caught.exception))


class R701Forgery(ReviewBase):
    """X19, X20, X20b, X22: a run cannot be forged from inside: result lines must be exactly one ok line per locked test and match
    the runner's own summary, and code that patches the runner, replaces stdout or stderr or reads its parent is found by a static
    scan of every Python file."""

    HIDDEN_SKIP = ("import unittest\n\n\ndef _setup(self):\n    raise vars(unittest)['Skip' + 'Test']('environment')\n\n\n"
                   "setattr(vars(unittest)['Test' + 'Case'], 'setUp', _setup)\n\n\ndef add(a, b):\n    return a + b\n")
    FAKE = ("test_add (test_calc.CalcTests.test_add) ... ok\\n"
            "test_add_negative (test_calc.CalcTests.test_add_negative) ... ok\\n")

    def replay(self, repo, *extra, cfg=None):
        env = {k: v for k, v in os.environ.items() if not any(w in k.upper() for w in ("BATUTA", "TDD", "REPLAY"))}
        with mock.patch.dict(os.environ, env, clear=True):
            return self.check(repo, "--replay", *extra, cfg=cfg)

    def forged(self, repo, stream):
        repo.write("calc.py", self.HIDDEN_SKIP)
        repo.write("tests/test_zz_fake.py", f"import sys\nimport unittest\n\nsys.{stream}.write(\"{self.FAKE}\")\n\n\n"
                                            "class F(unittest.TestCase):\n    def test_f(self):\n        self.assertTrue(True)\n")
        repo.commit("chore: tidy", "calc.py", "tests/test_zz_fake.py")

    def test_x20_fake_ok_lines_on_stderr_fail(self):
        repo = self.clone()
        self.forged(repo, "stderr")
        code, out = self.replay(repo)
        self.assertEqual(code, 1, out)
        self.assertRegex(out, r"result lines|skipped at runtime|more than once")

    def test_x20b_fake_ok_lines_on_stdout_fail(self):
        repo = self.clone()
        self.forged(repo, "stdout")
        code, out = self.replay(repo)
        self.assertEqual(code, 1, out)
        self.assertRegex(out, r"result lines|skipped at runtime|more than once")

    def test_x22_a_stderr_wrapper_that_rewrites_skipped_to_ok_fails(self):
        repo = self.clone()
        repo.write("calc.py", self.HIDDEN_SKIP)
        repo.write("tests/test_zz_wrap.py", "import sys\nimport unittest\n\n\nclass W:\n    def __init__(self, inner):\n        self.inner = inner\n\n"
                                            "    def write(self, text):\n        return self.inner.write(text.replace(' ... skipped', ' ... ok'))\n\n"
                                            "    def flush(self):\n        self.inner.flush()\n\n    def __getattr__(self, name):\n"
                                            "        return getattr(self.inner, name)\n\n\nsys.stderr = W(sys.stderr)\n\n\n"
                                            "class F(unittest.TestCase):\n    def test_f(self):\n        self.assertTrue(True)\n")
        repo.commit("chore: tidy", "calc.py", "tests/test_zz_wrap.py")
        code, out = self.replay(repo)
        self.assertEqual(code, 1, out)
        self.assertRegex(out, r"sys\.stderr|skipped=")

    def test_x19_a_read_of_the_parent_process_is_introduced_and_fails(self):
        repo = self.clone()
        repo.write("calc.py", "import os\n\nPARENT = os.getppid()\n\n\ndef add(a, b):\n    return a + b\n")
        repo.commit("chore: tidy", "calc.py")
        code, out = self.check(repo)
        self.assertEqual(code, 1, out)
        self.assertIn("os.getppid", out)
        self.assertIn("calc.py", out)

    def test_an_approved_request_naming_the_file_lets_it_through(self):
        repo = self.clone()
        commit_request_open_first(repo, requests(path="calc.py"))
        repo.write("specs/calc/spec.md", SPEC)
        repo.commit("docs: spec", "specs/calc/spec.md")
        repo.write("calc.py", "import os\n\nPARENT = os.getppid()\n\n\ndef add(a, b):\n    return a + b\n")
        repo.commit(message("refactor", "T-001", "read the parent", "CR-001"), "calc.py")
        code, out = self.check(repo)
        self.assertEqual(code, 0, out)

    def test_a_construct_that_was_already_there_at_the_base_is_a_warning(self):
        repo = self.fresh("forgery-at-base")
        repo.write("README.md", "x\n")
        repo.write("calc.py", "import os\n\nPARENT = os.getppid()\n")
        repo.commit("init", "README.md", "calc.py")
        code, out = self.check(repo)
        self.assertEqual(code, 2, out)
        self.assertIn("already holds", out)
        self.assertNotIn("FAIL", out)

    def test_a_clean_file_is_not_a_finding(self):
        repo = self.clone()
        repo.write("calc.py", "import sys\n\n\ndef add(a, b):\n    print(sys.argv)\n    return a + b\n")
        repo.commit("chore: tidy", "calc.py")
        code, out = self.check(repo)
        self.assertEqual(code, 0, out)


class R701Parsers(unittest.TestCase):
    def head(self):
        return hist.head_run('python -m unittest discover -s tests -p "test_*.py" -v', False, ".")[1]

    GOOD = ("test_a (test_m.C.test_a) ... ok\ntest_b (test_m.C.test_b) ... ok\n\n"
            "----------------------------------------------------------------------\nRan 2 tests in 0.001s\n\nOK\n")

    def test_a_consistent_run_is_read(self):
        self.assertEqual(len(self.head()(self.GOOD)), 2)

    def test_more_result_lines_than_the_runner_ran_are_refused(self):
        forged = "test_a (test_m.C.test_a) ... ok\n" + self.GOOD
        with self.assertRaises(ValueError) as caught:
            self.head()(forged)
        self.assertIn("result lines", str(caught.exception))

    def test_a_summary_that_counts_what_no_line_shows_is_refused(self):
        skipped = self.GOOD.replace("\nOK\n", "\nOK (skipped=1)\n")
        with self.assertRaises(ValueError) as caught:
            self.head()(skipped)
        self.assertIn("skipped", str(caught.exception))
        failed = self.GOOD.replace("\nOK\n", "\nFAILED (failures=1)\n")
        with self.assertRaises(ValueError):
            self.head()(failed)

    def test_a_run_of_no_tests_is_an_empty_list_not_a_forgery(self):
        empty = "\n----------------------------------------------------------------------\nRan 0 tests in 0.000s\n\nNO TESTS RAN\n"
        self.assertEqual(self.head()(empty), [])
        lines_without_tests = "test_a (test_m.C.test_a) ... ok\n" + empty
        with self.assertRaises(ValueError):
            self.head()(lines_without_tests)

    def test_a_missing_summary_is_refused(self):
        with self.assertRaises(ValueError):
            self.head()("test_a (test_m.C.test_a) ... ok\n")

    def test_a_skip_line_is_read_and_matches_its_tally(self):
        text = ("test_a (test_m.C.test_a) ... skipped 'x'\ntest_b (test_m.C.test_b) ... ok\n\n"
                "----------------------------------------------------------------------\nRan 2 tests in 0.001s\n\nOK (skipped=1)\n")
        got = {e["id"]: e["outcome"] for e in self.head()(text)}
        self.assertEqual(got["test_m.C.test_a"], "skipped")

    def test_a_junit_report_whose_count_differs_from_its_cases_is_refused(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "r.xml").write_text('<testsuites><testsuite tests="3"><testcase classname="t.a" name="test_x"/></testsuite></testsuites>',
                                                encoding="utf-8")
            parse = hist.head_run("pytest --junitxml=r.xml", False, folder)[1]
            with self.assertRaises(ValueError) as caught:
                parse("")
            self.assertIn("result", str(caught.exception))

    def test_a_pytest_summary_whose_counts_differ_from_its_lines_is_refused(self):
        parse = hist.head_run("pytest -rA", False, ".")[1]
        text = "=== short test summary info ===\nPASSED tests/test_a.py::test_x\n=== 2 passed in 0.1s ===\n"
        with self.assertRaises(ValueError):
            parse(text)
        self.assertEqual(len(parse("=== short test summary info ===\nPASSED tests/test_a.py::test_x\n=== 1 passed in 0.1s ===\n")), 1)

    def test_duplicates_and_every_skip_form_are_problems_for_a_locked_test(self):
        base = [("C", "test_a")]
        dup = [{"id": "test_m.C.test_a", "outcome": "passed"}, {"id": "test_m.C.test_a", "outcome": "passed"}]
        self.assertEqual(len(hist.compare_listing("tests/test_m.py", base, dup)), 1)
        for outcome in ("skipped", "expected failure", "unexpected success"):
            with self.subTest(outcome=outcome):
                mixed = [{"id": "test_m.C.test_a", "outcome": "passed"}, {"id": "test_m.C.test_a", "outcome": outcome}]
                self.assertTrue(hist.compare_listing("tests/test_m.py", base, mixed))
                self.assertTrue(hist.compare_listing("tests/test_m.py", base, mixed[1:]))
        self.assertEqual(hist.compare_listing("tests/test_m.py", base, dup[:1]), [])

    def test_a_parametrized_case_that_is_skipped_is_a_problem_but_several_passing_cases_are_not(self):
        ok = [{"id": "tests/test_p.py::test_x[1]", "outcome": "passed"}, {"id": "tests/test_p.py::test_x[2]", "outcome": "passed"}]
        self.assertEqual(hist.compare_listing("tests/test_p.py", [(None, "test_x")], ok), [])
        bad = ok[:1] + [{"id": "tests/test_p.py::test_x[2]", "outcome": "skipped"}]
        self.assertEqual(len(hist.compare_listing("tests/test_p.py", [(None, "test_x")], bad)), 1)


class R302ApprovedMoves(ReviewBase):
    def approve(self, repo):
        commit_request_open_first(repo, requests())
        repo.write("specs/calc/spec.md", SPEC)
        repo.commit("docs: spec", "specs/calc/spec.md")

    def test_an_approved_rename_does_not_fail_the_replay(self):
        repo = self.clone()
        self.approve(repo)
        repo.git("mv", "tests/test_calc.py", "tests/test_calc_renamed.py")
        code, out = self.lock(repo, "T-001", "tests/test_calc_renamed.py")
        self.assertEqual(code, 0, out)
        repo.commit(message("refactor", "T-001", "rename the test", "CR-001"), "tests/test_calc.py", "tests/test_calc_renamed.py", LOCK)
        code, out = self.check(repo, "--replay")
        self.assertEqual(code, 0, out)

    def test_an_approved_deletion_does_not_fail_the_replay(self):
        repo = self.clone()
        self.approve(repo)
        repo.git("rm", "-q", "tests/test_calc.py")
        repo.commit(message("refactor", "T-001", "drop the test", "CR-001"), "tests/test_calc.py")
        code, out = self.check(repo, "--replay")
        self.assertEqual(code, 0, out)


class Q3TestConfiguration(ReviewBase):
    def test_a_refactor_that_adds_a_conftest_needs_an_approved_request(self):
        repo = self.clone()
        repo.write("tests/conftest.py", "import pytest\n")
        repo.commit(message("refactor", "T-001", "conftest"), "tests/conftest.py")
        self.failing(repo, "test configuration", "tests/conftest.py")

    def test_a_green_that_adds_runner_settings_needs_an_approved_request(self):
        repo = self.clone()
        repo.write("pytest.ini", "[pytest]\nminversion = 6\n")
        repo.commit(message("green", "T-001", "settings"), "pytest.ini")
        self.failing(repo, "test configuration", "pytest.ini")

    def test_an_unrelated_pyproject_change_is_not_test_configuration(self):
        repo = self.clone()
        repo.write("pyproject.toml", '[project]\nname = "calc"\n')
        repo.commit(message("refactor", "T-001", "project metadata"), "pyproject.toml")
        code, out = self.check(repo)
        self.assertEqual(code, 0, out)

    def test_a_pytest_section_of_pyproject_is_test_configuration(self):
        repo = self.clone()
        repo.write("pyproject.toml", '[tool.pytest.ini_options]\naddopts = "-q"\n')
        repo.commit(message("refactor", "T-001", "pytest options"), "pyproject.toml")
        self.failing(repo, "test configuration", "pyproject.toml")


class C01Version11TddBlock(ReviewBase):
    """C01 1.1 closes the `tdd` block: test_command, replay_timeout_seconds (integer, at least 1), lock_file (a .json that is not
    batuta.json) and markers (an array of names replacing the default list). Each key is honoured, and a bad value is refused."""

    def config11(self, name, **tdd):
        folder = self.tmp / name
        folder.mkdir(exist_ok=True)
        cfg = config.default_config({})
        cfg["contract_version"] = "1.1"
        cfg["roots"] = {"temp": str(self.temp_root), "data": str(folder / "data"), "worktrees": str(folder / "wt")}
        cfg["tdd"] = tdd
        path = folder / "batuta.json"
        path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        return path

    def red_repo(self, name, test_text, cfg):
        repo = self.fresh(name)
        repo.write("README.md", "x\n")
        repo.commit("init", "README.md")
        repo.write("tests/test_calc.py", test_text)
        code, out = self.lock(repo, "T-001", "tests/test_calc.py", cfg=cfg)
        self.assertEqual(code, 0, out)
        code, out = run_cli("--config", cfg, "tdd", "commit", "--repo", repo.root, "--red", "T-001", "-m", "calc", "tests/test_calc.py", "--apply")
        self.assertEqual(code, 0, out)
        return repo

    PASSING = "# REQ: REQ-CALC-001\nimport unittest\n\n\nclass P(unittest.TestCase):\n    def test_p(self):\n        self.assertEqual(1, 1)\n"

    def test_test_command_is_honoured(self):
        cfg = self.config11("k-command", test_command='python -c "import sys; sys.exit(1)" {tests}')
        repo = self.red_repo("k-command", self.PASSING, cfg)
        code, out = self.check(repo, "--replay", cfg=cfg)
        self.assertIn("fails at the red commit", out)   # the default discovery would find these tests passing
        self.assertNotIn("pass at the red commit", out)

    def test_replay_timeout_seconds_is_honoured(self):
        slow = "# REQ: REQ-CALC-001\nimport time\nimport unittest\n\n\nclass S(unittest.TestCase):\n    def test_s(self):\n        time.sleep(30)\n        self.assertEqual(1, 2)\n"
        cfg = self.config11("k-timeout", replay_timeout_seconds=1)
        repo = self.red_repo("k-timeout", slow, cfg)
        code, out = self.check(repo, "--replay", cfg=cfg)
        self.assertEqual(code, 1, out)
        self.assertIn("timed out after 1 s", out)

    def test_lock_file_is_honoured(self):
        cfg = self.config11("k-lock", lock_file=".batuta/custom-locks.json")
        repo = self.red_repo("k-lock", self.PASSING, cfg)
        self.assertTrue((repo.root / ".batuta" / "custom-locks.json").is_file())
        self.assertFalse((repo.root / ".batuta" / "test-locks.json").exists())
        repo.write("tests/test_calc.py", self.PASSING + "\n# edited\n")
        repo.commit(message("refactor", "T-001", "edit a locked test"), "tests/test_calc.py")
        code, out = self.check(repo, cfg=cfg)
        self.assertEqual(code, 1, out)
        self.assertIn("touches locked test", out)

    def test_markers_extend_the_default_list_for_every_language(self):
        cfg = self.config11("k-markers", markers=["wip"])
        repo = self.red_repo("k-markers", self.PASSING, cfg)
        repo.write("tests/test_extra.py", "import unittest\n\n\n" "@wip\nclass E(unittest.TestCase):\n    def test_a(self):\n        self.assertTrue(True)\n")
        repo.commit(message("refactor", "T-001", "extra"), "tests/test_extra.py")
        code, out = self.check(repo, cfg=cfg)
        self.assertEqual(code, 1, out)
        self.assertIn("'wip'", out)
        repo.write("tests/test_other.py", "import unittest\n\n\n" "@unittest.skip('x')\nclass O(unittest.TestCase):\n    def test_a(self):\n        self.assertTrue(True)\n")
        repo.commit(message("refactor", "T-001", "other"), "tests/test_other.py")
        code, out = self.check(repo, cfg=cfg)
        self.assertIn("unittest.skip", out)   # a configured name adds to the defaults, it never removes one
        repo.write("web/a.test.js", "it.only('a', () => { expect(1).toBe(1); });\n")
        repo.commit(message("refactor", "T-001", "web"), "web/a.test.js")
        code, out = self.check(repo, cfg=cfg)
        self.assertIn("it.only", out)

    def test_every_key_together(self):
        cfg = self.config11("k-all", test_command='python -c "import sys; sys.exit(1)" {tests}', replay_timeout_seconds=60,
                            lock_file=".batuta/all-locks.json", markers=["wip"])
        repo = self.red_repo("k-all", self.PASSING, cfg)
        code, out = self.check(repo, "--replay", cfg=cfg)
        self.assertIn("fails at the red commit", out)
        self.assertTrue((repo.root / ".batuta" / "all-locks.json").is_file())

    def test_a_bad_value_is_refused_in_a_1_1_document(self):
        bad = {"markers-as-an-object": {"markers": {"python": ["wip"]}}, "lock-file-is-the-config": {"lock_file": ".batuta/batuta.json"},
               "lock-file-not-json": {"lock_file": ".batuta/locks.txt"}, "timeout-zero": {"replay_timeout_seconds": 0},
               "timeout-fraction": {"replay_timeout_seconds": 1.5}, "unknown-key": {"retries": 3},
               "lock-file-escapes": {"lock_file": "../locks.json"}}
        repo = self.clone()
        for name, block in bad.items():
            with self.subTest(case=name):
                cfg = self.config11("bad-" + name, **block)
                code, out = self.check(repo, cfg=cfg)
                self.assertEqual(code, 1, out)
                self.assertIn("tdd", out)

    def test_the_legacy_object_shape_of_markers_is_accepted_in_a_1_0_document(self):
        folder = self.tmp / "old-shape"
        folder.mkdir(exist_ok=True)
        cfg = write_config(folder, self.temp_root, markers={"python": ["wip"]})
        repo = self.clone()
        repo.write("tests/test_extra.py", "import unittest\n\n\n" "@wip\nclass E(unittest.TestCase):\n    def test_a(self):\n        self.assertTrue(True)\n")
        repo.commit(message("refactor", "T-001", "extra"), "tests/test_extra.py")
        code, out = self.check(repo, cfg=cfg)
        self.assertEqual(code, 1, out)
        self.assertIn("'wip'", out)
        self.assertNotIn("does not satisfy", out)

    def test_a_bad_legacy_object_is_refused_in_a_1_0_document(self):
        repo = self.clone()
        for name, markers in {"language-unknown": {"cobol": ["x"]}, "not-a-list": {"python": "wip"}, "empty-name": {"python": [""]}}.items():
            with self.subTest(case=name):
                folder = self.tmp / ("legacy-" + name)
                folder.mkdir(exist_ok=True)
                cfg = write_config(folder, self.temp_root, markers=markers)
                code, out = self.check(repo, cfg=cfg)
                self.assertEqual(code, 1, out)
                self.assertIn("markers", out)


if __name__ == "__main__":
    unittest.main()

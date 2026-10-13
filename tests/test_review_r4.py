"""The reproductions of the third review's findings R3-01 to R3-12 (contracts, U0 revision 4).

Each test is the review's reproduction turned into an assertion: it failed on the tree before the revision (c41b967) and
passes after it. Test names start with the finding id (`R301` is R3-01) so the re-check table can name them.
R3-08 (the plan row) is coordination text and has no test here; R3-10 has the offline half (the recorded row is a valid
C22 catalog) and a live half behind `BATUTA_CAOS_TOOLS`.
"""
import ast
import copy
import json
import os
import pathlib
import re
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins" / "batuta" / "scripts"))

from batuta_lib import config, contract  # noqa: E402
from batuta_lib.areas import contract as area  # noqa: E402

CONTRACTS = ROOT / "plugins" / "batuta" / "contracts"
FX = CONTRACTS / "fixtures"
README = (CONTRACTS / "README.md").read_text(encoding="utf-8")
CAOS_TOOLS = os.environ.get("BATUTA_CAOS_TOOLS")


def sp(cid):
    found = sorted(CONTRACTS.glob(f"{cid}-*.schema.json"))
    return found[0] if found else None


def read(cid, name):
    return (FX / cid / name).read_text(encoding="utf-8")


def check_text(cid, text, ext=None, name=None):
    if ext is None:
        ext = ".txt" if cid == "C32" else ".md" if list(CONTRACTS.glob(f"{cid}-*.sections.json")) else ".json"
    with tempfile.TemporaryDirectory() as d:
        p = pathlib.Path(d) / (name or f"artifact{ext}")
        p.write_text(text, encoding="utf-8", newline="")
        return contract.validate_file(p, sp(cid), cid)


def check_doc(cid, doc, name=None):
    return check_text(cid, json.dumps(doc), name=name)


def mentions(errs, *words):
    return any(all(w.lower() in e.lower() for w in words) for e in errs)


def fixture_doc(cid, name):
    doc = json.loads(read(cid, name))
    for k in contract.FIXTURE_KEYS:
        doc.pop(k, None)
    return doc


# ------------------------------------------------------------------ R3-01: environment variable names are never expanded

SECRET = "sk-PLANTED-not-a-real-secret-123"


def provider_config(d, **provider):
    doc = config.default_config({"BATUTA_HOME": str(d)})
    doc["dispatch"] = {"default_lane": "subagent", "lanes": ["subagent"],
                       "providers": {"openai": {"kind": "openai-compatible", **provider}}}
    return doc


def write(d, doc):
    p = pathlib.Path(d) / "batuta.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


def load_error(doc_for, env):
    with tempfile.TemporaryDirectory() as d:
        p = write(d, doc_for(d))
        try:
            config.load(config_arg=str(p), env={"BATUTA_HOME": d, **env})
        except config.ConfigError as exc:
            return str(exc)
    return None


class R301(unittest.TestCase):
    def test_R301_a_dollar_name_in_credential_env_is_refused_and_the_value_never_printed(self):
        msg = load_error(lambda d: provider_config(d, credential_env="$OPENAI_API_KEY"), {"OPENAI_API_KEY": SECRET})
        self.assertIsNotNone(msg, "the loader accepted $OPENAI_API_KEY as an environment variable name")
        self.assertNotIn(SECRET, msg)
        self.assertIn("$OPENAI_API_KEY", msg)   # the value as written
        self.assertIn("credential_env", msg)

    def test_R301_a_name_shaped_secret_behind_a_variable_is_not_loaded_as_the_name(self):
        msg = load_error(lambda d: provider_config(d, credential_env="${TOKEN}"), {"TOKEN": "ABCDEF123SECRET"})
        self.assertIsNotNone(msg, "${TOKEN} loaded as an environment variable name")
        self.assertNotIn("ABCDEF123SECRET", msg)
        self.assertIn("${TOKEN}", msg)

    def test_R301_endpoint_env_is_a_name_too(self):
        msg = load_error(lambda d: provider_config(d, credential_env="OPENAI_API_KEY", endpoint_env="$EP"), {"EP": "HTTPS_HOST"})
        self.assertIsNotNone(msg)
        self.assertNotIn("HTTPS_HOST", msg)
        self.assertIn("endpoint_env", msg)

    def test_R301_the_loaded_names_are_exactly_as_written(self):
        with tempfile.TemporaryDirectory() as d:
            p = write(d, provider_config(d, credential_env="OPENAI_API_KEY", endpoint_env="OPENAI_BASE_URL"))
            r = config.load(config_arg=str(p), env={"BATUTA_HOME": d, "OPENAI_API_KEY": SECRET})
            prov = r.config["dispatch"]["providers"]["openai"]
            self.assertEqual((prov["credential_env"], prov["endpoint_env"]), ("OPENAI_API_KEY", "OPENAI_BASE_URL"))
            self.assertNotIn(SECRET, json.dumps(r.config))

    def test_R301_no_error_names_an_environment_value_in_any_field(self):
        planted = "../" + SECRET

        def doc_for(d):
            doc = provider_config(d, credential_env="$S")                  # a nested provider block
            doc["coordination_root"] = "$S"                                # a path field that expands to a refused path
            doc["knowledge_manifest"] = "${S}/m.json"                      # a second path field
            doc["gates"]["adversary_model_routine"] = "$S"                 # an enum field
            doc["dispatch"]["providers"]["openai"]["kind"] = "$S"          # an enum inside the nested block
            return doc

        msg = load_error(doc_for, {"S": planted})
        self.assertIsNotNone(msg)
        self.assertNotIn(SECRET, msg)
        for written in ("coordination_root", "knowledge_manifest", "adversary_model_routine", "credential_env", "kind"):
            self.assertIn(written, msg)
        self.assertIn("'$S'", msg)   # values are quoted as written

    def test_R301_a_semantic_message_does_not_carry_the_expanded_value(self):
        def doc_for(d):
            doc = provider_config(d, credential_env="OPENAI_API_KEY")
            doc["dispatch"]["default_lane"] = "$LANE"
            return doc
        msg = load_error(doc_for, {"LANE": "provider:other"})
        self.assertIsNotNone(msg)
        self.assertNotIn("provider:other", msg)

    def test_R301_other_fields_still_expand(self):
        with tempfile.TemporaryDirectory() as d:
            doc = provider_config(d, credential_env="OPENAI_API_KEY")
            doc["coordination_root"] = "$SUB/coord"
            r = config.load(config_arg=str(write(d, doc)), env={"BATUTA_HOME": d, "SUB": "work"})
            self.assertEqual(r.config["coordination_root"], "work/coord")

    def test_R301_the_readme_says_names_are_not_expanded(self):
        text = README.lower()
        self.assertRegex(text, r"never expand")
        self.assertIn("as written", text)


# ------------------------------------------------------------------ R3-02 and R3-06: the ledger, decision 14

MANDATORY = "| ID | Agent | Model | Brief | Report | Status | Accepted |"
ROW = "| a-2026-10-12 | implementer | sonnet | {brief} | wip/p/a-2026-10-12.md | {status} | {acc} |"


def table(header, cells):
    cols = [c.strip() for c in header.strip("|").split("|")]
    return "# Delegation ledger: p\n\n" + header + "\n|" + "---|" * len(cols) + "\n| " + " | ".join(cells) + " |\n"


def ledger(brief="wip/p/delegation/a-2026-10-12.brief.md", status="complete", acc="no", report="wip/p/a-2026-10-12.md"):
    return table(MANDATORY, ["a-2026-10-12", "implementer", "sonnet", brief, report, status, acc])


class R302(unittest.TestCase):
    def test_R302_a_ledger_with_the_seven_columns_only_is_valid(self):
        self.assertEqual(check_text("C04", ledger()), [])

    def test_R302_notes_after_the_dispatch_columns(self):
        header = MANDATORY + " Provider | Tokens in | Tokens out | Cost USD | Notes |"
        text = table(header, ["a-1", "implementer", "sonnet", "wip/p/b.md", "wip/p/r.md", "complete", "yes", "anthropic", "10", "5", "0.1",
                              "accepted after verification: D5 completed by the parent"])
        self.assertEqual(check_text("C04", text), [])

    def test_R302_notes_before_the_dispatch_columns(self):
        header = MANDATORY + " Notes | Provider | Tokens in | Tokens out | Cost USD |"
        text = table(header, ["a-1", "implementer", "sonnet", "wip/p/b.md", "wip/p/r.md", "complete", "yes", "check_report COMPLETE", "anthropic", "10", "5", "0.1"])
        self.assertEqual(check_text("C04", text), [])

    def test_R302_notes_alone_after_the_mandatory_columns(self):
        text = table(MANDATORY + " Notes |", ["a-1", "implementer", "sonnet", "wip/p/b.md", "wip/p/r.md", "complete", "yes", "diff re-read 2026-10-11"])
        self.assertEqual(check_text("C04", text), [])

    def test_R302_the_free_text_belongs_in_notes_never_in_status(self):
        self.assertTrue(mentions(check_text("C04", ledger(status="complete, check_report COMPLETE and diff re-read")), "status"))
        self.assertTrue(mentions(check_text("C04", ledger(status="abandoned 2026-10-11: stopped before writing")), "status"))

    def test_R302_accepted_aliases_in_any_case(self):
        for alias in ("yes", "no", "y", "n", "Y", "N", "Yes", "NO", "YES", "nO"):
            with self.subTest(alias):
                self.assertEqual(check_text("C04", ledger(acc=alias)), [])

    def test_R302_accepted_maybe_is_refused(self):
        for bad in ("maybe", "yes, PARTIAL (open rows in backlog)", "yess", ""):
            with self.subTest(bad):
                self.assertTrue(mentions(check_text("C04", ledger(acc=bad)), "accepted"))

    def test_R302_status_accepted_needs_a_yes_alias_not_a_no_alias(self):
        for yes in ("y", "Y", "yes", "YES"):
            self.assertEqual(check_text("C04", ledger(status="accepted", acc=yes)), [])
        for no in ("n", "N", "no", "No"):
            with self.subTest(no):
                self.assertTrue(mentions(check_text("C04", ledger(status="accepted", acc=no)), "accepted"))

    def test_R302_the_fixtures_for_the_new_rules_exist(self):
        for name in ("valid-notes-column-after-the-dispatch-columns.md", "valid-notes-column-before-the-dispatch-columns.md",
                     "valid-accepted-aliases-in-any-case.md", "invalid-accepted-is-maybe.md",
                     "invalid-status-holds-free-text.md"):
            with self.subTest(name):
                self.assertTrue((FX / "C04" / name).is_file(), name)


class R306(unittest.TestCase):
    def test_R306_the_seven_columns_come_first_and_in_order(self):
        swapped = "| ID | Agent | Model | Brief | Report | Accepted | Status |"
        text = table(swapped, ["a-1", "implementer", "sonnet", "wip/p/b.md", "wip/p/r.md", "yes", "complete"])
        self.assertTrue(check_text("C04", text))
        notes_first = "| Notes | ID | Agent | Model | Brief | Report | Status | Accepted |"
        text = table(notes_first, ["x", "a-1", "implementer", "sonnet", "wip/p/b.md", "wip/p/r.md", "complete", "yes"])
        self.assertTrue(check_text("C04", text))
        provider_first = "| ID | Agent | Model | Brief | Report | Status | Provider | Accepted |"
        self.assertTrue(check_text("C04", table(provider_first, ["a-1", "implementer", "sonnet", "wip/p/b.md", "wip/p/r.md", "complete", "-", "no"])))

    def test_R306_a_swapped_ledger_is_refused_with_the_column_order(self):
        swapped = "| ID | Agent | Model | Brief | Report | Accepted | Status |"
        errs = check_text("C04", table(swapped, ["a-1", "implementer", "sonnet", "wip/p/b.md", "wip/p/r.md", "yes", "complete"]))
        self.assertTrue(mentions(errs, "ledger"), errs)

    def test_R306_brief_and_report_are_relative_paths(self):
        for bad in ("C:/x/b.md", "/x/b.md", "../b.md", "wip/../b.md", "./b.md", "wip\\b.md"):
            with self.subTest(brief=bad):
                self.assertTrue(mentions(check_text("C04", ledger(brief=bad)), "brief"))
            with self.subTest(report=bad):
                self.assertTrue(mentions(check_text("C04", ledger(report=bad)), "report"))

    def test_R306_the_path_pattern_is_the_shared_one_and_linted(self):
        row = json.loads(sp("C04").read_text(encoding="utf-8"))["$defs"]["ledger_row"]["properties"]
        self.assertEqual(row["Brief"]["pattern"], contract.REL_PATH_PATTERN)
        self.assertEqual(row["Report"]["pattern"], contract.REL_PATH_PATTERN)
        items = []
        area._lint_consistency({c: contract.load_schema(sp(c)) for c in ("C01", "C04", "C07", "C28", "C30")}, items)
        self.assertTrue(any(i["tag"] == "OK" and "relative path" in i["message"] and "C04" in i["message"] for i in items), items)

    def test_R306_the_fixtures_for_the_new_rules_exist(self):
        for name in ("invalid-columns-are-swapped.md", "invalid-brief-path-is-absolute.md", "invalid-brief-path-has-a-drive.md",
                     "invalid-brief-path-traverses-up.md", "invalid-report-path-is-absolute.md"):
            with self.subTest(name):
                self.assertTrue((FX / "C04" / name).is_file(), name)


# ------------------------------------------------------------------ R3-03: the typed approval phrase, decision 16

class R303(unittest.TestCase):
    def doc(self, excerpt):
        d = fixture_doc("C06", "valid-full.json")
        d["prompt_excerpt"] = excerpt
        return d

    def test_R303_every_valid_fixture_records_the_phrase(self):
        for p in sorted((FX / "C06").glob("valid-*.json")):
            with self.subTest(p.name):
                d = json.loads(p.read_text(encoding="utf-8"))
                self.assertIn(f"approve {d['spec_id']} {d['approved_spec_sha256_prefix']}".lower(), d["prompt_excerpt"].lower())

    def test_R303_an_excerpt_without_the_phrase_is_refused(self):
        for bad in ("approve spec 001", "ok", "approved", "approve 001-example", "approve aaaaaaaaaaaa", "approve  "):
            with self.subTest(bad):
                self.assertTrue(mentions(check_doc("C06", self.doc(bad)), "prompt_excerpt"))

    def test_R303_the_phrase_alone_and_inside_a_longer_prompt(self):
        for ok in ("approve 001-example aaaaaaaaaaaa", "looks good, approve 001-example aaaaaaaaaaaa now", "x\napprove 001-example aaaaaaaaaaaa\ny"):
            with self.subTest(ok):
                self.assertEqual(check_doc("C06", self.doc(ok)), [])

    def test_R303_the_keyword_and_the_hex_match_case_insensitively(self):
        for ok in ("APPROVE 001-example AAAAAAAAAAAA", "Approve 001-example aAaAaAaAaAaA"):
            with self.subTest(ok):
                d = self.doc(ok)
                self.assertEqual(d["approved_spec_sha256_prefix"], "aaaaaaaaaaaa")   # the stored prefix stays lower case
                self.assertEqual(check_doc("C06", d), [])

    def test_R303_the_spec_id_matches_exactly(self):
        for bad in ("approve 001-EXAMPLE aaaaaaaaaaaa", "approve 002-example aaaaaaaaaaaa", "approve 001-example-2 aaaaaaaaaaaa"):
            with self.subTest(bad):
                self.assertTrue(mentions(check_doc("C06", self.doc(bad)), "prompt_excerpt"))

    def test_R303_another_prefix_is_refused(self):
        d = fixture_doc("C06", "valid-full.json")
        d["spec_sha256"] = "ab12cd34ef56" + "0" * 52
        d["approved_spec_sha256_prefix"] = "ab12cd34ef56"
        d["prompt_excerpt"] = "approve 001-example aaaaaaaaaaaa"
        self.assertTrue(mentions(check_doc("C06", d), "prompt_excerpt"))
        d["prompt_excerpt"] = "approve 001-example AB12CD34EF56"
        self.assertEqual(check_doc("C06", d), [])

    def test_R303_the_phrase_is_a_whole_phrase_not_a_substring_of_a_longer_token(self):
        for bad in ("xapprove 001-example aaaaaaaaaaaa", "approve 001-example aaaaaaaaaaaab", "approve 001-example aaaaaaaaaaaa1",
                    "reapprove 001-example aaaaaaaaaaaa", "approve 001-example aaaaaaaaaaaa-x"):
            with self.subTest(bad):
                self.assertTrue(mentions(check_doc("C06", self.doc(bad)), "prompt_excerpt"))

    def test_R303_the_readme_states_the_case_rule(self):
        self.assertRegex(README, r"(?i)keyword and the hex match case-insensitively")
        self.assertRegex(README, r"(?i)spec id matches exactly")
        self.assertRegex(README, r"(?i)stored prefix is lower case")

    def test_R303_the_fixtures_for_the_new_rules_exist(self):
        for name in ("invalid-excerpt-names-another-prefix.json", "invalid-excerpt-names-another-spec-id.json",
                     "invalid-excerpt-has-no-phrase.json", "valid-excerpt-in-upper-case-hex.json"):
            with self.subTest(name):
                self.assertTrue((FX / "C06" / name).is_file(), name)


# ------------------------------------------------------------------ R3-04, R3-05, R3-07: hooks, decisions 15 and 17

LAUNCHER = "${CLAUDE_PLUGIN_ROOT}/scripts/hook.py"


def entry(**kw):
    base = {"type": "command", "command": "python", "args": [LAUNCHER, "report-check"]}
    base.update(kw)
    return base


def hooks_doc(event="PreToolUse", group=None, **kw):
    g = {"hooks": [entry(**kw)]}
    g.update(group or {})
    return {"hooks": {event: [g]}}


class R304(unittest.TestCase):
    def test_R304_on_failure_continue_is_the_official_default_value(self):
        self.assertEqual(check_doc("C31", hooks_doc(onFailure="continue")), [])
        self.assertEqual(check_doc("C31", hooks_doc(onFailure="block")), [])
        self.assertTrue(check_doc("C31", hooks_doc(onFailure="allow")))

    def test_R304_async_rewake_is_an_official_boolean(self):
        self.assertEqual(check_doc("C31", hooks_doc(asyncRewake=True)), [])
        self.assertEqual(check_doc("C31", hooks_doc(asyncRewake=False)), [])
        self.assertTrue(check_doc("C31", hooks_doc(asyncRewake="yes")))

    def test_R304_a_fail_closed_entry_that_is_async_is_refused(self):
        for value in ("block", "continue"):
            errs = check_doc("C31", hooks_doc(onFailure=value, **{"async": True}))
            with self.subTest(value):
                self.assertTrue(mentions(errs, "onFailure", "async"), errs)

    def test_R304_a_fail_closed_entry_with_async_rewake_is_refused(self):
        errs = check_doc("C31", hooks_doc(onFailure="block", asyncRewake=True))
        self.assertTrue(mentions(errs, "onFailure", "asyncRewake"), errs)

    def test_R304_false_flags_do_not_conflict(self):
        self.assertEqual(check_doc("C31", hooks_doc(onFailure="block", asyncRewake=False, **{"async": False})), [])

    def test_R304_the_fixtures_for_the_new_rules_exist(self):
        for name in ("valid-hooks-file-on-failure-continue.json", "valid-hooks-file-async-rewake.json",
                     "invalid-on-failure-with-async.json", "invalid-on-failure-with-async-rewake.json"):
            with self.subTest(name):
                self.assertTrue((FX / "C31" / name).is_file(), name)


class R305(unittest.TestCase):
    def test_R305_a_matcher_on_an_event_without_matcher_support_is_refused(self):
        for event in ("Stop", "UserPromptSubmit"):
            with self.subTest(event):
                errs = check_doc("C31", hooks_doc(event, {"matcher": "Bash"}))
                self.assertTrue(mentions(errs, "matcher", event), errs)

    def test_R305_matchers_stay_valid_where_the_platform_reads_them(self):
        for event, m in (("PreToolUse", "Write|Edit"), ("SessionStart", "startup|resume"), ("SubagentStop", "implementer")):
            with self.subTest(event):
                self.assertEqual(check_doc("C31", hooks_doc(event, {"matcher": m})), [])

    def test_R305_a_group_without_a_matcher_is_valid_everywhere(self):
        for event in ("Stop", "UserPromptSubmit", "PreToolUse", "SessionStart", "SubagentStop"):
            with self.subTest(event):
                self.assertEqual(check_doc("C31", hooks_doc(event)), [])

    def test_R305_the_fixtures_for_the_new_rules_exist(self):
        for name in ("invalid-matcher-on-stop.json", "invalid-matcher-on-user-prompt-submit.json"):
            with self.subTest(name):
                self.assertTrue((FX / "C31" / name).is_file(), name)


class R307(unittest.TestCase):
    SENTENCE = "an unknown or missing handler id, an invalid handler result or an exception writes the reason to stderr and exits 1"

    def test_R307_the_launcher_exit_behavior_is_stated_once_in_c31_and_in_the_readme(self):
        c31 = json.loads(sp("C31").read_text(encoding="utf-8"))["description"]
        self.assertEqual(c31.count(self.SENTENCE), 1)
        self.assertEqual(README.count(self.SENTENCE), 1)

    def test_R307_no_text_says_a_missing_handler_exits_0(self):
        c31 = json.loads(sp("C31").read_text(encoding="utf-8"))["description"]
        for text in (c31, README):
            self.assertNotRegex(text, r"(?i)missing[^.]*exits? 0")


# ------------------------------------------------------------------ R3-09: a test that asserts behavior, not a source string

class R309(unittest.TestCase):
    def test_R309_f15_calls_the_discovery_instead_of_reading_its_source(self):
        src = (ROOT / "tests" / "test_findings_contracts.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        func = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name.startswith("test_F15_"))
        body = ast.get_source_segment(src, func)
        self.assertNotIn("inspect_source", body)
        self.assertNotIn("getsource", body)
        self.assertIn("discover_hook_ids", body)

    def test_R309_two_modules_that_define_one_id_are_reported(self):
        with tempfile.TemporaryDirectory() as d:
            for name in ("a_area", "b_area"):
                (pathlib.Path(d) / f"{name}.py").write_text('HOOKS = {"same-id": lambda payload: {}}\n', encoding="utf-8")
            found, problems = contract.discover_hook_ids(d)
        self.assertEqual(found, {"same-id": ["a_area", "b_area"]})
        self.assertEqual(problems, ["duplicate handler id 'same-id' defined by a_area, b_area"])


# ------------------------------------------------------------------ R3-10: the template row

class R310(unittest.TestCase):
    ROW = re.compile(r"(?m)^\| alert-event \|.*$")

    def test_R310_the_recorded_template_row_is_a_valid_c22_catalog(self):
        text = read("C22", "valid-template-example-row.md")
        self.assertEqual(check_text("C22", text), [])
        self.assertEqual(len(self.ROW.findall(text)), 1)

    @unittest.skipUnless(CAOS_TOOLS, "BATUTA_CAOS_TOOLS is not set")
    def test_R310_the_caos_template_row_equals_the_recorded_row(self):
        theirs = (pathlib.Path(CAOS_TOOLS) / "contracts-template.md").read_text(encoding="utf-8")
        ours = read("C22", "valid-template-example-row.md")
        self.assertEqual(self.ROW.findall(theirs), self.ROW.findall(ours))
        self.assertEqual(len(self.ROW.findall(theirs)), 1)


# ------------------------------------------------------------------ R3-11: the change-request id pattern

CR_REFS = (("C07", ("$defs", "entry", "properties", "change_request", "pattern")),
           ("C32", ("properties", "trailers", "properties", "Test-Change-Approved", "pattern")),
           ("C33", ("$defs", "request_row", "properties", "Id", "pattern")))


class R311(unittest.TestCase):
    def loaded(self):
        return {c: contract.load_schema(sp(c)) for c in ("C07", "C32", "C33")}

    def test_R311_the_lint_reports_the_equality_of_the_three_patterns(self):
        items = []
        area._lint_consistency(self.loaded(), items)
        hits = [i for i in items if "change-request id pattern" in i["message"]]
        self.assertEqual([i["tag"] for i in hits], ["OK"], items)
        for cid in ("C07", "C32", "C33"):
            self.assertIn(cid, hits[0]["message"])

    def test_R311_a_drifted_pattern_fails_the_lint(self):
        for cid, keys in CR_REFS:
            with self.subTest(cid):
                loaded = copy.deepcopy(self.loaded())
                node = loaded[cid]
                for k in keys[:-1]:
                    node = node[k]
                node[keys[-1]] = "^[A-Z]{2}-\\d+$"
                items = []
                area._lint_consistency(loaded, items)
                self.assertTrue(any(i["tag"] == "FAIL" and "change-request id pattern" in i["message"] for i in items), items)

    def test_R311_the_three_patterns_are_equal_today(self):
        values = []
        for cid, keys in CR_REFS:
            node = json.loads(sp(cid).read_text(encoding="utf-8"))
            for k in keys:
                node = node[k]
            values.append(node)
        self.assertEqual(len(set(values)), 1, values)


# ------------------------------------------------------------------ R3-12: a supersedes names an earlier entry of the same path

def lock_entry(path="tests/test_a.py", sha="a" * 64, **kw):
    base = {"path": path, "sha256": sha, "task_id": "T-001", "req_ids": ["REQ-AUTH-001"], "locked_commit": "abc1234",
            "locked_at": "2026-10-11T12:00:00Z"}
    base.update(kw)
    return base


def locks(*entries):
    return {"contract_version": "1.0", "entries": list(entries)}


class R312(unittest.TestCase):
    def test_R312_a_single_entry_that_supersedes_a_sha_no_entry_has_is_refused(self):
        doc = locks(lock_entry(supersedes="c" * 64, change_request="CR-001"))
        errs = check_doc("C07", doc)
        self.assertTrue(mentions(errs, "supersedes", "no earlier entry"), errs)

    def test_R312_the_sha_of_another_path_does_not_count(self):
        doc = locks(lock_entry(path="tests/test_b.py", sha="d" * 64),
                    lock_entry(sha="b" * 64, supersedes="d" * 64, change_request="CR-001"))
        self.assertTrue(mentions(check_doc("C07", doc), "supersedes", "no earlier entry"))

    def test_R312_a_later_entry_does_not_count(self):
        doc = locks(lock_entry(sha="b" * 64, supersedes="a" * 64, change_request="CR-001"), lock_entry(sha="a" * 64))
        self.assertTrue(mentions(check_doc("C07", doc), "supersedes", "no earlier entry"))

    def test_R312_a_proper_chain_is_valid(self):
        doc = locks(lock_entry(), lock_entry(sha="b" * 64, supersedes="a" * 64, change_request="CR-001"),
                    lock_entry(sha="c" * 64, supersedes="b" * 64, change_request="CR-002"))
        self.assertEqual(check_doc("C07", doc), [])

    def test_R312_the_fixture_is_one_entry_with_one_error(self):
        errs = contract.validate_file(FX / "C07" / "invalid-supersedes-names-no-entry.json", sp("C07"))
        self.assertEqual(len(errs), 1, errs)
        self.assertTrue(mentions(errs, "supersedes", "no earlier entry"))


# ------------------------------------------------------------------ D19: the shipped and the rendered hook entry profiles

OPT = '"$CLAUDE_PLUGIN_OPTION_PYTHON"'
SHIPPED_LAUNCHER = '"${CLAUDE_PLUGIN_ROOT}/scripts/hook.py"'


def shell_entry(command, **kw):
    return {"type": "command", "command": command, **kw}


def one_entry_doc(e, event="PreToolUse", profile=None, **group):
    doc = {"hooks": {event: [{"hooks": [e], **group}]}}
    if profile:
        doc["profile"] = profile
    return doc


class D19(unittest.TestCase):
    def test_D19_the_option_variable_is_the_shell_form_interpreter_with_shell_bash(self):
        for flags in ("", " -I", " -I -B"):
            with self.subTest(flags):
                e = shell_entry(f"{OPT}{flags} {SHIPPED_LAUNCHER} report-check", shell="bash")
                self.assertEqual(check_doc("C31", one_entry_doc(e)), [])

    def test_D19_the_variable_needs_shell_bash(self):
        for extra in ({}, {"shell": "powershell"}):
            with self.subTest(extra):
                e = shell_entry(f"{OPT} {SHIPPED_LAUNCHER} report-check", **extra)
                self.assertTrue(mentions(check_doc("C31", one_entry_doc(e)), "shell", "bash"))

    def test_D19_the_variable_is_refused_in_exec_form_and_unquoted(self):
        exec_form = {"type": "command", "command": "$CLAUDE_PLUGIN_OPTION_PYTHON", "args": [LAUNCHER, "report-check"], "shell": "bash"}
        self.assertTrue(check_doc("C31", one_entry_doc(exec_form)))
        exec_quoted = dict(exec_form, command=OPT)
        self.assertTrue(check_doc("C31", one_entry_doc(exec_quoted)))
        unquoted = shell_entry(f"$CLAUDE_PLUGIN_OPTION_PYTHON {SHIPPED_LAUNCHER} report-check", shell="bash")
        self.assertTrue(check_doc("C31", one_entry_doc(unquoted)))

    def test_D19_any_other_variable_is_refused(self):
        e = shell_entry(f'"$PYTHON" {SHIPPED_LAUNCHER} report-check', shell="bash")
        self.assertTrue(check_doc("C31", one_entry_doc(e)))

    def test_D19_check_hook_entry_is_a_function_other_units_call(self):
        self.assertTrue(callable(contract.check_hook_entry))
        ok = shell_entry(f"{OPT} {SHIPPED_LAUNCHER} report-check", shell="bash")
        self.assertEqual(contract.check_hook_entry(ok, "PreToolUse", "shipped"), [])
        self.assertTrue(contract.check_hook_entry(dict(ok, shell="powershell"), "PreToolUse", "shipped"))
        self.assertTrue(contract.check_hook_entry(ok, "Stop", "shipped", matcher="Bash"))
        self.assertTrue(contract.check_hook_entry(dict(ok, onFailure="block"), "SessionStart", "shipped"))
        with self.assertRaises(ValueError):
            contract.check_hook_entry(ok, "PreToolUse", "nonsense")

    def test_D19_c31_describes_the_rendered_profile(self):
        defs = json.loads(sp("C31").read_text(encoding="utf-8"))["$defs"]
        self.assertIn("rendered_entry", defs)
        self.assertRegex(defs["rendered_entry"]["description"].lower(), r"absolute")

    RENDERED = [
        ("exec windows path with spaces", {"type": "command", "command": "C:/Program Files/Python 3/python.exe",
                                           "args": ["-I", "D:/Tools/a b/plugins/batuta/scripts/hook.py", "report-check"]}),
        ("exec posix path", {"type": "command", "command": "/usr/bin/python3", "args": ["/opt/tools/plugins/batuta/scripts/hook.py", "report-check"]}),
        ("exec bare interpreter", {"type": "command", "command": "python", "args": ["/opt/tools/plugins/batuta/scripts/hook.py", "report-check"]}),
        ("shell windows path quoted", {"type": "command", "command": '"C:/Program Files/Python 3/python.exe" -I "D:/Tools/a b/plugins/batuta/scripts/hook.py" report-check'}),
        ("shell posix path quoted", {"type": "command", "command": '"/usr/bin/python3" "/opt/tools/plugins/batuta/scripts/hook.py" report-check'}),
        ("shell bare interpreter", {"type": "command", "command": 'python -I "/opt/tools/plugins/batuta/scripts/hook.py" report-check'}),
    ]

    def test_D19_rendered_entries_are_valid(self):
        for label, e in self.RENDERED:
            with self.subTest(label):
                self.assertEqual(check_doc("C31", one_entry_doc(e, profile="rendered")), [])
                self.assertEqual(contract.check_hook_entry(e, "PreToolUse", "rendered"), [])

    def test_D19_a_rendered_entry_refuses_what_is_not_resolved(self):
        cases = {
            "leftover {{python}} exec": {"type": "command", "command": "{{python}}", "args": ["/opt/tools/plugins/batuta/scripts/hook.py", "report-check"]},
            "leftover {{python}} shell": {"type": "command", "command": '{{python}} "/opt/tools/plugins/batuta/scripts/hook.py" report-check'},
            "leftover plugin root exec": {"type": "command", "command": "python", "args": [LAUNCHER, "report-check"]},
            "leftover plugin root shell": {"type": "command", "command": f'python {SHIPPED_LAUNCHER} report-check'},
            "leftover option var": {"type": "command", "command": f'{OPT} "/opt/tools/plugins/batuta/scripts/hook.py" report-check', "shell": "bash"},
            "relative launcher exec": {"type": "command", "command": "python", "args": ["plugins/batuta/scripts/hook.py", "report-check"]},
            "relative launcher shell": {"type": "command", "command": 'python "plugins/batuta/scripts/hook.py" report-check'},
            "launcher is not scripts/hook.py": {"type": "command", "command": "python", "args": ["/opt/tools/plugins/batuta/hook.py", "report-check"]},
            "launcher is another script": {"type": "command", "command": 'python "/opt/tools/plugins/batuta/scripts/other.py" report-check'},
            "relative interpreter path": {"type": "command", "command": "bin/python", "args": ["/opt/tools/plugins/batuta/scripts/hook.py", "report-check"]},
            "unquoted absolute interpreter in shell form": {"type": "command", "command": 'C:/Python/python.exe "/opt/tools/plugins/batuta/scripts/hook.py" report-check'},
            "handler id not lower case": {"type": "command", "command": "python", "args": ["/opt/tools/plugins/batuta/scripts/hook.py", "Report"]},
            "extra argument": {"type": "command", "command": "python", "args": ["/opt/tools/plugins/batuta/scripts/hook.py", "report-check", "x"]},
        }
        for label, e in cases.items():
            with self.subTest(label):
                self.assertTrue(contract.check_hook_entry(e, "PreToolUse", "rendered"), label)
                self.assertTrue(check_doc("C31", one_entry_doc(e, profile="rendered")), label)

    def test_D19_the_rendered_profile_keeps_the_on_failure_and_matcher_rules(self):
        e = {"type": "command", "command": "python", "args": ["/opt/tools/plugins/batuta/scripts/hook.py", "report-check"]}
        self.assertTrue(contract.check_hook_entry(dict(e, onFailure="block"), "SessionStart", "rendered"))
        self.assertTrue(contract.check_hook_entry(dict(e, onFailure="block", **{"async": True}), "PreToolUse", "rendered"))
        self.assertTrue(contract.check_hook_entry(e, "Stop", "rendered", matcher="Bash"))
        self.assertEqual(contract.check_hook_entry(dict(e, onFailure="block"), "PreToolUse", "rendered", matcher="Bash"), [])
        self.assertTrue(check_doc("C31", one_entry_doc(dict(e, onFailure="block"), "SessionStart", profile="rendered")))
        self.assertTrue(check_doc("C31", one_entry_doc(e, "Stop", profile="rendered", matcher="Bash")))

    def test_D19_check_rendered_entry_validates_structure_and_semantics(self):
        e = {"type": "command", "command": "python", "args": ["/opt/tools/plugins/batuta/scripts/hook.py", "report-check"]}
        self.assertEqual(contract.check_rendered_entry(e, "PreToolUse"), [])
        self.assertTrue(contract.check_rendered_entry(dict(e, retry=3), "PreToolUse"))

    def test_D19_the_readme_documents_both_profiles(self):
        for word in ("shipped profile", "rendered profile", "CLAUDE_PLUGIN_OPTION_PYTHON", "check_hook_entry", "/scripts/hook.py"):
            with self.subTest(word):
                self.assertIn(word, README)

    def test_D19_the_fixtures_for_the_new_rules_exist(self):
        for name in ("valid-hooks-file-option-python-shell-bash.json", "valid-rendered-windows-path-with-spaces.json",
                     "valid-rendered-posix-path.json", "invalid-option-python-without-shell-bash.json",
                     "invalid-option-python-in-exec-form.json", "invalid-option-python-unquoted.json",
                     "invalid-rendered-leftover-placeholder.json", "invalid-rendered-relative-launcher.json",
                     "invalid-rendered-launcher-not-hook-py.json"):
            with self.subTest(name):
                self.assertTrue((FX / "C31" / name).is_file(), name)


if __name__ == "__main__":
    unittest.main()

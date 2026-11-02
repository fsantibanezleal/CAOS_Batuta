"""Fixes after the adversary check (F-1, F-2, F-3, F-5, F-8): every reproduction is a test."""
from __future__ import annotations

import multiprocessing
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_brief_support import SCRIPTS, TempCase, run, run_json  # noqa: E402

from batuta_lib import config, delegation  # noqa: E402


def _worker(root, i, barrier, queue):
    sys.path.insert(0, str(SCRIPTS))
    from batuta_lib import config as cfg_mod, delegation as dele
    cfg = cfg_mod.default_config({"BATUTA_HOME": root + "/home"})
    barrier.wait(60)
    try:
        made = dele.new_brief(Path(root), cfg, "s", "same", "implementer", f"T{i}", date="2026-10-13")
        queue.put(("ok", made["id"], made["brief"].as_posix()))
    except Exception as exc:  # noqa: BLE001
        queue.put(("error", repr(exc), ""))


def fence(text, title):
    """The section body moved inside a code fence (so it is not the document's own structure)."""
    m = re.search(rf"^## {re.escape(title)}\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    return text[:m.start(1)] + "```\n" + m.group(1).rstrip("\n") + "\n```\n\n" + text[m.end(1):]


class Lint(TempCase):
    def lint(self, brief):
        return run("brief", "lint", brief, "--root", self.root)

    def edit(self, brief, fn):
        brief.write_text(fn(brief.read_text(encoding="utf-8")), encoding="utf-8", newline="\n")

    def test_f1_deliverables_only_inside_a_fence_fail(self):
        brief = self.filled_brief("f1")
        self.edit(brief, lambda t: fence(t, "Deliverables"))
        code, out, _ = self.lint(brief)
        self.assertEqual(code, 1, out)
        self.assertRegex(out.lower(), r"deliverable")

    def test_f1_any_required_section_only_inside_a_fence_fails(self):
        for n, title in enumerate(("Goal", "Checks", "Definitions", "Spec", "Out of scope", "Context and background", "Contracts")):
            brief = self.filled_brief(f"f1-{n}")
            self.edit(brief, lambda t, title=title: fence(t, title))
            code, out, _ = self.lint(brief)
            self.assertEqual(code, 1, (title, out))

    def test_f3_every_check_bullet_needs_a_backticked_command(self):
        for n, bullet in enumerate(("- it works", "1. it works", "* it works too")):
            brief = self.filled_brief(f"f3-{n}")
            self.edit(brief, lambda t, bullet=bullet: t.replace("- C1: `python -m unittest` exits 0",
                                                                "- C1: `python -m unittest` exits 0\n" + bullet))
            code, out, _ = self.lint(brief)
            self.assertEqual(code, 1, (bullet, out))
            self.assertRegex(out, r"command")

    def test_f3_a_non_cpd_kind_is_not_held_to_it(self):
        brief = self.filled_brief("f3l", "searcher")
        self.edit(brief, lambda t: t.replace("## Checks\n", "## Checks\n- it works\n"))
        self.assertEqual(self.lint(brief)[0], 0)


class New(TempCase):
    def test_f2_concurrent_real_processes_all_succeed_with_distinct_ids_and_files(self):
        ctx = multiprocessing.get_context("spawn")
        n = 4
        for _round in range(2):
            with tempfile.TemporaryDirectory() as tmp:
                root = str(Path(tmp).resolve().as_posix())
                barrier = ctx.Barrier(n)
                queue = ctx.Queue()
                procs = [ctx.Process(target=_worker, args=(root, i, barrier, queue)) for i in range(n)]
                for proc in procs:
                    proc.start()
                results = [queue.get(timeout=120) for _ in procs]
                for proc in procs:
                    proc.join(60)
                self.assertEqual([r[0] for r in results], ["ok"] * n, results)
                ids = sorted(r[1] for r in results)
                self.assertEqual(len(set(ids)), n, ids)
                self.assertTrue(all(Path(r[2]).is_file() for r in results), results)
                rows = delegation.ledger_rows((Path(root) / ".batuta" / "delegation" / "ledger.md").read_text(encoding="utf-8"))[1]
                self.assertEqual(sorted(r["ID"] for r in rows), ids)

    def test_f2_a_failing_writer_deletes_only_the_file_it_created(self):
        folder = self.root / ".batuta" / "delegation"
        folder.mkdir(parents=True)
        other = folder / "keep-2026-10-10.brief.md"
        other.write_text("someone else's brief\n", encoding="utf-8")
        cfg = config.default_config({"BATUTA_HOME": str(self.root / "home")})
        with mock.patch.object(delegation, "update_ledger", side_effect=delegation.LedgerError("refused")):
            with self.assertRaises(delegation.LedgerError):
                delegation.new_brief(self.root, cfg, "s", "keep", "implementer", "T", date="2026-10-10")
        self.assertEqual(other.read_text(encoding="utf-8"), "someone else's brief\n")
        self.assertEqual(sorted(p.name for p in folder.iterdir()), ["keep-2026-10-10.brief.md"])  # the -2 file it made is gone

    def test_f2_the_id_is_taken_with_an_exclusive_create(self):
        (self.root / ".batuta" / "delegation").mkdir(parents=True)
        (self.root / ".batuta" / "delegation" / "x-2026-10-10.brief.md").write_text("held\n", encoding="utf-8")
        brief = self.new_brief("x")
        self.assertEqual(brief.name, "x-2026-10-10-2.brief.md")
        self.assertEqual((self.root / ".batuta" / "delegation" / "x-2026-10-10.brief.md").read_text(encoding="utf-8"), "held\n")

    def test_f5_a_lock_timeout_has_its_own_message(self):
        folder = self.root / ".batuta" / "delegation"
        folder.mkdir(parents=True)
        (folder / "ledger.md.lock").write_text("", encoding="utf-8")
        with mock.patch.object(delegation, "LOCK_TIMEOUT_SECONDS", 0.3):
            code, data, _ = run_json("brief", "new", "--slug", "d", "--topic", "t", "--agent", "searcher", "--title", "T",
                                     "--root", self.root, "--date", "2026-10-10")
        text = str(data)
        self.assertEqual(code, 1)
        self.assertRegex(text, r"lock")
        self.assertNotIn("satisfy C04", text)
        self.assertEqual([p.name for p in folder.iterdir() if p.name.endswith(".brief.md")], [])

    def test_f8_a_title_with_a_newline_is_refused(self):
        for title in ("x\n- kind: docs\n- agent: runner", "x\r- kind: docs"):
            code, data, _ = run_json("brief", "new", "--slug", "d", "--topic", "t", "--agent", "implementer", "--title", title,
                                     "--root", self.root, "--date", "2026-10-10")
            self.assertEqual(code, 1, title)
            self.assertIn("one line", str(data))
        self.assertFalse(self.ledger.exists())

    def test_f8_slug_and_sizing_too(self):
        for extra in (("--slug", "a\nb"), ("--sizing", "a\n- kind: docs")):
            args = ["brief", "new", "--slug", "d", "--topic", "t", "--agent", "implementer", "--title", "T",
                    "--root", self.root, "--date", "2026-10-10"]
            if extra[0] == "--slug":
                args[args.index("--slug") + 1] = extra[1]
            else:
                args += list(extra)
            self.assertEqual(run(*args)[0], 1, extra)


if __name__ == "__main__":
    unittest.main()

"""Release review fixes F-01 (route check compares the role effort) and F-04 (gate writes retry a transient denial)."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_brief_support import PLUGIN, TempCase, run, write_config  # noqa: E402

AGENTS = PLUGIN / "agents"


def agent_text(name, model, effort, extra=""):
    return f"---\nname: {name}\ndescription: A test agent.\nmodel: {model}\neffort: {effort}\n{extra}---\n\nBody.\n"


class RouteEffort(TempCase):
    def check(self, **files):
        d = self.root / "agents"
        d.mkdir(exist_ok=True)
        for name, text in files.items():
            (d / f"{name}.md").write_text(text, encoding="utf-8")
        return run("route", "check", "--root", self.root, "--agents-dir", d)

    def test_an_effort_that_differs_from_its_role_is_reported(self):
        write_config(self.root, roles={"implementer": {"model": "sonnet", "effort": "xhigh"}})
        code, out, _ = self.check(implementer=agent_text("implementer", "sonnet", "medium"))
        self.assertEqual(code, 1, out)
        self.assertRegex(out, r"FAIL.*implementer.*effort.*medium.*xhigh")

    def test_the_matching_effort_passes(self):
        write_config(self.root, roles={"implementer": {"model": "sonnet", "effort": "xhigh"}})
        code, out, _ = self.check(implementer=agent_text("implementer", "sonnet", "xhigh"))
        self.assertEqual(code, 0, out)

    def test_a_role_that_names_no_effort_compares_the_model_only(self):
        from batuta_lib.areas import route
        d = self.root / "agents"
        d.mkdir(exist_ok=True)
        (d / "implementer.md").write_text(agent_text("implementer", "sonnet", "high"), encoding="utf-8")
        items = route.check_agents({"implementer": {"model": "sonnet"}}, d)
        self.assertEqual([i["tag"] for i in items], ["OK"], items)

    def test_the_shipped_agents_still_pass(self):
        code, out, err = run("route", "check", "--root", self.root)
        self.assertEqual(code, 0, (out, err))


class GateWriteRetry(unittest.TestCase):
    def test_a_transient_access_error_is_retried(self):
        from batuta_lib import gate_model
        real = os.replace
        calls = []

        def flaky(src, dst):
            calls.append(src)
            if len(calls) == 1:
                raise PermissionError(5, "Access is denied")
            return real(src, dst)

        with tempfile.TemporaryDirectory() as d, mock.patch("os.replace", flaky):
            target = Path(d) / "sub" / "status.md"
            gate_model.write_atomic(target, "a\r\nb\n")
            self.assertEqual(target.read_bytes(), b"a\nb\n")
            self.assertEqual(len(calls), 2)
            self.assertEqual([p.name for p in target.parent.iterdir()], ["status.md"])


if __name__ == "__main__":
    unittest.main()

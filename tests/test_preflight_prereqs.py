"""preflight prereqs: each owner-prerequisite probe reports present or missing; a probe never leaks output."""
import json
import sys
import unittest
from pathlib import Path

from test_device_support import DeviceCase  # noqa: E402

PY = sys.executable


def probe(code):
    return [PY, "-c", code]


class Prereqs(DeviceCase):
    def register(self, items, name="prereqs.json"):
        path = self.root / name
        path.write_text(json.dumps({"prerequisites": items}), encoding="utf-8")
        return path

    def item(self, name, code, **extra):
        return {"name": name, "why": f"why {name}", "owner_action": f"do {name}", "probe": probe(code), **extra}

    def prereqs(self, path, *extra):
        return self.cli("preflight", "prereqs", "--register", str(path), *extra)

    def test_present_and_missing(self):
        path = self.register([self.item("good", "raise SystemExit(0)"), self.item("bad", "raise SystemExit(1)")])
        code, out, _ = self.prereqs(path)
        self.assertEqual(1, code)
        self.assertIn("OK good", out)
        self.assertIn("missing", out.lower())
        self.assertIn("do bad", out)

    def test_all_present_is_exit_0(self):
        path = self.register([self.item("good", "raise SystemExit(0)")])
        code, out, _ = self.prereqs(path)
        self.assertEqual(0, code, out)

    def test_probe_command_that_does_not_exist_is_missing_with_the_probe_text(self):
        path = self.register([{"name": "ghost", "why": "needs ghost", "owner_action": "install ghost",
                               "probe": ["no-such-binary-u7-xyz", "--version"]}])
        code, out, _ = self.prereqs(path)
        self.assertEqual(1, code)
        self.assertIn("ghost", out)
        self.assertIn("no-such-binary-u7-xyz", out)

    def test_a_slow_probe_times_out_as_missing(self):
        path = self.register([self.item("slow", "import time; time.sleep(30)")])
        code, out, _ = self.prereqs(path, "--timeout", "1")
        self.assertEqual(1, code)
        self.assertIn("timed out", out)

    def test_probe_output_is_never_printed(self):
        path = self.register([self.item("noisy", "print('SECRET-OUTPUT-U7'); raise SystemExit(0)")])
        code, out, err = self.prereqs(path)
        self.assertNotIn("SECRET-OUTPUT-U7", out + err)

    def test_string_probe_runs_through_the_shell(self):
        path = self.register([{"name": "sh", "why": "w", "owner_action": "a", "probe": f'"{PY}" -c "raise SystemExit(0)"'}])
        self.assertEqual(0, self.prereqs(path)[0])

    def test_invalid_item_is_missing_and_names_the_field(self):
        path = self.register([{"name": "half", "why": "w"}])
        code, out, _ = self.prereqs(path)
        self.assertEqual(1, code)
        self.assertIn("probe", out)

    def test_unreadable_register_fails(self):
        code, out, _ = self.prereqs(self.root / "none.json")
        self.assertEqual(1, code)
        self.assertIn("none.json", out)

    def test_register_without_list_fails(self):
        path = self.root / "bad.json"
        path.write_text(json.dumps({"x": 1}), encoding="utf-8")
        self.assertEqual(1, self.prereqs(path)[0])

    def test_json_output_lists_items(self):
        path = self.register([self.item("good", "raise SystemExit(0)")])
        code, out, _ = self.prereqs(path, "--json")
        doc = json.loads(out)
        self.assertEqual("preflight", doc["area"])
        self.assertEqual("OK", doc["items"][0]["tag"])


if __name__ == "__main__":
    unittest.main()

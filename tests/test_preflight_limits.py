"""preflight limits: measured machine limits; a missing GPU or Node is reported absent, never an error."""
import json
import sys
import unittest
from unittest import mock

from test_device_support import DeviceCase  # noqa: E402

from batuta_lib import config, contract  # noqa: E402
from batuta_lib.areas import preflight  # noqa: E402

GB = 1024 ** 3


class FakeSystem:
    """Readings injected in place of the machine."""

    def __init__(self, gpu="GPU 0", node="v20.1.0", memory=(16 * GB, 8 * GB), disk_free=50 * GB):
        self._gpu, self._node, self._memory, self._disk = gpu, node, memory, disk_free

    def cpu_count(self):
        return 8

    def memory(self):
        return None if self._memory is None else {"total": self._memory[0], "free": self._memory[1]}

    def disk_free(self, path):
        return self._disk

    def gpus(self):
        return None if self._gpu is None else [{"name": self._gpu, "mem_total_mib": 8192, "mem_free_mib": 6000}]

    def node_version(self):
        return self._node

    def python_version(self):
        return "3.14.0"


class Limits(DeviceCase):
    def limits(self, system, *extra):
        with mock.patch.object(preflight, "SYSTEM", system):
            return self.cli("preflight", "limits", "--deploy-root", str(self.deploy_dir), "--home", str(self.home), *extra)

    def test_prints_every_measure(self):
        code, out, _ = self.limits(FakeSystem())
        self.assertEqual(0, code, out)
        for word in ("cpu", "memory", "disk", "gpu", "python", "node"):
            self.assertIn(word, out.lower())
        self.assertIn("8", out)
        self.assertIn("16.0 GB", out)

    def test_disk_is_reported_for_each_root(self):
        code, out, _ = self.limits(FakeSystem(), "--json")
        doc = json.loads(out)
        disks = [i for i in doc["items"] if i["message"].startswith("disk")]
        self.assertEqual(5, len(disks))   # deploy, temp, data, models, worktrees

    def test_no_gpu_is_absent_not_an_error(self):
        code, out, _ = self.limits(FakeSystem(gpu=None))
        self.assertEqual(0, code)
        self.assertIn("no GPU", out)

    def test_no_node_is_absent_and_names_what_needs_it(self):
        code, out, _ = self.limits(FakeSystem(node=None))
        self.assertEqual(0, code)
        self.assertIn("npx", out)

    def test_unreadable_memory_is_a_warn(self):
        code, out, _ = self.limits(FakeSystem(memory=None))
        self.assertEqual(2, code)
        self.assertIn("WARN", out)

    def test_json_is_c20(self):
        code, out, _ = self.limits(FakeSystem(), "--json")
        sp = contract.find_schema(config.contracts_dir(), "C20")
        self.assertEqual([], contract.validate_instance("C20", json.loads(out), contract.load_schema(sp)))

    def test_real_system_reports_python_and_cpu(self):
        real = preflight.RealSystem()
        self.assertGreaterEqual(real.cpu_count(), 1)
        self.assertTrue(real.python_version().startswith(f"{sys.version_info.major}."))
        self.assertIsNone(preflight.parse_nvidia_smi(""))
        self.assertEqual("A", preflight.parse_nvidia_smi("A, 8192, 6000\n")[0]["name"])


if __name__ == "__main__":
    unittest.main()

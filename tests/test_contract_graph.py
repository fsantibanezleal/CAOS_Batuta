"""contract graph: waves, coupling WARN, cycle FAIL, on fixture tasks (tests/contracts/graph)."""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins" / "batuta" / "scripts"))

from batuta_lib.areas import contract as area  # noqa: E402

G = ROOT / "tests" / "contracts" / "graph"


def run(tasks, interfaces="interfaces-frozen.md"):
    return area.graph(G / tasks, G / interfaces, root=G)


def tags(items):
    return [i["tag"] for i in items]


def wave_of(items):
    """Map task id to wave from the 'wave N: T-1, T-2' OK lines."""
    out = {}
    for i in items:
        if i["tag"] == "OK" and i["message"].startswith("wave "):
            head, _, rest = i["message"].partition(":")
            n = int(head.split()[1])
            for t in rest.split(","):
                out[t.strip()] = n
    return out


class Waves(unittest.TestCase):
    def test_tasks_sharing_only_frozen_contracts_share_a_wave(self):
        items = run("tasks-parallel.md")
        self.assertNotIn("FAIL", tags(items))
        self.assertNotIn("WARN", tags(items))
        self.assertEqual(wave_of(items), {"T-001": 1, "T-002": 1, "T-003": 1})

    def test_depends_edges_order_the_waves(self):
        items = run("tasks-ordered.md")
        self.assertEqual(wave_of(items), {"T-001": 1, "T-002": 2, "T-003": 3})
        self.assertNotIn("WARN", tags(items))

    def test_a_shared_unfrozen_contract_separates_tasks(self):
        items = run("tasks-shared-unfrozen.md", "interfaces-a-missing-file.md")
        self.assertEqual(wave_of(items), {"T-001": 1, "T-002": 2, "T-003": 1})
        warns = [i["message"] for i in items if i["tag"] == "WARN"]
        self.assertTrue(any("NOPE" in w and "unfrozen" in w for w in warns), warns)

    def test_a_contract_missing_from_the_interface_table_is_unfrozen(self):
        items = run("tasks-shared-unfrozen.md", "interfaces-frozen.md")
        self.assertEqual(wave_of(items)["T-002"], 2)
        self.assertTrue(any(i["tag"] == "WARN" and "not declared" in i["message"] for i in items))


class Coupling(unittest.TestCase):
    def test_depends_justified_only_by_a_shared_frozen_contract_is_a_coupling_warn(self):
        items = run("tasks-coupling.md")
        warns = [i for i in items if i["tag"] == "WARN"]
        self.assertEqual(len(warns), 1, items)
        self.assertIn("coupling", warns[0]["message"])
        self.assertIn("T-002", warns[0]["message"])
        self.assertIn("T-001", warns[0]["message"])
        self.assertIn("A.schema.json", warns[0]["message"])
        self.assertNotIn("FAIL", tags(items))
        self.assertEqual(wave_of(items), {"T-001": 1, "T-002": 2})


class Failures(unittest.TestCase):
    def test_cycle_is_a_fail_naming_the_cycle(self):
        items = run("tasks-cycle.md")
        fails = [i for i in items if i["tag"] == "FAIL"]
        self.assertEqual(len(fails), 1, items)
        self.assertIn("cycle", fails[0]["message"])
        self.assertIn("T-001", fails[0]["message"])
        self.assertIn("T-002", fails[0]["message"])

    def test_unknown_depends_is_a_fail(self):
        items = run("tasks-unknown-depends.md")
        self.assertTrue(any(i["tag"] == "FAIL" and "T-009" in i["message"] for i in items), items)

    def test_invalid_tasks_table_is_a_fail(self):
        items = run("tasks-invalid.md")
        self.assertTrue(any(i["tag"] == "FAIL" for i in items))
        self.assertFalse(wave_of(items))

    def test_missing_file_is_a_fail(self):
        items = area.graph(G / "nope.md", G / "interfaces-frozen.md", root=G)
        self.assertTrue(any(i["tag"] == "FAIL" for i in items))


class WaveColumn(unittest.TestCase):
    def test_a_wave_column_that_differs_from_the_computed_wave_warns(self):
        items = run("tasks-wave-mismatch.md")
        warns = [i["message"] for i in items if i["tag"] == "WARN"]
        self.assertEqual(len(warns), 1, warns)
        self.assertIn("T-001", warns[0])
        self.assertIn("Wave column", warns[0])


INV = G / "inventory"


def run_inv(name, tasks=None):
    return area.graph_inventory(INV / name, tasks_path=(G / tasks) if tasks else None)


def unit_waves(items):
    out = {}
    for i in items:
        if i["tag"] == "OK" and i["message"].startswith("wave "):
            head, _, rest = i["message"].partition(":")
            out[int(head.split()[1])] = [x.strip() for x in rest.split(",") if x.strip()]
    return out


class InventoryWaves(unittest.TestCase):
    """Waves from the C23 inventory (ADR-0080 section 5): 0 contracts, 1 skeleton, then units by frozen contracts."""

    def test_wave_zero_is_the_contracts_and_wave_one_the_skeleton(self):
        waves = unit_waves(run_inv("frozen-parallel.json"))
        self.assertEqual(waves[0], ["tracks-api", "tracks-data"])
        self.assertEqual(waves[1], ["walking skeleton"])

    def test_units_whose_consumed_contracts_are_frozen_share_wave_two(self):
        items = run_inv("frozen-parallel.json")
        self.assertNotIn("FAIL", tags(items))
        self.assertEqual(unit_waves(items)[2], ["u-api", "u-pipe"])

    def test_a_unit_consuming_an_unfrozen_contract_waits_for_its_provider(self):
        items = run_inv("chain.json")
        waves = unit_waves(items)
        self.assertEqual(waves[2], ["u-pipe"])
        self.assertEqual(waves[3], ["u-api"])
        self.assertNotIn("FAIL", tags(items))

    def test_a_declared_wave_that_differs_warns(self):
        items = run_inv("chain-wrong-wave.json")
        warns = [i["message"] for i in items if i["tag"] == "WARN"]
        self.assertEqual(len(warns), 1, warns)
        self.assertIn("u-api", warns[0])
        self.assertIn("wave", warns[0])

    def test_a_unit_consuming_a_contract_nobody_provides_is_refused(self):
        items = run_inv("unprovided.json")
        fails = [i["message"] for i in items if i["tag"] == "FAIL"]
        self.assertTrue(any("nobody provides" in m and "u-api" in m and "tracks-extra" in m for m in fails), fails)
        self.assertFalse(unit_waves(items))

    def test_a_cycle_between_units_is_a_fail(self):
        items = run_inv("cycle.json")
        self.assertTrue(any(i["tag"] == "FAIL" and "cycle" in i["message"] for i in items), items)

    def test_an_invalid_inventory_is_a_fail(self):
        items = run_inv("invalid.json")
        self.assertTrue(any(i["tag"] == "FAIL" for i in items))
        self.assertFalse(unit_waves(items))

    def test_a_missing_inventory_file_is_a_fail(self):
        self.assertTrue(any(i["tag"] == "FAIL" for i in run_inv("nope.json")))

    def test_a_yaml_inventory_without_pyyaml_is_refused_naming_json(self):
        import builtins
        real = builtins.__import__

        def no_yaml(name, *a, **k):
            if name == "yaml":
                raise ImportError("no yaml")
            return real(name, *a, **k)

        builtins.__import__ = no_yaml
        try:
            items = run_inv("inventory.yaml")
        finally:
            builtins.__import__ = real
        fails = [i["message"] for i in items if i["tag"] == "FAIL"]
        self.assertTrue(any("PyYAML" in m and "JSON" in m for m in fails), fails)

    def test_a_task_naming_an_unknown_unit_is_a_fail(self):
        items = run_inv("frozen-parallel.json", "tasks-units-unknown.md")
        self.assertTrue(any(i["tag"] == "FAIL" and "u-ghost" in i["message"] for i in items), items)

    def test_a_task_naming_a_known_unit_reports_the_unit_wave(self):
        items = run_inv("chain.json", "tasks-units-known.md")
        self.assertNotIn("FAIL", tags(items))
        self.assertTrue(any(i["tag"] == "OK" and "T-001" in i["message"] and "u-api" in i["message"]
                            and "wave 3" in i["message"] for i in items), items)


class ExitCodes(unittest.TestCase):
    def test_exit_code_from_items(self):
        self.assertEqual(area.exit_code([{"tag": "OK", "message": "x"}]), 0)
        self.assertEqual(area.exit_code([{"tag": "OK", "message": "x"}, {"tag": "WARN", "message": "w"}]), 2)
        self.assertEqual(area.exit_code([{"tag": "WARN", "message": "w"}, {"tag": "FAIL", "message": "f"}]), 1)


if __name__ == "__main__":
    unittest.main()

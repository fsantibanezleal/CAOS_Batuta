"""contract graph: one wave numbering from the catalog (frozen rows), the sizing (units) and the tasks."""
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins" / "batuta" / "scripts"))

from batuta_lib.areas import contract as area  # noqa: E402

FX = ROOT / "plugins" / "batuta" / "contracts" / "fixtures"
SIZING = (FX / "C23" / "valid-product-sizing.md").read_text(encoding="utf-8")

CAT_HEAD = ("| id | version | owner | schema file | example | producer test | consumer test | missing-data behavior | provider | model io "
            "| swap test | status | frozen |\n|---|---|---|---|---|---|---|---|---|---|---|---|---|\n")
TASK_HEAD = "| Task | Title | Requirements | Contracts | Depends | Wave | Owner role | Unit |\n|---|---|---|---|---|---|---|---|\n"


def catalog_text(rows):
    """rows: (id, owner, frozen yes or no)."""
    return "# Catalog\n\n" + CAT_HEAD + "".join(
        f"| {i} | 1.0.0 | {o} | s/{i}.json | e/{i}.json | t/p.py | t/c.py | available: ok (test: t/a.py); missing: drop it (test: t/a.py) | fixture:f/{i}.json | - | t/s.py | active | {f} |\n"
        for i, o, f in rows)


def tasks_text(rows):
    """rows: (task, contracts, depends, wave, unit)."""
    return "# Tasks\n\n" + TASK_HEAD + "".join(
        f"| {t} | Title {t} | REQ-X-001 | {', '.join(c) or '-'} | {', '.join(d) or '-'} | {w} | implementer | {u} |\n"
        for t, c, d, w, u in rows)


# the sizing fixture's units: u-model (no deps), u-pipeline (severity-score), u-api (alert-event), u-ui (alert-list)
CAT_CHAIN = [("alert-event", "u-pipeline", "no"), ("alert-list", "u-api", "no"), ("severity-score", "u-model", "no")]


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = pathlib.Path(self.tmp.name)

    def write(self, name, text):
        p = self.dir / name
        p.write_text(text, encoding="utf-8")
        return p

    def run_graph(self, catalog, sizing=None, tasks=None):
        c = self.write("catalog.md", catalog_text(catalog))
        s = self.write("sizing.md", sizing) if sizing is not None else None
        t = self.write("tasks.md", tasks_text(tasks)) if tasks is not None else None
        return area.graph(c, s, t)


def tags(items):
    return [i["tag"] for i in items]


def waves(items):
    """Map wave number to the names on its 'wave N: a, b' OK line."""
    out = {}
    for i in items:
        if i["tag"] == "OK" and i["message"].startswith("wave "):
            head, _, rest = i["message"].partition(":")
            out[int(head.split()[1])] = [x.strip() for x in rest.split(",") if x.strip()]
    return out


def wave_of(items):
    return {name: n for n, names in waves(items).items() if n >= 2 for name in names}


def messages(items, tag):
    return [i["message"] for i in items if i["tag"] == tag]


class UnitWaves(Case):
    def test_wave_zero_is_the_contracts_and_wave_one_the_skeleton(self):
        items = self.run_graph([("alert-event", "u-pipeline", "yes"), ("alert-list", "u-api", "no"), ("severity-score", "u-model", "yes")], SIZING)
        self.assertEqual(waves(items)[0], ["alert-event", "severity-score"])
        self.assertEqual(waves(items)[1], ["walking skeleton"])

    def test_no_frozen_contract_says_so(self):
        items = self.run_graph(CAT_CHAIN, SIZING)
        self.assertEqual(waves(items)[0], ["(no frozen contract yet)"])

    def test_a_chain_of_unfrozen_contracts_orders_the_units_from_wave_two(self):
        items = self.run_graph(CAT_CHAIN, SIZING)
        self.assertNotIn("FAIL", tags(items))
        self.assertEqual(wave_of(items), {"u-model": 2, "u-pipeline": 3, "u-api": 4, "u-ui": 5})

    def test_a_frozen_contract_is_ready_at_wave_zero_so_its_consumer_starts_at_wave_two(self):
        cat = [("alert-event", "u-pipeline", "yes"), ("alert-list", "u-api", "no"), ("severity-score", "u-model", "no")]
        items = self.run_graph(cat, SIZING)
        self.assertEqual(wave_of(items), {"u-model": 2, "u-api": 2, "u-pipeline": 3, "u-ui": 3})

    def test_a_cycle_between_units_is_a_fail(self):
        sizing = SIZING.replace("| u-pipeline | pipeline/, tests/pipeline/ | severity-score |", "| u-pipeline | pipeline/, tests/pipeline/ | alert-list |")
        items = self.run_graph(CAT_CHAIN, sizing)
        fails = messages(items, "FAIL")
        self.assertTrue(any("cycle" in m for m in fails), items)

    def test_a_unit_depending_on_a_contract_missing_from_the_catalog_is_a_fail(self):
        items = self.run_graph([("alert-event", "u-pipeline", "no"), ("alert-list", "u-api", "no")], SIZING)
        self.assertTrue(any("severity-score" in m and "not a row of the catalog" in m for m in messages(items, "FAIL")), items)

    def test_an_unfrozen_contract_owned_by_a_team_that_is_not_a_unit_warns(self):
        cat = [("alert-event", "platform-team", "no"), ("alert-list", "u-api", "no"), ("severity-score", "u-model", "no")]
        items = self.run_graph(cat, SIZING)
        self.assertTrue(any("platform-team" in m and "not a unit" in m for m in messages(items, "WARN")), items)
        self.assertNotIn("FAIL", tags(items))

    def test_an_invalid_sizing_is_a_fail_and_no_waves(self):
        items = self.run_graph(CAT_CHAIN, SIZING.replace("\n## Reservations\nnone\n", "\n"))
        self.assertTrue(any("Reservations" in m for m in messages(items, "FAIL")))
        self.assertFalse(wave_of(items))

    def test_an_invalid_catalog_is_a_fail(self):
        c = self.write("catalog.md", "# Catalog\n\nNo table.\n")
        items = area.graph(c, None, None)
        self.assertTrue(messages(items, "FAIL"))


class TaskWavesWithoutASizing(Case):
    FROZEN = [("a-contract", "u-1", "yes"), ("b-contract", "u-1", "yes"), ("open-contract", "u-1", "no")]

    def test_tasks_sharing_only_frozen_contracts_share_wave_two(self):
        items = self.run_graph(self.FROZEN, None, [("T-001", ["a-contract"], [], "", "-"), ("T-002", ["a-contract", "b-contract"], [], "", "-"),
                                                   ("T-003", ["b-contract"], [], "", "-")])
        self.assertNotIn("FAIL", tags(items))
        self.assertNotIn("WARN", tags(items))
        self.assertEqual(wave_of(items), {"T-001": 2, "T-002": 2, "T-003": 2})

    def test_depends_edges_order_the_waves(self):
        items = self.run_graph(self.FROZEN, None, [("T-001", ["a-contract"], [], "", "-"), ("T-002", ["b-contract"], ["T-001"], "", "-"),
                                                   ("T-003", ["a-contract"], ["T-002"], "", "-")])
        self.assertEqual(wave_of(items), {"T-001": 2, "T-002": 3, "T-003": 4})

    def test_a_shared_unfrozen_contract_separates_tasks(self):
        items = self.run_graph(self.FROZEN, None, [("T-001", ["open-contract"], [], "", "-"), ("T-002", ["open-contract"], [], "", "-"),
                                                   ("T-003", ["a-contract"], [], "", "-")])
        self.assertEqual(wave_of(items), {"T-001": 2, "T-002": 3, "T-003": 2})

    def test_depends_justified_only_by_a_shared_frozen_contract_is_a_coupling_warn(self):
        items = self.run_graph(self.FROZEN, None, [("T-001", ["a-contract"], [], "", "-"), ("T-002", ["a-contract", "b-contract"], ["T-001"], "", "-")])
        warns = messages(items, "WARN")
        self.assertEqual(len(warns), 1, items)
        self.assertIn("coupling", warns[0])
        self.assertIn("a-contract", warns[0])
        self.assertNotIn("FAIL", tags(items))
        self.assertEqual(wave_of(items), {"T-001": 2, "T-002": 3})

    def test_a_cycle_is_a_fail_naming_the_cycle(self):
        items = self.run_graph(self.FROZEN, None, [("T-001", ["a-contract"], ["T-002"], "", "-"), ("T-002", ["a-contract"], ["T-001"], "", "-")])
        fails = messages(items, "FAIL")
        self.assertEqual(len(fails), 1, items)
        self.assertIn("cycle", fails[0])
        self.assertIn("T-001", fails[0])
        self.assertIn("T-002", fails[0])

    def test_an_unknown_depends_is_a_fail(self):
        items = self.run_graph(self.FROZEN, None, [("T-001", ["a-contract"], ["T-009"], "", "-")])
        self.assertTrue(any("T-009" in m for m in messages(items, "FAIL")), items)

    def test_a_contract_not_in_the_catalog_is_a_fail(self):
        items = self.run_graph(self.FROZEN, None, [("T-001", ["no-such-contract"], [], "", "-")])
        self.assertTrue(any("no-such-contract" in m and "not a row of the catalog" in m for m in messages(items, "FAIL")), items)

    def test_a_wave_column_that_differs_from_the_computed_wave_warns(self):
        items = self.run_graph(self.FROZEN, None, [("T-001", ["a-contract"], [], "5", "-")])
        warns = messages(items, "WARN")
        self.assertEqual(len(warns), 1, warns)
        self.assertIn("Wave column", warns[0])
        self.assertIn("T-001", warns[0])

    def test_an_invalid_tasks_table_is_a_fail_and_no_waves(self):
        c = self.write("catalog.md", catalog_text(self.FROZEN))
        t = self.write("tasks.md", "# Tasks\n\n| Task | Title |\n|---|---|\n| T-001 | x |\n")
        items = area.graph(c, None, t)
        self.assertTrue(messages(items, "FAIL"))
        self.assertFalse(wave_of(items))

    def test_a_missing_tasks_file_is_a_fail(self):
        c = self.write("catalog.md", catalog_text(self.FROZEN))
        items = area.graph(c, None, self.dir / "nope.md")
        self.assertTrue(messages(items, "FAIL"))


class TaskWavesWithASizing(Case):
    def test_a_task_runs_in_the_wave_of_its_unit(self):
        tasks = [("T-001", ["severity-score"], [], "", "u-model"), ("T-002", ["alert-event"], [], "", "u-pipeline"),
                 ("T-003", ["alert-list"], ["T-002"], "", "u-api")]
        items = self.run_graph(CAT_CHAIN, SIZING, tasks)
        msgs = [i["message"] for i in items if i["tag"] == "OK" and i["message"].startswith("task ")]
        self.assertIn("task T-001 runs in unit u-model (wave 2)", msgs)
        self.assertIn("task T-002 runs in unit u-pipeline (wave 3)", msgs)
        self.assertIn("task T-003 runs in unit u-api (wave 4)", msgs)

    def test_a_task_naming_an_unknown_unit_is_a_fail(self):
        items = self.run_graph(CAT_CHAIN, SIZING, [("T-001", ["alert-event"], [], "", "u-zzz")])
        self.assertTrue(any("u-zzz" in m for m in messages(items, "FAIL")), items)

    def test_a_task_without_a_unit_is_ordered_in_the_same_numbering(self):
        items = self.run_graph(CAT_CHAIN, SIZING, [("T-001", ["alert-event"], [], "", "-")])
        self.assertIn("task T-001 runs in wave 2", [i["message"] for i in items])

    def test_a_task_that_depends_on_a_task_of_a_later_wave_is_a_fail(self):
        tasks = [("T-001", ["severity-score"], ["T-002"], "", "u-model"), ("T-002", ["alert-event"], [], "", "u-pipeline")]
        items = self.run_graph(CAT_CHAIN, SIZING, tasks)
        self.assertTrue(any("T-001" in m and "T-002" in m and "later" in m for m in messages(items, "FAIL")), items)

    def test_a_dependency_inside_one_unit_is_fine(self):
        tasks = [("T-001", ["alert-event"], [], "", "u-pipeline"), ("T-002", ["severity-score"], ["T-001"], "", "u-pipeline")]
        items = self.run_graph(CAT_CHAIN, SIZING, tasks)
        self.assertNotIn("FAIL", tags(items))
        self.assertNotIn("WARN", [t for t in tags(items)])

    def test_a_task_using_a_contract_its_unit_neither_depends_on_nor_owns_warns(self):
        items = self.run_graph(CAT_CHAIN, SIZING, [("T-001", ["alert-list"], [], "", "u-model")])
        self.assertTrue(any("alert-list" in m and "neither depends on nor owns" in m for m in messages(items, "WARN")), items)

    def test_a_dependency_between_parallel_units_in_one_wave_warns_of_coupling(self):
        cat = [("alert-event", "u-pipeline", "yes"), ("alert-list", "u-api", "yes"), ("severity-score", "u-model", "yes")]
        tasks = [("T-001", ["alert-event"], [], "", "u-pipeline"), ("T-002", ["alert-event"], ["T-001"], "", "u-api")]
        items = self.run_graph(cat, SIZING, tasks)
        self.assertTrue(any("coupling" in m and "T-002" in m for m in messages(items, "WARN")), items)


class OneNumbering(Case):
    def test_unit_waves_and_task_waves_share_the_numbering(self):
        tasks = [("T-001", ["severity-score"], [], "", "u-model"), ("T-002", ["alert-event"], [], "", "-")]
        items = self.run_graph(CAT_CHAIN, SIZING, tasks)
        self.assertEqual(wave_of(items)["u-model"], 2)
        self.assertIn("task T-001 runs in unit u-model (wave 2)", [i["message"] for i in items])
        self.assertIn("task T-002 runs in wave 2", [i["message"] for i in items])

    def test_compute_waves_starts_at_the_base(self):
        t = [{"Task": "T-001", "Contracts": [], "Depends": []}, {"Task": "T-002", "Contracts": [], "Depends": ["T-001"]}]
        w, _ = area.compute_waves(t, set())
        self.assertEqual(w, {"T-001": 2, "T-002": 3})
        w, _ = area.compute_waves(t, set(), base=1)
        self.assertEqual(w, {"T-001": 1, "T-002": 2})


if __name__ == "__main__":
    unittest.main()

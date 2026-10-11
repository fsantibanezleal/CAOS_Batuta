"""Walk contracts/fixtures: every fixture must validate (or fail) as its name says, for the stated reason."""
import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins" / "harness" / "scripts"))

from harness_lib import contract  # noqa: E402

CONTRACTS = ROOT / "contracts"
IDS = [f"C{n:02d}" for n in range(1, 30)]
MD_IDS = {"C02", "C03", "C05", "C09", "C10", "C18", "C19", "C21", "C22", "C24"}
# Contracts whose artifacts are not harness-owned files and carry no contract_version of their own.
NO_ARTIFACT_VERSION = {"C16", "C14", "C02", "C03", "C05", "C09", "C10", "C18", "C19", "C21", "C22", "C24"}
UNKNOWN_KEYS_REJECTED = {"C04", "C06", "C07", "C08"}


def schema_path(cid):
    found = sorted(CONTRACTS.glob(f"{cid}-*.schema.json"))
    return found[0] if len(found) == 1 else None


def fixtures(cid, kind):
    d = CONTRACTS / "fixtures" / cid
    return sorted(p for p in d.glob(f"{kind}-*") if p.is_file())


class EveryContractIsPresent(unittest.TestCase):
    def test_c01_to_c29_each_have_one_schema_and_enough_fixtures(self):
        for cid in IDS:
            with self.subTest(contract=cid):
                self.assertIsNotNone(schema_path(cid), f"{cid} schema file missing")
                self.assertGreaterEqual(len(fixtures(cid, "valid")), 2, f"{cid} needs >= 2 valid fixtures")
                self.assertGreaterEqual(len(fixtures(cid, "invalid")), 3, f"{cid} needs >= 3 invalid fixtures")

    def test_schema_metadata_matches_the_file_name_and_version(self):
        for cid in IDS:
            with self.subTest(contract=cid):
                s = json.loads(schema_path(cid).read_text(encoding="utf-8"))
                self.assertEqual(s["contract_id"], cid)
                self.assertEqual(s["contract_version"], "1.0")

    def test_every_schema_loads_in_the_supported_subset(self):
        for cid in IDS:
            with self.subTest(contract=cid):
                contract.load_schema(schema_path(cid))

    def test_markdown_contracts_have_a_sections_file_and_json_ones_do_not(self):
        for cid in IDS:
            with self.subTest(contract=cid):
                has = bool(list(CONTRACTS.glob(f"{cid}-*.sections.json")))
                self.assertEqual(has, cid in MD_IDS)

    def test_json_contracts_require_contract_version_in_the_artifact(self):
        for cid in IDS:
            if cid in NO_ARTIFACT_VERSION or cid == "C04":
                continue
            with self.subTest(contract=cid):
                s = json.loads(schema_path(cid).read_text(encoding="utf-8"))
                self.assertIn("contract_version", s["required"])
                self.assertEqual(s["properties"]["contract_version"]["const"], "1.0")

    def test_c04_lines_require_contract_version(self):
        s = json.loads(schema_path("C04").read_text(encoding="utf-8"))
        self.assertIn("contract_version", s["required"])

    def test_integrity_records_reject_unknown_keys(self):
        for cid in UNKNOWN_KEYS_REJECTED:
            with self.subTest(contract=cid):
                s = json.loads(schema_path(cid).read_text(encoding="utf-8"))
                self.assertIs(s["additionalProperties"], False)
                self.assertTrue(any("unknown-key" in p.name for p in fixtures(cid, "invalid")))


class FixturesBehaveAsLabeled(unittest.TestCase):
    def test_valid_fixtures_validate(self):
        for cid in IDS:
            sp = schema_path(cid)
            for fx in fixtures(cid, "valid"):
                with self.subTest(fixture=f"{cid}/{fx.name}"):
                    self.assertEqual(contract.validate_file(fx, sp), [])

    def test_invalid_fixtures_fail_for_the_stated_reason(self):
        for cid in IDS:
            sp = schema_path(cid)
            for fx in fixtures(cid, "invalid"):
                with self.subTest(fixture=f"{cid}/{fx.name}"):
                    why, expect = contract.fixture_meta(fx)
                    self.assertTrue(why, "an invalid fixture states which rule it breaks")
                    out = contract.validate_file(fx, sp)
                    self.assertTrue(out, "an invalid fixture must produce at least one error")
                    if expect:
                        self.assertTrue(any(expect in e for e in out), f"expected {expect!r} in {out}")

    def test_no_fixture_has_another_name_shape(self):
        for cid in IDS:
            d = CONTRACTS / "fixtures" / cid
            for p in d.iterdir():
                with self.subTest(fixture=f"{cid}/{p.name}"):
                    self.assertTrue(p.name.startswith(("valid-", "invalid-")))


class KnownSemanticChecks(unittest.TestCase):
    """Rules a plain schema cannot say, enforced by contract.validate_file for the contracts that need them."""

    def load(self, cid, name):
        return json.loads((CONTRACTS / "fixtures" / cid / name).read_text(encoding="utf-8"))

    def test_c12_cycle_and_conditional_requirements(self):
        sp = schema_path("C12")
        doc = self.load("C12", "valid-three-units.json")
        self.assertEqual(contract.validate_instance("C12", doc, contract.load_schema(sp)), [])
        doc["units"][0]["requires"] = ["deploy-vps"]
        self.assertTrue(any("cycle" in e for e in contract.validate_instance("C12", doc, contract.load_schema(sp))))

    def test_c26_needs_a_fixture_or_baseline_provider(self):
        sp = contract.load_schema(schema_path("C26"))
        doc = self.load("C26", "valid-fixture-active.json")
        self.assertEqual(contract.validate_instance("C26", doc, sp), [])
        doc["interfaces"][0]["providers"] = [doc["interfaces"][0]["providers"][0]]
        doc["interfaces"][0]["active"] = doc["interfaces"][0]["providers"][0]["name"]
        self.assertTrue(any("fixture or baseline" in e for e in contract.validate_instance("C26", doc, sp)))

    def test_c16_dispatches_on_the_payload_shape(self):
        sp = contract.load_schema(schema_path("C16"))
        self.assertEqual(contract.validate_instance("C16", {"decision": "block", "reason": "r"}, sp), [])
        self.assertTrue(contract.validate_instance("C16", {"decision": "block"}, sp))


if __name__ == "__main__":
    unittest.main()

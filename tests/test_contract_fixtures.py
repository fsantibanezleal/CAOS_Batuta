"""Walk contracts/fixtures: every fixture must validate (or fail) as its name says, for the stated reason."""
import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins" / "batuta" / "scripts"))

from batuta_lib import contract  # noqa: E402

CONTRACTS = ROOT / "plugins" / "batuta" / "contracts"
IDS = [f"C{n:02d}" for n in range(1, 33)]
MD_IDS = {"C02", "C03", "C05", "C09", "C10", "C18", "C19", "C21", "C22", "C23", "C24"}
STATES = ["available", "partial", "stale", "provider", "training", "missing"]
RINGS = ["adopt", "trial", "assess", "caution"]
MODEL_STATUS = ["planned", "training", "candidate", "released", "retired"]
# Contracts whose artifacts are not batuta-owned files and carry no contract_version of their own.
NO_ARTIFACT_VERSION = {"C16", "C14", "C27", "C31", "C32", "C02", "C03", "C05", "C09", "C10", "C18", "C19", "C21", "C22", "C23", "C24"}
UNKNOWN_KEYS_REJECTED = {"C04", "C06", "C07", "C08", "C27"}


def schema_path(cid):
    found = sorted(CONTRACTS.glob(f"{cid}-*.schema.json"))
    return found[0] if len(found) == 1 else None


def fixtures(cid, kind):
    d = CONTRACTS / "fixtures" / cid
    return sorted(p for p in d.glob(f"{kind}-*") if p.is_file())


class EveryContractIsPresent(unittest.TestCase):
    def test_c01_to_c32_each_have_one_schema_and_enough_fixtures(self):
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

    def test_c26_dispatches_on_the_document_shape(self):
        sp = contract.load_schema(schema_path("C26"))
        self.assertEqual(contract.validate_instance("C26", self.load("C26", "valid-runtime-missing.json"), sp), [])
        self.assertEqual(contract.validate_instance("C26", self.load("C26", "valid-declaration-absent-components.json"), sp), [])
        self.assertTrue(any("declaration" in e for e in contract.validate_instance("C26", {"x": 1}, sp)))

    def test_c26_an_absent_component_needs_available_and_one_other_state_each_with_a_test(self):
        sp = contract.load_schema(schema_path("C26"))
        doc = self.load("C26", "valid-declaration-absent-components.json")
        doc["components"][0]["states"] = [doc["components"][0]["states"][0]]
        self.assertTrue(any("non-available" in e for e in contract.validate_instance("C26", doc, sp)))

    def test_c26_age_is_null_only_for_available_and_missing(self):
        sp = contract.load_schema(schema_path("C26"))
        for state in ("partial", "stale", "provider", "training"):
            with self.subTest(state=state):
                blk = {"state": state, "reason": "r", "source": "s", "age": None}
                self.assertTrue(any("age" in e for e in contract.validate_instance("C26", blk, sp)))
        for state in ("available", "missing"):
            with self.subTest(state=state):
                blk = {"state": state, "reason": None if state == "available" else "r", "source": "s", "age": None}
                self.assertEqual(contract.validate_instance("C26", blk, sp), [])

    def test_c28_serving_must_say_who_answered_when_the_model_is_not_released(self):
        sp = contract.load_schema(schema_path("C28"))
        doc = self.load("C28", "valid-training-served-by-baseline.json")
        self.assertEqual(contract.validate_instance("C28", doc, sp), [])
        del doc["serving"]
        self.assertTrue(any("serving" in e for e in contract.validate_instance("C28", doc, sp)))

    def test_c27_accepts_the_product_template_readiness_fixture(self):
        sp = contract.load_schema(schema_path("C27"))
        doc = self.load("C27", "valid-template-readiness.json")
        self.assertEqual(contract.validate_instance("C27", doc, sp), [])

    def test_c16_dispatches_on_the_payload_shape(self):
        sp = contract.load_schema(schema_path("C16"))
        self.assertEqual(contract.validate_instance("C16", {"decision": "block", "reason": "r"}, sp), [])
        self.assertTrue(contract.validate_instance("C16", {"decision": "block"}, sp))


class AlignedVocabulary(unittest.TestCase):
    """Batuta speaks the vocabulary of the dimensioned contract-first method (availability states, rings)."""

    def schema(self, cid):
        return json.loads(schema_path(cid).read_text(encoding="utf-8"))

    def test_c26_state_enum_is_the_six_states_in_order(self):
        self.assertEqual(self.schema("C26")["$defs"]["state"]["enum"], STATES)

    def test_c26_has_the_declaration_and_the_runtime_block_in_one_file(self):
        defs = self.schema("C26")["$defs"]
        self.assertEqual(sorted(defs["runtime_block"]["required"]), ["age", "reason", "source", "state"])
        self.assertEqual(sorted(defs["state_declaration"]["required"]),
                         ["adapter_returns", "response_block", "state", "test", "ui_shows"])
        names = [p.name for p in fixtures("C26", "valid")]
        self.assertTrue(any("runtime" in n for n in names))
        self.assertTrue(any("declaration" in n for n in names))

    def test_c27_states_are_exactly_the_six_states_with_no_alias(self):
        self.assertEqual(self.schema("C27")["$defs"]["entry"]["properties"]["state"]["enum"], STATES)

    def test_rings_are_adopt_trial_assess_caution(self):
        self.assertEqual(self.schema("C25")["properties"]["ring"]["enum"], RINGS)

    def test_c28_status_is_the_registry_enum(self):
        self.assertEqual(self.schema("C28")["properties"]["status"]["enum"], MODEL_STATUS)


class SchemaMetadata(unittest.TestCase):
    def test_root_metadata_keys_are_accepted_and_nowhere_else(self):
        root = {"$schema": "https://json-schema.org/draft/2020-12/schema", "$id": "x", "title": "T", "contract_id": "CX",
                "contract_version": "1.0", "type": "object"}
        self.assertEqual(contract.check_schema(root), [])
        nested = {"type": "object", "properties": {"a": {"type": "string", "contract_id": "CX"}}}
        self.assertTrue(any("contract_id" in e for e in contract.check_schema(nested)))


class C16FixturesAreLabelledSynthetic(unittest.TestCase):
    def test_every_c16_fixture_states_it_was_not_recorded(self):
        files = sorted((CONTRACTS / "fixtures" / "C16").glob("*.json"))
        self.assertTrue(files)
        for fx in files:
            with self.subTest(fixture=fx.name):
                self.assertIs(json.loads(fx.read_text(encoding="utf-8")).get("_recorded"), False)

    def test_the_label_is_not_part_of_the_validated_payload(self):
        sp = schema_path("C16")
        self.assertEqual(contract.validate_file(CONTRACTS / "fixtures" / "C16" / "valid-input-stop.json", sp), [])


if __name__ == "__main__":
    unittest.main()

"""Shared builder of a small, valid project for the U3 tests (sizing, catalog, ADR, tech decision, spec, tasks, tests).

The module holds no test; the suites of the size, tech, adr and spec areas import `make_project` and `run`.
Every file is generic content: a telemetry alert service, nothing private.
"""
import contextlib
import hashlib
import io
import json
import os
import sys
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "plugins" / "batuta" / "scripts"))
from _support import load_batuta  # noqa: E402

CONTRACTS = ROOT / "plugins" / "batuta" / "contracts"
SPEC_ID = "001-alerts"
TODAY = "2026-10-13"

SIZING = """# Sizing: Telemetry alert triage

## Problem
A service reads equipment telemetry files, raises alerts, and shows them to operators in a web page.

## Executive brief
- Initiative: reduce missed equipment alerts by 40 percent for plant operators (https://example.org/study-2026).
- Outcomes: operators see every alert with its provenance within one minute of arrival.
- Positioning: a small service for teams that run telemetry fleets without a monitoring suite.
- Credibility: built from the maintainers' own incident reviews and a recorded fleet sample.

## ADR constraints
- ADR-0001 (alert transport): no deviation.

## Repositories
- alert-triage: the product repository.

## Components
- ingest-pipeline (alert-triage): reads telemetry files and writes alert events (unit: u-pipeline).
- alerts-api (alert-triage): serves alerts over HTTP (unit: u-api).

## Modules and functions

| Module | Responsibility | Owner unit | Size estimate |
|---|---|---|---|
| pipeline/ingest.py | read telemetry files and emit alert events | u-pipeline | 6 functions |
| pipeline/score.py | score alerts | u-pipeline | 3 functions |
| api/routes.py | serve alerts | u-api | 8 functions |

## Boundaries

| ID | Producer | Consumer | Contract ID |
|---|---|---|---|
| B1 | ingest-pipeline | alerts-api | alert-event |
| B2 | alerts-api | ops-ui | alert-list |

## Technology matrix

| Tool | Version | Primary source URL | Verified date |
|---|---|---|---|
| Python | 3.13.1 | https://docs.python.org/3.13/ | 2026-10-12 |
| FastAPI | 0.115.2 | https://fastapi.tiangolo.com/ | 2026-10-12 |

## Machine limits
Any laptop; telemetry batches are capped at 200 MB.

## Parallel units

| Unit | Write scope | Depends on contract ids |
|---|---|---|
| u-pipeline | pipeline/, tests/pipeline/ | alert-event |
| u-api | api/, tests/api/ | alert-event, alert-list |

## Integrator and merge order
The main session merges: u-pipeline, then u-api.

## Reservations
none
"""

CATALOG_HEAD = ("# Contract catalog: Telemetry alert triage\n\n| id | version | owner | schema file | example | producer test | "
                "consumer test | missing-data behavior | provider | model io | swap test | status | frozen |\n"
                "|---|---|---|---|---|---|---|---|---|---|---|---|---|\n")


def catalog_row(cid, frozen="yes"):
    return (f"| {cid} | 1.0.0 | u-pipeline | docs/contracts/{cid}.schema.json | docs/contracts/examples/{cid}.json | "
            f"tests/contracts/test_{cid}_producer.py | tests/contracts/test_{cid}_consumer.py | available: use the real "
            f"producer (test: tests/contracts/test_{cid}_consumer.py::test_available); missing: show no data "
            f"(test: tests/contracts/test_{cid}_consumer.py::test_missing) | fixture:tests/fixtures/{cid}.json | - | "
            f"tests/contracts/test_{cid}_swap.py | active | {frozen} |\n")


ADR = """---
id: ADR-0001
title: Alert transport
status: Accepted
date: 2026-10-01
deciders: [alex]
review_trigger: review-by: 2027-04-01
tech_evaluations: [fastapi]
---

## Context

Alerts need an HTTP transport.

## Decision

Use FastAPI.

## Alternatives considered

Flask.

## Consequences

Typed models.

## Validation

docs/design/tech/fastapi.json
"""

TECH = {
    "contract_version": "1.0", "tool": "FastAPI", "version": "0.115.2", "primary_source_url": "https://fastapi.tiangolo.com/",
    "verified_date": "2026-10-12", "ring": "adopt", "adr": "ADR-0001",
    "evaluation": {"concern": "HTTP API framework", "chosen": "FastAPI", "candidates": [{
        "name": "FastAPI", "version": "0.115.2", "source_url": "https://fastapi.tiangolo.com/", "verified": "2026-10-12",
        "license": "MIT", "maturity": {"last_release": "2026-09-30", "maintainers": 3, "stars": 80000},
        "maintenance": "monthly releases", "size": "40 dependencies", "fit": "typed models", "risks": []}]},
}

SPEC = """---
id: 001-alerts
title: Alerts
status: Review
tier: M
owner: alex
created: 2026-10-13
---

## Problem

Operators miss alerts. Decision context: ADR-0001.

## Scope and out of scope

In: ingest and serve. Out: notifications.

## Requirements

| Id | Kind | EARS text | Gate | Verification | Status |
|---|---|---|---|---|---|
| REQ-ALR-001 | ubiquitous | The pipeline shall emit one alert event per breached limit. | `pytest tests/test_alerts.py` | unit test | active |
| REQ-ALR-002 | event | When an alert arrives, the API shall list it within one second. | tests/test_alerts.py::test_listing | unit test | active |
| REQ-ALR-003 | unwanted | If a file is malformed, then the pipeline shall skip it and log a warning. | `node --test tests/api.test.js` | unit test | active |

## Interfaces

- alert-event: produced by the pipeline, consumed by the API.
- alert-list: produced by the API, consumed by the page.

## Edge cases

Empty file.

## Open questions

None.
"""

TASKS = """# Tasks

| Task | Title | Requirements | Contracts | Depends | Wave | Owner role | Unit |
|---|---|---|---|---|---|---|---|
| T-001 | Emit alert events | REQ-ALR-001, REQ-ALR-003 | alert-event | - | 2 | implementer | u-pipeline |
| T-002 | List alerts | REQ-ALR-002 | alert-list | T-001 | 3 | implementer | u-api |
"""

PLAN = """# Plan: Alerts

## Constitution check

| Decision | Constitution article | Simpler alternative rejected |
|---|---|---|
| Events as files | Art. 1 | One shared database: couples the units |

## Design

Pipeline writes events; the API reads them.
"""

TEST_PY = """# REQ: REQ-ALR-001
def test_emit():
    assert True


# REQ: REQ-ALR-002
def test_listing():
    assert True
"""

TEST_JS = """// REQ: REQ-ALR-003
const test = require('node:test');
test('skips a malformed file', () => {});
"""


def write(root, rel, text, newline="\n"):
    p = Path(root) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(text.replace("\n", newline).encode("utf-8"))
    return p


def sha(path):
    return hashlib.sha256(Path(path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def make_project(root, frozen=("alert-event", "alert-list")):
    """Write the whole project under `root`; returns the root as a Path."""
    root = Path(root)
    write(root, ".batuta/sizing.md", SIZING)
    write(root, "docs/contracts/catalog.md", CATALOG_HEAD + "".join(catalog_row(c, "yes" if c in frozen else "no")
                                                                     for c in ("alert-event", "alert-list")))
    for cid in ("alert-event", "alert-list"):
        write(root, f"docs/contracts/{cid}.schema.json", json.dumps({"title": cid, "type": "object"}, indent=2) + "\n")
    write(root, "docs/decisions/ADR-0001-alert-transport.md", ADR)
    write(root, "docs/design/tech/fastapi.json", json.dumps(TECH, indent=2) + "\n")
    write(root, f"specs/{SPEC_ID}/spec.md", SPEC)
    write(root, f"specs/{SPEC_ID}/tasks.md", TASKS)
    write(root, f"specs/{SPEC_ID}/plan.md", PLAN)
    write(root, f"specs/{SPEC_ID}/test-change-requests.md",
          "# Test change requests: 001-alerts\n\n| Id | Date | Test path | Requirement | Reason | Proposed change | Status | Decided by |\n"
          "|---|---|---|---|---|---|---|---|\n")
    write(root, "specs/000-foundation/constitution.md", "# Constitution\n\n## Article 1: Real, not demo\nBuild the real thing.\n")
    write(root, "tests/test_alerts.py", TEST_PY)
    write(root, "tests/api.test.js", TEST_JS)
    return root


def run(*argv, stdin=None, cwd=None):
    """Run the CLI in process; returns (exit code, stdout, stderr). BATUTA_HOME points at a folder that does not exist."""
    batuta = load_batuta()
    out, err = io.StringIO(), io.StringIO()
    env = {"BATUTA_HOME": str(ROOT / "no-such-home"), "BATUTA_CONFIG": ""}
    stdin_obj = io.StringIO(stdin) if stdin is not None else io.StringIO("")
    old = os.getcwd()
    try:
        if cwd:
            os.chdir(cwd)
        with mock.patch.dict(os.environ, env), mock.patch.object(sys, "stdin", stdin_obj), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = batuta.main([str(a) for a in argv])
    finally:
        os.chdir(old)
    return code, out.getvalue(), err.getvalue()


def run_json(*argv, **kw):
    code, out, err = run(*argv, "--json", **kw)
    return code, json.loads(out), err


def messages(doc, tag=None):
    return [i["message"] for i in doc["items"] if tag is None or i["tag"] == tag]


def prefix_of(path):
    return sha(path)[:12]

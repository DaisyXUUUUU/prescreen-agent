"""Engine tests.

Expected statuses follow mechanically from the fixture data and the predicate
(e.g. LDL 162.4 >= 100 -> met). They test the engine's arithmetic and rules,
not clinical labels: patient-level ground truth comes from Ming (T11).
Injected-case tests below are engineering's own until Ming's list arrives.
"""

import copy
import json
from pathlib import Path

import pytest

from src.adapters import fhir_store
from src.adapters.fhir_store import FhirStore, QueryResult
from src.engine.evaluate import Verdict, evaluate, judge
from src.engine.units import to_unit

FIX = Path(__file__).parent / "fixtures"
DATE = "2026-10-09"
PREDS = {p["criterion_id"]: p for p in json.loads((FIX / "sample_predicates.json").read_text())["predicates"]}


@pytest.fixture(autouse=True)
def fixture_store():
    fhir_store.set_store(FhirStore(FIX / "patients"))
    yield
    fhir_store.set_store(FhirStore(FIX / "patients"))


def run(cid, pid):
    return evaluate(PREDS[cid], pid, DATE)


# ---------- sample predicates on the three fixture patients ----------

EXPECTED = {
    "fixture-complete": {"S-I1": ("met", ["fixture-complete"]), "S-I2": ("met", ["fixture-complete"]),
                         "S-I3": ("met", ["c-101"]), "S-I4": ("met", ["c-102"]), "S-I5": ("met", ["o-101"]),
                         "S-E1": ("not_met", ["o-103"]), "S-E2": ("not_met", ["o-104"]),
                         "S-E3": ("not_met", ["m-101"]), "S-N1": ("unknown", [])},
    "fixture-over-age": {"S-I1": ("met", ["fixture-over-age"]), "S-I2": ("not_met", ["fixture-over-age"]),
                         "S-I3": ("met", ["c-201"]), "S-I4": ("met", ["c-202"]), "S-I5": ("met", ["o-201"]),
                         "S-E1": ("unknown", []), "S-E2": ("not_met", ["o-202"]),
                         "S-E3": ("not_met", []), "S-N1": ("unknown", [])},
    "fixture-missing-ldl": {"S-I1": ("met", ["fixture-missing-ldl"]), "S-I2": ("met", ["fixture-missing-ldl"]),
                            "S-I3": ("met", ["c-301"]), "S-I4": ("met", ["c-302"]), "S-I5": ("unknown", []),
                            "S-E1": ("unknown", []), "S-E2": ("not_met", ["o-301"]),
                            "S-E3": ("not_met", []), "S-N1": ("unknown", [])},
}


@pytest.mark.parametrize("pid,cid", [(p, c) for p, cs in EXPECTED.items() for c in cs])
def test_sample_predicates_on_fixtures(pid, cid):
    v = run(cid, pid)
    status, ids = EXPECTED[pid][cid]
    assert v.status == status, v.note
    assert [e["resource_id"] for e in v.evidence] == ids


def test_missing_lab_flags_recovery():
    v = run("S-I5", "fixture-missing-ldl")
    assert v.needs_recovery and v.trace[-1]["tool"] == "rule:absence_means"


def test_stopped_medication_is_not_counted():
    v = run("S-E3", "fixture-complete")  # simvastatin is stopped; only HCTZ is active and listed
    assert "1 distinct" in v.note


def test_deterministic():
    assert run("S-I5", "fixture-complete").to_dict() == run("S-I5", "fixture-complete").to_dict()


def test_blocking_defaults_true_and_can_be_overridden():
    assert run("S-I5", "fixture-complete").blocking is True
    p = {**PREDS["S-I5"], "blocking": False}
    assert evaluate(p, "fixture-complete", DATE).blocking is False


def test_every_verdict_has_trace():
    for cid in PREDS:
        assert run(cid, "fixture-complete").trace


# ---------- injected cases (engineering placeholders for Ming's list) ----------

def store_with_ldl(tmp_path, *values):
    """fixture-complete with its LDL observations replaced by (value, unit, date) tuples."""
    bundle = json.loads((FIX / "patients" / "fixture-complete.json").read_text())
    template = next(e for e in bundle["entry"] if e["resource"]["id"] == "o-101")
    bundle["entry"] = [e for e in bundle["entry"] if e["resource"]["id"] not in ("o-101", "o-102")]
    for i, (value, unit, when) in enumerate(values):
        e = copy.deepcopy(template)
        e["resource"]["id"] = f"ldl-{i}"
        e["resource"]["valueQuantity"] = {"value": value, "unit": unit}
        e["resource"]["effectiveDateTime"] = when
        bundle["entry"].append(e)
    (tmp_path / "p.json").write_text(json.dumps(bundle))
    fhir_store.set_store(FhirStore(tmp_path))
    return lambda pred=PREDS["S-I5"]: evaluate(pred, "fixture-complete", DATE)


def test_boundary_value_equal_to_threshold_is_met(tmp_path):
    v = store_with_ldl(tmp_path, (100, "mg/dL", "2026-09-01"))()
    assert v.status == "met" and v.evidence[0]["resource_id"] == "ldl-0"


def test_just_below_threshold_is_not_met(tmp_path):
    assert store_with_ldl(tmp_path, (99.9, "mg/dL", "2026-09-01"))().status == "not_met"


def test_mmol_converted_before_comparison(tmp_path):
    v = store_with_ldl(tmp_path, (4.2, "mmol/L", "2026-09-01"))()  # 4.2 * 38.67 = 162.41
    assert v.status == "met"
    assert any(t["tool"] == "rule:unit_convert" and "converted" in t["result"] for t in v.trace)


def test_conversion_landing_on_boundary_is_stable(tmp_path):
    assert store_with_ldl(tmp_path, (2.586, "mmol/L", "2026-09-01"))().status == "met"  # 100.0006 -> 100.0


def test_unrecognised_unit_is_unknown(tmp_path):
    v = store_with_ldl(tmp_path, (160, "g/L", "2026-09-01"))()
    assert v.status == "unknown" and "cannot convert" in v.note
    assert v.evidence[0]["resource_id"] == "ldl-0"  # CRC still sees which record was rejected


def test_implausible_value_is_unknown(tmp_path):
    v = store_with_ldl(tmp_path, (1620, "mg/dL", "2026-09-01"))()
    assert v.status == "unknown" and "outside plausible range" in v.note


def test_bad_latest_value_does_not_fall_back_to_older(tmp_path):
    v = store_with_ldl(tmp_path, (1620, "mg/dL", "2026-09-01"), (150, "mg/dL", "2026-03-01"))()
    assert v.status == "unknown"


def test_record_outside_window_is_ignored(tmp_path):
    v = store_with_ldl(tmp_path, (150, "mg/dL", "2025-06-01"))()  # > 365 days before screening
    assert v.status == "unknown" and v.needs_recovery


def test_mean_of_last_3(tmp_path):
    run_ = store_with_ldl(tmp_path, (90, "mg/dL", "2026-09-01"), (100, "mg/dL", "2026-06-01"),
                          (113, "mg/dL", "2026-03-01"), (300, "mg/dL", "2026-01-01"))
    v = run_({**PREDS["S-I5"], "aggregation": "mean_of_last_3"})
    assert v.status == "met" and "mean of last 3 = 101" in v.note
    assert [e["resource_id"] for e in v.evidence] == ["ldl-0", "ldl-1", "ldl-2"]


# ---------- rules that never touch data ----------

def test_index_event_anchor_not_yet_supported():
    p = {**PREDS["S-I5"], "anchor": {"event": "index_event", "direction": "after"}}
    assert evaluate(p, "fixture-complete", DATE).status == "unknown"


def test_unsupported_operator_is_unknown():
    p = {**PREDS["S-I5"], "operator": "no_change"}
    assert "not implemented" in evaluate(p, "fixture-complete", DATE).note


def test_malformed_query_is_unknown_without_recovery():
    v = judge(PREDS["S-I5"], QueryResult("malformed", detail="bad bundle"), Verdict("x", "S-I5"), DATE)
    assert v.status == "unknown" and not v.needs_recovery


def test_judge_accepts_records_recovered_by_agent():
    """T7 path: the agent finds a record under another code; the engine still does the comparison."""
    rec = {"resource_id": "o-alt", "code": "13457-7", "value": 3.1, "unit": "mmol/L", "date": "2026-09-01"}
    v = judge(PREDS["S-I5"], QueryResult("ok", [rec]), Verdict("x", "S-I5"), DATE)
    assert v.status == "met" and v.evidence[0]["resource_id"] == "o-alt"  # 3.1 mmol/L = 119.88 mg/dL


def test_resource_inferred_from_code_system():
    p = {k: v for k, v in PREDS["S-I3"].items() if k != "resource"}
    assert evaluate(p, "fixture-complete", DATE).status == "met"


@pytest.mark.parametrize("value,unit,code,expected", [
    (4.2, "mmol/L", "18262-1", 162.41),
    (2.0, "mmol/L", "2571-8", 177.14),
    (142, "mm[Hg]", "8480-6", 142.0),
    (50, "IU/L", "1742-6", 50.0),
])
def test_units_table(value, unit, code, expected):
    assert to_unit(value, unit, code, None).value == expected

import copy
import json
from pathlib import Path

import pytest

from src import config, failures
from src.adapters import fhir_store
from src.adapters.fhir_store import FhirStore
from src.agent import agent as ag
from src.engine.evaluate import evaluate

FIX = Path(__file__).parent / "fixtures"
DATE = "2026-10-09"
PREDS = {p["criterion_id"]: p for p in json.loads((FIX / "sample_predicates.json").read_text())["predicates"]}


@pytest.fixture
def store(monkeypatch):
    monkeypatch.setattr(config, "FAILURES", {k: False for k in config.FAILURES})
    monkeypatch.setattr(config, "FAILURE_TARGETS", {})
    s = FhirStore(FIX / "patients")
    fhir_store.set_store(s)
    return s


def test_all_switches_off_changes_nothing(store):
    before = copy.deepcopy(store.index)
    assert failures.inject(store) == []
    assert store.index == before


def test_drop_codes_empties_rule_query_and_agent_recovers(store):
    config.enable_failure("drop_codes")
    lines = [i["text"] for i in failures.inject(store)]
    assert lines == ["drop_codes: fixture-complete LDL-C o-101, o-102 recoded 18262-6 -> 2089-1"]

    v = evaluate(PREDS["S-I5"], "fixture-complete", DATE)
    assert v.status == "unknown" and v.needs_recovery

    case = ag.RecoveryCase("fixture-complete", PREDS["S-I5"], DATE)
    t = {x.tool_spec["name"]: x for x in ag.build_tools(case)}
    t["lookup_equivalent_codes"]()
    q = t["fhir_query_codes"](codes=["2089-1"])
    t["evaluate_with_records"](resource_ids=[q["records"][0]["resource_id"]])
    r = ag.finalize(v, case, "")
    assert r.status == "met" and r.evidence[0]["resource_id"] == "o-101"


def test_bad_units_convertible_and_implausible(store):
    config.enable_failure("bad_units")
    lines = [i["text"] for i in failures.inject(store)]
    assert lines == ["bad_units: fixture-complete LDL-C o-101 162.4 mg/dL -> 4.2 mmol/L",
                     "bad_units: fixture-over-age LDL-C o-201 148 mg/dL -> 1480 mg/dL"]

    converted = evaluate(PREDS["S-I5"], "fixture-complete", DATE)
    assert converted.status == "met"
    assert any(e["tool"] == "rule:unit_convert" for e in converted.trace)

    junk = evaluate(PREDS["S-I5"], "fixture-over-age", DATE)
    assert junk.status == "unknown" and not junk.needs_recovery
    assert "outside plausible range" in junk.note and junk.trace[-1]["tool"] == "rule:unit_check"


def test_switches_pick_distinct_patients(store):
    config.enable_failure("drop_codes")
    config.enable_failure("bad_units")
    assert [i["patient_id"] for i in failures.inject(store)] == ["fixture-complete", "fixture-over-age"]


def test_explicit_targets_from_config(store, monkeypatch):
    monkeypatch.setattr(config, "FAILURE_TARGETS", {"drop_codes": ["fixture-over-age"]})
    config.enable_failure("drop_codes")
    assert failures.inject(store)[0]["patient_id"] == "fixture-over-age"


def test_unknown_switch_rejected():
    with pytest.raises(ValueError):
        config.enable_failure("disk_full")

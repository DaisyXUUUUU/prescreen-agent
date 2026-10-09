"""Recovery agent tests without a model: the tools and the merge logic are plain code.

The live behaviour with Nova 2 Lite is checked by hand (see the T7 acceptance run).
"""

import json
from pathlib import Path

import pytest
from strands.hooks import BeforeToolCallEvent

from src.adapters import fhir_store
from src.adapters.fhir_store import FhirStore
from src.agent import agent as ag
from src.engine.evaluate import evaluate

FIX = Path(__file__).parent / "fixtures"
DATE = "2026-10-09"
LDL = {p["criterion_id"]: p for p in json.loads((FIX / "sample_predicates.json").read_text())["predicates"]}["S-I5"]


@pytest.fixture(autouse=True)
def store():
    fhir_store.set_store(FhirStore(FIX / "patients"))


def case_and_tools(pid):
    case = ag.RecoveryCase(pid, LDL, DATE)
    return case, {t.tool_spec["name"]: t for t in ag.build_tools(case)}


def test_alt_code_is_recovered_and_engine_decides():
    case, t = case_and_tools("fixture-alt-code")
    eq = t["lookup_equivalent_codes"]()
    assert [c["code"] for c in eq["equivalent_codes"]] == ["13457-7", "2089-1"]
    q = t["fhir_query_codes"](codes=["13457-7"])
    assert q["status"] == "ok" and q["records"][0]["resource_id"] == "o-401"
    out = t["evaluate_with_records"](resource_ids=["o-401"])
    assert out["status"] == "met"  # 3.4 mmol/L -> 131.48 mg/dL, converted by the engine

    v = ag.finalize(evaluate(LDL, "fixture-alt-code", DATE), case, "done")
    assert v.status == "met" and v.evidence[0]["resource_id"] == "o-401"
    assert "13457-7" in v.recovery
    assert [e["step"] for e in v.trace] == list(range(1, len(v.trace) + 1))


def test_agent_cannot_evaluate_records_it_did_not_query():
    case, t = case_and_tools("fixture-missing-ldl")
    t["search_notes"](keywords=["LDL"])
    out = t["evaluate_with_records"](resource_ids=["d-301"])  # a note, not a lab record
    assert "error" in out and case.engine_verdict is None


def test_unrecovered_case_keeps_status_and_explains():
    case, t = case_and_tools("fixture-missing-ldl")
    t["lookup_equivalent_codes"]()
    t["fhir_query_codes"](codes=["13457-7", "2089-1"])
    t["search_notes"](keywords=["LDL", "cholesterol"])
    v = ag.finalize(evaluate(LDL, "fixture-missing-ldl", DATE), case, "Obtain the outside lab report.")
    assert v.status == "unknown" and v.evidence == []
    assert "tried codes 13457-7, 18262-1, 2089-1" in v.recovery
    assert "d-301" in v.recovery and "not a lab value" in v.recovery
    assert {"rule:abstain", "agent:summary"} <= {e["tool"] for e in v.trace}


def test_every_tool_call_is_traced():
    case, t = case_and_tools("fixture-missing-ldl")
    t["get_predicate"]()
    t["lookup_equivalent_codes"]()
    t["fhir_query_codes"](codes=["2089-1"])
    t["search_notes"](keywords=["LDL"])
    t["record_decision"](action="a", result="b", decision="c")
    assert [e["tool"] for e in case.agent_trace] == ["get_predicate", "lookup_equivalent_codes",
                                                     "fhir_query_codes", "search_notes", "record_decision"]


def test_tool_budget_cancels_seventh_call():
    case = ag.RecoveryCase("p", LDL, DATE)
    hook = ag._budget_hook(case)
    events = [BeforeToolCallEvent(agent=None, selected_tool=None, tool_use={}, invocation_state={}) for _ in range(7)]
    for e in events:
        hook(e)
    assert not any(e.cancel_tool for e in events[:6]) and events[6].cancel_tool


def test_model_failure_keeps_rule_verdict():
    v0 = evaluate(LDL, "fixture-missing-ldl", DATE)
    v = ag.recover(v0, LDL, DATE)  # conftest blanks BEDROCK_MODEL_ID -> make_model raises
    assert v.status == "unknown" and any(e["tool"] == "agent:error" for e in v.trace)


def test_ming_mapping_file_is_preferred(tmp_path, monkeypatch):
    from src import config
    (tmp_path / "mappings").mkdir()
    (tmp_path / "mappings" / "local_code_map.json").write_text(json.dumps(
        {"groups": [{"concept": "LDL-C", "codes": [{"system": "http://loinc.org", "code": "18262-1"},
                                                   {"system": "http://loinc.org", "code": "99999-9"}]}]}))
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "ROOT", tmp_path.parent)
    groups, source = ag.load_equivalents()
    assert source.endswith("local_code_map.json") and groups[0]["codes"][1]["code"] == "99999-9"

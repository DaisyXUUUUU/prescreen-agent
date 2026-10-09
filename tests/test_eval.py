"""Metric arithmetic on tiny hand-made inputs (not labels for any real trial)."""

import importlib.util
from pathlib import Path

from src.adapters.fhir_store import FhirStore

spec = importlib.util.spec_from_file_location("evaluate", Path(__file__).parent.parent / "eval" / "evaluate.py")
ev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ev)

FIX = Path(__file__).parent / "fixtures"


def row(pid, cid, status, cat="likely_eligible", ids="", computable="True", note=""):
    return {"patient_id": pid, "criterion_id": cid, "status": status, "patient_category": cat,
            "evidence_ids": ids, "computable": computable, "note": note}


def t(tool, result="", decision="", actor=None):
    return {"tool": tool, "result": result, "decision": decision,
            "actor": actor or ("rule" if tool.startswith("rule:") else "engine" if tool == "fhir_query" else "agent")}


def test_wrongful_exclusion_and_sensitivity():
    rows = [row("a", "I1", "met", "likely_eligible"), row("b", "I1", "not_met", "excluded"),
            row("c", "I1", "unknown", "pending"), row("d", "I1", "met", "likely_eligible")]
    m = ev.patient_metrics(rows, {"a": "eligible", "b": "eligible", "c": "eligible", "d": "not_eligible", "e": "eligible"})
    assert m["wrongful_exclusions"] == ["b"]
    assert m["sensitivity"] == 66.7  # a and c kept out of a, b, c
    assert m["ineligible_marked_likely_eligible"] == ["d"]
    assert m["missing_from_log"] == ["e"]


def test_criterion_accuracy_strict_and_decided():
    rows = [row("a", "I1", "met"), row("a", "I2", "unknown"), row("a", "E1", "met"), row("a", "N1", "unknown", computable="False")]
    m = ev.criterion_metrics(rows, {("a", "I1"): "met", ("a", "I2"): "met", ("a", "E1"): "not_met"})
    assert m["accuracy_strict"] == 33.3 and m["accuracy_decided"] == 50.0
    assert m["abstention"] == 33.3  # N1 is not computable, so 1 of 3
    assert [(x["criterion_id"], x["actual"]) for x in m["mismatches"]] == [("I2", "unknown"), ("E1", "met")]


def test_evidence_coverage_checks_ids_exist_and_skips_absence():
    store = FhirStore(FIX / "patients")
    rows = [row("fixture-complete", "I5", "met", ids="o-101"), row("fixture-complete", "I6", "met", ids="o-999"),
            row("fixture-complete", "E3", "not_met")]
    trace = {("fixture-complete", "E3"): [t("fhir_query", "-> empty"), t("rule:absence_means", "", "not_met")]}
    m = ev.evidence_coverage(rows, trace, store)
    assert m["coverage"] == 50.0 and m["invalid"] == ["fixture-complete/I6"] and m["decided_from_absence"] == 1


def test_trace_coverage_counts_agent_verdicts_and_classified_changes():
    trace = {("a", "I5"): [t("fhir_query"), t("get_predicate"), t("evaluate_with_records", "engine: x", "met")],
             ("b", "I5"): [t("fhir_query"), t("get_predicate")],  # agent touched it but left no decision
             ("c", "I1"): [t("fhir_query"), t("rule:compare>=", "", "met")]}
    impact = {"changes": [{"trace": [t("classify_change", "r", "substantive")], "reason": "r"},
                          {"trace": [t("rule:normalize", "r", "wording")], "reason": "r"}]}
    m = ev.trace_coverage(trace, impact)
    assert (m["agent_verdicts"], m["classified_changes"], m["coverage"]) == (2, 1, 66.7)


def test_recovery_only_counts_cases_planted_by_drop_codes():
    base = {"rows": [row("p", "I5", "met")], "trace": {("p", "I5"): [t("fhir_query", "Observation -> ok (1)")]}}
    drop = {"meta": {"injections": [{"switch": "drop_codes", "patient_id": "p"}]},
            "rows": [row("p", "I5", "met"), row("q", "I5", "unknown")],
            "trace": {("p", "I5"): [t("fhir_query", "Observation -> empty (0)")],
                      ("q", "I5"): [t("fhir_query", "Observation -> empty (0)")]}}
    m = ev.recovery(base, drop)
    assert (m["planted"], m["recovered"], m["rate"]) == (1, 1, 100.0)


def test_amendment_recall():
    run = {"impact": {"flips": ["a", "b"]}}
    assert ev.amendment_recall(run, ["a", "c"])["missed"] == ["c"]
    assert ev.amendment_recall(run, None)["recall"] is None


def test_labels_file_parses_patient_rows():
    crit, patient = ev.load_labels(FIX / "sample_labels.csv")
    assert patient["fixture-over-age"] == "not_eligible" and crit[("fixture-over-age", "S-I2")] == "not_met"

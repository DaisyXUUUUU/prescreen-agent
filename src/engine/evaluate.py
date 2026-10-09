"""T5: deterministic evaluation of one predicate for one patient.

No LLM, no clock: the same predicate, patient data and screening date always
give the same Verdict. `status` says whether the predicate's condition holds;
whether that includes or excludes the patient is decided later (T6) from the
predicate's `type`.

evaluate() queries the FHIR adapter and hands the result to judge(). The agent
(T7) calls judge() directly with records it recovered, so every comparison is
still made here and never by the model.

    python -m src.engine.evaluate --predicates tests/fixtures/sample_predicates.json \
        --patients tests/fixtures/patients --date 2026-10-09
"""

import argparse
import json
import operator
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from statistics import mean

from src.adapters import fhir_store
from src.adapters.fhir_store import LOINC, RXNORM, SNOMED, ATC, QueryResult, norm_system
from src.engine.units import normalize_unit, to_unit

COMPARE = {"<": operator.lt, "<=": operator.le, ">": operator.gt, ">=": operator.ge}
SUPPORTED_OPERATORS = set(COMPARE) | {"exists"}

# brief section 5: missing diagnosis -> not_met, missing lab -> unknown, missing intolerance -> unknown.
# Medications follow diagnoses (no active order = not taking); predicates can override.
DEFAULT_ABSENCE = {
    "Condition": "not_met",
    "Observation": "unknown",
    "AllergyIntolerance": "unknown",
    "MedicationRequest": "not_met",
    "Patient": "unknown",
}
SYSTEM_TO_RESOURCE = {LOINC: "Observation", SNOMED: "Condition", RXNORM: "MedicationRequest", ATC: "MedicationRequest"}
MAX_EVIDENCE = 5


@dataclass
class Verdict:
    patient_id: str
    criterion_id: str
    status: str = "unknown"  # met | not_met | unknown
    evidence: list[dict] = field(default_factory=list)
    note: str = ""
    blocking: bool = True
    needs_recovery: bool = False  # empty query: T7 agent may retry codes / notes
    trace: list[dict] = field(default_factory=list)

    def log(self, step: str, tool: str, result: str, decision: str) -> None:
        self.trace.append({"step": step, "tool": tool, "result": result, "decision": decision})

    def to_dict(self) -> dict:
        return asdict(self)


def _resource(pred: dict) -> str:
    if pred.get("resource"):
        return pred["resource"].split(".")[0]
    systems = {norm_system(c.get("system", "")) for c in pred.get("codes") or []}
    for system in systems:
        if system in SYSTEM_TO_RESOURCE:
            return SYSTEM_TO_RESOURCE[system]
    return "Observation"


def _evidence(records: list[dict], value_key: str = "value") -> list[dict]:
    return [{"resource_id": r["resource_id"], "value": r.get(value_key), "date": r.get("date")} for r in records[:MAX_EVIDENCE]]


def _age(birth: str, on: str) -> int:
    b, d = date.fromisoformat(birth[:10]), date.fromisoformat(on[:10])
    return d.year - b.year - ((d.month, d.day) < (b.month, b.day))


def _fmt(x) -> str:
    return f"{x:g}" if isinstance(x, (int, float)) else str(x)


def evaluate(predicate: dict, patient_id: str, screening_date: str) -> Verdict:
    v = Verdict(patient_id, predicate["criterion_id"], blocking=predicate.get("blocking", True))
    op = predicate.get("operator")

    if predicate.get("computable") is False or predicate.get("grade") == "N":
        v.note = "not computable from structured data; left to CRC"
        v.log("screen", "rule:not_computable", f"computable={predicate.get('computable')} grade={predicate.get('grade')}", "unknown")
        return v
    if (predicate.get("anchor") or {}).get("event") == "index_event":
        v.note = "index-event anchor not implemented yet (trial G)"
        v.log("anchor", "rule:anchor", "index_event", "unknown")
        return v
    if op not in SUPPORTED_OPERATORS:
        v.note = f"operator {op!r} not implemented yet"
        v.log("screen", "rule:operator", str(op), "unknown")
        return v

    resource = _resource(predicate)
    q = fhir_store.fhir_query(patient_id, resource, predicate.get("codes") or [],
                              window_days=predicate.get("window_days"), anchor_date=screening_date)
    codes = ",".join(str(c.get("code")) for c in predicate.get("codes") or []) or "-"
    v.log("query", "fhir_query", f"{resource} [{codes}] window={predicate.get('window_days')} -> {q.status} ({len(q.records)})", "")
    return judge(predicate, q, v, screening_date, resource)


def judge(predicate: dict, q: QueryResult, v: Verdict, screening_date: str, resource: str | None = None) -> Verdict:
    """Decide a verdict from query results. Pure: no I/O."""
    resource = resource or _resource(predicate)
    op = predicate["operator"]

    if q.status in ("timeout", "malformed"):
        v.status, v.note = "unknown", f"data query {q.status}: {q.detail}"
        v.log("decide", f"rule:{q.status}", q.detail, "unknown")
        return v

    records = q.records
    if resource == "MedicationRequest":
        # only current orders count as "taking"
        records = [r for r in records if r.get("status") == "active"]
        if len(records) < len(q.records):
            v.log("filter", "rule:active_medication", f"{len(q.records) - len(records)} non-active orders ignored", "")

    if resource == "Patient":
        return _judge_age(predicate, records, v, screening_date)

    if not records:
        absence = predicate.get("absence_means") or DEFAULT_ABSENCE.get(resource, "unknown")
        v.status, v.needs_recovery = absence, True
        v.note = f"no {resource} record found; absence means {absence}"
        v.log("decide", "rule:absence_means", q.detail or "empty", absence)
        return v

    if op == "exists":
        v.status, v.evidence = "met", _evidence(records)
        v.note = f"{len(records)} matching {resource} record(s); most recent {records[0].get('date', '')[:10]}"
        v.log("decide", "rule:exists", f"{len(records)} records", "met")
        return v

    if predicate.get("aggregation") == "count_distinct_active_ingredients":
        # Distinct RxNorm codes; true ingredient-level counting needs Ming's ATC->RxNorm map.
        distinct = sorted({r["code"] for r in records})
        return _compare(predicate, v, float(len(distinct)), f"{len(distinct)} distinct active medication(s)",
                        _evidence(records, "display"))

    return _judge_numeric(predicate, records, v)


def _judge_numeric(predicate: dict, records: list[dict], v: Verdict) -> Verdict:
    agg = predicate.get("aggregation") or "most_recent"
    chosen = records[:3] if agg == "mean_of_last_3" else records[:1]
    v.evidence = _evidence(chosen)

    values, problems = [], []
    for r in chosen:
        c = to_unit(r.get("value"), r.get("unit"), r.get("code"), predicate.get("unit"))
        if c.value is None:
            problems.append(f"{r['resource_id']}: {c.reason}")
        else:
            values.append(c.value)
            if c.reason:
                v.log("normalize", "rule:units", f"{r['resource_id']}: {c.reason}", "")
    if problems:
        # Never fall back to an older value silently: the CRC sees why.
        v.status, v.note = "unknown", "; ".join(problems)
        v.log("normalize", "rule:units", v.note, "unknown")
        return v

    if agg == "mean_of_last_3":
        value = round(mean(values), 2)
        label = f"mean of last {len(values)} = {value:g}"
    else:
        value = values[0]
        label = f"{chosen[0].get('display') or chosen[0].get('code')} {value:g} on {str(chosen[0].get('date'))[:10]}"
    return _compare(predicate, v, value, label, v.evidence)


def _judge_age(predicate: dict, records: list[dict], v: Verdict, screening_date: str) -> Verdict:
    birth = next((r["value"] for r in records if r.get("code") == "birthDate"), None)
    if not birth:
        v.status, v.note = "unknown", "no birth date"
        v.log("decide", "rule:absence_means", "no birthDate", "unknown")
        return v
    unit = normalize_unit(predicate.get("unit")) or "years"
    if unit != "years":
        v.status, v.note = "unknown", f"age unit {predicate.get('unit')!r} not supported"
        return v
    age = _age(birth, screening_date)
    rid = records[0]["resource_id"]
    return _compare(predicate, v, float(age), f"age {age} at {screening_date}",
                    [{"resource_id": rid, "value": birth, "date": birth}])


def _compare(predicate: dict, v: Verdict, value: float, label: str, evidence: list[dict]) -> Verdict:
    op = predicate["operator"]
    try:
        threshold = float(predicate["value"])
    except (KeyError, TypeError, ValueError):
        v.status, v.note = "unknown", f"predicate has no numeric threshold ({predicate.get('value')!r})"
        v.log("decide", "rule:predicate", v.note, "unknown")
        return v
    held = COMPARE[op](value, threshold)
    v.status = "met" if held else "not_met"
    v.evidence = evidence
    unit = predicate.get("unit") or ""
    v.note = f"{label}; {_fmt(value)} {op} {_fmt(threshold)} {unit}".rstrip() + f" -> {v.status}"
    v.log("decide", f"rule:compare{op}", f"{_fmt(value)} vs {_fmt(threshold)}", v.status)
    return v


def main() -> None:
    from src import config

    parser = argparse.ArgumentParser(description="Evaluate predicates for every patient (no aggregation)")
    parser.add_argument("--predicates", type=Path, required=True)
    parser.add_argument("--patients", type=Path, default=config.PATIENT_DIR)
    parser.add_argument("--date", default=config.SCREENING_DATE)
    parser.add_argument("--json", action="store_true", help="print full verdicts")
    args = parser.parse_args()

    fhir_store.set_store(fhir_store.FhirStore(args.patients))
    preds = json.loads(args.predicates.read_text())
    preds = preds["predicates"] if isinstance(preds, dict) else preds
    for pid in fhir_store.list_patients():
        print(f"\n== {pid}  (screening {args.date})")
        for p in preds:
            verdict = evaluate(p, pid, args.date)
            if args.json:
                print(json.dumps(verdict.to_dict(), indent=2))
                continue
            flag = " [needs_recovery]" if verdict.needs_recovery else ""
            ev = ",".join(e["resource_id"] for e in verdict.evidence) or "-"
            print(f"  {p['criterion_id']:<8} {p['type'][:3]:<4} {verdict.status:<8} ev={ev:<12} {verdict.note}{flag}")


if __name__ == "__main__":
    main()

"""SAD (NCT07347678) adapter: the deterministic SAD evaluator inside the screening pipeline.

Clinical logic stays in `trials/nct07347678_sad/engine.py`, the frozen, separately tested SAD
evaluator; it is never edited here. This module connects it:

  - loads the frozen rule pack, cases and contexts, and checks their SHA-256 against the
    manifests, as the evaluator's own runner does;
  - builds one in-memory FHIR store over the same bundle objects, so failure injection and
    the recovery agent see exactly what the evaluator sees;
  - converts its per-criterion rows into pipeline Verdicts (evidence, note, conflict,
    trace) and the rule pack into predicate dicts for aggregation and the log;
  - adds two guards before the evaluator runs, both traced as rules: unit conversion where unambiguous (e.g. LDL mmol/L -> mg/dL) and
    plausibility ranges (src/engine/units.py), which the evaluator does not check;
  - lets the recovery agent hand an equivalently coded record back to the evaluator.
"""

import copy
import hashlib
import importlib.util
import json
from dataclasses import dataclass
from pathlib import Path

from src import config
from src.adapters import fhir_store
from src.adapters.fhir_store import LOINC, FhirStore
from src.agent import trace
from src.engine.aggregate import PatientResult, aggregate
from src.engine.evaluate import Verdict
from src.engine.units import analyte_for, to_unit

SAD_DIR = config.ROOT / "trials/nct07347678_sad"
SPEC_PATH = SAD_DIR / "rules" / "sad-1.0.0.json"

# Mirrors the codes and units hard-wired in trials/nct07347678_sad/engine.py. Used for the trace, the
# unit/plausibility guard and the agent's equivalent-code lookup; never for the verdict itself.
OBSERVATIONS = {
    "I1": [("39156-5", "kg/m2", "BMI")],
    "I2": [("18262-6", "mg/dL", "LDL-C (direct)")],
    "I3": [("43583-4", "nmol/L", "Lp(a) molar")],
    "I4": [("2571-8", "mg/dL", "Triglycerides")],
    "E1": [("1742-6", "U/L", "ALT"), ("1920-8", "U/L", "AST")],
    "E2": [("4548-4", "%", "HbA1c")],
}
HISTORY = {"E3", "E4", "E5"}
# Default failure-injection targets (case IDs):
# drop_codes on a passing case so recovery restores a real verdict; bad_units converts a passing
# case's LDL to mmol/L (rule converts back) and makes a failing case's LDL implausible (x10).
DEFAULT_FAILURE_TARGETS = {"drop_codes": ["SAD04"], "bad_units": ["SAD01", "SAD02"]}
DECISION_TO_CATEGORY = {"passes_evaluated_criteria": "likely_eligible", "fails_evaluated_criteria": "excluded",
                        "pending": "pending", "review": "needs_review"}


@dataclass
class SadCase:
    case_id: str
    ctx: dict
    bundle: dict

    @property
    def patient_id(self) -> str:
        return self.ctx["patient_id"]

    @property
    def screening_date(self) -> str:
        return self.ctx["screening_at"][:10]


# ---------- loading ----------

def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_engine():
    spec = importlib.util.spec_from_file_location("sad_evaluator", SAD_DIR / "engine.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_spec(path: Path | None = None) -> dict:
    return json.loads(Path(path or SPEC_PATH).read_text(encoding="utf-8"))


def verify_inputs(spec_path: Path, cases_dir: Path) -> list[str]:
    """Hash checks against the SAD manifests. Returns problems (empty = all inputs as frozen)."""
    problems = []
    manifest = json.loads((SAD_DIR / "rules" / "manifest.json").read_text())
    if Path(spec_path).resolve() == SPEC_PATH.resolve() and _sha(SPEC_PATH) != manifest["sha256"]:
        problems.append("rule pack sad-1.0.0.json differs from its manifest hash")
    if _sha(SAD_DIR / "source" / "NCT07347678.json") != manifest["source_sha256"]:
        problems.append("source registry snapshot differs from its manifest hash")
    if Path(cases_dir).resolve() == (SAD_DIR / "data" / "cases").resolve():
        for c in json.loads((SAD_DIR / "data" / "case_manifest.json").read_text())["cases"]:
            for path, key in [(SAD_DIR / "data" / "cases" / f"{c['case_id']}.json", "case_sha256"),
                              (SAD_DIR / "data" / "context" / f"{c['case_id']}.json", "context_sha256")]:
                if _sha(path) != c[key]:
                    problems.append(f"{path.name} differs from case_manifest hash")
    return problems


def load_cases(cases_dir: Path | None = None) -> list[SadCase]:
    cases_dir = Path(cases_dir or SAD_DIR / "data" / "cases")
    context_dir = cases_dir.parent / "context"
    cases = []
    for ctx_path in sorted(context_dir.glob("*.json")):
        ctx = json.loads(ctx_path.read_text(encoding="utf-8"))
        bundle = json.loads((cases_dir.parent / ctx["FHIR_file"]).read_text(encoding="utf-8"))
        cases.append(SadCase(ctx["case_id"], ctx, bundle))
    return cases


def install_store(cases: list[SadCase]) -> FhirStore:
    """One store over the very bundle objects the engine evaluates."""
    store = FhirStore.from_bundles({c.case_id: c.bundle for c in cases})
    fhir_store.set_store(store)
    return store


# ---------- rule pack -> predicate dicts (for aggregation, log, agent) ----------

def predicates(spec: dict) -> list[dict]:
    age = spec["age_metadata"]
    out = [{"criterion_id": "AGE", "trial_id": spec["trial_id"], "type": "inclusion",
            "concept": f"Age {age['minimum']}-{age['maximum']} at screening", "computable": True, "grade": "C",
            "resource": "Patient", "codes": [], "source_text": f"Age {age['minimum']} to {age['maximum']} years",
            "rule": age}]
    for r in spec["rules"]:
        manual = r["predicate"].get("mode") == "manual_review"
        obs = OBSERVATIONS.get(r["id"], [])
        out.append({
            "criterion_id": r["id"], "trial_id": spec["trial_id"], "type": r["type"],
            "concept": r.get("concept") or r["source_text"][:60],
            "computable": not manual, "grade": "N" if manual else "C",
            "resource": "QuestionnaireResponse" if r["id"] in HISTORY else ("Observation" if obs else None),
            "codes": [{"system": LOINC, "code": c, "display": d} for c, _, d in obs],
            "unit": obs[0][1] if obs else "", "window_days": None,
            "source_text": r["source_text"], "rule": r["predicate"],
        })
    return out


# ---------- guards (before the SAD evaluator) ----------

def _normalise(bundle: dict) -> dict[str, list[tuple[str, str]]]:
    """Convert unambiguous units to the unit the engine expects and flag implausible values,
    on the given (copied) bundle. Returns {criterion_id: [(tool, message)]}."""
    expected = {code: (cid, unit) for cid, obs in OBSERVATIONS.items() for code, unit, _ in obs}
    notes: dict[str, list[tuple[str, str]]] = {}
    for e in bundle["entry"]:
        r = e["resource"]
        if r.get("resourceType") != "Observation":
            continue
        code = next((c.get("code") for c in r.get("code", {}).get("coding", []) if c.get("code") in expected), None)
        q = r.get("valueQuantity")
        if not code or not q or analyte_for(code) is None:
            continue
        cid, unit = expected[code]
        c = to_unit(q.get("value"), q.get("code") or q.get("unit"), code, unit)
        ref = f"Observation/{r['id']}"
        if c.value is None:
            if "outside plausible range" in (c.reason or ""):
                notes.setdefault(cid, []).append(("rule:unit_check", f"{ref}: {c.reason}"))
            continue  # unknown unit: left for the engine, which reports it
        if c.reason:  # converted
            q.update(value=c.value, unit=unit, code=unit)
            notes.setdefault(cid, []).append(("rule:unit_convert", f"{ref}: {c.reason}"))
    return notes


# ---------- engine rows -> Verdicts ----------

def _fmt_value(v) -> str:
    if isinstance(v, dict) and "value" in v:
        return f"{v['value']:g} {v.get('code') or v.get('unit') or ''}".strip() if isinstance(v["value"], (int, float)) \
            else str(v["value"])
    return str(v)


def _evidence(rows: list[dict]) -> list[dict]:
    """Group the evaluator's field-level evidence by resource: value, date, and the other checked fields."""
    by_ref: dict[str, dict] = {}
    for e in rows:
        item = by_ref.setdefault(e["resource_ref"], {"resource_id": e["resource_ref"], "value": None, "date": None, "fields": []})
        if e["field"] == "valueQuantity":
            item["value"] = _fmt_value(e["value"])
        elif e["field"] == "effectiveDateTime":
            item["date"] = e["value"]
        elif e["field"] == "birthDate":
            item["value"] = f"born {e['value']}"
        else:
            item["fields"].append(f"{e['field'].replace('collection.', '')}={_fmt_value(e['value'])}")
    out = []
    for item in by_ref.values():
        extra = "; ".join(item.pop("fields"))
        item["value"] = "; ".join(x for x in [item["value"], extra] if x) or None
        out.append(item)
    return out


def _engine_trace(cid: str, tool_trace: list[dict]) -> list[str]:
    codes = {c for c, _, _ in OBSERVATIONS.get(cid, [])}
    lines = []
    for t in tool_trace:
        if t["type"] == "Observation" and t.get("code") in codes:
            lines.append(f"Observation {t['code']} in screening encounter -> {t['count']} found")
        elif t["type"] == "Patient" and cid == "AGE":
            lines.append("Patient birthDate")
        elif t["type"] == "QuestionnaireResponse" and cid in HISTORY and not lines:
            lines.append("QuestionnaireResponse screening history")
    return lines


def to_verdicts(case: SadCase, result: dict, guard: dict | None = None) -> list[Verdict]:
    verdicts = []
    for row in result["criteria"]:
        cid = row["criterion_id"]
        v = Verdict(case.case_id, cid, status=row["status"], evidence=_evidence(row["evidence"]),
                    note=row["reason"], conflict=bool(row["conflict"]))
        for line in _engine_trace(cid, result["tool_trace"]):
            trace.add(v.trace, "fhir_query", line)
        for tool, msg in (guard or {}).get(cid, []):
            trace.add(v.trace, tool, msg)
        if row.get("manual"):
            trace.add(v.trace, "rule:not_computable", row["reason"], "unknown")
        else:
            trace.add(v.trace, "rule:sad_engine", row["reason"] + (" [conflict]" if row["conflict"] else ""), row["status"])
        rejected = [m for tool, m in (guard or {}).get(cid, []) if tool == "rule:unit_check"]
        used = {e["resource_id"] for e in v.evidence}
        if rejected and any(m.split(":")[0] in used for m in rejected):
            v.status, v.note = "unknown", "; ".join(rejected)
            trace.add(v.trace, "rule:unit_check", v.note, "unknown")
        # An empty screening query is what the recovery agent may help with; other unknowns are not.
        v.needs_recovery = v.status == "unknown" and row["reason"].startswith("No matching screening observation")
        verdicts.append(v)
    return verdicts


def evaluate_case(case: SadCase, spec: dict, engine=None) -> tuple[list[Verdict], dict]:
    engine = engine or load_engine()
    bundle = copy.deepcopy(case.bundle)  # guards rewrite units on a copy; injected changes are already in case.bundle
    guard = _normalise(bundle)
    result = engine.evaluate(bundle, case.ctx, spec)
    return to_verdicts(case, result, guard), result


def evaluate_with_records(case: SadCase, spec: dict, cid: str, records: list[dict], engine=None) -> Verdict:
    """Agent path: records found under an equivalent code are evaluated by the SAD evaluator as if
    recorded under the criterion's own code. Everything else (encounter, fasting, unit, threshold)
    is still checked by the evaluator."""
    engine = engine or load_engine()
    canonical = {code for code, _, _ in OBSERVATIONS.get(cid, [])}
    target = OBSERVATIONS[cid][0]
    bundle = copy.deepcopy(case.bundle)
    ids = {r["resource_id"] for r in records}
    swapped = []
    for e in bundle["entry"]:
        r = e["resource"]
        if r.get("resourceType") == "Observation" and r.get("id") in ids:
            original = next((c.get("code") for c in r.get("code", {}).get("coding", [])), None)
            if original not in canonical:
                r["code"] = {"coding": [{"system": LOINC, "code": target[0], "display": target[2]}]}
                swapped.append(f"{r['id']} {original} -> {target[0]}")
    guard = _normalise(bundle)
    result = engine.evaluate(bundle, case.ctx, spec)
    v = next(v for v in to_verdicts(case, result, guard) if v.criterion_id == cid)
    v.note = f"{v.note} (record found under an equivalent code: {', '.join(swapped) or 'none'}; evaluated by the SAD engine)"
    v.needs_recovery = False
    return v


# ---------- screening ----------

def screen(cases: list[SadCase], spec: dict, use_agent: bool = True, label: str = "") -> tuple[list[PatientResult], int, int, dict]:
    """Returns (results, agent tasks, tasks that changed the rule result, engine decisions by case).

    With the agent on, each case goes through: recovery of empty queries, free-text interpretation of
    history criteria, conflict explanation, and the I5 evidence pack. With it off, results equal
    the rules-only SAD evaluator exactly."""
    from src.agent import conflict, evidence, interpret

    engine = load_engine()
    preds = predicates(spec)
    by_id = {p["criterion_id"]: p for p in preds}
    rules = {r["id"]: r for r in spec["rules"]}
    model = None
    if use_agent:
        from src.agent.agent import preflight
        model, reason = preflight()
        if model is None:
            print(f"  agent{label}: model unavailable ({reason}); continuing with rules only")
            use_agent = False

    results, attempted, changed, decisions = [], 0, 0, {}

    def step(case, what, fn, v):
        nonlocal attempted, changed
        attempted += 1
        print(f"  agent{label}: {case.case_id} {v.criterion_id} {what} ...", end="", flush=True)
        out = fn()
        changed += (out.status, out.conflict, bool(out.review_reason)) != (v.status, v.conflict, False)
        print(f" {out.status}" + (" [review]" if out.review_reason else "") + (" [conflict]" if out.conflict else ""))
        return out

    for case in cases:
        verdicts, raw = evaluate_case(case, spec, engine)
        decisions[case.case_id] = raw["decision"]
        if use_agent:
            from src.agent.agent import recover
            for i, v in enumerate(verdicts):
                cid = v.criterion_id
                if v.needs_recovery:
                    verdicts[i] = step(case, "recover", lambda v=v, cid=cid: recover(
                        v, by_id[cid], case.screening_date, model=model, query_patient_id=case.patient_id,
                        evaluate_records=lambda recs, c=case, k=cid: evaluate_with_records(c, spec, k, recs, engine)), v)
                elif v.status == "unknown" and cid in HISTORY and interpret.has_free_text(case, cid):
                    verdicts[i] = step(case, "interpret", lambda v=v, cid=cid: interpret.interpret(
                        case, cid, rules[cid]["predicate"], rules[cid]["source_text"], v, model), v)
                elif v.conflict:
                    verdicts[i] = step(case, "conflict", lambda v=v: conflict.explain(case, spec, v, engine, model), v)
                elif cid == "I5":
                    verdicts[i] = step(case, "evidence", lambda v=v: evidence.evidence_pack(case, v, model), v)
        results.append(aggregate(case.case_id, preds, verdicts, failed_first=True))
    return results, attempted, changed, decisions

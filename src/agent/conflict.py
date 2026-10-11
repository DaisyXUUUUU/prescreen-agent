"""Conflict explanation (brief decision 4) for SAD: several candidate results for one criterion.

Ming's rule sends any conflict to review. The CRC still has to work out what is going on, so:

  - the code re-runs Ming's engine once per candidate (keeping only that result) and reports
    whether choosing one or the other would change the criterion: material vs immaterial;
  - the model compares the candidates' recorded metadata (value, time, status, specimen,
    method) and writes what most likely happened and what to check. It never picks a result.

The verdict stays `unknown` with the conflict flag, so the patient stays in review, unless
config.IMMATERIAL_CONFLICT_RESOLVES is switched on (pending Ming's decision): then an
immaterial conflict takes the status every candidate agrees on, with the conflict kept visible.
"""

import copy

from pydantic import BaseModel, Field

from src import config
from src.agent import llm, trace
from src.engine.evaluate import Verdict

SYSTEM = """You help a clinical research coordinator understand conflicting lab results for one patient.
Compare only what the records show. Do not choose which result is correct and do not decide eligibility."""


class ConflictNote(BaseModel):
    differences: str = Field(description="What differs between the candidates (value, time, specimen, method, status) and what is identical")
    likely_cause: str = Field(description="Most plausible explanation given the metadata, or 'cannot tell'")
    what_to_check: str = Field(description="Concrete next step for the CRC, e.g. ask the lab which result was reported")


def _candidates(case, v: Verdict) -> list[dict]:
    """The competing results: observations in the evidence whose code occurs more than once
    (for E1, two ALT results compete; the single AST result is context, not a candidate)."""
    ids = {e["resource_id"].split("/")[-1] for e in v.evidence if e["resource_id"].startswith("Observation/")}
    obs = [e["resource"] for e in case.bundle["entry"] if e["resource"].get("id") in ids]
    code = lambda o: o["code"]["coding"][0]["code"]  # noqa: E731
    counts = {}
    for o in obs:
        counts[code(o)] = counts.get(code(o), 0) + 1
    return [o for o in obs if counts[code(o)] > 1]


def _describe(o: dict) -> dict:
    q = o.get("valueQuantity", {})
    return {"id": o["id"], "value": f"{q.get('value')} {q.get('code') or q.get('unit')}", "status": o.get("status"),
            "time": o.get("effectiveDateTime"), "issued": o.get("issued"),
            "specimen": (o.get("specimen") or {}).get("reference"), "method": (o.get("method") or {}).get("text")}


def explain(case, spec: dict, v: Verdict, engine, model=None) -> Verdict:
    cands = _candidates(case, v)
    if len(cands) < 2:
        return v
    # Deterministic part: what would each candidate alone give?
    outcomes = {}
    for keep in cands:
        bundle = copy.deepcopy(case.bundle)
        drop = {c["id"] for c in cands if c["id"] != keep["id"]}
        bundle["entry"] = [e for e in bundle["entry"] if e["resource"].get("id") not in drop]
        row = next(r for r in engine.evaluate(bundle, case.ctx, spec)["criteria"] if r["criterion_id"] == v.criterion_id)
        outcomes[keep["id"]] = row["status"]
    material = len(set(outcomes.values())) > 1
    summary = ", ".join(f"{_describe(c)['value']} -> {outcomes[c['id']]}" for c in cands)
    trace.add(v.trace, "rule:conflict_materiality",
              f"each candidate alone: {summary}", "material" if material else "immaterial")

    described = [_describe(c) for c in cands]
    try:
        note = llm.structured_call(SYSTEM, (
            f"Criterion {v.criterion_id}. Candidate results:\n"
            + "\n".join(str(d) for d in described)
            + f"\nThe rules engine computed that choosing one or the other {'WOULD' if material else 'would NOT'} change the result."),
            ConflictNote, model)
        text = f"{note.differences} Likely cause: {note.likely_cause} Check: {note.what_to_check}"
        trace.add(v.trace, "explain_conflict", " ".join(text.split())[:600])
    except Exception as e:  # noqa: BLE001
        text = "model unavailable for the explanation"
        trace.add(v.trace, "agent:error", f"{type(e).__name__}: {str(e)[:160]}")

    impact = ("choosing either result changes the outcome" if material
              else f"every candidate gives {next(iter(outcomes.values()))}, so the choice does not change the outcome")
    v.recovery = f"conflict: {summary}; {impact}. {text}"
    if not material and config.IMMATERIAL_CONFLICT_RESOLVES and next(iter(outcomes.values())) != "unknown":
        v.status = next(iter(outcomes.values()))
        v.note += f"; conflict immaterial (all candidates {v.status}), resolved by rule"
        v.conflict = False
        trace.add(v.trace, "rule:immaterial_conflict", "all candidates agree", v.status)
    return v

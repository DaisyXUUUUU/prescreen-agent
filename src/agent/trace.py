"""T8: trace lines. One line per rule application and per model decision.

    {"step": 3, "tool": "lookup_equivalent_codes", "result": "...", "decision": "..."}

`tool` names the actor: "rule:*" is a fixed rule, "fhir_query" a data query made
by the engine, anything else a tool the recovery agent chose to call. The
JSONL file lets the evaluation count trace coverage.
"""

import json
from pathlib import Path

ENGINE_TOOLS = {"fhir_query", "rxnav"}  # deterministic lookups, not model decisions


def add(trace: list[dict], tool: str, result: str, decision: str = "") -> dict:
    entry = {"step": len(trace) + 1, "tool": tool, "result": result, "decision": decision}
    trace.append(entry)
    return entry


def actor(entry: dict) -> str:
    tool = entry["tool"]
    if tool.startswith("rule:"):
        return "rule"
    if tool in ENGINE_TOOLS:
        return "engine"
    return "agent"


def write_jsonl(path: Path, trial: str, screening_date: str, results) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in results:
            for v in r.verdicts:
                for t in v.trace:
                    f.write(json.dumps({"trial": trial, "screening_date": screening_date, "patient_id": r.patient_id,
                                        "criterion_id": v.criterion_id, "actor": actor(t), **t}) + "\n")
    return path

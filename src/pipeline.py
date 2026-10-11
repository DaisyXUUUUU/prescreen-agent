"""Screen every loaded patient against one predicate set (evaluate, recover, aggregate).

Used by run.py for the weekly log and by the amendment monitor (T10) to
re-screen under the amended predicates.
"""

from src.adapters import fhir_store
from src.engine.aggregate import PatientResult, aggregate
from src.engine.evaluate import evaluate


def screen(predicates: list[dict], screening_date: str, use_agent: bool = True,
           label: str = "") -> tuple[list[PatientResult], int, int]:
    """Returns (results, empty queries sent to the agent, of which resolved)."""
    by_id = {p["criterion_id"]: p for p in predicates}
    results, attempted, recovered = [], 0, 0
    model = None
    if use_agent:
        # One preflight instead of failing once per case when Bedrock is not reachable.
        from src.agent.agent import preflight
        model, reason = preflight()
        if model is None:
            print(f"  agent{label}: model unavailable ({reason}); continuing with rules only")
            use_agent = False
    for pid in fhir_store.list_patients():
        verdicts = [evaluate(p, pid, screening_date) for p in predicates]
        if use_agent:
            # T7: only empty queries left as `unknown` go to the agent; settled verdicts are untouched.
            from src.agent.agent import recover
            for i, v in enumerate(verdicts):
                if v.needs_recovery and v.status == "unknown":
                    attempted += 1
                    print(f"  agent{label}: {pid} {v.criterion_id} ...", end="", flush=True)
                    verdicts[i] = recover(v, by_id[v.criterion_id], screening_date, model=model)
                    recovered += verdicts[i].status != "unknown"
                    print(f" {verdicts[i].status}")
        results.append(aggregate(pid, predicates, verdicts))
    return results, attempted, recovered

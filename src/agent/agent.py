"""T7: recovery agent for empty queries (brief decision 2).

For one verdict whose query came back empty, the agent may try equivalent
codes, then search the notes, then give up. It never compares numbers and
never sets the final status:

  - records it finds are passed back by resource_id to the deterministic
    engine (judge), which reads the stored values itself;
  - note text is never a lab value; at most it supports a recommendation;
  - every tool call is traced by code, whether or not the model also calls
    record_decision, so trace coverage does not depend on the model.

Fresh Agent per case, temperature 0, at most MAX_TOOL_CALLS tool calls.
"""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from strands import Agent, ModelRetryStrategy, tool
from strands.hooks import BeforeToolCallEvent

from src import config
from src.adapters import fhir_store
from src.adapters.fhir_store import LOINC, SNOMED, QueryResult, norm_system
from src.agent import trace
from src.engine.evaluate import Verdict, _resource, judge

log = logging.getLogger(__name__)

MAX_TOOL_CALLS = 6
MAX_NOTE_HITS = 5

# Engineering placeholder until Ming's data/mappings/local_code_map.json lands.
PLACEHOLDER_EQUIVALENTS = [
    {"concept": "LDL-C", "codes": [{"system": LOINC, "code": "18262-6", "display": "LDL-C direct"},
                                   {"system": LOINC, "code": "13457-7", "display": "LDL-C calculated"},
                                   {"system": LOINC, "code": "2089-1", "display": "LDL-C"}]},
    {"concept": "Triglycerides", "codes": [{"system": LOINC, "code": "2571-8", "display": "Triglyceride serum/plasma"},
                                           {"system": LOINC, "code": "3043-7", "display": "Triglyceride blood"}]},
    {"concept": "Hypercholesterolemia", "codes": [{"system": SNOMED, "code": "13644009", "display": "Hypercholesterolemia"},
                                                  {"system": SNOMED, "code": "55822004", "display": "Hyperlipidemia"}]},
]

RECOVERY_PROMPT = """You help a clinical research coordinator (CRC) pre-screen patients for a clinical trial.
A structured query for one eligibility criterion returned no records for one patient. Your job is to
find out whether the data exists under a different code, and otherwise explain what was tried.

Work in this order and stop as soon as one step succeeds:
1. Call get_predicate to see the criterion.
2. Call lookup_equivalent_codes, then fhir_query_codes with the equivalent codes.
3. If fhir_query_codes returns records, call evaluate_with_records with their resource_ids. Then stop.
4. Otherwise call search_notes with 2-4 short keywords for the concept (e.g. "LDL", "cholesterol").
5. Stop. Do not repeat a query that already returned nothing.

Rules:
- Never compare numbers or decide eligibility yourself. Only evaluate_with_records decides.
- Text found in notes is NOT a lab result. Never pass notes to evaluate_with_records. A note can only
  support a recommendation such as "obtain the outside lab report".
- After each step, call record_decision with what you did, what you found, and what you decided next.
- Finish with one or two sentences for the CRC: what was tried and what you recommend.
"""


def load_equivalents() -> tuple[list[dict], str]:
    path = config.DATA_DIR / "mappings" / "local_code_map.json"
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            groups = data["groups"] if isinstance(data, dict) else data
            if groups and all("codes" in g for g in groups):
                return groups, str(path.relative_to(config.ROOT))
            log.warning("%s has an unexpected shape; using placeholder equivalents", path)
        except (ValueError, KeyError, TypeError) as e:
            log.warning("cannot read %s (%s); using placeholder equivalents", path, e)
    return PLACEHOLDER_EQUIVALENTS, "engineering placeholder table"


@dataclass
class RecoveryCase:
    patient_id: str
    predicate: dict
    screening_date: str
    tried_codes: set[str] = field(default_factory=set)
    keywords: list[str] = field(default_factory=list)
    retrieved: dict[str, dict] = field(default_factory=dict)  # resource_id -> record from a real query
    note_hits: list[dict] = field(default_factory=list)
    engine_verdict: Verdict | None = None
    agent_trace: list[dict] = field(default_factory=list)
    tool_calls: int = 0

    def log(self, tool_name: str, result: str, decision: str = "") -> None:
        trace.add(self.agent_trace, tool_name, result, decision)


def build_tools(case: RecoveryCase) -> list:
    pred = case.predicate
    resource = _resource(pred)
    case.tried_codes = {str(c.get("code")) for c in pred.get("codes") or []}
    systems = {str(c.get("code")): norm_system(c.get("system", "")) for c in pred.get("codes") or []}
    groups, source = load_equivalents()

    @tool
    def get_predicate() -> dict:
        """Read the eligibility criterion whose query came back empty."""
        out = {k: pred.get(k) for k in ("criterion_id", "type", "concept", "resource", "codes", "unit",
                                        "window_days", "source_text")}
        case.log("get_predicate", f"{pred.get('criterion_id')} {pred.get('concept')}")
        return out

    @tool
    def lookup_equivalent_codes() -> dict:
        """Codes that mean the same concept as the criterion's codes, from the site's local mapping table."""
        found = []
        for g in groups:
            g_codes = {str(c["code"]) for c in g["codes"]}
            if g_codes & case.tried_codes:
                for c in g["codes"]:
                    if str(c["code"]) not in case.tried_codes and c not in found:
                        found.append(c)
                        systems[str(c["code"])] = norm_system(c.get("system", ""))
        summary = ", ".join(f"{c['code']} ({c.get('display', '')})" for c in found) or "none"
        case.log("lookup_equivalent_codes", f"{summary} [source: {source}]")
        return {"equivalent_codes": found, "already_tried": sorted(case.tried_codes), "source": source}

    @tool
    def fhir_query_codes(codes: list[str]) -> dict:
        """Re-query this patient's records for the criterion using other codes.

        Args:
            codes: Codes to try, e.g. ["13457-7"]. Use codes from lookup_equivalent_codes.
        """
        codes = [str(c).strip() for c in codes if str(c).strip()]
        query = [{"system": systems.get(c, LOINC if resource == "Observation" else SNOMED), "code": c} for c in codes]
        q = fhir_store.fhir_query(case.patient_id, resource, query, window_days=pred.get("window_days"),
                                  anchor_date=case.screening_date)
        case.tried_codes.update(codes)
        for r in q.records:
            case.retrieved[r["resource_id"]] = r
        rows = [{k: r.get(k) for k in ("resource_id", "code", "value", "unit", "date")} for r in q.records[:5]]
        case.log("fhir_query_codes", f"{resource} [{','.join(codes)}] -> {q.status} ({len(q.records)})")
        return {"status": q.status, "records": rows, "detail": q.detail}

    @tool
    def search_notes(keywords: list[str]) -> dict:
        """Search this patient's clinical notes. Hits are text, not lab results.

        Args:
            keywords: 2-4 short keywords, e.g. ["LDL", "cholesterol"].
        """
        case.keywords += [k for k in keywords if k not in case.keywords]
        q = fhir_store.search_notes(case.patient_id, keywords)
        hits = [{"resource_id": r["resource_id"], "date": r.get("date"), "snippet": r["value"]} for r in q.records[:MAX_NOTE_HITS]]
        case.note_hits += [h for h in hits if h not in case.note_hits]
        case.log("search_notes", f"{keywords} -> {q.status} ({len(q.records)} hits)")
        return {"status": q.status, "hits": hits, "warning": "Note text is not a lab value."}

    @tool
    def evaluate_with_records(resource_ids: list[str]) -> dict:
        """Hand records found by fhir_query_codes to the deterministic engine, which decides the criterion.

        Args:
            resource_ids: resource_id values returned by fhir_query_codes.
        """
        unknown = [r for r in resource_ids if r not in case.retrieved]
        if unknown:
            case.log("evaluate_with_records", f"rejected {unknown}: not returned by fhir_query_codes", "")
            return {"error": f"{unknown} were not returned by fhir_query_codes; only queried records can be evaluated"}
        records = sorted((case.retrieved[r] for r in resource_ids), key=lambda r: r.get("date") or "", reverse=True)
        v = judge(pred, QueryResult("ok", records), Verdict(case.patient_id, pred["criterion_id"],
                                                            blocking=pred.get("blocking", True)), case.screening_date)
        case.engine_verdict = v
        case.log("evaluate_with_records", f"engine: {v.note}", v.status)
        return {"status": v.status, "note": v.note}

    @tool
    def record_decision(action: str, result: str, decision: str) -> str:
        """Write one trace line explaining a step for the CRC.

        Args:
            action: what you just did, e.g. "looked up equivalent LDL codes".
            result: what came back.
            decision: what you will do next and why.
        """
        case.log("record_decision", f"{action}: {result}", decision)
        return "recorded"

    return [get_predicate, lookup_equivalent_codes, fhir_query_codes, search_notes, evaluate_with_records, record_decision]


# Fail fast: a daily-quota throttle does not clear by waiting, so do not back off for minutes.
BOTO_CONFIG = {"retries": {"max_attempts": 2, "mode": "standard"}, "connect_timeout": 10, "read_timeout": 90}


def retry_strategy() -> ModelRetryStrategy:
    return ModelRetryStrategy(max_attempts=2, initial_delay=2, max_delay=4)


def _session():
    import boto3
    return boto3.Session(profile_name=config.AWS_PROFILE, region_name=config.AWS_REGION)


def make_model():
    from botocore.config import Config
    from strands.models import BedrockModel

    model_id = config.BEDROCK_MODEL_ID
    if not model_id:
        raise RuntimeError("BEDROCK_MODEL_ID is not set")
    return BedrockModel(model_id=model_id, boto_session=_session(), boto_client_config=Config(**BOTO_CONFIG),
                        temperature=0.0, max_tokens=1024)


def preflight():
    """One tiny real call. Returns (model, None) when Bedrock answers, else (None, reason)."""
    try:
        from botocore.config import Config

        model = make_model()
        client = _session().client("bedrock-runtime", config=Config(**BOTO_CONFIG))
        client.converse(modelId=config.BEDROCK_MODEL_ID, inferenceConfig={"maxTokens": 4},
                        messages=[{"role": "user", "content": [{"text": "ok"}]}])
        return model, None
    except Exception as e:  # noqa: BLE001
        code = getattr(e, "response", {}).get("Error", {}).get("Code") if hasattr(e, "response") else None
        return None, f"{code or type(e).__name__}: {str(e)[:160]}"


def _budget_hook(case: RecoveryCase):
    def limit(event: BeforeToolCallEvent) -> None:
        case.tool_calls += 1
        if case.tool_calls > MAX_TOOL_CALLS:
            event.cancel_tool = f"Tool budget of {MAX_TOOL_CALLS} calls used up. Stop and give your summary now."
    return limit


def recover(verdict: Verdict, predicate: dict, screening_date: str, model=None) -> Verdict:
    """Run the agent on one empty-query verdict. Returns a new Verdict; never raises."""
    case = RecoveryCase(verdict.patient_id, predicate, screening_date)
    final_text = ""
    try:
        agent = Agent(model=model or make_model(), tools=build_tools(case), system_prompt=RECOVERY_PROMPT,
                      hooks=[_budget_hook(case)], callback_handler=None, retry_strategy=retry_strategy())
        result = agent(f"Patient {verdict.patient_id}: the query for criterion {predicate['criterion_id']} "
                       f"({predicate.get('concept')}) returned no records. Try to recover it.")
        final_text = " ".join(str(result).split())
    except Exception as e:  # noqa: BLE001 - a model outage must not break the run
        log.warning("recovery agent failed for %s/%s: %s", verdict.patient_id, predicate["criterion_id"], e)
        case.log("agent:error", f"{type(e).__name__}: {str(e)[:200]}", "kept rule verdict")
    return finalize(verdict, case, final_text)


def _merge_trace(*parts: list[dict]) -> list[dict]:
    merged = [dict(e) for part in parts for e in part]
    for i, e in enumerate(merged, 1):
        e["step"] = i
    return merged


def _short(text: str, limit: int = 240) -> str:
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + " ..."


def finalize(original: Verdict, case: RecoveryCase, final_text: str) -> Verdict:
    """Merge the agent's work into a verdict. The status comes from the engine or stays as it was."""
    tried = sorted(case.tried_codes)
    if case.engine_verdict is not None:
        v = case.engine_verdict
        v.trace = _merge_trace(original.trace, case.agent_trace)
        used = {e["resource_id"] for e in v.evidence}
        codes = ", ".join(sorted({str(case.retrieved[i]["code"]) for i in used if i in case.retrieved}))
        v.recovery = f"original code had no record; found under equivalent code {codes}; engine decided {v.status}"
        v.note = f"{v.note} (recovered by agent)"
        return v

    v = Verdict(original.patient_id, original.criterion_id, status=original.status, evidence=original.evidence,
                note=original.note, blocking=original.blocking, needs_recovery=True,
                trace=_merge_trace(original.trace, case.agent_trace))
    parts = [f"tried codes {', '.join(tried)}"]
    if case.keywords:
        parts.append(f"searched notes for {', '.join(case.keywords)}")
    if case.note_hits:
        ids = ", ".join(sorted({h["resource_id"] for h in case.note_hits}))
        parts.append(f"note(s) {ids} matched the keywords (text only, not a lab value; see detail)")
    v.recovery = "not recovered: " + "; ".join(parts)
    v.note = f"{original.note}; agent could not recover it"
    trace.add(v.trace, "rule:abstain", v.recovery, v.status)
    if final_text:
        trace.add(v.trace, "agent:summary", _short(final_text, 600))
    return v

"""Free-text history interpretation for SAD E3 (smoking), E4 (advanced therapies), E5 (lipid-lowering drugs).

Ming's rule pack only reads fixed questionnaire fields; anything else is `unknown`. When a
history criterion is unknown and the questionnaire carries free text, the model reads it and
returns structured facts. It does not decide the criterion:

  - every fact must carry a quote; quotes that do not occur in the source are dropped, and a
    fact without a verified quote is ignored;
  - the code applies Ming's thresholds and windows (cigarettes/day and /week, lookback months
    or days, date arithmetic) to those facts;
  - anything the model marks unclear stays `unknown`, with the model's explanation for the CRC.

The resulting verdict is marked `interpreted`. When it settles an exclusion (verified quote,
code-applied threshold or window, drug class confirmed by RxNav) the patient is excluded like any
other exclusion, with the quote shown (decided 2026-10-09). A class vouched for only by the model
sets `review_reason` and goes to review instead.
"""

import calendar
from datetime import date, timedelta
from typing import Literal

from pydantic import BaseModel, Field

from src.agent import llm, trace
from src.tools import rxnav
from src.engine.evaluate import Verdict

FREE_TEXT_FIELD = {"E3": "smoking_free_text", "E4": "advanced_free_text", "E5": "lipid_free_text"}

SYSTEM = """You help a clinical research coordinator read a patient's own words from a screening interview.
Extract facts only. Do not decide eligibility and do not compare numbers with any threshold.
For every fact give a short exact quote copied from the text that supports it.
If the text does not say something, use null or "unclear"; never guess."""


class SmokingFacts(BaseModel):
    currently_smokes: Literal["yes", "no", "unclear"] = Field(description="Smoked at any time in the lookback window")
    smokes_every_day: Literal["yes", "no", "unclear"]
    cigarettes_on_a_smoking_day: float | None = Field(description="Typical number on a day the patient smokes")
    smoking_days_per_week: float | None = Field(description="Typical number of smoking days per week (7 if daily)")
    quotes: list[str] = Field(description="Exact quotes from the text supporting the facts")
    explanation: str = Field(description="One or two sentences for the CRC")


class Exposure(BaseModel):
    substance: str
    in_class: Literal["yes", "no", "unclear"] = Field(description="Belongs to the drug class named in the criterion")
    prescription: Literal["yes", "no", "unclear"] = Field(description="Prescription medicine (not OTC or a supplement)")
    last_use_date: str | None = Field(description="ISO date of last use if stated (YYYY-MM-DD; month only -> first of month)")
    ongoing: bool = Field(description="Still taking it at screening")
    quote: str = Field(description="Exact quote from the text about this substance")
    why: str = Field(description="Why it is or is not in the class, e.g. brand name -> generic -> class")


class ExposureFacts(BaseModel):
    exposures: list[Exposure] = Field(description="EVERY drug, injection, supplement or product the text mentions, "
                                                    "whether or not you think it belongs to the class")
    explicitly_none: bool = Field(description="The text explicitly says there was no such exposure")
    explanation: str = Field(description="One or two sentences for the CRC")


def _answers(case) -> dict:
    qr = next(e["resource"] for e in case.bundle["entry"] if e["resource"]["resourceType"] == "QuestionnaireResponse")
    out = {}
    for item in qr.get("item", []):
        vals = [v for a in item.get("answer", []) for k, v in a.items() if k.startswith("value")]
        if vals:
            out[item["linkId"]] = vals[0]
    return out, f"QuestionnaireResponse/{qr['id']}"


def has_free_text(case, cid: str) -> bool:
    return bool(_answers(case)[0].get(FREE_TEXT_FIELD.get(cid, "")))


def _window_start(screening: date, rule: dict) -> date:
    if rule.get("lookback_days"):
        return screening - timedelta(days=rule["lookback_days"])
    months = rule.get("lookback_calendar_months", 0)
    y, m = divmod(screening.year * 12 + screening.month - 1 - months, 12)  # same as Ming's subtract_months
    return screening.replace(year=y, month=m + 1, day=min(screening.day, calendar.monthrange(y, m + 1)[1]))


def _date(s: str | None) -> date | None:
    try:
        return date.fromisoformat(s[:10]) if s else None
    except ValueError:
        return None


def interpret(case, cid: str, rule: dict, source_text: str, prior: Verdict, model=None) -> Verdict:
    answers, ref = _answers(case)
    text = answers.get(FREE_TEXT_FIELD[cid], "")
    screening = date.fromisoformat(case.screening_date)
    v = Verdict(prior.patient_id, cid, status="unknown", trace=[dict(t) for t in prior.trace], blocking=prior.blocking)
    v.evidence = [{"resource_id": ref, "value": f"{FREE_TEXT_FIELD[cid]}: \"{text}\"", "date": case.ctx.get("screening_at")}]
    v.interpreted = True

    try:
        if cid == "E3":
            facts = llm.structured_call(SYSTEM, (
                f"Protocol criterion: {source_text}\nLookback window: {_window_start(screening, rule)} to {screening}.\n"
                f"Patient's words: \"{text}\""), SmokingFacts, model)
        else:
            facts = llm.structured_call(SYSTEM, (
                f"Protocol criterion: {source_text}\nScreening date: {screening}.\n"
                f"Patient's words: \"{text}\""), ExposureFacts, model)
    except Exception as e:  # noqa: BLE001 - model trouble leaves the rule result in place
        trace.add(v.trace, "agent:error", f"{type(e).__name__}: {str(e)[:160]}", "unknown")
        v.note, v.interpreted = prior.note, False
        return v

    if cid == "E3":
        verified = [q for q in facts.quotes if llm.quote_found(q, text)]
        per_day, days = facts.cigarettes_on_a_smoking_day, facts.smoking_days_per_week
        if facts.smokes_every_day == "yes" and days is None:
            days = 7
        per_week = per_day * days if per_day is not None and days is not None else None
        trace.add(v.trace, "interpret_free_text",
                  f"smokes={facts.currently_smokes} daily={facts.smokes_every_day} per_smoking_day={per_day} "
                  f"days/week={days}; quotes verified {len(verified)}/{len(facts.quotes)}")
        g = lambda x: "?" if x is None else f"{x:g}"  # noqa: E731
        # The protocol's two definitions, applied by code: >daily per day, >weekly per week.
        over_day = per_day is not None and per_day > rule["daily"]
        over_week = per_week is not None and per_week > rule["weekly"]
        if not verified:
            v.note = "free text not usable: no supporting quote found in the source"
        elif facts.currently_smokes == "no":
            v.status, v.note = "not_met", f"patient reports no smoking in the window ({verified[0]!r})"
        elif facts.currently_smokes != "yes" or per_day is None:
            v.note = "smoking status or amount unclear from the patient's words"
        elif facts.smokes_every_day == "yes":
            v.status = "met" if (over_day or over_week) else "not_met"
            v.note = f"daily smoking, {g(per_day)}/day (~{g(per_week)}/week) vs >{rule['daily']}/day or >{rule['weekly']}/week"
        elif over_day != over_week or per_week is None:
            # Non-daily smoking where the per-day and per-week definitions disagree: a genuine boundary case.
            week_part = ("per-week amount not stated" if per_week is None else
                         f"~{g(per_week)}/week ({'>' if over_week else '<='}{rule['weekly']}/week)")
            v.note = (f"intermittent smoking: {g(per_day)} on smoking days ({'>' if over_day else '<='}{rule['daily']}/day), "
                      f"{week_part}; the per-day and per-week definitions do not settle whether this is 'regular' "
                      f"smoking, CRC to judge")
        else:
            v.status = "met" if over_day else "not_met"
            v.note = f"intermittent smoking, {g(per_day)}/smoking day, ~{g(per_week)}/week; both definitions agree"
        v.note += f". Agent: {facts.explanation}"
        trace.add(v.trace, "rule:interpreted_threshold", v.note, v.status)
        return v

    start = _window_start(screening, rule)
    counted, unclear, outside, weak = [], [], [], []
    for x in facts.exposures:
        if not llm.quote_found(x.quote, text):
            trace.add(v.trace, "rule:quote_check", f"dropped {x.substance!r}: quote not found in source")
            continue
        last = screening if x.ongoing else _date(x.last_use_date)
        # Drug class from the terminology service, not from the model's memory.
        term = rxnav.lookup(x.substance)
        klass = rxnav.in_class(term, cid)
        matched = rxnav.matched_class(term, cid)
        source = f"RxNav: {', '.join(term['ingredients'][:1]) or x.substance}" + (f" -> {matched}" if matched else "")
        model_only = klass is None
        if model_only:  # terminology cannot tell: keep the model's yes, never trust its no
            klass, source = ("yes" if x.in_class == "yes" else "unclear"), "model (not in terminology)"
        trace.add(v.trace, "rxnav", f"{x.substance} -> {term['status']} {term['ingredients'][:2]} -> in class: {klass} "
                                    f"(model said {x.in_class})")
        needs_rx = cid == "E5"  # E5 is about prescription lipid-lowering medication
        in_window = last is not None and start <= last <= screening
        label = f"{x.substance} (class {klass} per {source}; prescription {x.prescription}; last use {last or 'unknown'})"
        if klass == "yes" and in_window and (x.prescription == "yes" or not needs_rx):
            counted.append(label)
            if model_only:
                weak.append(x.substance)
        elif klass == "no" or (last is not None and not in_window):
            outside.append(label)
        else:
            # in class but OTC / prescription unclear, class unclear, or no date: a person decides
            unclear.append(label)
    # Safety net independent of the model: drug names RxNorm finds in the text that belong to the class.
    # The model has left out a drug it wrongly thought irrelevant (Leqvio); such a drug can never vanish.
    reported = " ".join(f"{x.substance} {' '.join(rxnav.lookup(x.substance).get('ingredients', []))}" for x in facts.exposures).lower()
    for hit in rxnav.scan_text(text, cid):
        names = [hit["phrase"]] + hit["ingredients"]
        if not any(n.lower() in reported for n in names):
            label = (f"{hit['phrase']} (RxNorm: {', '.join(hit['ingredients'][:1])} -> {rxnav.matched_class(hit, cid)}; "
                     f"found in the text but not reported by the model)")
            unclear.append(label)
            trace.add(v.trace, "rule:terminology_scan", label, "unknown")
    trace.add(v.trace, "interpret_free_text",
              f"{len(facts.exposures)} substance(s): in class & in window {len(counted)}, unclear {len(unclear)}, "
              f"not counted {len(outside)}; window {start}..{screening}")
    if counted:
        v.status = "met"
        if weak and len(weak) == len(counted):
            # Only the model vouches for the drug class: not firm enough to exclude without a person.
            v.review_reason = f"drug class of {', '.join(weak)} from the model only, not confirmed by RxNav"
    elif not unclear and (outside or facts.explicitly_none):
        v.status = "not_met"
    parts = [f"counts: {'; '.join(counted)}" if counted else "",
             f"needs CRC judgement: {'; '.join(unclear)}" if unclear else "",
             f"not counted: {'; '.join(outside)}" if outside else "",
             "patient explicitly reports none" if facts.explicitly_none and not facts.exposures and not unclear else ""]
    v.note = " | ".join(p for p in parts if p) or "no usable statement about this class"
    # The model's own prose can contain wrong drug facts (it called inclisiran an ASO); keep it in the
    # trace, labelled, and build the CRC-facing note only from verified facts and the terminology.
    trace.add(v.trace, "agent:summary", f"model text, not verified: {facts.explanation}")
    trace.add(v.trace, "rule:interpreted_window", v.note, v.status)
    return v

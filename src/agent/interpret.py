"""Free-text history interpretation for SAD E3 (smoking), E4 (advanced therapies), E5 (lipid-lowering drugs).

The SAD rule pack only reads fixed questionnaire fields; anything else is `unknown`. When a
history criterion is unknown and the questionnaire carries free text, the model reads it and
returns structured facts. It does not decide the criterion:

  - every fact must carry a quote; quotes that do not occur in the source are dropped, and a
    fact without a verified quote is ignored;
  - the code applies the rule pack's thresholds and windows (cigarettes/day and /week, lookback months
    or days, date arithmetic) to those facts;
  - anything the model marks unclear stays `unknown`, with the model's explanation for the CRC.

The resulting verdict is marked `interpreted`. Aggregation routes interpreted failures to
review: quote existence and terminology do not verify the extracted amount, date or negation.
Ranges and uncertain facts stay unknown rather than becoming a point estimate.
"""

import calendar
import math
import re
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
If the text does not say something, use null only for nullable fields, or "unclear"; never guess.
The uncertain field must be true or false, never null. Mark approximate or uncertain amounts true.
Range fields must be null or an object with lower and upper numbers, never a single number.
Put a single quantity in the corresponding cigarettes quantity field, not in a range field."""


class NumericRange(BaseModel):
    lower: float
    upper: float


class SmokingFacts(BaseModel):
    currently_smokes: Literal["yes", "no", "unclear"] = Field(description="Smoked at any time in the lookback window")
    smokes_every_day: Literal["yes", "no", "unclear"]
    cigarettes_on_a_smoking_day: float | None = Field(description="Typical number on a day the patient smokes")
    smoking_days_per_week: float | None = Field(description="Typical number of smoking days per week (7 if daily)")
    cigarettes_per_week: float | None = Field(default=None, description="Cigarettes per week if stated or directly implied (a pack = 20)")
    quotes: list[str] = Field(description="Exact quotes from the text supporting the facts")
    explanation: str = Field(description="One or two sentences for the CRC")
    uncertain: bool = Field(description="True for uncertain, conflicting or approximate amounts; never replace a range with its midpoint or upper bound")
    daily_range: NumericRange | None = Field(description="Inclusive lower and upper cigarettes/day when a range is stated; otherwise null, never a scalar")
    weekly_range: NumericRange | None = Field(description="Inclusive lower and upper cigarettes/week when a range is stated; otherwise null, never a scalar")


class Exposure(BaseModel):
    substance: str
    in_class: Literal["yes", "no", "unclear"] = Field(description="Belongs to the drug class named in the criterion")
    prescription: Literal["yes", "no", "unclear"] = Field(description="Prescription medicine (not OTC or a supplement)")
    last_use_date: str | None = Field(description="Exact ISO date only (YYYY-MM-DD). Month-only, approximate or uncertain dates must be null; never invent the first day")
    ongoing: bool = Field(description="Still taking it at screening")
    quote: str = Field(description="Exact quote from the text about this substance")
    why: str = Field(description="Why it is or is not in the class, e.g. brand name -> generic -> class")
    uncertain: bool = Field(description="True if exposure, prescription status or date is uncertain")


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
    y, m = divmod(screening.year * 12 + screening.month - 1 - months, 12)  # same as the SAD evaluator's subtract_months
    return screening.replace(year=y, month=m + 1, day=min(screening.day, calendar.monthrange(y, m + 1)[1]))


def _date(s: str | None) -> date | None:
    try:
        return date.fromisoformat(s) if s and re.fullmatch(r'\d{4}-\d{2}-\d{2}', s) else None
    except (ValueError, TypeError):
        return None


def _uncertain_smoking_source(text):
    # Independent source guard: a model must not collapse "one or two" into 14/week.
    number = r'(?:\d+(?:\.\d+)?|one|two|three|four|five|six|seven|eight|nine|ten)'
    without_dates = re.sub(r'\d{4}-\d{2}-\d{2}', '', text.lower())
    ranged = re.search(rf'\b{number}\s*(?:or|to|[-–—])\s*{number}\b|\bbetween\s+{number}\s+and\s+{number}\b', without_dates)
    approximate = re.search(rf'\b(?:about|around|roughly|approximately|up to|at least|less than|more than)\s+(?:{number}|half|a\b)', without_dates)
    return bool(ranged or approximate)


def _uncertain_smoking(facts, text):
    values = [facts.cigarettes_on_a_smoking_day, facts.smoking_days_per_week, facts.cigarettes_per_week]
    invalid = any(x is not None and (not math.isfinite(x) or x < 0) for x in values)
    invalid |= facts.smoking_days_per_week is not None and facts.smoking_days_per_week > 7
    return bool(facts.uncertain or facts.daily_range is not None or facts.weekly_range is not None
                or _uncertain_smoking_source(text) or invalid)


def interpret(case, cid: str, rule: dict, source_text: str, prior: Verdict, model=None) -> Verdict:
    answers, ref = _answers(case)
    text = answers.get(FREE_TEXT_FIELD[cid], "")
    screening = date.fromisoformat(case.screening_date)
    v = Verdict(prior.patient_id, cid, status="unknown", trace=[dict(t) for t in prior.trace], blocking=prior.blocking)
    v.evidence = [{"resource_id": ref, "value": f"{FREE_TEXT_FIELD[cid]}: \"{text}\"", "date": case.ctx.get("screening_at")}]
    v.interpreted = True

    if cid == 'E3' and _uncertain_smoking_source(text):
        v.note = 'source smoking amount is a range or approximate; CRC to judge; do not substitute a point estimate'
        trace.add(v.trace, 'rule:uncertain_fact', v.note, 'unknown')
        return v

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
        if verified and _uncertain_smoking(facts, text):
            v.note = 'smoking amount is a range, uncertain or invalid; CRC to judge; do not substitute a point estimate'
            trace.add(v.trace, 'rule:uncertain_fact', v.note, 'unknown')
            return v
        per_day, days = facts.cigarettes_on_a_smoking_day, facts.smoking_days_per_week
        if facts.smokes_every_day == "yes" and days is None:
            days = 7
        per_week = facts.cigarettes_per_week
        if per_week is None and per_day is not None and days is not None:
            per_week = per_day * days
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
        elif facts.currently_smokes == "yes" and over_week:
            # >10/week is unambiguous whatever the daily pattern
            v.status = "met"
            v.note = (f"{g(per_day) + '/day, ' if per_day is not None else ''}~{g(per_week)} cigarettes/week "
                      f"> {rule['weekly']}/week")
        elif facts.currently_smokes != "yes" or (per_day is None and per_week is None):
            v.note = "smoking status or amount unclear from the patient's words"
        elif per_day is None:
            v.status = "not_met" if per_week is not None and not over_week and facts.smokes_every_day != "yes" else "unknown"
            v.note = f"~{g(per_week)}/week, per-day amount not stated"
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
    # Self-check: drugs RxNorm finds in the text that belong to the class but the model did not report.
    # The model is asked once more, naming them; this is the agent correcting its own omission.
    def missed(f):
        reported = " ".join(f"{x.substance} {' '.join(rxnav.lookup(x.substance).get('ingredients', []))}"
                            for x in f.exposures).lower()
        return [h for h in rxnav.scan_text(text, cid)
                if not any(n.lower() in reported for n in [h["phrase"]] + h["ingredients"])]
    first_missed = missed(facts)
    if first_missed:
        names = ", ".join(h["phrase"] for h in first_missed)
        trace.add(v.trace, "rule:terminology_scan", f"model did not report {names}, which RxNorm finds in the text; asking again")
        try:
            facts = llm.structured_call(SYSTEM, (
                f"Protocol criterion: {source_text}\nScreening date: {screening}.\nPatient's words: \"{text}\"\n"
                f"Your previous answer left out these products mentioned in the text: {names}. "
                f"List every product the text mentions, including these, with its last use date."), ExposureFacts, model)
            trace.add(v.trace, "interpret_free_text", f"second pass reported: {', '.join(x.substance for x in facts.exposures) or 'nothing'}")
        except Exception as e:  # noqa: BLE001
            trace.add(v.trace, "agent:error", f"{type(e).__name__}: {str(e)[:160]}")
    counted, unclear, outside, weak = [], [], [], []
    for x in facts.exposures:
        if not llm.quote_found(x.quote, text):
            trace.add(v.trace, "rule:quote_check", f"dropped {x.substance!r}: quote not found in source")
            continue
        if x.uncertain:
            unclear.append(f'{x.substance}: uncertain exposure facts')
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
    # Safety net independent of the model: an in-class drug still missing after the second pass can never vanish.
    for hit in missed(facts):
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

"""Patient-level conclusion from per-criterion verdicts. Fixed rules, no model.

Rules, first match wins:
  1. any exclusion met                         -> excluded (names the criterion)
  2. any verdict flagged as conflict           -> needs_review
  3. any blocking unknown                      -> pending (names the missing data)
  4. all computable inclusions met             -> likely_eligible (+ confirm-at-visit notes)
  5. any inclusion not_met                     -> excluded
Rules 3 and 5 swap when config.PENDING_BEFORE_INCLUSION_FAIL is False.

Predicates that are not computable (computable=false or grade N) never block:
they are listed as checks the CRC does herself.
"""

from dataclasses import dataclass, field

from src import config
from src.engine.evaluate import Verdict

CATEGORIES = ["likely_eligible", "pending", "excluded", "needs_review"]
LABELS = {
    "likely_eligible": "Likely eligible",
    "pending": "Pending (data needed)",
    "excluded": "Excluded",
    "needs_review": "Needs review",
}


@dataclass
class PatientResult:
    patient_id: str
    category: str
    reasons: list[str] = field(default_factory=list)  # why this category, one line each
    decisive: list[str] = field(default_factory=list)  # criterion_ids that decided the category
    missing: list[str] = field(default_factory=list)  # data items holding the patient in pending
    also_fails: list[str] = field(default_factory=list)  # pending patients: inclusions already not met
    confirm_at_visit: list[str] = field(default_factory=list)  # non-blocking unknowns
    crc_checks: list[str] = field(default_factory=list)  # not computable by design
    verdicts: list[Verdict] = field(default_factory=list)


def _computable(p: dict) -> bool:
    return p.get("computable") is not False and p.get("grade") != "N"


def _label(p: dict) -> str:
    return f"{p['criterion_id']} {p.get('concept', '')}".strip()


def _why(p: dict, v: Verdict) -> str:
    return f"{_label(p)}: {'(from free text) ' if v.interpreted else ''}{v.note}"


def aggregate(patient_id: str, predicates: list[dict], verdicts: list[Verdict], failed_first: bool = False) -> PatientResult:
    """failed_first (SAD rule): any clearly failed criterion -> excluded before conflicts and unknowns."""
    by_id = {p["criterion_id"]: p for p in predicates}
    pairs = [(by_id[v.criterion_id], v) for v in verdicts]
    r = PatientResult(patient_id, "pending", verdicts=verdicts)

    computable = [(p, v) for p, v in pairs if _computable(p)]
    r.crc_checks = [_label(p) for p, _ in pairs if not _computable(p)]

    failing = [(p, v) for p, v in computable
               if (p["type"] == "exclusion" and v.status == "met") or (p["type"] == "inclusion" and v.status == "not_met")]
    # Quote existence and a terminology match do not verify extracted amount/date/negation.
    # No model-interpreted failure can directly exclude, even if it omitted review_reason.
    suggested = [(p, v) for p, v in failing if v.interpreted]
    excl_met = [(p, v) for p, v in computable if p["type"] == "exclusion" and v.status == "met"
                and not v.interpreted]
    conflicts = [(p, v) for p, v in computable if v.conflict]
    flagged = [(p, v) for p, v in pairs if v.review_reason and not v.interpreted]  # agent evidence, e.g. I5
    blocking_unknown = [(p, v) for p, v in computable if v.status == "unknown" and v.blocking]
    soft_unknown = [(p, v) for p, v in computable if v.status == "unknown" and not v.blocking]
    incl = [(p, v) for p, v in computable if p["type"] == "inclusion"]
    incl_failed = [(p, v) for p, v in incl if v.status == "not_met" and not v.interpreted]

    def pending() -> PatientResult:
        r.category = "pending"
        # "missing" = no record; a rejected record (bad unit, implausible value) is named as such
        r.missing = [_label(p) + (" (record unusable, see note)" if v.evidence else "") for p, v in blocking_unknown]
        r.reasons = [_why(p, v) for p, v in blocking_unknown]
        r.decisive = [v.criterion_id for _, v in blocking_unknown]
        # the CRC should not chase missing data for a patient who already fails an inclusion
        r.also_fails = [_why(p, v) for p, v in incl_failed]
        return r

    def excluded_by_inclusion() -> PatientResult:
        r.category = "excluded"
        r.reasons = [_why(p, v) for p, v in incl_failed]
        r.decisive = [v.criterion_id for _, v in incl_failed]
        return r

    if failed_first and (excl_met or incl_failed):
        failed = excl_met + incl_failed
        r.category = "excluded"
        r.reasons = [_why(p, v) for p, v in failed]
        r.decisive = [v.criterion_id for _, v in failed]
        return r
    if excl_met:
        r.category = "excluded"
        r.reasons = [_why(p, v) for p, v in excl_met]
        r.decisive = [v.criterion_id for _, v in excl_met]
        return r
    if conflicts or suggested or flagged:
        r.category = "needs_review"
        r.reasons = ([_why(p, v) for p, v in conflicts]
                     + [f"{_label(p)}: agent reading suggests {'exclusion' if p['type'] == 'exclusion' else 'not met'}, "
                        f"CRC to confirm: {v.note}" for p, v in suggested]
                     + [f"{_label(p)}: {v.review_reason}" for p, v in flagged])
        r.decisive = [v.criterion_id for _, v in conflicts + suggested + flagged]
        return r

    if config.PENDING_BEFORE_INCLUSION_FAIL:
        if blocking_unknown:
            return pending()
        if incl_failed:
            return excluded_by_inclusion()
    else:
        if incl_failed:
            return excluded_by_inclusion()
        if blocking_unknown:
            return pending()

    # every computable inclusion is met (or a non-blocking unknown)
    r.category = "likely_eligible"
    r.reasons = [f"all {len(incl)} computable inclusion criteria met; no exclusion met"]
    r.decisive = [v.criterion_id for _, v in incl if v.status == "met"]
    r.confirm_at_visit = [_label(p) for p, _ in soft_unknown] + [
        f"{_label(p)} (from free text)" for p, v in computable if v.interpreted and v.status in ("met", "not_met")]
    return r

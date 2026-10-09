"""T10: amendment impact report: what changed in the criteria, and which patients change status and why."""

from pathlib import Path

from src.amendment.monitor import AmendmentCheck, PatientChange
from src.engine.aggregate import LABELS
from src.report.log_writer import _cell

ACTION = {"substantive": "re-screen", "wording": "recorded, no re-screen", "ambiguous": "CRC to confirm, no re-screen"}


def render(trial: str, nct: str, screening_date: str, chk: AmendmentCheck, rescreened: bool, blocked: str,
           pred_changes: dict[str, list[str]], patients: list[PatientChange], v2_source: str, generated_at: str,
           n_patients: int) -> str:
    out = [
        f"# Amendment impact report: trial {trial} ({nct})",
        "",
        f"- Screening date: {screening_date} · Generated: {generated_at}",
        f"- Previous criteria: `{chk.old_source}` SHA-256 `{chk.old_sha[:12]}`",
        f"- New criteria: `{chk.new_source}` SHA-256 `{chk.new_sha[:12]}`",
        f"- Changed items: {len(chk.changes)} · substantive {len(chk.labelled('substantive'))}"
        f" · wording {len(chk.labelled('wording'))} · ambiguous {len(chk.labelled('ambiguous'))}",
        f"- Re-screen: " + (f"done with `{v2_source}`; {n_patients} patients, {len(patients)} affected"
                            if rescreened else f"not run ({blocked})"),
        "",
        "> Classification is by the model (or by rule when only case, spacing or punctuation differ).",
        "> Amended predicates are prepared and reviewed by a person; they are not compiled automatically.",
        "",
        "## Changed criteria",
        "",
        "| # | Section | Change | Before | After | Classification | Reason | Action |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for i, c in enumerate(chk.changes, 1):
        out.append(f"| {i} | {c.section} | {c.kind} | {_cell(c.old or '-')} | {_cell(c.new or '-')} | "
                   f"**{c.label}** | {_cell(c.reason)} | {ACTION[c.label]} |")
    out.append("")

    if pred_changes:
        out += ["## Predicate changes (amended predicate file)", ""]
        out += [f"- **{cid}**: " + "; ".join(_cell(d) for d in diffs) for cid, diffs in pred_changes.items()]
        out.append("")

    out += [f"## Patients whose status changes ({sum(p.old_category != p.new_category for p in patients)})", ""]
    flipped = [p for p in patients if p.old_category != p.new_category]
    if not rescreened:
        out += ["_no re-screen run_", ""]
    elif not flipped:
        out += ["_none_", ""]
    else:
        out += ["| Patient | Before | After | Because |", "|---|---|---|---|"]
        for p in flipped:
            why = "<br>".join(f"**{cid}** {old} → {new}: {_cell(note)}" for cid, old, new, note in p.criteria)
            out.append(f"| `{p.patient_id}` | {LABELS[p.old_category]} | **{LABELS[p.new_category]}** | {why} |")
        out.append("")

    same = [p for p in patients if p.old_category == p.new_category]
    if same:
        out += ["## Criterion changes without a status change", "", "| Patient | Status | Criterion changes |", "|---|---|---|"]
        for p in same:
            why = "<br>".join(f"**{cid}** {old} → {new}" for cid, old, new, _ in p.criteria)
            out.append(f"| `{p.patient_id}` | {LABELS[p.new_category]} | {why} |")
        out.append("")

    out += ["## Trace", "", "```"]
    for i, c in enumerate(chk.changes, 1):
        for t in c.trace:
            out.append(f"change {i:<3} {t['tool']:<18} {t['result']} => {t['decision']}")
    out += ["```", ""]
    return "\n".join(out)


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path

"""T6: write the pre-screening log the CRC reads (Markdown) and the eval reads (CSV)."""

import csv
import logging
from datetime import datetime, timezone
from pathlib import Path

from src import config
from src.engine.aggregate import CATEGORIES, LABELS, PatientResult

log = logging.getLogger(__name__)


def _cell(text) -> str:
    return str(text if text is not None else "").replace("|", "\\|").replace("\n", " ")


def _ev(v) -> str:
    return "; ".join(f"`{e['resource_id']}` {e.get('value')}" + (f" ({str(e['date'])[:10]})" if e.get("date") else "")
                     for e in v.evidence) or "no record"


def _key_evidence(r: PatientResult) -> str:
    decisive = [v for v in r.verdicts if v.criterion_id in r.decisive]
    return "<br>".join(f"**{v.criterion_id}** {_ev(v)}" for v in decisive)


def _notes(r: PatientResult) -> str:
    parts = []
    if r.category == "pending":
        parts.append("Needs data: " + ", ".join(r.missing))
        parts += [f"Already fails {x}" for x in r.also_fails]
    elif r.category != "likely_eligible":
        parts += r.reasons
    if r.confirm_at_visit:
        parts.append("Confirm at visit: " + ", ".join(r.confirm_at_visit))
    if r.crc_checks:
        parts.append("CRC to check: " + ", ".join(r.crc_checks))
    parts += [f"↳ {v.criterion_id} agent: {v.recovery}" for v in r.verdicts if v.recovery]
    return "<br>".join(_cell(p) for p in parts)


def render_markdown(trial: str, nct: str, fetch, screening_date: str, results: list[PatientResult],
                    predicates: list[dict], generated_at: str, injections: list[str] = (),
                    criteria_source: str | None = None) -> str:
    preds = {p["criterion_id"]: p for p in predicates}
    groups = {c: [r for r in results if r.category == c] for c in CATEGORIES}

    if criteria_source:
        source = criteria_source
    elif fetch.status == "stale":
        source = f"**STALE**: served from cache, {fetch.cache_age_days:g} days old (fetched {fetch.fetched_at[:16]} UTC; live fetch failed: {fetch.error})"
    else:
        source = f"fetched live {fetch.fetched_at[:16]} UTC"

    out = [
        f"# Pre-screening log: trial {trial} ({nct})",
        "",
        f"- Screening date: {screening_date}",
        f"- Eligibility criteria: {source}; SHA-256 `{(fetch.sha256 or '')[:12]}`",
        f"- Generated: {generated_at}",
        f"- Patients screened: {len(results)} · " + " · ".join(f"{LABELS[c]}: {len(groups[c])}" for c in CATEGORIES),
        "",
    ]
    if injections:
        out += ["> **Failure injection active (demo).** The following data was altered in memory for this run:", ">"]
        out += [f"> - {_cell(x)}" for x in injections]
        out += [""]
    out += [
        "> Synthetic data only. No patient has been contacted. Every verdict links to the record it used;"
        " anything the data cannot settle is marked pending or left to the CRC, never guessed.",
        "",
    ]
    for c in CATEGORIES:
        out += [f"## {LABELS[c]} ({len(groups[c])})", ""]
        if not groups[c]:
            out += ["_none_", ""]
            continue
        out += ["| Patient | Key evidence | Notes |", "|---|---|---|"]
        for r in groups[c]:
            out.append(f"| `{r.patient_id}` | {_key_evidence(r)} | {_notes(r)} |")
        out.append("")

    out += ["## Per-patient detail", ""]
    for r in sorted(results, key=lambda r: (CATEGORIES.index(r.category), r.patient_id)):
        out += [f"<details><summary><code>{r.patient_id}</code>: {LABELS[r.category]}</summary>", "",
                "| Criterion | Type | Status | Evidence | Note |", "|---|---|---|---|---|"]
        for v in r.verdicts:
            p = preds[v.criterion_id]
            flag = " (non-blocking)" if v.status == "unknown" and not v.blocking else ""
            out.append(f"| {v.criterion_id} {_cell(p.get('concept'))} | {p['type']} | {v.status}{flag} | {_ev(v)} | {_cell(v.note)} |")
        out += [f"\n↳ **{v.criterion_id}** agent: {_cell(v.recovery)}" for v in r.verdicts if v.recovery]
        out += ["", "Trace (`rule:*` = fixed rule, `fhir_query` = engine query, anything else = agent tool call):", "", "```"]
        for v in r.verdicts:
            for t in v.trace:
                out.append(f"{v.criterion_id:<8} {t['step']:>2}. {t['tool']:<24} {t['result']}" + (f" => {t['decision']}" if t["decision"] else ""))
        out += ["```", "", "</details>", ""]
    return "\n".join(out)


CSV_FIELDS = ["trial", "screening_date", "patient_id", "patient_category", "criterion_id", "type", "computable",
              "status", "blocking", "needs_recovery", "interpreted", "evidence_ids", "note", "agent_summary",
              "review_reason"]


def write_csv(path: Path, trial: str, screening_date: str, results: list[PatientResult], predicates: list[dict]) -> None:
    preds = {p["criterion_id"]: p for p in predicates}
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        for r in results:
            for v in r.verdicts:
                w.writerow({"trial": trial, "screening_date": screening_date, "patient_id": r.patient_id,
                            "patient_category": r.category, "criterion_id": v.criterion_id,
                            "type": preds[v.criterion_id]["type"],
                            "computable": preds[v.criterion_id].get("computable") is not False
                            and preds[v.criterion_id].get("grade") != "N",
                            "status": v.status, "blocking": v.blocking,
                            "needs_recovery": v.needs_recovery,
                            "interpreted": v.interpreted,
                            "evidence_ids": ";".join(str(e["resource_id"]) for e in v.evidence), "note": v.note,
                            "agent_summary": v.recovery, "review_reason": v.review_reason})


def write_log(trial: str, nct: str, fetch, screening_date: str, results: list[PatientResult],
              predicates: list[dict], out_dir: Path | None = None, generated_at: str | None = None,
              injections: list[str] = (), criteria_source: str | None = None) -> tuple[Path, Path, list[str]]:
    out_dir = Path(out_dir or config.OUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    generated_at = generated_at or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    stem = f"prescreen_log_{trial}_{screening_date}"
    md, csv_path = out_dir / f"{stem}.md", out_dir / f"{stem}.csv"
    md.write_text(render_markdown(trial, nct, fetch, screening_date, results, predicates, generated_at, injections,
                                  criteria_source),
                  encoding="utf-8")
    write_csv(csv_path, trial, screening_date, results, predicates)
    return md, csv_path, _upload(trial, screening_date, [md, csv_path])


def _upload(trial: str, screening_date: str, paths: list[Path]) -> list[str]:
    if not config.s3_enabled():
        return ["S3_BUCKET not set; log kept locally only"]
    try:
        import boto3

        s3 = boto3.Session(profile_name=config.AWS_PROFILE, region_name=config.AWS_REGION).client("s3")
        for p in paths:
            s3.upload_file(str(p), config.S3_BUCKET, f"logs/{trial}/{screening_date}/{p.name}")
        return []
    except Exception as e:  # noqa: BLE001 - S3 must never lose the local log
        return [f"S3 upload failed: {e}"]

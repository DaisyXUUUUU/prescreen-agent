"""Weekly pre-screening run for one trial.

    python run.py --trial B --date 2026-10-12
    python run.py --trial B --fail ctgov_timeout

Development run on fixtures (until Ming's data lands):

    python run.py --trial SAMPLE --nct NCT02178098 \
        --predicates tests/fixtures/sample_predicates.json --patients tests/fixtures/patients --date 2026-10-09
"""

import argparse
import json
import logging
import sys
from pathlib import Path

from src import config, failures
from src.adapters import fhir_store
from src.agent import trace
from src.amendment.rescreen import run_amendment
from src.engine.aggregate import CATEGORIES, LABELS
from src.pipeline import screen
from src.report.log_writer import write_log
from src.tools.ctgov import ctgov_fetch


def load_predicates(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["predicates"] if isinstance(data, dict) else data


def main() -> int:
    parser = argparse.ArgumentParser(description="Pre-screen every patient for one trial and write the CRC log")
    parser.add_argument("--trial", required=True, help="trial letter, e.g. B")
    parser.add_argument("--date", default=config.SCREENING_DATE, help="screening date YYYY-MM-DD (default today)")
    parser.add_argument("--nct", help="override the trial's NCT ID from src/config.py")
    parser.add_argument("--predicates", type=Path, help="default data/predicates/trial_{TRIAL}.json")
    parser.add_argument("--patients", type=Path, default=config.PATIENT_DIR)
    parser.add_argument("--out", type=Path, default=config.OUT_DIR)
    parser.add_argument("--no-agent", action="store_true", help="skip the recovery agent (rules only)")
    parser.add_argument("--v1-snapshot", type=Path, help="T10: previous criteria text (default: latest snapshot)")
    parser.add_argument("--v2-snapshot", type=Path,
                        help="T10 with --fail amendment_v2: amended criteria text (default data/snapshots/{NCT}/amendment_v2.txt)")
    parser.add_argument("--v2-predicates", type=Path, help="T10: amended predicates (default data/predicates/trial_{TRIAL}_v2.json)")
    parser.add_argument("--fail", action="append", default=[], choices=sorted(config.FAILURES),
                        help="enable a failure-injection switch (repeatable)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    for name in args.fail:
        config.enable_failure(name)

    try:
        nct = args.nct or config.trial_nct(args.trial)
    except ValueError as e:
        print(f"error: {e}. Pass --nct to run anyway.", file=sys.stderr)
        return 2
    pred_path = args.predicates or config.DATA_DIR / "predicates" / f"trial_{args.trial}.json"
    if not pred_path.exists():
        print(f"error: predicate file {pred_path} not found", file=sys.stderr)
        return 2

    fetch = ctgov_fetch(nct)
    if fetch.status == "error":
        # brief section 6: no log on criteria we cannot vouch for
        print(f"error: cannot issue a log, eligibility criteria unavailable: {fetch.error}", file=sys.stderr)
        return 3

    predicates = load_predicates(pred_path)
    store = fhir_store.FhirStore(args.patients)
    injections = failures.inject(store)
    if config.failure_enabled("ctgov_timeout"):
        injections.insert(0, f"ctgov_timeout: ClinicalTrials.gov call forced to time out; criteria {fetch.status}")
    fhir_store.set_store(store)
    patients = fhir_store.list_patients()
    if not patients:
        print(f"error: no patients loaded from {args.patients}", file=sys.stderr)
        return 2

    results, attempted, recovered = screen(predicates, args.date, use_agent=not args.no_agent)

    md, csv_path, warnings = write_log(args.trial, nct, fetch, args.date, results, predicates, args.out,
                                       injections=injections)
    impact = run_amendment(args.trial, nct, fetch, args.date, predicates, results, args.out, use_agent=not args.no_agent,
                           v1_snapshot=args.v1_snapshot, v2_snapshot=args.v2_snapshot, v2_predicates=args.v2_predicates)
    trace_path = trace.write_jsonl(args.out / f"trace_{args.trial}_{args.date}.jsonl", args.trial, args.date, results)

    counts = {c: sum(r.category == c for r in results) for c in CATEGORIES}
    print(f"trial {args.trial} ({nct}) · {args.date} · criteria {fetch.status}"
          + (f" ({fetch.cache_age_days:g} days old)" if fetch.status == "stale" else ""))
    for line in injections:
        print(f"injected: {line}")
    print(f"{len(results)} patients: " + ", ".join(f"{LABELS[c]} {n}" for c, n in counts.items()))
    if not args.no_agent:
        print(f"recovery agent: {attempted} empty queries handled, {recovered} resolved")
    print(f"log: {md}\ncsv: {csv_path}\ntrace: {trace_path}" + (f"\namendment impact: {impact}" if impact else ""))
    for w in fetch.warnings + warnings:
        print(f"warning: {w}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

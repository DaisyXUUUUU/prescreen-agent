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

from src import config
from src.adapters import fhir_store
from src.engine.aggregate import CATEGORIES, LABELS, aggregate
from src.engine.evaluate import evaluate
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
    fhir_store.set_store(fhir_store.FhirStore(args.patients))
    patients = fhir_store.list_patients()
    if not patients:
        print(f"error: no patients loaded from {args.patients}", file=sys.stderr)
        return 2

    results = []
    for pid in patients:
        verdicts = [evaluate(p, pid, args.date) for p in predicates]
        # T7 hook: hand verdicts with needs_recovery to the agent before aggregating.
        results.append(aggregate(pid, predicates, verdicts))

    md, csv_path, warnings = write_log(args.trial, nct, fetch, args.date, results, predicates, args.out)

    counts = {c: sum(r.category == c for r in results) for c in CATEGORIES}
    print(f"trial {args.trial} ({nct}) · {args.date} · criteria {fetch.status}"
          + (f" ({fetch.cache_age_days:g} days old)" if fetch.status == "stale" else ""))
    print(f"{len(results)} patients: " + ", ".join(f"{LABELS[c]} {n}" for c, n in counts.items()))
    print(f"log: {md}\ncsv: {csv_path}")
    for w in fetch.warnings + warnings:
        print(f"warning: {w}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

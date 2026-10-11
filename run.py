"""Weekly pre-screening run for one trial.

    python run.py --trial SAD --date 2026-10-09
    python run.py --trial SAD --fail ctgov_timeout

Run on the test fixtures:

    python run.py --trial SAMPLE --nct NCT02178098 \
        --predicates tests/fixtures/sample_predicates.json --patients tests/fixtures/patients --date 2026-10-09
"""

import argparse
import json
import logging
import sys
from datetime import date
from pathlib import Path

from src import config, failures
from src.adapters import fhir_store
from src.agent import trace
from src.amendment.rescreen import run_amendment, unchanged_verdicts
from src.engine.aggregate import CATEGORIES, LABELS
from src.pipeline import screen
from src.report.log_writer import write_log
from src.tools.ctgov import ctgov_fetch


def load_predicates(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["predicates"] if isinstance(data, dict) else data


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description="Pre-screen every patient for one trial and write the CRC log")
    parser.add_argument("--trial", required=True, help="trial key from src/config.py, e.g. SAD")
    parser.add_argument("--date", default=config.SCREENING_DATE, help="screening date YYYY-MM-DD (default today)")
    parser.add_argument("--nct", help="override the trial's NCT ID from src/config.py")
    parser.add_argument("--predicates", type=Path,
                        help="default data/predicates/trial_{TRIAL}.json; for SAD, trials/nct07347678_sad/rules/sad-1.0.0.json")
    parser.add_argument("--patients", type=Path,
                        help="default data/patients/; for SAD, trials/nct07347678_sad/data/cases (contexts in ../context)")
    parser.add_argument("--out", type=Path, default=config.OUT_DIR)
    parser.add_argument("--no-agent", action="store_true", help="skip the recovery agent (rules only)")
    parser.add_argument("--no-extended-cases", action="store_true",
                        help="SAD: core screening set only (default adds the extended scenario set in data/extended_cases/)")
    parser.add_argument("--v1-snapshot", type=Path, help="T10: previous criteria text (default: latest snapshot)")
    parser.add_argument("--v2-snapshot", type=Path,
                        help="T10 with --fail amendment_v2: amended criteria text (default data/snapshots/{NCT}/amendment_v2.txt)")
    parser.add_argument("--v2-predicates", type=Path, help="T10: amended predicates (default data/predicates/trial_{TRIAL}_v2.json)")
    parser.add_argument("--fail", action="append", default=[], choices=sorted(config.FAILURES),
                        help="enable a failure-injection switch (repeatable)")
    args = parser.parse_args()
    try:
        date.fromisoformat(args.date)
    except ValueError:
        parser.error('--date must be YYYY-MM-DD')
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    for name in args.fail:
        config.enable_failure(name)

    try:
        nct = args.nct or config.trial_nct(args.trial)
    except ValueError as e:
        print(f"error: {e}. Pass --nct to run anyway.", file=sys.stderr)
        return 2
    sad = args.trial == "SAD"
    if sad:
        from src.engine import sad_adapter as sa
        pred_path = args.predicates or sa.SPEC_PATH
    else:
        pred_path = args.predicates or config.DATA_DIR / "predicates" / f"trial_{args.trial}.json"
    if not pred_path.exists():
        print(f"error: predicate file {pred_path} not found", file=sys.stderr)
        return 2

    use_agent = not args.no_agent
    model, mode_reason = None, ''
    input_problems = []
    if sad:
        # SAD rule pack and core cases, evaluated by the SAD evaluator through the adapter.
        spec = sa.load_spec(pred_path)
        cases_dir = args.patients or sa.SAD_DIR / "data" / "cases"
        input_problems = sa.verify_inputs(pred_path, cases_dir)
        cases = sa.load_cases(cases_dir)
        ext_dir = config.DATA_DIR / "extended_cases" / "cases"
        if not args.patients and not args.no_extended_cases and ext_dir.exists():
            cases += sa.load_cases(ext_dir)
        if not cases or any(c.screening_date != args.date for c in cases):
            print('error: SAD is a fixed-encounter replay; --date must match every case screening_at. '
                  'Provide new contexts for a new screening date.', file=sys.stderr)
            return 2
        fetch = ctgov_fetch(nct)
        if fetch.status == 'error':
            print(f'error: cannot issue a log, eligibility criteria unavailable: {fetch.error}', file=sys.stderr)
            return 3
        predicates = sa.predicates(spec)
        store = sa.install_store(cases)
        if not config.FAILURE_TARGETS:
            ids = {c.case_id: c.patient_id for c in cases}
            config.FAILURE_TARGETS = {k: [ids[x] for x in v if x in ids] for k, v in sa.DEFAULT_FAILURE_TARGETS.items()}
        injections = failures.inject(store)
        names = {c.patient_id: c.case_id for c in cases}
        for i in injections:  # show case IDs in the log, keep the FHIR ID in the record
            if i.get("patient_id") in names:
                i["case_id"] = names[i["patient_id"]]
                i["text"] = i["text"].replace(i["patient_id"], i["case_id"])
        if use_agent:
            from src.agent.agent import preflight
            model, mode_reason = preflight()
            use_agent = model is not None
        results, attempted, recovered, _ = sa.screen(cases, spec, use_agent=use_agent, model=model, preflight_done=True)

        def rescreen(v2_path):
            spec2 = sa.load_spec(v2_path)
            res, _, _, _ = sa.screen(cases, spec2, use_agent=use_agent, label=" (v2)", model=model, preflight_done=True,
                                      reused_verdicts=unchanged_verdicts(results, predicates, sa.predicates(spec2)))
            return res, sa.predicates(spec2)
    else:
        predicates = load_predicates(pred_path)
        store = fhir_store.FhirStore(args.patients or config.PATIENT_DIR)
        injections = failures.inject(store)
        fhir_store.set_store(store)
        if not fhir_store.list_patients():
            print(f"error: no patients loaded from {args.patients or config.PATIENT_DIR}", file=sys.stderr)
            return 2
        fetch = ctgov_fetch(nct)
        if fetch.status == 'error':
            print(f'error: cannot issue a log, eligibility criteria unavailable: {fetch.error}', file=sys.stderr)
            return 3
        if use_agent:
            from src.agent.agent import preflight
            model, mode_reason = preflight()
            use_agent = model is not None
        results, attempted, recovered = screen(predicates, args.date, use_agent=use_agent, model=model, preflight_done=True)
        rescreen = None
    if mode_reason:
        print(f'agent unavailable; entire run uses rules_only: {mode_reason}')
    if config.failure_enabled("ctgov_timeout"):
        injections.insert(0, {"switch": "ctgov_timeout", "patient_id": None, "resource_ids": [],
                              "text": f"ctgov_timeout: ClinicalTrials.gov call forced to time out; criteria {fetch.status}"})
    for p in input_problems:
        print(f"warning: input check: {p}")

    md, csv_path, warnings = write_log(args.trial, nct, fetch, args.date, results, predicates, args.out,
                                       injections=[i["text"] for i in injections])
    impact = run_amendment(args.trial, nct, fetch, args.date, predicates, results, args.out, use_agent=use_agent,
                           v1_snapshot=args.v1_snapshot, v2_snapshot=args.v2_snapshot, v2_predicates=args.v2_predicates,
                           rescreen_fn=rescreen, model=model, preflight_done=True)
    trace_path = trace.write_jsonl(args.out / f"trace_{args.trial}_{args.date}.jsonl", args.trial, args.date, results)

    counts = {c: sum(r.category == c for r in results) for c in CATEGORIES}
    meta = {
        "trial": args.trial, "nct": nct, "screening_date": args.date,
        "failures": sorted(k for k, on in config.FAILURES.items() if on),
        "criteria_status": fetch.status, "criteria_cache_age_days": fetch.cache_age_days,
        "injections": injections, "agent": None if args.no_agent else {"attempted": attempted, "recovered": recovered},
        "input_problems": input_problems,
        "execution_mode": 'agent' if use_agent else 'rules_only', 'mode_reason': mode_reason,
        "requested_agent": not args.no_agent,
        "counts": counts, "patients": len(results),
        "files": {"log": str(md), "csv": str(csv_path), "trace": str(trace_path),
                  "impact": str(impact) if impact else None,
                  "impact_json": str(impact.with_suffix(".json")) if impact else None},
    }
    (args.out / f"run_{args.trial}_{args.date}.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"trial {args.trial} ({nct}) · {args.date} · criteria {fetch.status}"
          + (f" ({fetch.cache_age_days:g} days old)" if fetch.status == "stale" else ""))
    for i in injections:
        print(f"injected: {i['text']}")
    print(f"{len(results)} patients: " + ", ".join(f"{LABELS[c]} {n}" for c, n in counts.items()))
    if not args.no_agent:
        print(f"agent: {attempted} task(s), {recovered} changed the rule result")
    print(f"log: {md}\ncsv: {csv_path}\ntrace: {trace_path}" + (f"\namendment impact: {impact}" if impact else ""))
    for w in fetch.warnings + warnings:
        print(f"warning: {w}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

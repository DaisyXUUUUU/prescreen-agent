"""T11: evaluate the pre-screening runs against ground-truth labels (brief section 11).

One command runs the baseline and every failure switch through run.py, then
computes the metric table and writes out/eval/eval_report_{trial}_{date}.md:

    python eval/evaluate.py --trial SAD --labels data/extended_cases/design_labels.csv
    python eval/evaluate.py --trial SAD --labels ... --reuse      # read existing runs, do not re-run

Label file (CSV, header required):
    patient_id,criterion_id,expected
    P-001,B-I5,met            # one row per computable criterion: met | not_met
    P-001,PATIENT,eligible    # one row per patient: eligible | not_eligible
Planted amendment flips (optional): one patient_id per line,
default data/ground_truth/trial_{T}_amendment_flips.txt.
"""

import argparse
import csv
import json
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import config  # noqa: E402
from src.adapters.fhir_store import FhirStore  # noqa: E402

RUNS = ["baseline", "ctgov_timeout", "drop_codes", "bad_units", "amendment_v2"]
SWITCHES = ["ctgov_timeout", "drop_codes", "bad_units", "amendment_v2", "note_conflict"]
DECIDED = {"met", "not_met"}


# ---------- loading ----------

def load_labels(path: Path) -> tuple[dict, dict]:
    crit, patient = {}, {}
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            pid, cid, exp = row["patient_id"].strip(), row["criterion_id"].strip(), row["expected"].strip()
            if cid.upper() == "PATIENT":
                patient[pid] = exp
            else:
                crit[(pid, cid)] = exp
    return crit, patient


def load_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_trace(path: Path) -> dict[tuple, list[dict]]:
    out = defaultdict(list)
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            t = json.loads(line)
            out[(t["patient_id"], t["criterion_id"])].append(t)
    return out


def load_run(out_dir: Path, trial: str, date: str) -> dict | None:
    meta_path = out_dir / f"run_{trial}_{date}.json"
    if not meta_path.exists():
        return None
    meta = json.loads(meta_path.read_text())
    run = {"meta": meta, "rows": load_csv(Path(meta["files"]["csv"])), "trace": load_trace(Path(meta["files"]["trace"]))}
    ij = meta["files"].get("impact_json")
    run["impact"] = json.loads(Path(ij).read_text()) if ij and Path(ij).exists() else None
    return run


# ---------- metrics ----------

def pct(n: int, d: int) -> float | None:
    return round(100 * n / d, 1) if d else None


def patient_metrics(rows: list[dict], patient_labels: dict) -> dict:
    category = {r["patient_id"]: r["patient_category"] for r in rows}
    eligible = [p for p, lab in patient_labels.items() if lab == "eligible" and p in category]
    wrongful = [p for p in eligible if category[p] == "excluded"]
    kept = [p for p in eligible if category[p] in ("likely_eligible", "pending")]
    false_pos = [p for p, lab in patient_labels.items() if lab == "not_eligible" and category.get(p) == "likely_eligible"]
    return {"labelled_patients": len([p for p in patient_labels if p in category]), "truly_eligible": len(eligible),
            "wrongful_exclusions": wrongful, "sensitivity": pct(len(kept), len(eligible)),
            "ineligible_marked_likely_eligible": false_pos,
            "missing_from_log": sorted(p for p in patient_labels if p not in category)}


def criterion_metrics(rows: list[dict], crit_labels: dict) -> dict:
    status = {(r["patient_id"], r["criterion_id"]): r for r in rows}
    labelled = [(k, exp) for k, exp in crit_labels.items() if k in status]
    agree = [k for k, exp in labelled if status[k]["status"] == exp]
    decided = [(k, exp) for k, exp in labelled if status[k]["status"] in DECIDED]
    mismatches = [{"patient_id": k[0], "criterion_id": k[1], "expected": exp, "actual": status[k]["status"],
                   "note": status[k]["note"]} for k, exp in labelled if status[k]["status"] != exp]
    computable = [r for r in rows if r.get("computable", "True") == "True"]
    return {"labelled_criteria": len(labelled), "accuracy_strict": pct(len(agree), len(labelled)),
            "accuracy_decided": pct(sum(status[k]["status"] == exp for k, exp in decided), len(decided)),
            "abstention": pct(sum(r["status"] == "unknown" for r in computable), len(computable)),
            "computable_verdicts": len(computable), "mismatches": mismatches,
            "unlabelled_in_log": len({k for k in status if status[k].get("computable", "True") == "True"} - set(crit_labels))}


def _valid_ids(store: FhirStore, pid: str) -> set[str]:
    ids = {pid}
    for resources in store.index.get(pid, {}).values():
        ids |= {r.get("id") for r in resources}
    return ids | {f"{r.get('resourceType')}/{r.get('id')}" for rs in store.index.get(pid, {}).values() for r in rs}


def evidence_coverage(rows: list[dict], trace: dict, store: FhirStore) -> dict:
    """Decided verdicts must point at a record that exists, unless the rule decided from absence."""
    need, ok, from_absence, invalid = 0, 0, 0, []
    for r in rows:
        if r["status"] not in DECIDED or r.get("computable", "True") != "True":
            continue
        steps = trace.get((r["patient_id"], r["criterion_id"]), [])
        last = next((t["tool"] for t in reversed(steps) if t.get("decision")), "")
        if last == "rule:absence_means":
            from_absence += 1
            continue
        need += 1
        ids = [i for i in r["evidence_ids"].split(";") if i]
        if ids and set(ids) <= _valid_ids(store, r["patient_id"]):
            ok += 1
        else:
            invalid.append(f"{r['patient_id']}/{r['criterion_id']}")
    return {"coverage": pct(ok, need), "with_record": need, "decided_from_absence": from_absence, "invalid": invalid}


def trace_coverage(trace: dict, impact: dict | None) -> dict:
    """Every model decision must leave a reason: agent-handled verdicts and amendment classifications."""
    handled = [k for k, steps in trace.items() if any(t["actor"] == "agent" for t in steps)]
    terminal = {"evaluate_with_records", "rule:abstain", "agent:error", "rule:interpreted_threshold",
                "rule:interpreted_window", "explain_conflict", "rule:conflict_materiality", "agent:summary",
                "rule:i5_lab_flags"}
    covered = [k for k in handled if any(t["tool"] in terminal and (t["result"] or t["decision"]) for t in trace[k])]
    changes = (impact or {}).get("changes", [])
    model_changes = [c for c in changes if any(t["tool"] != "rule:normalize" for t in c["trace"])]
    covered_changes = [c for c in model_changes if c["trace"] and c["reason"]]
    total = len(handled) + len(model_changes)
    return {"coverage": pct(len(covered) + len(covered_changes), total), "agent_verdicts": len(handled),
            "classified_changes": len(model_changes),
            "all_verdicts_traced": pct(sum(bool(s) for s in trace.values()), len(trace))}


def _first_query(steps: list[dict]) -> str:
    return next((t["result"] for t in steps if t["tool"] == "fhir_query"), "")


def _empty(q: str) -> bool:  # generic engine: "-> empty (0)"; SAD adapter: "-> 0 found"
    return "-> empty" in q or q.endswith("-> 0 found")


def _found(q: str) -> bool:
    return "-> ok" in q or (q.endswith(" found") and not q.endswith("-> 0 found"))


def recovery(base: dict, drop: dict | None) -> dict:
    """Planted wrong-code cases: found by the rule query at baseline, empty under drop_codes."""
    if not drop:
        return {"rate": None, "planted": 0, "recovered": 0, "cases": []}
    targets = {i["patient_id"] for i in drop["meta"]["injections"] if i["switch"] == "drop_codes"}
    base_status = {(r["patient_id"], r["criterion_id"]): r["status"] for r in base["rows"]}
    drop_status = {(r["patient_id"], r["criterion_id"]): r["status"] for r in drop["rows"]}
    cases = []
    for key, steps in drop["trace"].items():
        targets_case = targets | {i.get("case_id") for i in drop["meta"]["injections"] if i["switch"] == "drop_codes"}
        if key[0] in targets_case and _empty(_first_query(steps)) and _found(_first_query(base["trace"].get(key, []))):
            cases.append({"patient_id": key[0], "criterion_id": key[1], "baseline": base_status.get(key),
                          "under_drop_codes": drop_status.get(key)})
    rec = [c for c in cases if c["under_drop_codes"] == c["baseline"] and c["baseline"] in DECIDED]
    return {"rate": pct(len(rec), len(cases)), "planted": len(cases), "recovered": len(rec), "cases": cases}


def amendment_recall(amend: dict | None, planted: list[str] | None) -> dict:
    impact = (amend or {}).get("impact")
    detected = set((impact or {}).get("flips", []))
    if planted is None:
        return {"recall": None, "planted": None, "detected": sorted(detected), "missed": []}
    missed = sorted(set(planted) - detected)
    return {"recall": pct(len(planted) - len(missed), len(planted)), "planted": len(planted),
            "detected": sorted(detected), "missed": missed}


def failure_paths(runs: dict) -> dict:
    ok = {s: False for s in SWITCHES}
    if (r := runs.get("ctgov_timeout")):
        ok["ctgov_timeout"] = r["meta"]["criteria_status"] == "stale"
    if (r := runs.get("drop_codes")):
        ok["drop_codes"] = recovery(runs["baseline"], r)["recovered"] > 0
    if (r := runs.get("bad_units")):
        rows = {(x["patient_id"], x["criterion_id"]): x for x in r["rows"]}
        checks = []
        for inj in (i for i in r["meta"]["injections"] if i["switch"] == "bad_units"):
            ids = lambda x: {i.split("/")[-1] for i in x["evidence_ids"].split(";")}  # noqa: E731
            hit = [x for (p, _), x in rows.items() if p in (inj["patient_id"], inj.get("case_id"))
                   and set(inj["resource_ids"]) & ids(x)]
            want_unknown = inj.get("kind") == "implausible"
            checks.append(bool(hit) and all((x["status"] == "unknown") == want_unknown for x in hit))
        ok["bad_units"] = bool(checks) and all(checks)
    if (r := runs.get("amendment_v2")) and r["impact"]:
        ok["amendment_v2"] = r["impact"]["rescreened"] and any(c["label"] == "substantive" for c in r["impact"]["changes"])
    return ok


# ---------- orchestration ----------

def run_all(args, out_root: Path) -> dict:
    """Runs the baseline and every switch in parallel (independent processes, separate output folders)."""
    procs = {}
    for name in RUNS:
        out = out_root / name
        if not (args.reuse and (out / f"run_{args.trial}_{args.date}.json").exists()):
            cmd = [sys.executable, str(ROOT / "run.py"), "--trial", args.trial, "--date", args.date, "--out", str(out)]
            for flag in ("nct", "predicates", "patients"):
                if getattr(args, flag):
                    cmd += [f"--{flag}", str(getattr(args, flag))]
            if args.no_agent:
                cmd.append("--no-agent")
            if name != "baseline":
                cmd += ["--fail", name]
            if name == "amendment_v2":
                for flag in ("v1_snapshot", "v2_snapshot", "v2_predicates"):
                    if getattr(args, flag):
                        cmd += [f"--{flag.replace('_', '-')}", str(getattr(args, flag))]
            print(f"[eval] starting {name} ...", flush=True)
            out.mkdir(parents=True, exist_ok=True)
            log = open(out / "console.txt", "w")
            procs[name] = (subprocess.Popen(cmd, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, text=True), log)
    for name, (proc, log) in procs.items():
        code = proc.wait()
        log.close()
        print(f"[eval] {name} finished (exit {code})", flush=True)
    runs = {name: load_run(out_root / name, args.trial, args.date) for name in RUNS}
    return {k: v for k, v in runs.items() if v}


def mark(value, target: str) -> str:
    if value is None:
        return "not measured"
    if target == "0":
        return "✅" if value == 0 else "❌"
    if target.startswith(">="):
        return "✅" if value >= float(target[2:].rstrip("%")) else "❌"
    if target == "100%":
        return "✅" if value == 100 else "❌"
    if target == "5 of 5":
        return "✅" if value == 5 else "❌"
    return ""


def render(args, labels_path: Path, m: dict, runs: dict) -> str:
    sample = "tests/" in str(labels_path)
    fmt = lambda v: "n/a" if v is None else f"{v}%"  # noqa: E731
    pm, cm, ev, tc, rc, ar, fp = m["patient"], m["criterion"], m["evidence"], m["trace"], m["recovery"], m["amendment"], m["failures"]
    rows = [
        ("Wrongful exclusions", "truly eligible patients marked excluded", len(pm["wrongful_exclusions"]), "0",
         str(len(pm["wrongful_exclusions"]))),
        ("Patient-level sensitivity", "truly eligible placed in likely eligible or pending", pm["sensitivity"], ">=95%",
         fmt(pm["sensitivity"])),
        ("Criterion-level accuracy", "agreement on met / not_met (unknown counts as disagreement)", cm["accuracy_strict"],
         ">=90%", fmt(cm["accuracy_strict"])),
        ("  of decided verdicts", "agreement where the engine did decide", cm["accuracy_decided"], "", fmt(cm["accuracy_decided"])),
        ("Abstention rate", "computable verdicts returned unknown", cm["abstention"], "", fmt(cm["abstention"])),
        ("Evidence coverage", "decided verdicts pointing at an existing record (absence-based excluded)", ev["coverage"],
         "100%", fmt(ev["coverage"])),
        ("Trace coverage", "model decisions with a recorded reason", tc["coverage"], "100%", fmt(tc["coverage"])),
        ("Recovery rate", "planted wrong-code cases resolved by the agent", rc["rate"], "",
         f"{fmt(rc['rate'])} ({rc['recovered']}/{rc['planted']})"),
        ("Amendment recall", "planted status flips detected after the amendment", ar["recall"], "100%",
         fmt(ar["recall"]) if ar["planted"] is not None else "not measured (no planted list)"),
        ("Failure paths", "scenarios reproducible with a switch", sum(fp.values()), "5 of 5",
         f"{sum(fp.values())} of {len(fp)}"),
    ]
    out = [f"# Evaluation report: trial {args.trial}", "",
           f"- Screening date: {args.date} · Generated: {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}",
           f"- Labels: `{labels_path}` ({pm['labelled_patients']} patients, {cm['labelled_criteria']} criterion labels)",
           f"- Runs: {', '.join(runs)}" + (" · agent off" if args.no_agent else ""), ""]
    if sample:
        out += ["> ⚠️ **Sample labels used to exercise this script. These numbers are NOT an evaluation.**", ""]
    out += ["| Metric | Definition | Result | Target | |", "|---|---|---|---|---|"]
    for name, desc, val, target, shown in rows:
        out.append(f"| {name} | {desc} | {shown} | {target} | {mark(val, target) if target else ''} |")
    out += ["", "## Failure paths", ""]
    out += [f"- {'✅' if ok else '❌'} `{s}`" + ("" if ok or s != "note_conflict" else " (optional, not implemented)")
            for s, ok in fp.items()]
    if pm["wrongful_exclusions"]:
        out += ["", "## Wrongful exclusions", ""] + [f"- `{p}`" for p in pm["wrongful_exclusions"]]
    if pm["missing_from_log"]:
        out += ["", "## Labelled patients missing from the log", ""] + [f"- `{p}`" for p in pm["missing_from_log"]]
    if rc["cases"]:
        out += ["", "## Recovery cases (drop_codes)", "", "| Patient | Criterion | Baseline | Under drop_codes |", "|---|---|---|---|"]
        out += [f"| `{c['patient_id']}` | {c['criterion_id']} | {c['baseline']} | {c['under_drop_codes']} |" for c in rc["cases"]]
    if ar["detected"] or ar["missed"]:
        out += ["", "## Amendment", "", f"- Detected flips: {', '.join(ar['detected']) or 'none'}",
                f"- Missed planted flips: {', '.join(ar['missed']) or 'none'}"]
    out += ["", "## Error attribution", "",
            "Each disagreement with the labels. `Cause` is assigned in review: criteria compilation, concept mapping, "
            "data problem, or engine defect.", ""]
    if cm["mismatches"]:
        out += ["| Patient | Criterion | Expected | Actual | Engine note | Cause |", "|---|---|---|---|---|---|"]
        out += [f"| `{x['patient_id']}` | {x['criterion_id']} | {x['expected']} | {x['actual']} | "
                f"{x['note'].replace('|', '/')[:160]} | |" for x in cm["mismatches"]]
    else:
        out.append("_none_")
    return "\n".join(out) + "\n"


def evaluate(runs: dict, crit_labels: dict, patient_labels: dict, store: FhirStore, planted: list[str] | None) -> dict:
    base = runs["baseline"]
    return {
        "patient": patient_metrics(base["rows"], patient_labels),
        "criterion": criterion_metrics(base["rows"], crit_labels),
        "evidence": evidence_coverage(base["rows"], base["trace"], store),
        "trace": trace_coverage(base["trace"], (runs.get("amendment_v2") or {}).get("impact")),
        "recovery": recovery(base, runs.get("drop_codes")),
        "amendment": amendment_recall(runs.get("amendment_v2"), planted),
        "failures": failure_paths(runs),
    }


def main() -> int:
    p = argparse.ArgumentParser(description="Evaluate pre-screening against ground truth")
    p.add_argument("--trial", required=True)
    p.add_argument("--labels", type=Path, required=True)
    p.add_argument("--flips", type=Path, help="planted amendment flips, one patient_id per line")
    p.add_argument("--date", default=config.SCREENING_DATE)
    p.add_argument("--reuse", action="store_true", help="use existing run outputs instead of re-running")
    p.add_argument("--no-agent", action="store_true")
    for flag in ("nct", "predicates", "patients", "v1-snapshot", "v2-snapshot", "v2-predicates"):
        p.add_argument(f"--{flag}", type=str if flag == "nct" else Path)
    args = p.parse_args()

    out_root = config.OUT_DIR / "eval" / args.trial
    runs = run_all(args, out_root)
    if "baseline" not in runs:
        print("error: baseline run produced no output", file=sys.stderr)
        return 2
    crit_labels, patient_labels = load_labels(args.labels)
    flips_path = args.flips or config.DATA_DIR / "ground_truth" / f"trial_{args.trial}_amendment_flips.txt"
    planted = [l.strip() for l in flips_path.read_text().splitlines() if l.strip()] if flips_path.exists() else None
    if args.trial == "SAD":
        from src.engine import sad_adapter as sa
        cases = sa.load_cases(args.patients) if args.patients else sa.load_cases() + sa.load_cases(config.DATA_DIR / "extended_cases" / "cases")
        store = FhirStore.from_bundles({c.case_id: c.bundle for c in cases})
        store.index = {c.case_id: store.index[c.patient_id] for c in cases}  # log IDs are case IDs
    else:
        store = FhirStore(args.patients or config.PATIENT_DIR)

    metrics = evaluate(runs, crit_labels, patient_labels, store, planted)
    report = render(args, args.labels, metrics, runs)
    path = out_root / f"eval_report_{args.trial}_{args.date}.md"
    path.write_text(report, encoding="utf-8")
    (out_root / f"eval_metrics_{args.trial}_{args.date}.json").write_text(json.dumps(metrics, indent=2, default=str))
    print(report)
    print(f"[eval] report: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

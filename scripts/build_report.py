"""Build the reviewer-facing report for the SAD evaluation runs.

Reads out/eval/SAD/ (written by `python eval/evaluate.py --trial SAD ...`) and writes:
  - out/eval/SAD/report.html   one self-contained page: input, agent, output, evaluation
  - docs/demo/index.html       the same page, committed so reviewers can open it without running anything
  - out/eval/SAD/REVIEW.md     short Markdown summary

No model calls; everything shown comes from the run files.

    python scripts/build_report.py
"""

import csv
import html
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import config  # noqa: E402
from src.agent.trace import actor  # noqa: E402
from src.engine import sad_adapter as sa  # noqa: E402

R = config.OUT_DIR / "eval" / "SAD"
DATE = "2026-10-09"
RUNS = ["baseline", "ctgov_timeout", "drop_codes", "bad_units", "amendment_v2"]
CRITERIA = ["AGE", "I1", "I2", "I3", "I4", "I5", "E1", "E2", "E3", "E4", "E5"]
LOINC_OF = {"I1": "39156-5", "I2": "18262-6", "I3": "43583-4", "I4": "2571-8", "E2": "4548-4"}


def rows(run):
    return list(csv.DictReader(open(R / run / f"prescreen_log_SAD_{DATE}.csv", encoding="utf-8")))


def traces(run):
    out = defaultdict(list)
    for line in open(R / run / f"trace_SAD_{DATE}.jsonl", encoding="utf-8"):
        t = json.loads(line)
        out[f"{t['patient_id']}|{t['criterion_id']}"].append(
            {"tool": t["tool"], "actor": t["actor"], "result": t["result"], "decision": t["decision"]})
    return out


def case_facts(case):
    """Key values a reader wants in the roster, read from the bundle as recorded."""
    facts = {}
    pat = next(e["resource"] for e in case.bundle["entry"] if e["resource"]["resourceType"] == "Patient")
    facts["birth"] = pat.get("birthDate")
    for e in case.bundle["entry"]:
        r = e["resource"]
        if r["resourceType"] == "Observation" and "valueQuantity" in r:
            code = r["code"]["coding"][0]["code"]
            q = r["valueQuantity"]
            facts.setdefault(code, []).append(f"{q['value']:g} {q.get('code') or q.get('unit')}")
        if r["resourceType"] == "QuestionnaireResponse":
            for item in r.get("item", []):
                if item["linkId"].endswith("_free_text"):
                    facts[item["linkId"]] = item["answer"][0].get("valueString")
    return facts


def main():
    global R, DATE
    import argparse
    ap = argparse.ArgumentParser(description="Build the reviewer report from evaluation runs")
    ap.add_argument("--runs", type=Path, default=R, help="folder with the five run folders (default out/eval/SAD)")
    ap.add_argument('--date', default=DATE)
    args = ap.parse_args()
    R, DATE = args.runs, args.date
    status_path = R/'execution_status.json'
    if not status_path.exists() or not json.loads(status_path.read_text(encoding='utf-8')).get('complete'):
        raise SystemExit('Refusing to publish: complete execution_status.json is required; failed/missing runs must be resolved.')
    spec = sa.load_spec()
    cases = sa.load_cases() + sa.load_cases(config.DATA_DIR / "extended_cases" / "cases")
    rules_only, *_ = sa.screen(cases, spec, use_agent=False)
    rules_cat = {r.patient_id: r.category for r in rules_only}
    rules_status = {(r.patient_id, v.criterion_id): v.status for r in rules_only for v in r.verdicts}

    runs = {}
    for run in RUNS:
        meta = json.loads((R / run / f"run_SAD_{DATE}.json").read_text(encoding='utf-8'))
        rs = rows(run)
        runs[run] = {"meta": meta, "cat": {r["patient_id"]: r["patient_category"] for r in rs}}
    base = rows("baseline")
    tr = traces("baseline")
    drop_tr = traces("drop_codes")

    patients = []
    by_pid = defaultdict(dict)
    for r in base:
        by_pid[r["patient_id"]][r["criterion_id"]] = r
    for c in cases:
        crit = {}
        for cid in CRITERIA:
            r = by_pid[c.case_id][cid]
            steps = tr.get(f"{c.case_id}|{cid}", [])
            crit[cid] = {"status": r["status"], "rules_status": rules_status[(c.case_id, cid)],
                         "note": r["note"], "agent": r["agent_summary"], "review": r["review_reason"],
                         "interpreted": r["interpreted"] == "True", "evidence": r["evidence_ids"],
                         "agent_used": any(t["actor"] == "agent" for t in steps), "trace": steps}
        facts = case_facts(c)
        patients.append({
            "id": c.case_id, "source": "Core" if c.case_id.startswith("SAD") else "Extended",
            "purpose": c.ctx.get("purpose", "core screening case"),
            "design": c.ctx.get("design_category"), "rules_category": rules_cat[c.case_id],
            "category": runs["baseline"]["cat"][c.case_id],
            "by_run": {run: runs[run]["cat"][c.case_id] for run in RUNS},
            "facts": {"Birth date": facts.get("birth"),
                      **{label: ", ".join(facts.get(code, [])) or None
                         for label, code in [("BMI", "39156-5"), ("LDL-C", "18262-6"), ("Lp(a)", "43583-4"),
                                             ("TG", "2571-8"), ("ALT", "1742-6"), ("AST", "1920-8"),
                                             ("HbA1c", "4548-4")]},
                      **{k.replace("_free_text", " (free text)").capitalize(): v
                         for k, v in facts.items() if k.endswith("_free_text")}},
            "criteria": crit,
        })

    criteria = [{"id": "AGE", "type": "inclusion", "text": "Age 18 to 65 years at screening", "rule": "18 ≤ age ≤ 65",
                 "by": "Rules"}]
    handled = {"I5": "Investigator (agent gathers evidence)", "E3": "Rules; agent reads free text",
               "E4": "Rules; agent reads free text, RxNav classes", "E5": "Rules; agent reads free text, RxNav classes"}
    for r in spec["rules"]:
        p = {k: v for k, v in r["predicate"].items() if k not in ("cohort",)}
        criteria.append({"id": r["id"], "type": r["type"], "text": r["source_text"].replace("\\<", "<").replace("\\>", ">"),
                         "rule": ", ".join(f"{k} {v}" for k, v in p.items()), "by": handled.get(r["id"], "Rules")})

    impact = json.loads((R / "amendment_v2" / f"amendment_impact_SAD_{DATE}.json").read_text(encoding='utf-8'))
    metrics = json.loads((R / f"eval_metrics_SAD_{DATE}.json").read_text(encoding='utf-8'))

    # Agent activity in the baseline run, by kind of task
    kinds = Counter()
    for key, steps in tr.items():
        tools = {t["tool"] for t in steps}
        if "lookup_equivalent_codes" in tools or "get_predicate" in tools:
            kinds["Investigated a missing result"] += 1
        if "interpret_free_text" in tools:
            kinds["Read free-text history"] += 1
        if "explain_conflict" in tools or "rule:conflict_materiality" in tools:
            kinds["Explained a conflict"] += 1
        if "overview" in tools:
            kinds["Gathered I5 evidence"] += 1
    safety = [f"{run}: {k.split('|')[0]} {k.split('|')[1]}" for run in RUNS
              for k, steps in traces(run).items() if any(t["tool"] == "rule:terminology_scan" for t in steps)]

    showcase = {
        "recovery": {"case": "SAD04", "criterion": "I2", "run": "drop_codes",
                     "trace": drop_tr.get("SAD04|I2", [])},
        "free_text": {"case": "EXT04", "criterion": "E4", "trace": tr.get("EXT04|E4", [])},
        "boundary": {"case": "EXT01", "criterion": "E3", "trace": tr.get("EXT01|E3", [])},
        "conflict": {"case": "EXT07", "criterion": "I2", "trace": tr.get("EXT07|I2", [])},
        "evidence": {"case": "EXT06", "criterion": "I5", "trace": tr.get("EXT06|I5", [])},
    }

    data = {
        "trial": {"nct": "NCT07347678", "cohort": "SAD", "date": DATE, "model": config.BEDROCK_MODEL_ID or "us.amazon.nova-2-lite-v1:0",
                  "criteria_status": runs["baseline"]["meta"]["criteria_status"],
                  "mode":runs['baseline']['meta']['execution_mode']},
        "criteria": criteria, "patients": patients,
        "runs": {run: {"counts": runs[run]["meta"]["counts"], "agent": runs[run]["meta"]["agent"],
                       "injections": [i["text"] for i in runs[run]["meta"]["injections"]]} for run in RUNS},
        "impact": {"valid":impact.get('comparison_valid',False), "blocked":impact.get('blocked',''),
                   "mode":impact.get('execution_mode'),
                   "changes": [{k: c[k] for k in ("kind", "section", "old", "new", "label", "reason")} for c in impact["changes"]],
                   "flips": impact["flips"], "patients": impact["patients"]},
        "metrics": metrics, "agent_kinds": dict(kinds), "safety": safety, "showcase": showcase,
    }
    page = TEMPLATE.replace("/*DATA*/", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))
    (R / "report.html").write_text(page, encoding="utf-8")
    (R / 'reviewer_data.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    demo = ROOT / "docs" / "demo"
    demo.mkdir(parents=True, exist_ok=True)
    (demo / "index.html").write_text("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
                                     "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1, viewport-fit=cover\">"
                                     "</head><body>" + page + "</body></html>", encoding="utf-8")

    cat = Counter(p["category"] for p in patients)
    changed = [p for p in patients if p["category"] != p["rules_category"]]
    md = [f"# SAD pre-screening run, {DATE}", "",
          f"{len(patients)} synthetic patients (8 core screening cases, {len(patients) - 8} extended scenarios), trial NCT07347678 SAD cohort. "
          "Open `report.html` (or `docs/demo/index.html` in the repo) for the full interactive view.", "",
          "| Section | Patients |", "|---|---|"] + [f"| {k} | {cat.get(k, 0)} |" for k in ("likely_eligible", "pending", "excluded", "needs_review")] + [
          "", f"Patients whose result differs from the rules-only evaluation: {len(changed)}", ""] + [
          f"- {p['id']}: {p['rules_category']} → {p['category']} ({p['purpose']})" for p in changed]
    (R / "REVIEW.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"wrote {R / 'report.html'} ({len(page) // 1024} KB), {demo / 'index.html'}, {R / 'REVIEW.md'}")


TEMPLATE = r"""<title>SAD Pre-Screening Run</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Public+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;600&display=swap">
<style>
/* Layout: a run record read top to bottom - input, agent, output, evaluation - with a sticky section index; the output matrix is the centrepiece. */
:root {
  --bg: #f6f8f9; --surface: #ffffff; --ink: #14212b; --muted: #5b6b77; --rule: #d9e1e6;
  --accent: #1d4e89; --accent-soft: #e4edf7;
  --met: #1f7a4d; --met-bg: #e2f2e9; --fail: #b3261e; --fail-bg: #fbe5e3;
  --unk: #9a6400; --unk-bg: #fbf0d9; --review: #6b3fa0; --review-bg: #efe7f8;
  --agent: #0b7a86;
  --display: "Public Sans", "Helvetica Neue", Arial, sans-serif;
  --body: "Public Sans", "Helvetica Neue", Arial, sans-serif;
  --mono: "JetBrains Mono", ui-monospace, "SFMono-Regular", Menlo, monospace;
}
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --bg: #0f161c; --surface: #16212a; --ink: #e3eaef; --muted: #93a4b1; --rule: #2a3843;
  --accent: #7fb0e8; --accent-soft: #1b2d42;
  --met: #6fcf9a; --met-bg: #133224; --fail: #f08a82; --fail-bg: #3a1b19; --unk: #e7b75a; --unk-bg: #352812;
  --review: #c3a1ef; --review-bg: #2b1f3d; --agent: #5ccfd9; color-scheme: dark } }
:root[data-theme="dark"] {
  --bg: #0f161c; --surface: #16212a; --ink: #e3eaef; --muted: #93a4b1; --rule: #2a3843;
  --accent: #7fb0e8; --accent-soft: #1b2d42;
  --met: #6fcf9a; --met-bg: #133224; --fail: #f08a82; --fail-bg: #3a1b19; --unk: #e7b75a; --unk-bg: #352812;
  --review: #c3a1ef; --review-bg: #2b1f3d; --agent: #5ccfd9; color-scheme: dark }
body { background: var(--bg); color: var(--ink); font: 15px/1.55 var(--body); }
.wrap { max-width: 1180px; margin: 0 auto; padding-inline: 20px; padding-block: 28px 64px; }
h1, h2, h3 { font-family: var(--display); text-wrap: balance; margin: 0; }
h1 { font-size: clamp(1.7rem, 3.2vw, 2.4rem); font-weight: 800; letter-spacing: -0.02em; }
h2 { font-size: 1.45rem; font-weight: 750; letter-spacing: -0.01em; }
h3 { font-size: 1.02rem; font-weight: 700; }
p { margin: 0; max-width: 72ch; }
.muted { color: var(--muted); }
.eyebrow { font: 600 0.72rem/1 var(--mono); letter-spacing: 0.12em; text-transform: uppercase; color: var(--accent); }
code, .mono { font-family: var(--mono); font-size: 0.86em; }
header.top { display: grid; gap: 10px; padding-bottom: 20px; border-bottom: 1px solid var(--rule); }
.chips { display: flex; flex-wrap: wrap; gap: 8px; }
.chip { font: 500 0.78rem/1 var(--mono); padding: 6px 9px; border: 1px solid var(--rule); border-radius: 4px; background: var(--surface); }
nav.index { position: sticky; top: env(safe-area-inset-top, 0px); z-index: 5; background: var(--bg); border-bottom: 1px solid var(--rule);
  display: flex; gap: 4px; overflow-x: auto; padding-block: 8px; }
nav.index a { font-weight: 600; font-size: 0.88rem; color: var(--muted); text-decoration: none; padding: 6px 10px; border-radius: 4px; white-space: nowrap; }
nav.index a:hover, nav.index a:focus-visible { color: var(--ink); background: var(--accent-soft); outline: none; }
section { display: grid; gap: 16px; padding-block: 34px 6px; scroll-margin-top: 54px; }
.lede { font-size: 1.04rem; }
/* pipeline strip: the real flow, left to right */
.flow { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 0; border: 1px solid var(--rule); border-radius: 6px; background: var(--surface); overflow: hidden; }
.flow > div { padding: 16px; display: grid; gap: 6px; align-content: start; border-right: 1px solid var(--rule); min-width: 0; }
.flow > div:last-child { border-right: 0; }
.flow .n { font: 700 1.6rem/1 var(--display); font-variant-numeric: tabular-nums; }
.flow .agentcol { background: var(--accent-soft); }
@media (max-width: 760px) { .flow { grid-template-columns: 1fr 1fr; } .flow > div:nth-child(2) { border-right: 0; } .flow > div:nth-child(-n+2) { border-bottom: 1px solid var(--rule); } }
.panel { background: var(--surface); border: 1px solid var(--rule); border-radius: 6px; }
.scroll { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-size: 0.88rem; }
th, td { text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--rule); vertical-align: top; }
th { font: 600 0.72rem/1.2 var(--mono); letter-spacing: 0.06em; text-transform: uppercase; color: var(--muted); background: var(--surface); }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
.pill { display: inline-block; font: 600 0.74rem/1 var(--body); padding: 4px 8px; border-radius: 999px; white-space: nowrap; }
.c-likely_eligible { color: var(--met); background: var(--met-bg); }
.c-excluded { color: var(--fail); background: var(--fail-bg); }
.c-pending { color: var(--unk); background: var(--unk-bg); }
.c-needs_review { color: var(--review); background: var(--review-bg); }
.sections4 { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; }
.sections4 button { all: unset; cursor: pointer; padding: 14px; border-radius: 6px; border: 1px solid var(--rule); background: var(--surface); display: grid; gap: 4px; }
.sections4 button:focus-visible, .sections4 button[aria-pressed="true"] { outline: 2px solid var(--accent); outline-offset: -2px; }
.sections4 .n { font: 800 1.8rem/1 var(--display); font-variant-numeric: tabular-nums; }
@media (max-width: 700px) { .sections4 { grid-template-columns: 1fr 1fr; } }
.filters { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.filters label { display: inline-flex; gap: 6px; align-items: center; font-size: 0.86rem; color: var(--muted); }
/* matrix */
.matrix-wrap { max-height: min(62vh, 560px); overflow: auto; }
table.matrix thead th { position: sticky; top: 0; z-index: 1; }
table.matrix th, table.matrix td { padding: 6px 6px; text-align: center; }
table.matrix td.pid, table.matrix th.pid { text-align: left; white-space: nowrap; }
table.matrix tbody tr { cursor: pointer; }
table.matrix tbody tr:hover, table.matrix tbody tr.sel { background: var(--accent-soft); }
.cell { display: inline-grid; place-items: center; width: 26px; height: 22px; border-radius: 4px; font: 700 0.72rem/1 var(--mono); position: relative; }
.s-pass { color: var(--met); background: var(--met-bg); }
.s-fail { color: var(--fail); background: var(--fail-bg); }
.s-unknown { color: var(--unk); background: var(--unk-bg); }
.cell.agent::after { content: ""; position: absolute; top: -3px; right: -3px; width: 8px; height: 8px; border-radius: 50%; background: var(--agent); border: 2px solid var(--surface); }
.legend { display: flex; flex-wrap: wrap; gap: 14px; font-size: 0.82rem; color: var(--muted); align-items: center; }
.legend span { display: inline-flex; gap: 6px; align-items: center; }
.dot { width: 9px; height: 9px; border-radius: 50%; background: var(--agent); display: inline-block; }
/* detail */
.detail { display: grid; gap: 14px; padding: 18px; }
.detail .head { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; justify-content: space-between; }
.facts { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 8px 16px; }
.facts div { display: grid; gap: 2px; min-width: 0; }
.facts dt { font: 600 0.7rem/1.2 var(--mono); text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); }
.facts dd { margin: 0; overflow-wrap: anywhere; }
.facts .wide { grid-column: 1 / -1; }
.crit { border-top: 1px solid var(--rule); padding-top: 10px; display: grid; gap: 6px; }
.crit .line { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.trace { font: 0.78rem/1.5 var(--mono); background: var(--bg); border: 1px solid var(--rule); border-radius: 4px; padding: 8px 10px; overflow-x: auto; white-space: pre-wrap; overflow-wrap: anywhere; }
.trace .rule { color: var(--muted); }
.trace .agent { color: var(--agent); font-weight: 600; }
.trace .engine { color: var(--accent); }
/* agent cards */
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 12px; }
.card { padding: 16px; display: grid; gap: 10px; align-content: start; min-width: 0; }
.card .k { font: 700 1.3rem/1 var(--display); color: var(--agent); font-variant-numeric: tabular-nums; }
.split { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 12px; }
@media (max-width: 760px) { .split { grid-template-columns: 1fr; } }
.split > div { padding: 14px 16px; display: grid; gap: 8px; align-content: start; }
.split ul { margin: 0; padding-left: 18px; display: grid; gap: 4px; }
.change-label { font: 700 0.72rem/1 var(--mono); text-transform: uppercase; letter-spacing: 0.06em; }
.ok { color: var(--met); } .bad { color: var(--fail); }
footer { margin-top: 40px; padding-top: 16px; border-top: 1px solid var(--rule); font-size: 0.84rem; color: var(--muted); display: grid; gap: 6px; }
a { color: var(--accent); }
@media (prefers-reduced-motion: no-preference) { table.matrix tbody tr { transition: background 120ms; } }
</style>

<div class="wrap">
  <header class="top">
    <span class="eyebrow">Clinical trial pre-screening · run record</span>
    <h1>SAD Pre-Screening Run</h1>
    <p class="lede">An agent takes over a research coordinator's weekly pre-screening for <a href="https://clinicaltrials.gov/study/NCT07347678" target="_blank" rel="noopener">NCT07347678</a> (SAD cohort). Deterministic rules decide everything a rule can decide; the agent handles what rules cannot read: missing results, free-text history, conflicting results and evidence for the investigator. Synthetic data only; no patient is contacted.</p>
    <div class="chips" id="chips"></div>
    <p class="muted" id="validation-note"></p>
  </header>
  <nav class="index" aria-label="Sections">
    <a href="#flow">Overview</a><a href="#input">Input</a><a href="#agent">Agent</a><a href="#output">Output</a><a href="#amendment">Amendment</a><a href="#scenarios">Failure scenarios</a><a href="#evaluation">Evaluation</a>
  </nav>

  <section id="flow">
    <h2>From criteria to a coordinator's log</h2>
    <div class="flow" id="flowstrip"></div>
  </section>

  <section id="input">
    <span class="eyebrow">1 · Input</span>
    <h2>Eligibility criteria</h2>
    <p class="muted">Fetched from the ClinicalTrials.gov API, snapshotted with SHA-256, and manually compiled into the rule pack <code>sad-1.0.0</code>. The last column says who settles each criterion.</p>
    <div class="panel scroll"><table id="crit-table"><thead><tr><th>ID</th><th>Type</th><th>Criterion text (registry)</th><th>Compiled rule</th><th>Settled by</th></tr></thead><tbody></tbody></table></div>
    <h2>Patients</h2>
    <p class="muted" id="roster-note"></p>
    <div class="panel scroll"><table id="roster"><thead><tr><th>Patient</th><th>Source</th><th>What the case tests</th><th>LDL-C</th><th>Lp(a)</th><th>BMI</th></tr></thead><tbody></tbody></table></div>
  </section>

  <section id="agent">
    <span class="eyebrow">2 · Agent</span>
    <h2>What the agent does that rules cannot</h2>
    <p class="muted">Strands Agents on Amazon Bedrock (Amazon Nova 2 Lite). The model reads, searches and explains; code compares numbers, applies windows and makes the call. Every step is traced.</p>
    <div class="split">
      <div class="panel"><h3>The model does</h3><ul>
        <li>Chooses codes from the criterion allowlist and re-queries when a result is missing</li>
        <li>Reads patients' own words (smoking, drug history) into facts, each with a quote</li>
        <li>Decides which liver and kidney records to look up for the investigator</li>
        <li>Explains conflicting results and what to check</li>
        <li>Labels changed criteria as substantive, wording or ambiguous</li></ul></div>
      <div class="panel"><h3>Code does</h3><ul>
        <li>Every numeric comparison and time window, with the rule pack's thresholds</li>
        <li>Checks each quote really occurs in the source; drops it otherwise</li>
        <li>Uses NLM RxNav classes where available; model-only class suggestions require review</li>
        <li>Scans the text for drugs the model failed to report</li>
        <li>Decides whether a conflict changes the outcome; flags abnormal labs from reference ranges</li></ul></div>
    </div>
    <div class="cards" id="showcase"></div>
    <div class="panel" style="padding:14px 16px;display:grid;gap:6px" id="safety"></div>
  </section>

  <section id="output">
    <span class="eyebrow">3 · Output</span>
    <h2>The coordinator's pre-screening log</h2>
    <p class="muted">Four sections, as a coordinator writes them by hand. Select a section to filter; select a patient to see every criterion with its evidence and trace.</p>
    <div class="sections4" id="sections4"></div>
    <div class="filters">
      <label><input type="checkbox" id="f-changed"> Only patients the agent changed (vs rules-only evaluation)</label>
      <label><input type="checkbox" id="f-agent"> Only patients the agent worked on</label>
    </div>
    <div class="legend">
      <span>Letters: M met, N not met, ? unknown.</span><span><span class="cell s-pass">✓</span> criterion passed (inclusion met, or exclusion not met)</span><span><span class="cell s-fail">✗</span> failed</span><span><span class="cell s-unknown">?</span> unknown</span><span><span class="dot"></span> agent involved</span><span>I5 is always the investigator's call</span>
    </div>
    <div class="panel matrix-wrap"><table class="matrix" id="matrix"><thead></thead><tbody></tbody></table></div>
    <div class="panel" id="detail" style="scroll-margin-top:56px"></div>
  </section>

  <section id="amendment">
    <span class="eyebrow">Amendment monitoring</span>
    <h2>When the criteria change</h2>
    <p class="muted">Numeric/operator changes are classified by code; other semantic changes may require the model or CRC. Both versions use the same execution mode. Unchanged criteria reuse the same evidence interpretation. Agent errors block attribution. The example amends SAD LDL-C from 70 to 100 mg/dL.</p>
    <div class="panel scroll"><table id="changes"><thead><tr><th>Before</th><th>After</th><th>Classification</th><th>Model's reason</th></tr></thead><tbody></tbody></table></div>
    <p id="flips"></p>
  </section>

  <section id="scenarios">
    <span class="eyebrow">Failure paths</span>
    <h2>Baseline and four mandatory failure scenarios</h2>
    <div class="panel scroll"><table id="runs"><thead><tr><th>Scenario</th><th>What was injected</th><th class="num">Likely eligible</th><th class="num">Pending</th><th class="num">Excluded</th><th class="num">Needs review</th><th class="num">Agent tasks</th></tr></thead><tbody></tbody></table></div>
  </section>

  <section id="evaluation">
    <span class="eyebrow">4 · Evaluation</span>
    <h2>Measured against the scenarios' design intent</h2>
    <p class="muted">Labels are the extended scenario set's design intent, written before any run (<code>data/extended_cases/design_labels.csv</code>). They test whether the pipeline does what each case was built to test; they are not clinical ground truth.</p>
    <div class="panel scroll"><table id="metrics"><thead><tr><th>Metric</th><th>Result</th><th>Target</th></tr></thead><tbody></tbody></table></div>
  </section>

  <footer>
    <span>Synthetic data only (Synthea demographics; designed screening records). Public APIs: ClinicalTrials.gov, NLM RxNav. AWS: Amazon Bedrock, Amazon S3.</span>
    <span>Source: <a href="https://github.com/DaisyXUUUUU/prescreen-agent" target="_blank" rel="noopener">github.com/DaisyXUUUUU/prescreen-agent</a></span>
  </footer>
</div>

<script id="data" type="application/json">/*DATA*/</script>
<script>
const D = JSON.parse(document.getElementById('data').textContent);
document.getElementById('validation-note').textContent = `Execution mode: ${D.trial.mode}. Design-intent labels cover ${D.metrics.criterion.labelled_criteria} of ${D.metrics.criterion.computable_verdicts} computable verdicts and ${D.metrics.patient.labelled_patients} patients. Independent clinical validation is pending; EXT11 and EXT43 require label/data review. Interpreted failures go to CRC review, never direct exclusion.`;
const LABEL = {likely_eligible: 'Likely eligible', pending: 'Pending', excluded: 'Excluded', needs_review: 'Needs review'};
const ORDER = ['likely_eligible', 'pending', 'excluded', 'needs_review'];
const CRIT = ['AGE','I1','I2','I3','I4','I5','E1','E2','E3','E4','E5'];
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const pill = c => `<span class="pill c-${c}">${LABEL[c] || c}</span>`;
const glyph = {met: 'M', not_met: 'N', unknown: '?'};
const TYPE = {}; // colour by effect on eligibility: an exclusion that is not met is a pass
const effect = (c, status) => status === 'unknown' ? 'unknown' : ((TYPE[c] === 'exclusion') === (status === 'met') ? 'fail' : 'pass');
const P = D.patients;
D.criteria.forEach(c => { TYPE[c.id] = c.type; });

document.getElementById('chips').innerHTML = [
  `trial ${D.trial.nct} · ${D.trial.cohort}`, `screening ${D.trial.date}`, `${P.length} synthetic patients`,
  `model ${D.trial.model}`, `criteria fetched ${D.trial.criteria_status}`].map(t => `<span class="chip">${esc(t)}</span>`).join('');

const base = D.runs.baseline;
const agentTasks = Object.values(D.agent_kinds).reduce((a, b) => a + b, 0);
document.getElementById('flowstrip').innerHTML = `
  <div><span class="eyebrow">Input</span><span class="n">${D.criteria.length}</span><span class="muted">criteria from ClinicalTrials.gov, ${P.length} patients as FHIR R4 records</span></div>
  <div><span class="eyebrow">Rules</span><span class="n">${P.length * CRIT.length}</span><span class="muted">criterion checks by the deterministic SAD evaluator</span></div>
  <div class="agentcol"><span class="eyebrow">Agent</span><span class="n">${agentTasks}</span><span class="muted">${Object.entries(D.agent_kinds).map(([k, v]) => `${v} × ${k}`).join(' · ')}</span></div>
  <div><span class="eyebrow">Output</span><span class="n">${ORDER.map(c => base.counts[c]).join(' / ')}</span><span class="muted">likely eligible / pending / excluded / needs review</span></div>`;

document.querySelector('#crit-table tbody').innerHTML = D.criteria.map(c =>
  `<tr><td class="mono">${c.id}</td><td>${c.type}</td><td>${esc(c.text)}</td><td class="mono">${esc(c.rule)}</td><td>${esc(c.by)}</td></tr>`).join('');
const nCore = P.filter(p => p.source === 'Core').length;
document.getElementById('roster-note').textContent = `${nCore} core screening cases (Synthea demographics, designed screening records) and ${P.length - nCore} extended scenarios generated from core case SAD01, one deliberate situation each: both sides of every threshold, exact boundaries, unit conversion, missing data, hand-written free text, liver and kidney evidence, conflicts.`;
document.querySelector('#roster tbody').innerHTML = P.map(p =>
  `<tr><td class="mono">${p.id}</td><td>${p.source}</td><td>${esc(p.purpose)}</td><td class="mono">${esc(p.facts['LDL-C'] || '-')}</td><td class="mono">${esc(p.facts['Lp(a)'] || '-')}</td><td class="mono">${esc(p.facts['BMI'] || '-')}</td></tr>`).join('');

const traceHTML = steps => steps.length ? steps.map(t =>
  `<span class="${t.actor}">${esc(t.tool.padEnd(24))}</span> ${esc(t.result)}${t.decision ? ' → ' + esc(t.decision) : ''}`).join('\n') : 'no trace';
const show = D.showcase;
const card = (title, k, text, s) => `<article class="card panel"><span class="eyebrow">${title}</span><h3>${esc(s.case)} · ${s.criterion}</h3><p>${text}</p><div class="trace">${traceHTML(s.trace)}</div></article>`;
document.getElementById('showcase').innerHTML = [
  card('Missing result', 0, 'Under <code>drop_codes</code>, direct LDL is filed under generic code 2089-1 while retaining its method. Recovery is restricted to the criterion allowlist and the original patient/encounter; code checks the method and value. See the trace for this run\'s actual outcome.', show.recovery),
  card('Free text and drug knowledge', 0, '"Received a twice-yearly cholesterol injection called Leqvio". The model extracts the drug and date; RxNav resolves Leqvio to inclisiran, classed as RNA, Small Interfering; code checks the 12-month window.', show.free_text),
  card('Fuzzy boundary', 0, '"4 or 5 cigarettes on a Friday or Saturday night" contains a range. The source guard keeps it unknown for the coordinator; it must not become a midpoint or upper-bound fact.', show.boundary),
  card('Conflicting results', 0, 'Two LDL-C results, 65 and 85 mg/dL, same time and specimen. Code re-runs the evaluator with each: the choice changes the outcome, so it goes to review with the model\'s explanation.', show.conflict),
  card('Evidence for the investigator (I5)', 0, 'Liver enzymes are normal, so the rules pass this patient. The agent finds creatinine 1.9, eGFR 38, a CKD stage 3 diagnosis and an ultrasound note, and sends the patient to review.', show.evidence),
].join('');
document.getElementById('safety').innerHTML = `<h3>Safety nets that fired in these runs</h3><p class="muted">The model sometimes leaves out a drug it wrongly believes is irrelevant. The terminology scan caught it ${D.safety.length} time(s): ${esc(D.safety.join('; ') || 'none')}. Without the scan these patients would have been passed as likely eligible.</p>`;

let filterCat = null;
function renderSections() {
  document.getElementById('sections4').innerHTML = ORDER.map(c => `<button type="button" aria-pressed="${filterCat === c}" data-c="${c}"><span class="pill c-${c}" style="justify-self:start">${LABEL[c]}</span><span class="n">${base.counts[c]}</span><span class="muted" style="font-size:.8rem">rules only: ${P.filter(p => p.rules_category === c).length}</span></button>`).join('');
  document.querySelectorAll('#sections4 button').forEach(b => b.onclick = () => { filterCat = filterCat === b.dataset.c ? null : b.dataset.c; renderSections(); renderMatrix(); });
}
document.querySelector('#matrix thead').innerHTML = `<tr><th class="pid">Patient</th>${CRIT.map(c => `<th>${c}</th>`).join('')}<th class="pid">Result</th><th class="pid">Rules only</th></tr>`;
function renderMatrix() {
  const onlyChanged = document.getElementById('f-changed').checked, onlyAgent = document.getElementById('f-agent').checked;
  const list = P.filter(p => (!filterCat || p.category === filterCat) && (!onlyChanged || p.category !== p.rules_category) && (!onlyAgent || CRIT.some(c => p.criteria[c].agent_used)));
  document.querySelector('#matrix tbody').innerHTML = list.map(p => `<tr data-id="${p.id}"><td class="pid mono">${p.id}</td>${CRIT.map(c => { const v = p.criteria[c]; return `<td><span class="cell s-${effect(c, v.status)}${v.agent_used ? ' agent' : ''}" title="${c}: ${v.status}">${glyph[v.status]}</span></td>`; }).join('')}<td class="pid">${pill(p.category)}</td><td class="pid">${p.rules_category === p.category ? '<span class="muted">same</span>' : pill(p.rules_category)}</td></tr>`).join('') || `<tr><td colspan="14" class="muted">No patients match these filters.</td></tr>`;
  document.querySelectorAll('#matrix tbody tr[data-id]').forEach(tr => tr.onclick = () => {
    select(tr.dataset.id);
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    document.getElementById('detail').scrollIntoView({behavior: reduce ? 'auto' : 'smooth', block: 'start'});
  });
}
function select(id) {
  const p = P.find(x => x.id === id);
  document.querySelectorAll('#matrix tbody tr').forEach(tr => tr.classList.toggle('sel', tr.dataset.id === id));
  const facts = Object.entries(p.facts).filter(([, v]) => v).map(([k, v]) => `<div class="${k.includes('free text') ? 'wide' : ''}"><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join('');
  const crit = CRIT.map(c => { const v = p.criteria[c]; const meta = D.criteria.find(x => x.id === c);
    return `<div class="crit"><div class="line"><span class="cell s-${effect(c, v.status)}${v.agent_used ? ' agent' : ''}">${glyph[v.status]}</span><strong class="mono">${c}</strong><span class="muted">${esc(meta.text.slice(0, 110))}</span>${v.rules_status !== v.status ? `<span class="pill c-needs_review">rules alone: ${v.rules_status}</span>` : ''}${v.interpreted ? '<span class="pill c-likely_eligible">from free text</span>' : ''}${v.review ? '<span class="pill c-needs_review">review</span>' : ''}</div>
      <p>${esc(v.note)}</p>${v.agent ? `<p><strong>Agent:</strong> ${esc(v.agent)}</p>` : ''}${v.evidence ? `<p class="muted mono" style="font-size:.76rem;overflow-wrap:anywhere">evidence: ${esc(v.evidence)}</p>` : ''}
      <details${v.agent_used ? ' open' : ''}><summary>Trace (${v.trace.length} steps)</summary><div class="trace">${traceHTML(v.trace)}</div></details></div>`; }).join('');
  const runs = Object.entries(p.by_run).map(([r, c]) => `<span class="chip">${r}: ${LABEL[c]}</span>`).join('');
  document.getElementById('detail').innerHTML = `<div class="detail"><div class="head"><h3><span class="mono">${p.id}</span> · ${esc(p.purpose)}</h3><div class="chips">${pill(p.category)}${p.rules_category !== p.category ? `<span class="muted">rules only: ${LABEL[p.rules_category]}</span>` : ''}</div></div><dl class="facts">${facts}</dl><div class="chips">${runs}</div>${crit}</div>`;
}
document.getElementById('f-changed').onchange = renderMatrix;
document.getElementById('f-agent').onchange = renderMatrix;
renderSections(); renderMatrix(); select('EXT04');

document.querySelector('#changes tbody').innerHTML = D.impact.changes.map(c => `<tr><td>${esc(c.old || '-')}</td><td>${esc(c.new || '-')}</td><td><span class="change-label ${c.label === 'substantive' ? 'bad' : 'ok'}">${c.label}</span></td><td>${esc(c.reason)}</td></tr>`).join('');
document.getElementById('flips').textContent = D.impact.valid ? `${D.impact.flips.length} patients change status in ${D.impact.mode} mode: ${D.impact.flips.join(', ')}.` : `Comparison blocked: ${D.impact.blocked}`;

const NAMES = {baseline: 'Normal run', ctgov_timeout: 'ClinicalTrials.gov times out', drop_codes: 'Result filed under another code', bad_units: 'Wrong unit / absurd value', amendment_v2: 'Criteria amended'};
document.querySelector('#runs tbody').innerHTML = Object.entries(D.runs).map(([r, v]) => `<tr><td><strong>${NAMES[r]}</strong><br><code>${r}</code></td><td>${esc(v.injections.join('; ') || 'nothing')}</td>${ORDER.map(c => `<td class="num">${v.counts[c]}</td>`).join('')}<td class="num">${v.agent ? v.agent.attempted : '-'}</td></tr>`).join('');

const M = D.metrics, pct = v => v == null ? 'n/a' : v + '%';
const rowsM = [
  ['Wrongful exclusions (eligible by design, output excluded)', String(M.patient.wrongful_exclusions.length), '0', M.patient.wrongful_exclusions.length === 0],
  ['Patient-level sensitivity', pct(M.patient.sensitivity), '≥ 95%', M.patient.sensitivity >= 95],
  ['Criterion accuracy, unknown counted as wrong', pct(M.criterion.accuracy_strict), '≥ 90%', M.criterion.accuracy_strict >= 90],
  ['Criterion accuracy where the pipeline decided', pct(M.criterion.accuracy_decided), '', null],
  ['Abstention (computable criteria left unknown)', pct(M.criterion.abstention), 'reported', null],
  ['Evidence coverage (decided verdicts citing an existing record)', pct(M.evidence.coverage), '100%', M.evidence.coverage === 100],
  ['Trace coverage (model decisions with a recorded reason)', pct(M.trace.coverage), '100%', M.trace.coverage === 100],
  ['Recovery rate (planted wrong-code cases)', `${pct(M.recovery.rate)} (${M.recovery.recovered}/${M.recovery.planted})`, 'reported', null],
  ['Amendment recall (planted status flips detected)', pct(M.amendment.recall), '100%', M.amendment.recall === 100],
  ['Required failure paths (note_conflict is optional)', `${['ctgov_timeout','drop_codes','bad_units','amendment_v2'].filter(k => M.failures[k]).length} of 4`, '4 of 4', null],
];
document.querySelector('#metrics tbody').innerHTML = rowsM.map(([n, v, t, ok]) => `<tr><td>${n}</td><td class="mono ${ok === true ? 'ok' : ok === false ? 'bad' : ''}">${v}</td><td class="muted">${t}</td></tr>`).join('');
</script>
"""

if __name__ == "__main__":
    main()

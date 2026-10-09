# CLAUDE.md — Trial Pre-Screening Agent

AWS Community Day Bay Area 2026 hackathon ("Hand it off" challenge).
Submission deadline: **Sunday 2026-10-11, 11:59 AM PT**. Time is very tight — favor working code over completeness.

Full background: `docs/PROJECT_BRIEF.md` (teammate Ming's brief, v2).
Full task breakdown with function signatures and acceptance criteria: `docs/TASKS.md` (T1–T12).
Read the relevant T-section of `docs/TASKS.md` before starting any task.

## What we are building

An agent that takes over a clinical research coordinator's (CRC) weekly clinical-trial pre-screening.
Input: synthetic patients (Synthea FHIR R4 bundles) + trial eligibility criteria (ClinicalTrials.gov API v2) + hand-compiled predicates.
Output: the same pre-screening log the CRC writes by hand (4 sections: likely eligible / pending / excluded / needs review), every verdict with evidence, plus an amendment impact report when criteria change. No patient is ever contacted.

Team split: Ming = clinical data, predicates, ground-truth labels, evaluation judgment. Me = all engineering (T1–T12).

## Decisions already made (do not revisit without asking)

1. **Form factor:** a Python CLI batch job (`python run.py --trial B`). Not a chatbot, not a web app. No frontend. Optional later: terminal output with `rich`, and a static HTML version of the log.
2. **No FHIR server.** A file-based adapter reads Synthea JSON from `data/patients/` and exposes FHIR-style query functions. Interface stays FHIR-compatible so a real server could be swapped in.
3. **Deterministic engine first, agent only for exceptions.** Every numeric and temporal comparison is plain Python. The LLM is called only for:
   - Decision 2 (priority): a query returned empty → try equivalent codes → search notes → abstain, explaining what was tried.
   - Decision 5: criteria text changed → classify each changed item as substantive / wording / ambiguous.
   - Decision 4 (optional): structured data vs. note conflict → list both, route to review.
4. **The model never compares numbers and never makes the final eligibility call.** Found records go back to the deterministic engine. Conflicts go to the CRC.
5. **Every model decision writes a trace line** (`step`, `tool`, `result`, `decision`). Rule-based handling also writes trace with `tool: "rule:..."`.
6. **Tools return typed statuses, never raise to the agent:** `ok | empty | timeout | malformed` (data), `ok | stale | error` (ctgov).
7. **Agent framework:** Strands Agents SDK + Amazon Bedrock. **Model: Amazon Nova 2 Lite** (`us.amazon.nova-2-lite-v1:0`), decided 2026-10-09 because Claude is unavailable on our accounts. Model ID comes from env var `BEDROCK_MODEL_ID`; keep code model-agnostic (Converse API). temperature 0, max ~6 tool calls per case, fresh conversation per case.
8. **Amendments:** compare SHA-256 of criteria snapshots; item-level diff with `difflib`; on substantive change, re-run the whole trial with the v2 predicate file (prepared by Ming) and diff patient statuses. No automatic predicate compilation (disclosed as human-reviewed).
9. **Failure injection via config switches** in `src/config.py`: `ctgov_timeout`, `bad_units`, `drop_codes`, `amendment_v2`, `note_conflict` (optional). Also overridable with `--fail <name>`.
10. **AWS services:** Bedrock + S3 required. EventBridge, Lambda, SES are optional and come last.
11. **Scope:** trial B only until it works end to end. Trial G and F are optional.

## Data contracts (from brief section 5)

Predicate fields: `criterion_id, trial_id, type (inclusion|exclusion), concept, codes[{system,code,display}], operator, value, unit, window_days, computable, source_text`, plus optional `grade (C|P|N), resource, anchor{event,direction}, aggregation, absence_means (met|not_met|unknown), assumption`.

Verdict fields: `patient_id, criterion_id, status (met|not_met|unknown), evidence[{resource_id,value,date}], note`, plus optional `blocking, trace[]`.

Operators for v1: `<, <=, >, >=, exists`. (`no_change`, `active_for_days` later.)

`absence_means` defaults: missing diagnosis → `not_met`; missing lab → `unknown`; missing intolerance record → `unknown`.

## Directory layout

```
data/{patients,predicates,mappings,snapshots,ground_truth}/
src/adapters/fhir_store.py   # T3
src/tools/ctgov.py           # T4
src/engine/evaluate.py       # T5
src/engine/units.py          # T5
src/engine/aggregate.py      # T6
src/report/log_writer.py     # T6
src/agent/agent.py           # T7
src/agent/trace.py           # T8
src/amendment/monitor.py     # T10
src/config.py                # T9
eval/evaluate.py             # T11
tests/
run.py
docs/PROJECT_BRIEF.md, docs/TASKS.md
```

## Working rules

- Work on **one T-task at a time**. When done, run its acceptance check from `docs/TASKS.md` and show me the output before moving on.
- **Never edit files in `data/predicates/`, `data/mappings/`, or `data/ground_truth/`** — Ming owns them. If something looks wrong, tell me.
- **Tests:** expected values come from Ming's labels or from me, not invented to match the code.
- **Synthetic data only.** No real patient data anywhere.
- **Secrets:** never write AWS keys or tokens into files. Use the local AWS profile / env vars; keep `.env` git-ignored and only commit `.env.example`.
- **Strands is a newer library:** check its current docs / installed package source before writing agent code instead of relying on memory.
- When inspecting real Synthea or ClinicalTrials.gov data, trust the actual structure over assumptions.
- Keep README updated as each module lands; it must run from a clean clone.
- Python 3.11+. Keep dependencies minimal.

## ⏳ Waiting on Ming (requested 2026-10-09, no reply yet)

Work proceeds on placeholders; every item below must be swapped in and **re-verified** when it arrives.

| Item | Needed for | Due | Placeholder meanwhile | Re-verify when it lands |
|---|---|---|---|---|
| GitHub username | invite → T1 "Ming clones and pushes" | Fri | — | Ming's commit visible after `git pull` |
| NCT IDs for B and G | T4, T10 | Fri | a public test NCT, never labelled as trial B | T4 acceptance on the real ID |
| S3 bucket name + write access for `prescreen-dev-xzy` | T4 snapshots, logs | Fri | local-only, warning printed | snapshot appears in S3 |
| `data/predicates/trial_B.json` (15 predicates) | T5 | Fri night | none — engine tested on hand-written fixture predicates in `tests/` | T5 runs on real file; schema mismatches reported to Ming, not fixed by us |
| Confirm extension fields (`grade, resource, anchor, aggregation, absence_means, assumption`) | T5 scope | Fri | assume all enabled | — |
| Synthea patients in `data/patients/` (5 first is fine) | T3 | Fri night | 3 hand-written minimal bundles in `tests/fixtures/` (eligible / excluded / missing lab) | T3 loads real bundles; trust real structure over fixtures |
| Injected-case list | T5 tests, T9 | Sat AM | — | — |
| ATC→RxNorm map, local code map | medication / code matching | Sat AM | — | — |
| v2 snapshot + v2 predicates | T10 | Sat PM | — | — |
| Ground truth (≥20 patients) | T11 | Sat night | — | — |

Open questions for Ming:
- Aggregation order: a patient with an inclusion criterion clearly `not_met` AND a blocking `unknown` elsewhere — "excluded" or "pending"? Current draft says pending; to confirm.
- Unit conversion factors and plausible ranges in `units.py` need Ming's review.

## Bedrock access (resolved 2026-10-09)

Daisy's own account cannot use Bedrock (new-account verification + Free plan: Claude blocked by an AWS-managed SCP, all on-demand token quotas at 0). It is **not used**.
We run on **Ming's account** via local AWS profile `prescreen-dev-xzy`, region `us-west-2`, model `us.amazon.nova-2-lite-v1:0`. `check_bedrock.py` passed 2026-10-09.
If Daisy's account is ever needed (e.g. for S3 ownership), recheck its quotas first.

## Current status

T1 done (pending: Ming clones and pushes). T4 done on placeholder NCT. T3 done on fixtures in `tests/fixtures/patients/`. Next: T5.

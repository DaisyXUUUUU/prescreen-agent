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

1. **Form factor:** a Python CLI batch job (`python run.py --trial SAD`). Not a chatbot, not a web app. No frontend. Optional later: terminal output with `rich`, and a static HTML version of the log.
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
11. **Scope (changed 2026-10-09):** primary trial is Ming's **T6 = NCT07347678, SAD cohort only** (config key `SAD`). Ming's T2 = NCT07610278 (hypertension + hypercholesterolemia, the original "trial B" idea) is kept as reference only; it has rules but no patients. The old B/G labels are retired.
12. **SAD evaluation reuses Ming's engine (decided 2026-10-09).** `t6_sad_demo/engine.py` is the deterministic evaluator for SAD; engineering wraps it with an adapter (`src/engine/sad_adapter.py`, P1) and adds the agent, trace, aggregation, log, amendment, failure switches and eval around it. Clinical logic stays in one place, owned by Ming. Acceptance for the adapter: reproduce Ming's 8-case result exactly (2 passes / 4 fails / 1 pending / 1 review) before adding anything.
13. **Aggregation for SAD follows Ming's rule:** any clearly failed criterion → fails (excluded), even with unknowns elsewhere; manual items (I5) remain listed. This answers the old open question: `PENDING_BEFORE_INCLUSION_FAIL` = False for SAD.

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
- **Never edit files in `data/predicates/`, `data/mappings/`, `data/ground_truth/`, `t6_sad_demo/`, `t2_backup/`** — Ming owns them. If something looks wrong, tell me.
- **Do not run `t6_sad_demo/run.py`**: it rewrites Ming's tracked `t6_sad_demo/outputs/` (CRLF → LF churn). Call `engine.evaluate()` from our adapter instead.
- **Tests:** expected values come from Ming's labels or from me, not invented to match the code.
- **Synthetic data only.** No real patient data anywhere.
- **Secrets:** never write AWS keys or tokens into files. Use the local AWS profile / env vars; keep `.env` git-ignored and only commit `.env.example`.
- **Strands is a newer library:** check its current docs / installed package source before writing agent code instead of relying on memory.
- When inspecting real Synthea or ClinicalTrials.gov data, trust the actual structure over assumptions.
- Keep README updated as each module lands; it must run from a clean clone.
- Python 3.11+. Keep dependencies minimal.

## ⏳ Waiting on Ming (updated 2026-10-09 after her `ming/t6-sad-integration` delivery, merged into main)

Delivered: SAD rules `t6_sad_demo/rules/sad-1.0.0.json` (10 criteria + age, own `rules[].predicate` format, codes live in her `engine.py`), 8 cases + contexts `t6_sad_demo/data/{cases,context}/`, her engine and outputs, T2 reference rules. Ming pushes to the repo (GitHub `Charlottttttte`), so T1's "Ming clones and pushes" is done.

| Item | Needed for | Status / placeholder | Re-verify when it lands |
|---|---|---|---|
| Ground truth for SAD (≥20 patients, format `patient_id,criterion_id,expected` + `PATIENT` rows; flips list) | T11 | **missing**; Ming says her 8-case outputs are not independent labels | `python eval/evaluate.py --trial SAD --labels data/ground_truth/trial_SAD.csv` |
| More SAD patients (8 now) | scale, demo | 8 cases | rerun adapter acceptance |
| Injected-case list mapped to switches (`drop_codes`, `bad_units`, …) | T9 | her scenarios live in `prepare.py`/`test_demo.py`; not mapped to `FAILURE_TARGETS` | set `config.FAILURE_TARGETS`, rerun each `--fail` |
| Equivalent-code map (e.g. LDL 18262-6 / 13457-7 / 2089-1) | agent recovery | placeholder table in `src/agent/agent.py` | agent reports source = Ming's file |
| v2 amendment text + v2 rules for SAD | T10 | missing; engineering fixtures on NCT02178098 only | `--fail amendment_v2` on SAD; planted flips in impact report |
| Fasting ≥ 6 h policy in her engine; method-check scope; I5 evidence-retrieval agent | SAD correctness | open items in her README; her engine still checks fasting > 0 h | — |
| Raw Synthea files (~62 MB, not committed) | her `test_originals_unchanged`, I5 longitudinal retrieval | not needed for the adapter | — |

S3: bucket **`prescreen-hack-5b19ed`** (us-west-2, Ming's account, public access blocked, SSE-S3) created 2026-10-09 with Ming's consent; `prescreen-dev-xzy` can write; SAD snapshot upload verified.

Open questions for Ming (engine assumptions below were made for the generic engine on fixtures; most do not apply to SAD, which uses her engine):
- ~~Aggregation order~~ answered by Ming's SAD rules: failed criterion wins (decision 13).
- Non-computable predicates (computable=false or grade N) never block; they are listed as "CRC to check". Confirm.
- Unit conversion factors and plausible ranges in `units.py` need Ming's review.
- Engine assumptions made in T5 (confirm or correct):
  1. `exists` on Condition counts any clinical status, including resolved (history counts).
  2. MedicationRequest counts only `status == "active"` orders; no active order → default `absence_means` = `not_met`.
  3. `count_distinct_active_ingredients` counts distinct RxNorm codes; true ingredient-level counting needs the ATC→RxNorm map.
  4. `mean_of_last_3` uses however many values exist (1–3) inside the window.
  5. If the value chosen by aggregation is unconvertible or implausible → `unknown`; never fall back to an older value.
  6. Values are rounded to 2 decimals after unit conversion before comparing (boundary stability).
  7. Every empty query sets `needs_recovery`; T7 sends only those still `unknown` (labs, allergies) to the agent. Missing diagnoses/medications stay `not_met` by rule and are not sent (saves model calls). Confirm.
  8. Recovery agent uses a placeholder equivalent-code table (LDL 18262-6/13457-7/2089-1, TG 2571-8/3043-7, hypercholesterolemia 13644009/55822004) until `data/mappings/local_code_map.json` exists; expected shape `{"groups": [{"concept", "codes": [{system, code, display}]}]}`.

## Bedrock access (resolved 2026-10-09)

Daisy's own account cannot use Bedrock (new-account verification + Free plan: Claude blocked by an AWS-managed SCP, all on-demand token quotas at 0). It is **not used**.
We run on **Ming's account** via local AWS profile `prescreen-dev-xzy`, region `us-west-2`, model `us.amazon.nova-2-lite-v1:0`. `check_bedrock.py` passed 2026-10-09.
If Daisy's account is ever needed (e.g. for S3 ownership), recheck its quotas first.

## Current status

Engineering T1, T3–T11 done and verified on engineering fixtures (`tests/fixtures/`, NCT02178098, NOT a project trial); README verified from a clean clone. LOINC LDL code corrected 18262-1 → 18262-6 everywhere (2026-10-09; 18262-1 was an engineering typo).
SAD pivot plan: **P0 done 2026-10-09** (Ming's branch merged, decisions recorded, LOINC fix, TRIALS = SAD/T2, S3 bucket live). **Next: P1** adapter `src/engine/sad_adapter.py` + `run.py --trial SAD`, acceptance = Ming's 2/4/1/1. Then P2 agent on SAD, P3 switches + amendment on SAD, P4 eval / HTML report / README / demo script.
Remaining T12: demo video, make repo public, writeup, submit. Optional: note_conflict (5/5 failure paths). Known model limitation: borderline amendment wording flips between substantive and wording across runs.

# Trial Pre-Screening Agent: engineering task plan

Oct 9, 2026 · @Daisy Xu

> Translated from the Chinese original on 2026-10-11. This is the plan as written on Oct 9, when the primary trial was still a placeholder "trial B". The project later switched to Ming's SAD trial (NCT07347678) and the agent grew beyond empty-query recovery; see the [root README](../README.md) and `CLAUDE.md` for what was built.

## Overview

Engineering has 12 tasks. The goal is to run trial B end to end by Saturday night and submit before Sunday 11:59 AM PT. Based on PROJECT_BRIEF v2, three changes were made to the original D1–D10: the FHIR server became a local file adapter, the agent handles only exceptions, and email and scheduling became optional.

**Core architecture principle: the deterministic engine evaluates every patient first; the agent takes over only the exceptions.**

1. Load the compiled predicates (compiled by hand by Ming; 15 for trial B).
2. The deterministic engine evaluates each predicate for each patient and outputs `met` / `not_met` / `unknown`.
3. Aggregation rules sort the results into four sections.
4. Only two kinds of case go to the agent: an empty query that needs retrieval recovery (brief decision 2), and changed criteria text that needs judgement (decision 5). Decision 4 (conflicting evidence routed to review) is added if time allows.
5. Every model decision writes one trace line, output with the log.

Why: letting the model decide 50 patients × 15 predicates one by one would be slow and expensive, and results would vary between runs, so evaluation numbers would not be trustworthy. The exceptions are exactly what a CRC handles from experience and a script cannot, so this still meets "not a pipeline". The model **does not make the final eligibility call**; conflicting evidence always goes to the CRC.

**Timeline**

| When | Tasks | Must achieve |
| --- | --- | --- |
| Friday | T1 infrastructure, T2 interface agreement, T3 data adapter, T4 ctgov_fetch | One successful Bedrock call; one patient's LDL value retrieved |
| Saturday morning | T5 decision engine, T6 aggregation and log | **Log for trial B's 50 patients (the critical line)** |
| Saturday afternoon | T7 agent, T8 trace, T9 failure switches | Decision 2 visible in the demo |
| Saturday night | T10 amendment re-screen | Editing a snapshot triggers a re-screen report |
| Sunday morning | T11 evaluation, T12 README and submission | Evaluation numbers, runnable README, 3-minute video |

**Needed from Ming** (details in T2): trial B predicate JSON, Synthea patients with the list of injected cases, ground-truth labels, ATC→RxNorm map, NCT IDs of both trials.

## T1 Infrastructure (Friday, about 2 hours)

Goal: a public repository both of us can push to, plus one successful Bedrock call.

**Steps**

- **Repository**: public GitHub repository with an MIT license; add Ming as collaborator. `.gitignore` excludes `.env`, `__pycache__` and local cache directories.
- **AWS region**: use `us-west-2` or `us-east-1` (whichever has the Claude model enabled on Bedrock), recorded in `.env.example`.
- **Bedrock access**: console → Bedrock → Model access, request the Anthropic Claude models. A use-case form may be required; **do this first today**.
- **Budget alert**: AWS Budgets alert at $20, emailing both of us.
- **S3 bucket**: one bucket such as `prescreen-hack-<random suffix>` with three prefixes: `snapshots/`, `logs/`, `cache/`.
- **README skeleton**: installation steps and one run command first; add a section as each module lands.

**Directory layout**

```
prescreen-agent/
├── data/
│   ├── patients/          # Ming's Synthea FHIR JSON
│   ├── predicates/        # trial_B.json, trial_G.json
│   ├── mappings/          # atc_to_rxnorm.json, local_code_map.json
│   ├── snapshots/         # criteria text snapshots (v1, v2 for the simulated amendment)
│   └── ground_truth/      # Ming's labels
├── src/
│   ├── adapters/fhir_store.py     # T3
│   ├── tools/ctgov.py             # T4
│   ├── engine/evaluate.py         # T5
│   ├── engine/units.py            # T5 unit conversion and ranges
│   ├── engine/aggregate.py        # T6
│   ├── report/log_writer.py       # T6
│   ├── agent/agent.py             # T7
│   ├── agent/trace.py             # T8
│   ├── amendment/monitor.py       # T10
│   └── config.py                  # T9 failure switches
├── eval/evaluate.py               # T11
├── tests/
├── run.py                         # one command for the whole flow
├── requirements.txt
├── .env.example
└── README.md
```

**Acceptance**: one Bedrock call via `python -c` returns text; Ming can clone and push a commit.

## T2 Interface agreement with Ming (Friday, about 1 hour, together)

Goal: settle today every format the engine depends on; afterwards neither side changes them unilaterally.

**Items to agree**

| Item | From Ming | Engineering use | Latest |
| --- | --- | --- | --- |
| Predicate file | Trial B's 15 predicates as JSON, in the brief section 5 Predicate structure | T5 engine input | Friday night |
| Extension fields | Confirm `grade`, `resource`, `anchor`, `aggregation`, `absence_means`, `assumption` are all in use | T5 must implement them | Friday |
| Patient data | Synthea FHIR Bundle JSON exports, one file per person, in `data/patients/` | T3 reads them | Friday night; 5 first is fine |
| Injected-case list | For each injected case: patient ID, what was injected, expected result | T5 unit tests, T9 failure scenarios | Saturday morning |
| ATC→RxNorm map | For each ATC class in the predicates, the list of RxNorm ingredient codes | Medication predicate matching | Saturday morning |
| Local code map | E.g. Hyperlipidemia accepted as hypercholesterolemia, as a separate table | Taken out of the predicates | Saturday morning |
| Ground truth | At least 20 patients, `met`/`not_met` for each computable predicate, plus a patient-level conclusion | T11 evaluation | Saturday night |
| NCT IDs | Real NCT IDs of trials B and G | T4, T10 | Friday |
| Amendment snapshot v2 | A hand-edited version of trial B's criteria text with at least one substantive and one wording-only change | T10 demo | Saturday afternoon |

**Engineering does first**: while waiting for data, hand-write 3 minimal patient JSONs (one eligible, one excluded, one missing a lab) so T3 and T5 can start without blocking.

**Division of responsibility**: predicate content, code correctness and labels belong to Ming; how predicates are executed and how results are aggregated and presented belong to engineering. When a predicate looks wrong, engineering raises it and Ming changes it; engineering does not edit predicate files.

## T3 Data adapter (Friday, about 3 hours)

Goal: a data layer with the same interface as FHIR queries that reads local Synthea JSON directly. It replaces the HAPI FHIR server of the original D2 and saves deployment time; the interface is unchanged, so production can swap in a real FHIR service.

**Loading**

- At start-up read `data/patients/*.json` (FHIR Bundles) and build an in-memory index `patient_id → resourceType → [resources]`.
- Resource types needed: `Patient`, `Condition`, `Observation`, `MedicationRequest`, `AllergyIntolerance`, and `DocumentReference` for injected note text (or the text field agreed with Ming).

**Public functions**

```python
def fhir_query(patient_id: str, resource: str, codes: list[dict],
               window_days: int | None = None,
               anchor_date: str | None = None) -> QueryResult

def search_notes(patient_id: str, keywords: list[str]) -> QueryResult

def list_patients(since_date: str | None = None) -> list[str]
```

- `codes` match on `system + code`; several codes for one concept are OR.
- `window_days` and `anchor_date` together define the time window; the default anchor is the screening date.
- `search_notes` serves the agent's retrieval recovery; simple keyword matching returning snippets and source IDs is enough.

**Return structure (typed errors, so the agent can handle them differently)**

```python
QueryResult = {
  "status": "ok" | "empty" | "timeout" | "malformed",
  "records": [ {"resource_id", "code", "value", "unit", "date"} ],
  "detail": ""   # explanation on error
}
```

- `empty`: the query worked but found nothing; this is the signal that triggers decision 2.
- `timeout` / `malformed`: simulated by T9 switches; the engine handles them by rule.

**Acceptance**: retrieve a hand-written patient's LDL-C value with its `resource_id`; a query with a non-existent code returns `empty`, not an error.

## T4 ctgov_fetch tool (Friday, about 1.5 hours)

Goal: fetch trial eligibility criteria from the ClinicalTrials.gov API v2; the main basis for "calls a tool you didn't build".

**Function**

```python
def ctgov_fetch(nct_id: str) -> FetchResult
# GET https://clinicaltrials.gov/api/v2/studies/{nct_id}
# take from protocolSection.eligibilityModule:
#   eligibilityCriteria, minimumAge, maximumAge, sex
```

**Robustness**

- 10-second timeout, one retry on failure.
- On success write the cache `cache/ctgov/{nct_id}.json` with the fetch time.
- If it still fails, fall back to the cache and return `status: "stale"` with the cache age. A cache older than 14 days returns `status: "error"` and no log is issued (brief section 6 rule).
- Typed return values as well: `ok` / `stale` / `error`, with `fetched_at`.

**Snapshots (for T10)**

- On every successful fetch save the criteria text as `snapshots/{nct_id}/{YYYY-MM-DD}.txt` and compute its SHA-256.
- Keep one copy locally and one in S3.

**Acceptance**: a real NCT ID returns the criteria text; with the network off (or the T9 timeout switch on) the cache is returned and marked `stale`.

## T5 Decision engine (Saturday morning, about 4 hours)

Goal: a pure function that takes one predicate and one patient and returns one Verdict. No LLM; the same input always gives the same output. This is the core of the technical-depth score.

**Function**

```python
def evaluate(predicate: dict, patient_id: str, screening_date: str) -> Verdict
```

**Steps**

1. If `computable == false` or `grade == "N"`: return `unknown` directly, note "left to the CRC".
2. Determine the time anchor: with `anchor.event == "index_event"`, first find the most recent qualifying stroke or TIA as the anchor (trial G only; can wait for B).
3. Call `fhir_query` with `resource`, `codes` and `window_days`.
4. If the result is `empty`: return per `absence_means` (missing diagnosis → `not_met`, missing lab → `unknown`, missing intolerance → `unknown`), and set `needs_recovery: true` on the Verdict for the T7 agent.
5. Numeric values: unit conversion and plausibility range check first (below), then pick the value per `aggregation` (`most_recent` / `mean_of_last_3` / `count_distinct_active_ingredients`), then compare per `operator`.
6. Fill `evidence`: `resource_id`, `value`, `date` for every record used.
7. Set `blocking`: taken from the predicate, default `true`.

**First version implements only the operators trial B uses**: `<`, `<=`, `>`, `>=`, `exists`. `no_change`, `active_for_days` and the like for trial G or if time allows.

**Unit conversion and range check (`engine/units.py`)**

| Analyte | Standard unit | Convertible unit | Plausible range |
| --- | --- | --- | --- |
| LDL-C / total cholesterol / HDL-C | mg/dL | mmol/L × 38.67 | 10–500 |
| Triglycerides | mg/dL | mmol/L × 88.57 | 20–5000 |
| Systolic BP | mmHg | none | 60–260 |
| Diastolic BP | mmHg | none | 30–160 |
| ALT | U/L | none | 1–2000 |

Ming to review the conversion factors and ranges. An unrecognized unit, or a value out of range after conversion → that predicate returns `unknown` with the reason in the note (brief failure path "tool returns garbage").

**Tests (`tests/test_evaluate.py`)**

- One test per injected case from Ming: boundary values (exactly at the threshold), missing labs, wrong units, records outside the time window.
- Each test asserts `status` and the `resource_id` in `evidence`.

**Acceptance**: every computable trial B predicate returns the expected result for the 3 hand-written patients; all injected-case tests pass.

## T6 Aggregation and log (Saturday morning, about 2 hours)

Goal: aggregate each patient's predicate results into a patient-level conclusion and output a pre-screening log the CRC can use directly. **With this done, trial B runs end to end.**

**Aggregation rules (`engine/aggregate.py`, fixed rules, no model)**

Checked in this order; the first match wins:

1. Any exclusion `met` → **excluded**, naming which one.
2. Any predicate carrying a conflict flag (from T7 decision 4) → **needs review**.
3. Any predicate with `blocking: true` that is `unknown` → **pending**, listing the missing data items.
4. All computable inclusions `met` → **likely eligible**; if there is an `unknown` with `blocking: false`, add a "confirm at visit" note.
5. Any inclusion `not_met` → **excluded**.

Confirm with Ming that rule 3 comes before rule 5; it reflects brief goal 2: "answer unknown before answering excluded".

**Log format (`report/log_writer.py`)**

- Two outputs: `prescreen_log_{trial}_{date}.md` (for people) and `.csv` (for the evaluation script).
- Markdown header: trial ID, criteria fetch time (stale and age when cached), count per section.
- Four sections: likely eligible, pending, excluded, needs review. Each row: patient ID, conclusion, key evidence (`resource_id` + value + date), notes, and the patient's trace entries.
- Written to local `out/` and uploaded to S3 `logs/{trial}/{date}/`.

**Entry point**

```bash
python run.py --trial B --date 2026-10-12
```

**Acceptance**: all 50 patients appear in exactly one section of the log, none missing; every "excluded" traces back to a specific predicate and record.

## T7 Agent exception layer (Saturday afternoon, about 4 hours)

Goal: implement brief decision 2 (retrieval recovery) with Strands Agents + Bedrock. This is the part of the demo that best shows "an agent, not a pipeline".

**Trigger**

After T5, collect every Verdict with `needs_recovery: true` and hand them to the agent one by one. The agent does not touch predicates that already have a conclusion.

**Agent tools**

| Tool | Purpose | Source |
| --- | --- | --- |
| `get_predicate(criterion_id)` | Read the predicate definition: concept, codes, threshold | Predicate file |
| `lookup_equivalent_codes(concept, system)` | Return equivalent codes for the same concept (LOINC, SNOMED, ...) | Ming's local mapping table |
| `fhir_query(...)` | Re-query with the new codes | T3 |
| `search_notes(patient_id, keywords)` | Search clinical note text | T3 |
| `evaluate_with_records(criterion_id, records)` | Hand found records back to the deterministic engine; the model does no numeric comparison itself | T5 |
| `record_decision(...)` | Write trace and give the final status | T8 |

**System prompt points**

- You help a clinical research coordinator handle "the query came back empty".
- Try in order: equivalent codes → note text → give up. Call `record_decision` after each step to say what was done and why.
- Found records must go to `evaluate_with_records`; **never compare values or decide yourself**.
- A description in note text (e.g. "patient says LDL is high") is not a lab value; it can only support "recommend repeating the test".
- When giving up, return `unknown` with a note listing the codes and keywords tried and a recommendation (e.g. "recommend a lipid panel").

**Skeleton**

```python
from strands import Agent
from strands.models import BedrockModel

recovery_agent = Agent(
    model=BedrockModel(model_id=os.environ["BEDROCK_MODEL_ID"]),
    tools=[get_predicate, lookup_equivalent_codes, fhir_query,
           search_notes, evaluate_with_records, record_decision],
    system_prompt=RECOVERY_PROMPT,
)

for v in pending_recovery:
    recovery_agent(f"Patient {v.patient_id}: the query for predicate {v.criterion_id} came back empty. Please handle it.")
```

**Cost and stability**: a fresh conversation per Verdict (no accumulated context); at most 6 tool calls; temperature 0.

**If time allows: decision 4 (conflicting evidence)**: when structured data and note text contradict each other, the agent lists both pieces of evidence and marks the conflict; T6 puts the patient in "needs review". The model presents, it does not adjudicate.

**Acceptance**: for Ming's planted "wrong code" cases the agent recovers the value through an equivalent code; cases with no data at all return `unknown` with a readable explanation.

## T8 Trace (Saturday afternoon, about 1 hour, alongside T7)

Goal: every model decision leaves one readable line, shown in the log and the star of the demo. The brief requires 100 % trace coverage.

**Structure** (the `trace` field of the brief's Verdict)

```python
{"step": 1,
 "tool": "lookup_equivalent_codes",
 "result": "found LOINC 13457-7 (calculated LDL)",
 "decision": "re-query with the equivalent code, because the original code 18262-6 has no record"}
```

**Implementation**

- The `record_decision` tool appends the trace to the current Verdict.
- Rule-based handling (cache fallback, unit conversion) also writes trace, with `tool` set to `rule:cache_fallback`, `rule:unit_convert`, so reviewers can tell model decisions from fixed rules.
- The full trace is also saved as `out/trace_{trial}_{date}.jsonl` for the evaluation script to measure coverage.

**In the log**: indented under the patient row, e.g.

```
P-017  pending  LDL-C cannot be assessed
  ↳ original code has no record → re-queried with equivalent code, no record → searched notes for "LDL / cholesterol", no lab value
  ↳ conclusion: unknown; recommend a lipid panel
```

**Acceptance**: every Verdict that went through the agent has at least one trace line; the log shows plainly what the agent did.

## T9 Failure-injection switches (Saturday afternoon, about 1.5 hours)

Goal: every failure scenario is reproducible with one configuration switch, so video recording and live demos do not depend on real failures happening by chance.

**Configuration (`config.py`, overridable on the command line)**

```python
FAILURES = {
    "ctgov_timeout": False,   # ctgov_fetch raises a timeout
    "bad_units": False,       # a designated patient's LDL gets a wrong unit or absurd value
    "drop_codes": False,      # a designated patient's LDL records use an unusual code
    "amendment_v2": False,    # T10 reads the v2 snapshot instead of a real fetch
    "note_conflict": False,   # optional: inject note text contradicting the structured data
}
```

```bash
python run.py --trial B --fail ctgov_timeout
```

**Scenarios and expected behaviour**

| Switch | Brief scenario | Type | Expected behaviour | Priority |
| --- | --- | --- | --- | --- |
| `ctgov_timeout` | Tool fails | Rule | Use the cache; log header marked stale with its age | Must |
| `bad_units` | Tool returns garbage | Rule | Convert if possible, else `unknown`; trace states the reason | Must |
| `drop_codes` | Tool returns nothing | Model | Agent switches code and recovers the value; trace visible | **Must, demo star** |
| `amendment_v2` | Ambiguous amendment | Model | See T10 | Must |
| `note_conflict` | Tool and model disagree | Model | Both pieces of evidence side by side; needs review | Optional |

Minimum for the video: one rule scenario + `drop_codes` + one of amendment or conflict.

**Acceptance**: each switch run once with output matching the table; with all switches off the result equals a normal run.

## T10 Amendment monitoring and re-screen (Saturday night, about 3 hours)

Goal: when the criteria text changes, judge whether the change is substantive and report which patients change status and why. Implements brief decision 5.

**Flow**

1. **Detect**: compare the SHA-256 of the newly fetched text with the previous snapshot; stop if equal.
2. **Item-level diff**: split both versions into items (by line and numbering) and find added, removed and modified items with `difflib`.
3. **Model classification**: each changed item goes to Bedrock, which returns one of `substantive` (e.g. a threshold or time window changed) / `wording` (phrasing only) / `ambiguous` (cannot tell), with a one-sentence reason, written to the trace.
4. **Handling**:
   - `wording` → recorded, no re-screen.
   - `ambiguous` → flagged "CRC to confirm", no re-screen (brief: never re-screen on a guess).
   - `substantive` → step 5.
5. **Recompile**: substantively changed items need updated predicates. **For the demo Ming prepares the v2 predicate file in advance**, paired with the v2 snapshot; automatic compilation is brief decision 1, disclosed as human-reviewed, and not done.
6. **Re-screen**: run T5–T6 again for all of the trial's patients with the v2 predicates and compare with the previous result patient by patient. No dependency tracking to re-run only affected verdicts; the engine is fast and a full re-run gives the same output.
7. **Impact report**: `amendment_impact_{trial}_{date}.md`, listing the changed items and their classification, and every patient whose status changes: old status → new status, with the reason pointing to the item and the evidence.

**Demo preparation** (depends on Ming's v2 snapshot from T2): v2 contains at least one substantive change (e.g. a lower LDL threshold that makes a previously excluded patient likely eligible) and one wording-only change.

**Acceptance**: running with `amendment_v2` on, the report classifies both changes correctly; every status-flip patient Ming planted appears in the report (brief metric: amendment recall 100 %).

## T11 Evaluation script (Sunday morning, about 2 hours)

Goal: compare the engine's output with Ming's ground truth and compute the brief's section 11 metrics. The brief says the evaluation numbers "must never be cut".

**Inputs**: T6's CSV, T8's trace JSONL, Ming's label file, and the results of each T9 switch run.

**Metrics**

| Metric | How computed | Target |
| --- | --- | --- |
| Wrongful exclusions | Patients labelled eligible but output as excluded | 0 |
| Patient-level sensitivity | Share of labelled-eligible patients placed in "likely eligible" or "pending" | ≥ 95 % |
| Criterion-level accuracy | Share of computable predicates where `met`/`not_met` agrees with the label | ≥ 90 % |
| Abstention rate | Share of predicates output as `unknown` | Reported |
| Evidence coverage | Share of Verdicts with a valid `resource_id` | 100 % |
| Trace coverage | Share of agent-handled Verdicts that have a trace | 100 % |
| Recovery rate | Share of `drop_codes` planted cases the agent recovers | Reported |
| Amendment recall | Share of planted status flips detected in the report | 100 % |
| Failure paths | Number of scenarios reproducible with a switch | actual / 5 |

**Error attribution**: one detail line (patient, predicate, expected, actual) for each result disagreeing with the labels, which Ming assigns to one of four causes: predicate compilation, concept mapping, data problem, engine defect.

**Run**

```bash
python eval/evaluate.py --trial B --labels data/ground_truth/trial_B.csv
```

Outputs `eval_report.md`; the numbers go straight into the writeup and video. **Acceptance**: one command produces the full metric table.

## T12 README check, demo and submission (Sunday morning, deadline 11:59 PT)

Goal: all four submission items in place; a reviewer who is not logged in can open the repository and run it by following the README.

**The README must contain**

- One paragraph: for whom (the CRC), what it solves, what it produces.
- Installation: Python version, `pip install -r requirements.txt`, the meaning of each `.env.example` variable (AWS region, Bedrock model ID, S3 bucket name).
- One command that runs it: `python run.py --trial B`, and the command for each failure switch.
- An architecture diagram or short explanation: deterministic engine + agent exception handling, and the boundary between model decisions and fixed rules.
- Data statement: only Synthea synthetic data and public APIs, no PHI.
- Known limitations: copied from brief section 7.

**Checks**

- [ ] In a brand-new directory (or a new virtual environment), follow the README exactly from `git clone`.
- [ ] Open the repository link in a private window and confirm it is not a 404.
- [ ] A LICENSE file is in the repository root.

**Video (3 minutes, recorded with Ming)**: who the CRC is and the weekly cost (20 s) → normal run producing the log (40 s) → `drop_codes` showing the agent trace (50 s) → one rule failure scenario (20 s) → amendment re-screen report (30 s) → evaluation numbers (20 s). Engineering prepares the commands for each segment and pre-generated outputs, so there is no waiting during recording.

**Engineering's paragraphs in the writeup**: architecture, the boundary between agent decisions and fixed rules, failure handling, use of AWS services.

## Optional (in order, if there is time)

1. **Decision 4, conflicting evidence**: see the end of T7.
2. **EventBridge schedule**: a rule firing every Monday at 8:00; a screenshot in the README is enough, it need not actually run.
3. **Lambda packaging**: package `run.py` as a Lambda triggered by EventBridge.
4. **SES email**: in sandbox mode both sender and recipient must be verified, so do it early; if not finished, keep only the S3 write.
5. **Trial G**: needs the `index_event` anchor and the `no_change`, `active_for_days` operators.
6. **Local HAPI FHIR**: replace T3's file adapter with HAPI FHIR in Docker, interface unchanged.

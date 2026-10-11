# Trial Pre-Screening Agent

AWS Community Day Bay Area 2026 hackathon — "Hand it off" challenge.

A clinical research coordinator (CRC) checks upcoming patients against trial eligibility criteria and writes a pre-screening log: who is likely eligible, who is excluded and by which criterion, and who cannot be assessed yet. Protocol amendments require re-checking those assessments. Interview-based workload and measured time savings are still pending.

This system takes over that work. It reads a trial's criteria from ClinicalTrials.gov and patient records as FHIR R4, and writes the log the CRC would write: **likely eligible / pending / excluded / needs review**, with the record, value and date behind every verdict. Deterministic rules decide everything a rule can decide. An agent on Amazon Bedrock handles what rules cannot read: results filed under another code, patients' own words about smoking and drug history, conflicting results, and evidence for criteria that need an investigator's judgement. When the criteria change, it classifies each change and re-screens. No patient is ever contacted. **Synthetic data only.**

**Historical demonstration:** [`docs/demo/index.html`](docs/demo/index.html) and the previously shared hosted artifact predate these repairs. They are not current validation evidence. Run the commands below to validate the updated code; static reports have not been regenerated.

## Trial and data

- **Trial:** [NCT07347678](https://clinicaltrials.gov/study/NCT07347678), SAD cohort: 10 criteria plus age 18–65. The compiled rule pack (`sad-1.0.0`), the deterministic SAD evaluator and the core screening cases are in [`trials/nct07347678_sad/`](trials/nct07347678_sad/README.md); every input is checked against SHA-256 manifests before a run. A second compiled rule set, [NCT07610278](trials/nct07610278/README.md) (hypertension with hypercholesterolemia), is included for reference.
- **Patients:** 58 synthetic patients as FHIR R4 bundles.
  - **Core screening set** (SAD01–SAD08): Synthea 3.3.0 demographics with designed screening records (labs with fasting specimens and reference ranges, a screening interview).
  - **Extended scenario set** (EXT01–EXT50, [`data/extended_cases/`](data/extended_cases/README.md)): generated deterministically by `scripts/build_extended_cases.py` from core case SAD01, one deliberate situation per case: both sides of every threshold, exact boundaries, unit conversion, missing data, hand-written free text, liver and kidney evidence, conflicting results. Each case records its design intent before any run (`design_labels.csv`); evaluation measures the system against it. It is not clinical ground truth.

## Quick start

Requires Python 3.11+. Everything below runs from a clean clone.

```bash
git clone https://github.com/DaisyXUUUUU/prescreen-agent.git
cd prescreen-agent
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m pytest tests/            # offline, no AWS needed
```

**Without AWS** (rules only, agent off):

```bash
python run.py --trial SAD --date 2026-10-09 --no-agent
```

**With AWS.** You need an AWS profile with Bedrock access to Amazon Nova 2 Lite in `us-west-2`. Credentials come from your local profile (`aws configure` or `aws sso login`); nothing secret goes in the repository. In `.env`, set **`AWS_PROFILE`** to that profile (the template says `default`), check `AWS_REGION` and `BEDROCK_MODEL_ID`, and set `S3_BUCKET` to have logs and snapshots copied to S3. Then:

```bash
python check_bedrock.py            # expect: response: bedrock ok
python run.py --trial SAD --date 2026-10-09
```

Open `out/prescreen_log_SAD_2026-10-09.md`. If Bedrock is unreachable, the run says so once and continues with rules only. `--no-extended-cases` screens the core set only.

## Outputs

Each run writes to `out/` (and to `s3://$S3_BUCKET/logs/{trial}/{date}/` when `S3_BUCKET` is set):

- `prescreen_log_{trial}_{date}.md`: the CRC's log, four sections with key evidence (record, value, date), notes, and per-patient detail with every criterion and its trace;
- `prescreen_log_{trial}_{date}.csv`: one row per patient and criterion;
- `trace_{trial}_{date}.jsonl`: every rule and model step, labelled by actor (rule, engine, agent);
- `run_{trial}_{date}.json`: run summary; `amendment_impact_{trial}_{date}.md` when the criteria changed.

If the criteria cannot be fetched and the cached copy is older than 14 days, no log is written.

## How a verdict is made

1. **Criteria** are fetched from the ClinicalTrials.gov API v2, cached, and snapshotted with a SHA-256.
2. **Patient records** are loaded into one in-memory FHIR store (`src/adapters/fhir_store.py`), with FHIR-style queries so a real FHIR server can replace it. The evaluator, the failure switches and the agent share it.
3. **Guards** run first and are traced as rules: unambiguous unit conversion (LDL mmol/L → mg/dL, rounded to 0.1 mg/dL) and plausibility ranges (an LDL of 690 mg/dL becomes `unknown`, not "met").
4. **The SAD evaluator** decides each criterion: binding to the screening encounter, fasting specimen, the upper limit of normal from each result's reference range (ALT or AST > 1.5 × ULN), questionnaire coverage windows for smoking and drug history. Criterion I5 ("no clinically significant hepatic or renal abnormality") is always the investigator's call.
5. **The agent** (Strands Agents + Amazon Nova 2 Lite) handles what the rules cannot settle. The model reads, searches and explains; code compares numbers, applies windows and makes the call:
   - *Result missing* → the agent looks up equivalent codes and re-queries; a record it finds goes back to the evaluator by ID, never by value.
   - *Free-text history* (smoking, advanced therapies, lipid-lowering drugs) → the model extracts facts, each with a quote; quotes absent from the source are dropped; drug classes come from the NLM **RxNav** terminology (RxNorm / RxClass), not the model's memory; code scans the text for in-class drugs the model left out and asks it again; code applies the thresholds and windows. Where the protocol's definitions disagree (4–5 cigarettes on weekend nights: over 2 a day, under 10 a week) the criterion stays unknown for the CRC.
   - *Conflicting results* → code re-runs the evaluator with each candidate to tell whether the choice changes the outcome; the model explains the difference and what to check, and never picks one.
   - *I5 evidence* → a tool-using agent looks up liver and kidney labs, diagnoses and notes; lab flags come from reference ranges in code; every cited record is verified; a real finding sends the patient to review.
6. **Aggregation** (fixed rules): a failed structured criterion → excluded; a failure interpreted from free text, unresolved conflict or flagged I5 evidence → needs review; unknown → pending; else likely eligible. Quotes and terminology matches do not independently verify extracted amounts, dates or negation, so interpreted failures never directly exclude. Smoking ranges and uncertain quantities stay unknown, without choosing a midpoint or upper bound. A conflict resolves only when every candidate passes through the same evidence guards and gives the same decided result.

Fresh model conversation per case, temperature 0, at most 6–8 tool calls per task. Every step is traced; `--no-agent` gives a rules-only run.

A generic predicate engine (`src/engine/evaluate.py`) evaluates trials compiled into the general predicate format (thresholds, time windows, aggregation, what a missing record means); `tests/fixtures/` exercises it.

## Amendment monitoring

Every run compares the fetched criteria with the previous snapshot (SHA-256). Text is split into items and diffed. Numeric or comparison-operator changes are substantive by rule, including decimal-point and inequality changes. Safe whitespace/case/trailing-period and equivalent operator-glyph changes are wording; other changes go to the model as substantive, wording or ambiguous, with model failure remaining ambiguous. Only substantive changes trigger re-screening with a person-prepared amended rule pack. Rules are not compiled automatically.

Simulated amendment (SAD LDL-C threshold 70 → 100 mg/dL, HbA1c line reworded):

```bash
python run.py --trial SAD --date 2026-10-09 --fail amendment_v2 \
  --v1-snapshot tests/fixtures/sad/NCT07347678_v1.txt \
  --v2-snapshot tests/fixtures/sad/NCT07347678_v2.txt \
  --v2-predicates tests/fixtures/sad/sad-1.0.1-sample.json
```

## Failure scenarios

Each failure path is reproducible with `--fail` (repeatable). Data failures alter the loaded records in memory only, and the log announces exactly what was altered.

| Switch | What it does | Behaviour |
|---|---|---|
| `ctgov_timeout` | ClinicalTrials.gov call times out | criteria served from cache, log stamped STALE (no log if the cache is older than 14 days) |
| `drop_codes` | SAD04's LDL-C filed under generic LDL 2089-1, preserving its direct method | rule query empty → agent finds it under the equivalent code → evaluator revalidates and decides |
| `bad_units` | SAD01's LDL-C in mmol/L, SAD02's ×10 | first converted by rule; second rejected as implausible → `unknown` with the reason |
| `amendment_v2` | an amended criteria text stands in for the live fetch | changes classified; substantive → re-screen and impact report |
| `note_conflict` | not implemented | |

Targets: `DEFAULT_FAILURE_TARGETS` in `src/engine/sad_adapter.py`, overridable with `FAILURE_TARGETS` in `src/config.py`.

## Evaluation

One command runs the normal run and four failure scenarios sequentially, then scores them against the extended set's design intent; a second builds the reviewer page. Use `--jobs 2` only if the account's model quota permits concurrent scenarios. Runtime depends on model latency and quotas.

```bash
python eval/evaluate.py --trial SAD --date 2026-10-09 \
  --labels data/extended_cases/design_labels.csv --flips data/extended_cases/design_amendment_flips.txt \
  --v1-snapshot tests/fixtures/sad/NCT07347678_v1.txt --v2-snapshot tests/fixtures/sad/NCT07347678_v2.txt \
  --v2-predicates tests/fixtures/sad/sad-1.0.1-sample.json
python scripts/build_report.py     # out/eval/SAD/report.html and docs/demo/index.html
```

The report covers wrongful exclusions, patient-level sensitivity, criterion accuracy, abstention, evidence and trace coverage, recovery rate, amendment recall and failure paths, and lists every disagreement for error attribution. Labels use the CSV format `patient_id,criterion_id,expected` (`met` / `not_met` per criterion, `eligible` / `not_eligible` in a `PATIENT` row). `--reuse` scores existing runs without launching missing runs. `--out-root` isolates an evaluation. Missing runs, child failures, mode downgrades or failed required failure checks produce a nonzero exit code. The report builder requires a complete execution marker.

SAD is a replay of the fixed 2026-10-09 encounters: another `--date` is rejected before fetching criteria. New dates need reviewed new case contexts. `--no-agent` disables Bedrock throughout, including amendment classification, but still permits public API calls. One preflight pins the same effective mode for v1/v2. Unchanged criteria reuse their v1 verdicts; agent errors block amendment attribution.

Agent calls have SDK turn limits and cancellation timers (60 seconds for structured facts/classification, 120 seconds for recovery/evidence). Cancellation is cooperative; an in-flight transport may take its configured timeout to unwind. Exhausted budgets become traced errors and cannot manufacture recovered evidence.

Structured facts use JSON responses with local Pydantic validation and at most one format repair within a shared 60-second deadline; a second malformed output stays unknown instead of entering the SDK's automatic tool-schema repair loop. Explicit smoking ranges and approximate quantities are detected before model calls. The source remains unchanged, including EXT02's approximate quantity and EXT11's range.

Independent clinical review is pending. `python scripts/prepare_independent_review.py` creates blank review sheets and source records. See [delivery status](docs/DELIVERY_STATUS.md), [video outline](docs/DEMO_SCRIPT.md), and [writeup draft](docs/WRITEUP_DRAFT.md).

## Individual tools

```bash
python -m src.tools.ctgov NCT07347678                                    # fetch criteria (add --fail ctgov_timeout)
python -m src.adapters.fhir_store --dir tests/fixtures/patients          # list patients
python -m src.adapters.fhir_store fixture-complete 18262-6 --dir tests/fixtures/patients   # LDL-C by LOINC
```

## Layout

```
run.py         weekly run for one trial
src/           config.py, pipeline.py, failures.py
  adapters/    FHIR store                         tools/      ClinicalTrials.gov, RxNav
  engine/      SAD adapter, generic engine, units, aggregation
  agent/       recovery, free-text interpretation, conflict explanation, I5 evidence, trace
  amendment/   diff, classify, re-screen          report/     log and impact report writers
trials/        compiled rule packs, SAD evaluator and core cases
data/          extended scenario set, criteria snapshots
eval/          evaluation
scripts/       extended-set generator, reviewer page builder
docs/demo/     reviewer page
tests/         offline tests (no model calls) and fixtures
```

## Known limitations

- Rule packs are compiled from the registry text by hand and reviewed; changed criteria are classified automatically, but the amended rules are prepared by a person.
- All data is synthetic. The screening records are designed, not full longitudinal charts; the extended set's labels are design intent, not independent clinical ground truth, so the evaluation measures behaviour against intent, not clinical accuracy.
- Supported: structured criteria on diagnoses, labs, medications and vital signs with thresholds and time windows, and free-text history for smoking and drug exposure. Not supported: imaging reports, oncology staging, lines of therapy, genomic criteria.
- The model is not perfectly stable at temperature 0 (for example it sometimes leaves a drug out); the terminology scan and the re-ask catch those cases, and anything still unsettled goes to the CRC.
- The pipeline's versioned `src/engine/sad_validation_policy.json` enforces finite numeric fasting duration >=6 hours for LDL/TG. Booleans and malformed values return unknown. No sponsor-approved upper duration cutoff is available; extremely long finite durations still need independent review. The standalone frozen evaluator remains unchanged.
- Method validation currently covers LDL only, using explicit synthetic method strings matched to the original code (direct vs calculated). Missing, unsupported or conflicting method representations return unknown. These strings are a demo allowlist, not clinically validated laboratory method codes; other labs need an approved per-lab policy before adding checks.
- Recovery accepts only a system-qualified, one-hop equivalence allowlist rooted in the criterion, and revalidates the actual bound patient/encounter record. The `drop_codes` injection now uses generic LDL 2089-1 with the original direct method. EXT43's frozen calculated-code/direct-method conflict remains unknown for independent review. Frozen data and design labels were not rewritten to improve scores.
- The committed reviewer HTML and its metrics describe the earlier run, before these boundary fixes. Re-run evaluation before presenting them as current; EXT11's design label and the old recovered-code case need independent review.

## Data and privacy

Synthetic patients only (Synthea demographics; designed screening records). No PHI or PII. External services: ClinicalTrials.gov API v2 and NLM RxNav (public), Amazon Bedrock and Amazon S3.

## License

MIT

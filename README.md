# Trial Pre-Screening Agent

AWS Community Day Bay Area 2026 hackathon — "Hand it off" challenge.

Takes over a clinical research coordinator's weekly clinical-trial pre-screening: reads synthetic patients (Synthea FHIR R4) and trial eligibility criteria (ClinicalTrials.gov), and writes the same pre-screening log the CRC writes by hand: likely eligible / pending / excluded / needs review, with evidence for every verdict. Deterministic code makes every comparison; an agent on Amazon Bedrock (Strands Agents + Amazon Nova 2 Lite) handles only the exceptions (empty queries, changed criteria). No patient is ever contacted. **Synthetic data only.**

**Primary trial:** [NCT07347678](https://clinicaltrials.gov/study/NCT07347678), SAD cohort (Ming's "T6"): 10 criteria plus age 18–65, 8 synthetic screening cases. Clinical rules, cases and the SAD evaluator are Ming's (`t6_sad_demo/`, see [its README](t6_sad_demo/README.md) and [her handoff notes](docs/MING_SUBMISSION.md)); the engineering pipeline in `src/` wraps her evaluator unchanged. NCT07610278 ("T2", hypertension with hypercholesterolemia) is kept as reference in `t2_backup/`.

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

**Without AWS** (rules only, recovery agent off):

```bash
python run.py --trial SAD --date 2026-10-09 --no-agent
```

**With AWS.** You need an AWS profile with Bedrock access to Amazon Nova 2 Lite in `us-west-2`. Credentials come from your local profile (`aws configure` or `aws sso login`); nothing secret goes in the repo. In `.env`, set **`AWS_PROFILE`** to that profile (the template says `default`), check `AWS_REGION` and `BEDROCK_MODEL_ID`, and set `S3_BUCKET` if you have one. Then:

```bash
python check_bedrock.py            # expect: response: bedrock ok
python run.py --trial SAD --date 2026-10-09
```

Open `out/prescreen_log_SAD_2026-10-09.md`. If Bedrock is unreachable, the run says so once and continues with rules only. The SAD run includes Ming's 8 cases plus 7 engineering-authored cases in `data/eng_cases/` (free text, boundaries, I5 evidence, material conflict; `--no-eng-cases` to leave them out). With `--no-agent` the result equals Ming's own evaluator (checked by `tests/test_sad.py`).

`tests/fixtures/` holds engineering's own sample data (four hand-written patients on NCT02178098, sample labels, a sample SAD amendment). None of it is a project trial or ground truth; see [tests/fixtures/README.md](tests/fixtures/README.md).

## Weekly run for a trial

```bash
python run.py --trial SAD --date 2026-10-09
```

`--trial SAD` evaluates Ming's rule pack `t6_sad_demo/rules/sad-1.0.0.json` on her cases with her evaluator (`t6_sad_demo/engine.py`), after checking every input against her SHA-256 manifests. Other trials use the generic engine: NCT ID in `TRIALS` in `src/config.py`, predicates in `data/predicates/trial_{T}.json`, patients in `data/patients/`.

Writes to `out/`:

- `prescreen_log_{trial}_{date}.md`: the CRC's log, four sections with key evidence (record ID, value, date), notes, and a per-patient detail with every criterion and its trace;
- `prescreen_log_{trial}_{date}.csv`: one row per patient and criterion, for evaluation;
- `trace_{trial}_{date}.jsonl`: every rule and model step; `run_{trial}_{date}.json`: run summary.

Logs are uploaded to `s3://$S3_BUCKET/logs/{trial}/{date}/` when `S3_BUCKET` is set. If the criteria cannot be fetched and the cached copy is older than 14 days, no log is written.

### How a verdict is made (SAD)

1. **Criteria** for NCT07347678 are fetched from ClinicalTrials.gov, cached, snapshotted with SHA-256 (and copied to S3).
2. **Cases** are loaded into one in-memory FHIR store shared by the evaluator, the failure switches and the agent.
3. **Engineering guards** run first and are traced as rules: unambiguous unit conversion (e.g. LDL mmol/L → mg/dL) and plausibility ranges (an LDL of 690 mg/dL becomes `unknown`, not "met").
4. **Ming's evaluator** decides each criterion: screening-encounter binding, fasting specimen, ULN from the reference range (ALT or AST > 1.5×ULN), questionnaire coverage windows for smoking and drug history; I5 is always left to the investigator.
5. **The agent** (Strands + Nova 2 Lite) handles what the rules cannot settle. The model reads and explains; code compares and decides:
   - *Empty query* → recovery agent: equivalent codes, then notes, then abstain; a found record goes back to Ming's evaluator by ID.
   - *Free-text history* (smoking, advanced therapies, lipid-lowering drugs) → the model extracts facts with quotes; quotes absent from the source are dropped; drug classes come from NLM **RxNav** (RxNorm/RxClass), not the model's memory; code applies Ming's thresholds and windows; where the protocol's definitions disagree (e.g. 4–5 cigarettes on weekend nights) the criterion stays unknown for the CRC.
   - *Conflicting results* → code re-runs Ming's evaluator per candidate to tell whether the choice matters; the model explains the difference and what to check, never picks one.
   - *I5 (investigator judgement)* → a tool-using evidence agent looks up liver and kidney labs, diagnoses and notes; lab flags come from reference ranges in code; cited records are verified; abnormal findings send the patient to review.
6. **Aggregation** follows Ming's rule: any clearly failed criterion → excluded, including an exclusion read from free text when its basis is firm (verified quote, code-applied threshold, drug class confirmed by RxNav; shown as "from free text" with the quote); then an unresolved conflict, an exclusion resting on the model alone, or flagged I5 evidence → needs review; then unknown → pending; else likely eligible. I5 is listed as "CRC to check".

### How a verdict is made (generic engine)

1. **Criteria** are fetched from the ClinicalTrials.gov API v2 (`src/tools/ctgov.py`), cached, and snapshotted with a SHA-256.
2. **Data** comes from a file-based FHIR adapter over Synthea bundles (`src/adapters/fhir_store.py`), with FHIR-style queries so a real FHIR server could replace it.
3. **The engine** (`src/engine/`) evaluates each predicate: thresholds, time windows, unit conversion with plausibility ranges, what a missing record means. Same input, same output; no model.
4. **The recovery agent** (`src/agent/agent.py`) takes only criteria left `unknown` because a query came back empty. It tries equivalent codes, then searches clinical notes, then abstains with an explanation. It hands records back to the engine by ID, never values; note text is never treated as a lab value. Fresh conversation per case, temperature 0, at most 6 tool calls.
5. **Aggregation** (`src/engine/aggregate.py`) applies fixed rules: any exclusion met → excluded; conflict → needs review; blocking unknown → pending (named data item); all inclusions met → likely eligible. Criteria that cannot be computed are listed for the CRC, never guessed.

Use `--no-agent` for a rules-only run.

## Amendment monitoring

Every run compares the fetched criteria with the previous snapshot (SHA-256). When they differ, the text is split into items and diffed; the model labels each changed item **substantive**, **wording** or **ambiguous** (case/spacing/punctuation-only changes are wording by rule; a model failure counts as ambiguous). Only substantive changes trigger a re-screen, using the amended predicate file `data/predicates/trial_{T}_v2.json`, which a person prepares and reviews (no automatic compilation). The result is `out/amendment_impact_{trial}_{date}.md`: what changed, how it was classified and why, and every patient whose status changes with the criterion and record behind it.

Demo on SAD with an engineering sample amendment (SAD LDL-C threshold 70 → 100, HbA1c line reworded; not Ming's v2):

```bash
python run.py --trial SAD --date 2026-10-09 --fail amendment_v2 \
  --v1-snapshot tests/fixtures/sad/NCT07347678_v1.txt \
  --v2-snapshot tests/fixtures/sad/NCT07347678_v2.txt \
  --v2-predicates tests/fixtures/sad/sad-1.0.1-sample.json
```

Expected: one substantive and one wording change; SAD01, SAD04 and SAD06 change status.

Demo on the engineering fixtures:

```bash
python run.py --trial SAMPLE --nct NCT02178098 --predicates tests/fixtures/sample_predicates.json \
  --patients tests/fixtures/patients --date 2026-10-09 --fail amendment_v2 \
  --v1-snapshot tests/fixtures/snapshots/NCT02178098_v1.txt \
  --v2-snapshot tests/fixtures/snapshots/NCT02178098_v2.txt \
  --v2-predicates tests/fixtures/sample_predicates_v2.json
```

## Failure injection (for demos)

Each failure path can be reproduced on demand with `--fail` (repeatable). Data failures alter the loaded records in memory only, and the log announces exactly what was altered.

| Switch | What it does | Expected behaviour |
|---|---|---|
| `ctgov_timeout` | ClinicalTrials.gov call times out | criteria served from cache, log stamped STALE (no log if cache > 14 days) |
| `drop_codes` | one patient's LDL-C recoded 18262-6 → 13457-7 | rule query empty → recovery agent finds it under the equivalent code → engine decides |
| `bad_units` | one patient's latest LDL-C in mmol/L, another's ×10 | first converted by rule; second rejected as implausible → `unknown` with reason |
| `amendment_v2` | a prepared amended criteria text stands in for the live fetch | changes classified; substantive → re-screen and impact report |
| `note_conflict` | (optional, not implemented) | |

On SAD the targets are SAD04 (`drop_codes`), SAD01 and SAD02 (`bad_units`) until Ming maps her injected cases (`DEFAULT_FAILURE_TARGETS` in `src/engine/sad_adapter.py`; override with `FAILURE_TARGETS` in `src/config.py`). Example: `python run.py --trial SAD --date 2026-10-09 --fail drop_codes`.

## Evaluation

One command runs the baseline and every failure switch, then scores the baseline against the labels:

```bash
python eval/evaluate.py --trial SAD --labels data/ground_truth/trial_SAD.csv   # once Ming delivers labels
```

On the fixtures (sample labels; the report says the numbers are not an evaluation):

```bash
python eval/evaluate.py --trial SAMPLE --labels tests/fixtures/sample_labels.csv \
  --flips tests/fixtures/sample_amendment_flips.txt --nct NCT02178098 \
  --predicates tests/fixtures/sample_predicates.json --patients tests/fixtures/patients --date 2026-10-09 \
  --v1-snapshot tests/fixtures/snapshots/NCT02178098_v1.txt \
  --v2-snapshot tests/fixtures/snapshots/NCT02178098_v2.txt \
  --v2-predicates tests/fixtures/sample_predicates_v2.json
```

Labels are a CSV `patient_id,criterion_id,expected` with one row per computable criterion (`met` / `not_met`) and one `PATIENT` row per patient (`eligible` / `not_eligible`). Planted amendment flips go in `data/ground_truth/trial_{T}_amendment_flips.txt`, one patient ID per line. The report (`out/eval/{T}/eval_report_{T}_{date}.md`) covers wrongful exclusions, patient-level sensitivity, criterion accuracy, abstention, evidence and trace coverage, recovery rate, amendment recall and failure paths, and lists every disagreement for error attribution. `--reuse` scores existing runs without re-running.

## Individual tools

```bash
python -m src.tools.ctgov NCT02178098                                   # fetch criteria (add --fail ctgov_timeout)
python -m src.adapters.fhir_store --dir tests/fixtures/patients         # list patients
python -m src.adapters.fhir_store fixture-complete 18262-6 --dir tests/fixtures/patients   # LDL-C by LOINC
python -m src.engine.evaluate --predicates tests/fixtures/sample_predicates.json \
  --patients tests/fixtures/patients --date 2026-10-09                  # per-criterion verdicts, no aggregation
```

## Layout

```
run.py       weekly run for one trial
src/         config.py, pipeline.py, failures.py
  adapters/  file-based FHIR store            tools/      ClinicalTrials.gov fetch
  engine/    evaluate, units, aggregate       agent/      recovery agent, trace
  amendment/ diff, classify, re-screen        report/     log and impact report writers
eval/        evaluation against ground-truth labels
data/        patients/, predicates/, mappings/, snapshots/, ground_truth/  (trial data)
tests/       offline tests and fixtures
```

## Status

- [x] T1 infrastructure: scaffold, Bedrock check (Amazon Nova 2 Lite)
- [x] T3 FHIR file adapter · T4 ClinicalTrials.gov tool · T5 engine · T6 aggregation and log
- [x] T7 recovery agent · T8 trace · T9 failure switches (`note_conflict` optional, not done)
- [x] T10 amendment monitoring and re-screen · T11 evaluation script
- [x] SAD (NCT07347678) end to end through Ming's evaluator, with agent, switches and amendment demo
- [ ] Ground-truth labels, a real amendment (v2) and more cases from Ming; evaluation numbers wait for labels
- [ ] T12 demo video, submission

## License

MIT

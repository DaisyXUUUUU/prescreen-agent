# Trial Pre-Screening Agent

AWS Community Day Bay Area 2026 hackathon — "Hand it off" challenge.

## Ming's T6 SAD materials

Data handoff: [delivery locations and integration gaps](docs/DATA_DELIVERY.md), [file inventory](docs/data_inventory.json). These describe local materials; they do not indicate an upload or completed T6 integration.

The local T6 / NCT07347678 SAD demonstration and T2 reference materials are described in [MING_DEMO.md](MING_DEMO.md). See [Ming handoff status](docs/MING_HANDOFF.md) for the confirmed rule review and integration boundary. These materials currently run with `python t6_sad_demo/run.py`; they have not yet been adapted to the `src/` engine or the root `run.py` command below. The local trial labels T6/T2 are distinct from engineering task numbers T1–T12.

Takes over a clinical research coordinator's weekly clinical-trial pre-screening: reads synthetic patients (Synthea FHIR R4) and trial eligibility criteria (ClinicalTrials.gov), and writes the same pre-screening log the CRC writes by hand: likely eligible / pending / excluded / needs review, with evidence for every verdict. A deterministic engine makes every comparison; an agent on Amazon Bedrock (Strands Agents + Amazon Nova 2 Lite) handles only the exceptions (empty queries, changed criteria). No patient is ever contacted. **Synthetic data only.**

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
python run.py --trial SAMPLE --nct NCT02178098 --predicates tests/fixtures/sample_predicates.json \
  --patients tests/fixtures/patients --date 2026-10-09 --no-agent
```

**With AWS.** You need an AWS profile with Bedrock access to Amazon Nova 2 Lite in `us-west-2`. Credentials come from your local profile (`aws configure` or `aws sso login`); nothing secret goes in the repo. In `.env`, set **`AWS_PROFILE`** to that profile (the template says `default`), and check `AWS_REGION` and `BEDROCK_MODEL_ID`. Then:

```bash
python check_bedrock.py            # expect: response: bedrock ok
python run.py --trial SAMPLE --nct NCT02178098 --predicates tests/fixtures/sample_predicates.json \
  --patients tests/fixtures/patients --date 2026-10-09
```

Open `out/prescreen_log_SAMPLE_2026-10-09.md`. If Bedrock is unreachable, the run says so once and continues with rules only.

The `tests/fixtures/` data is engineering's sample (four hand-written patients, sample predicates shaped like trial B). It is **not** trial B and not ground truth; see [tests/fixtures/README.md](tests/fixtures/README.md).

## Weekly run for a trial

Needs the trial's NCT ID in `TRIALS` in `src/config.py`, its predicates in `data/predicates/trial_{T}.json` and patients in `data/patients/`:

```bash
python run.py --trial B --date 2026-10-12
```

Writes to `out/`:

- `prescreen_log_{trial}_{date}.md`: the CRC's log, four sections with key evidence (record ID, value, date), notes, and a per-patient detail with every criterion and its trace;
- `prescreen_log_{trial}_{date}.csv`: one row per patient and criterion, for evaluation;
- `trace_{trial}_{date}.jsonl`: every rule and model step; `run_{trial}_{date}.json`: run summary.

Logs are uploaded to `s3://$S3_BUCKET/logs/{trial}/{date}/` when `S3_BUCKET` is set. If the criteria cannot be fetched and the cached copy is older than 14 days, no log is written.

### How a verdict is made

1. **Criteria** are fetched from the ClinicalTrials.gov API v2 (`src/tools/ctgov.py`), cached, and snapshotted with a SHA-256.
2. **Data** comes from a file-based FHIR adapter over Synthea bundles (`src/adapters/fhir_store.py`), with FHIR-style queries so a real FHIR server could replace it.
3. **The engine** (`src/engine/`) evaluates each predicate: thresholds, time windows, unit conversion with plausibility ranges, what a missing record means. Same input, same output; no model.
4. **The recovery agent** (`src/agent/agent.py`) takes only criteria left `unknown` because a query came back empty. It tries equivalent codes, then searches clinical notes, then abstains with an explanation. It hands records back to the engine by ID, never values; note text is never treated as a lab value. Fresh conversation per case, temperature 0, at most 6 tool calls.
5. **Aggregation** (`src/engine/aggregate.py`) applies fixed rules: any exclusion met → excluded; conflict → needs review; blocking unknown → pending (named data item); all inclusions met → likely eligible. Criteria that cannot be computed are listed for the CRC, never guessed.

Use `--no-agent` for a rules-only run.

## Amendment monitoring

Every run compares the fetched criteria with the previous snapshot (SHA-256). When they differ, the text is split into items and diffed; the model labels each changed item **substantive**, **wording** or **ambiguous** (case/spacing/punctuation-only changes are wording by rule; a model failure counts as ambiguous). Only substantive changes trigger a re-screen, using the amended predicate file `data/predicates/trial_{T}_v2.json`, which a person prepares and reviews (no automatic compilation). The result is `out/amendment_impact_{trial}_{date}.md`: what changed, how it was classified and why, and every patient whose status changes with the criterion and record behind it.

Demo on the fixtures:

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
| `drop_codes` | one patient's LDL-C recoded 18262-1 → 13457-7 | rule query empty → recovery agent finds it under the equivalent code → engine decides |
| `bad_units` | one patient's latest LDL-C in mmol/L, another's ×10 | first converted by rule; second rejected as implausible → `unknown` with reason |
| `amendment_v2` | a prepared amended criteria text stands in for the live fetch | changes classified; substantive → re-screen and impact report |
| `note_conflict` | (optional, not implemented) | |

Target patients: `FAILURE_TARGETS` in `src/config.py`, otherwise the first patients with an LDL-C record. Add the fixture arguments from the quick start to try them, e.g. `... --date 2026-10-09 --fail drop_codes`.

## Evaluation

One command runs the baseline and every failure switch, then scores the baseline against the labels:

```bash
python eval/evaluate.py --trial B --labels data/ground_truth/trial_B.csv
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
python -m src.adapters.fhir_store fixture-complete 18262-1 --dir tests/fixtures/patients   # LDL-C by LOINC
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
- [ ] Trial B data (predicates, patients, labels) pending; everything above is verified on the fixtures
- [ ] T12 demo video, submission

## License

MIT

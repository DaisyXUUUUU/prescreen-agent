# Trial Pre-Screening Agent

AWS Community Day Bay Area 2026 hackathon — "Hand it off" challenge.

Takes over a clinical research coordinator's weekly clinical-trial pre-screening: reads synthetic patients (Synthea FHIR R4) and trial eligibility criteria (ClinicalTrials.gov), and writes the same pre-screening log the CRC writes by hand: likely eligible / pending / excluded / needs review, with evidence for every verdict. A deterministic engine makes every comparison; an agent on Amazon Bedrock (Strands + Nova 2 Lite) handles only the exceptions (empty queries, changed criteria). No patient is ever contacted. **Synthetic data only.**

## Setup

Requires Python 3.11+ and an AWS account with Bedrock access to Amazon Nova 2 Lite (`us.amazon.nova-2-lite-v1:0`).

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then edit AWS_REGION, BEDROCK_MODEL_ID, S3_BUCKET
```

AWS credentials come from your local profile (`aws configure` or `aws sso login`); nothing secret goes in the repo.

Check that Bedrock works:

```bash
python check_bedrock.py
```

## Run

```bash
python run.py --trial B
```

_(not implemented yet: lands with T5/T6)_

Fetch a trial's eligibility criteria from ClinicalTrials.gov (caches to `cache/ctgov/`, snapshots to `data/snapshots/{nct}/{date}.txt`, and to S3 when `S3_BUCKET` is set):

```bash
python -m src.tools.ctgov NCT02178098                       # live
python -m src.tools.ctgov NCT02178098 --fail ctgov_timeout  # simulated outage -> "stale" from cache
```

Query the local FHIR store (Synthea bundles in `data/patients/`; `--dir` points elsewhere):

```bash
python -m src.adapters.fhir_store --dir tests/fixtures/patients                            # list patients
python -m src.adapters.fhir_store fixture-complete 18262-1 --dir tests/fixtures/patients   # LDL-C by LOINC
```

Evaluate predicates for every patient (engine only, no aggregation yet):

```bash
python -m src.engine.evaluate --predicates tests/fixtures/sample_predicates.json --patients tests/fixtures/patients --date 2026-10-09
```

Tests: `python -m pytest tests/`

## Layout

```
data/        patients/, predicates/, mappings/, snapshots/, ground_truth/
src/         adapters/ (FHIR file store), tools/ (ctgov), engine/, report/, agent/, amendment/, config.py
eval/        evaluation against ground-truth labels
tests/
```

## Status

- [x] T1 infrastructure: scaffold, Bedrock check (Amazon Nova 2 Lite)
- [x] T4 ctgov tool (tested on placeholder NCT02178098; real trial B/G IDs pending)
- [x] T3 FHIR file adapter (tested on 3 hand-written fixture bundles; real Synthea data pending)
- [x] T5 engine (tested on fixtures and sample predicates; trial B predicates pending)
- [ ] T6 log · T7–T9 agent/trace/failures · T10 amendments · T11 eval

## License

MIT

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
python run.py --trial B --date 2026-10-12
python run.py --trial B --fail ctgov_timeout   # criteria served from cache, log stamped STALE
```

Writes `out/prescreen_log_{trial}_{date}.md` (for the CRC: likely eligible / pending / excluded / needs review, with evidence and trace per patient) and a `.csv` with one row per patient and criterion (for evaluation). Uploads both to `s3://$S3_BUCKET/logs/{trial}/{date}/` when `S3_BUCKET` is set. If the criteria cannot be fetched and the cache is older than 14 days, no log is written.

Queries that come back empty and leave a criterion `unknown` go to a recovery agent (Strands Agents + Amazon Nova 2 Lite on Bedrock): it tries equivalent codes, then searches clinical notes, then abstains with an explanation. Records it finds go back to the deterministic engine, which makes every comparison; note text is never treated as a lab value. Every step is traced in the log and in `out/trace_{trial}_{date}.jsonl`. Use `--no-agent` for a rules-only run.

Until trial B's data arrives, run on the fixtures:

```bash
python run.py --trial SAMPLE --nct NCT02178098 --predicates tests/fixtures/sample_predicates.json --patients tests/fixtures/patients --date 2026-10-09
```

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
- [x] T6 aggregation and log (end to end on fixtures)
- [x] T7 recovery agent, T8 trace (live-tested on fixtures)
- [ ] T9 failures · T10 amendments · T11 eval

## License

MIT

# I5: FHIR evidence retrieval and human judgement

> Translated from Ming's Chinese original on 2026-10-11. State as of 2026-10-09. A first version of this retrieval has since been implemented in `src/agent/evidence.py` (I5 stays manual); see the [root README](../README.md).

Updated 2026-10-09. Scope: T6 / NCT07347678 / SAD.

Status: the user has authorized read-only evidence retrieval and organization within the patient's record; code not yet implemented. This file describes the next step, not a completed run, and does not modify the frozen `sad-1.0.0.json`.

## Decision boundary

Text: No clinically significant abnormalities of hepatic or renal function.

The agent finds, organizes and delivers evidence; a person decides whether a clinically significant hepatic or renal abnormality exists. Automated I5 stays `unknown`, `manual=true`; finding normal results, finding no abnormality, or E1 not triggering never makes I5 met automatically. I5 remains a criterion that needs human judgement and does not count as automatically decidable just because retrieval is automated.

## What to retrieve

- `Observation`: liver- and kidney-related tests, keeping result, unit, reference range, abnormal flag, date and any available trend.
- `Condition`: liver- and kidney-related diagnoses with their clinical status and onset or recorded time.
- `DiagnosticReport`, `DocumentReference`: relevant reports or clinician notes the source actually provides and can be read; say so explicitly when absent or unreadable.

This is the candidate search scope, not additional inclusion or exclusion criteria. Ming needs to confirm concepts/codes, time ranges, test methods and sufficiency requirements. No new clinical thresholds may be invented and no fixed rule such as "normal tests pass" may be introduced.

Each search is bound to the patient ID, trial / rule version and screening time; record the dataset used, resource types, time range, filters, search time, number of results, failures and incomplete parts. Historical evidence keeps its original date and status and is not automatically read as the status at screening; records after screening cannot count as evidence known at that time.

## Tools and LLM division of work

FHIR read tools fetch the actual records with values, dates, units and resource references; both local files and a future FHIR server must keep the source. The LLM may choose among the permitted retrieval tools and write a summary; every fact in the summary must point back to evidence a tool returned. Record and report contents are data to analyse, not instructions to follow.

Read-only search never modifies patient records. A successful search with no results, an unavailable resource, a tool failure and a partly completed search must be told apart. No record must never be read as no history; no result may be made up; no contradicting evidence may be hidden.

## Proposed evidence pack

The following are data requirements to implement, not fields the current output already promises:

- Patient, trial, I5, rule version, screening time, evidence-pack version.
- For each item: resource reference and field location, text or value, unit, reference range, date and source; recorded facts kept apart from the agent's summary.
- Search scope and tool execution record, including what was not found, inaccessible or failed.
- Missing information, conflicting candidate results, outdated records and questions needing human confirmation.
- The automated conclusion fixed at `unknown` and marked for human review; evidence-pack completion recorded separately.

The human conclusion can be "met / not met / more information needed", stored with reasons, reviewer, review time and the evidence-pack and rule versions it relied on. Human review records are stored separately and do not overwrite the automated log; nothing unreviewed may be shown as human-confirmed or as complete eligibility.

## Current data and implementation gaps

`engine.py` currently returns only the manual-review reason for I5, with empty evidence; the 8 cases in `outputs/` have no I5 evidence packs. `data/cases/` reuses only Synthea demographics; the rest are designed screening records. `data/raw/` keeps the original charts but is not yet connected or reconciled with the study records; whether a resource exists there must actually be checked. The two unreconciled data sets must not be claimed to be a complete, conflict-free history.

The rule semantics remain a human judgement; this update does not change the frozen rules, cases, evaluator or generated results. Implementation status and outputs will be updated once retrieval exists.

## Division of work and acceptance

1. Ming confirms retrieval concepts, time ranges, fields and human-review requirements, and independently labels the evidence expected to be found.
2. Engineering implements patient-scoped retrieval, the evidence pack and separate review records; first on synthetic data, with the longitudinal data source reconciled.
3. Tests cover evidence present, no matching evidence, conflicts, partial failure / inaccessibility, the wrong patient and post-screening records. Check that source references resolve, dates and values are preserved, and missing data and failures are explicit.
4. In all of these scenarios I5 stays `unknown` before human review; normal ALT/AST or an empty search never turns into a pass.
5. Evidence coverage and correctness are evaluated separately; technical test or retrieval success rates are not reported as I5 clinical-judgement accuracy.

# SAD rule pack and evaluator, v1.0.0

The frozen rule pack, core screening cases and deterministic evaluator for the SAD cohort. The screening pipeline wraps this evaluator unchanged and adds the agent; see the [root README](../../README.md).

The primary trial is [NCT07347678](https://clinicaltrials.gov/study/NCT07347678); this implementation supports the SAD cohort only. POC input is rejected so that SAD thresholds are never applied to it by mistake.

2026-10-09: clinical review confirmed that the trial text and the compiled rules are consistent. That confirmation covers the semantics of the SAD rules. It does not cover the FHIR mapping, independent case labels, full-protocol requirements or clinical accuracy; the frozen files were not rewritten.

## Done

1. Saved the official registry snapshot, froze the 10 criteria, plus the age 18–65 metadata constraint.
2. Fixed Synthea 3.3.0, seed/clinician seed 20261009, reference/end date 2026-10-09, and regenerated 8 base patients aged 18–65.
3. Kept each patient's birth date and other Patient demographics, and independently designed BMI / fasting lipids / Lp(a) / liver enzymes / ULN / HbA1c and a time-bounded screening interview, producing 8 FHIR R4 study records.
4. Implemented a local FHIR retrieval adapter and a deterministic SAD evaluator that output the 10 criteria plus age, evidence fields / resource references, retrieval trace and an exception queue.
5. Tests for boundaries, missing data, conflicts, units, date windows, the error queue and protection of the original files.

## Data boundaries

SAD02's original smoking records were checked separately: both records inside the window are Ex-smoker, which does not directly conflict with the synthetic interview answer "no smoking in the window"; the whole-window status was not inferred from them and the case was not changed. Evidence and limits: [SAD02 review](SAD02_REVIEW.md).

`data/raw/` keeps the complete, unmodified Synthea output; `data/cases/` are trial-specific synthetic records that reuse only the Patient demographics, with everything else designed by the author. They **do not contain or reconcile the full longitudinal history**, and they are not "eligible patients" obtained by editing real histories. A negative drug history rests on an explicit answer in the synthetic interview and its look-back coverage; "no drug found in the original chart" is never treated as "not taking it".

These data verify software boundaries and evidence traceability. They do not estimate recruitment rates, real-world data coverage or clinical performance. No clinical judgement about healthy volunteers is confirmed automatically, and nobody may be called confirmed healthy / enrollable.

## Fixed rules and demo conventions

SAD uses LDL ≥70 mg/dL and Lp(a) ≥25 nmol/L; BMI 18–35 inclusive; TG <400; HbA1c ≥6.5 excludes; ALT or AST >1.5× their own ULN excludes. Lp(a) code 43583-4 was checked against the [LOINC](https://loinc.org/43583-4) molar-concentration definition, with no fixed conversion to mg/dL.

Calendar-month and 30-day windows are computed separately; including both window ends is an explicit demo policy. Smoking is evaluated automatically only for an explicit interview of no smoking through the whole window, or of current continuous smoking; unclear or intermittent patterns become unknown. The real screening workflow needs confirmation from the full protocol.

I5 "no clinically significant hepatic or renal abnormality" always stays for human review: normal ALT/AST cannot automatically show that it is met. Missing records and conflicting results are marked pending / review respectively. Any clearly failed inclusion or triggered exclusion gives fails_evaluated_criteria, with the manual items still kept.

E1 uses OR logic: if either the ALT or the AST branch has valid evidence, without unresolved conflict, that it exceeds its own 1.5×ULN, E1 is `met`. A missing or conflicting other branch does not overturn that independently established result, but its evidence and conflict flag are kept, and the patient's computed result is `fails_evaluated_criteria` with the manual items still to handle. If the only branch suspected of being high has an unresolved conflict itself, it cannot settle E1; with no valid high branch and the other branch unresolved, E1 is `unknown`.

## FHIR mapping review: open items (2026-10-09)

The user confirmed that the text and the rule semantics agree; the following are operational definitions and implementation gaps raised afterwards. They are not fixed and are not closed by that confirmation.

### Fasting duration: minimum 6 hours confirmed, not yet implemented

`Reader.observation()` currently only checks that the linked specimen belongs to the patient, that the duration unit is `h` and that the value is above 0; there is no minimum fasting duration, plausible upper bound or full type / finite-value check. A record that passes the current check cannot be described as meeting a clinical fasting requirement: 0.5 hours and 9999 hours may both pass, and adding only a lower bound does not exclude absurdly large values.

On 2026-10-09 the user set the minimum fasting duration at ≥6 hours (6 included) for I2 LDL and I4 TG. The public text gives no number of hours, so this is recorded as a user-confirmed demo policy pending sponsor / full-protocol confirmation, not as a requirement of the text. The earlier open item on the minimum is resolved; the plausibility upper bound and its handling are still to be defined. The policy is to go into a new version of the configuration rather than only into a Python constant. Insufficient fasting evidence should return `unknown` and must not exclude the patient. This record does not change the current evaluator, which still checks only > 0.

Tests to prepare: missing, 0, negative, 0.5 h, just below / equal to / just above the lower bound, non-numeric, boolean, non-finite, absurdly large, wrong unit and a specimen belonging to another patient. Boundary tests can use 5.99 / 6 / 6.01 hours; the expected handling of absurd values needs the plausibility policy.

### Test method: documentation and code disagree; scope to be defined

The frozen rules' `demo_policies` say "missing fasting/method/ULN ... return unknown", but the current evaluator reads no Observation `method`. In the current cases only LDL has `method.text`; the other relevant labs have none. It cannot be claimed that a method check is performed, nor should every lab be required to have a method without a decision.

To be confirmed per lab: which ones must state a method, the acceptable representation and content, and how missing / unknown / unsupported methods are handled. A non-empty method.text does not mean the method requirement is met; the synthetic LDL note is not an independent method validation. The check is then implemented, or narrows and describes the requirement precisely in a new version; the frozen 1.0.0 and its hashes must not be rewritten.

Tests to prepare: labs that need and do not need a method; missing / blank / acceptable / unsupported methods. If cases need methods added, they must be clearly new synthetic data, not presented as taken from the original charts.

### OR semantics: defined, targeted regression tests still to add

Current tests cover "one side high, other side missing its ULN". Still to cover explicitly: "valid high ALT + conflicting AST results" and the symmetric case: E1 is `met`, the patient's computed result fails, `conflict=true` and the conflicting evidence is kept. Also test a suspected-high branch that is only conflicting while the other side is normal: E1 stays `unknown`. These are logic and evidence-retention tests and do not replace the I5 human judgement.

## I5: automated evidence retrieval, human decision (authorized, not yet implemented)

The agent may search, read-only, the specified patient's FHIR record for liver- and kidney-related tests, diagnoses and reports, and organize the evidence, gaps, conflicts and search coverage for a person to judge I5. FHIR tools return actual records, values, dates and references; the LLM may choose tools and write a summary, but must not invent missing results or decide on its own what is "clinically significant". Finding no abnormality does not mean there is none; E1 not being triggered does not show I5 is met.

The automated I5 result stays `status=unknown`, `manual=true`, separately from whether the evidence search succeeded. The human conclusion, reasons, reviewer, time and the evidence version used are stored separately and never overwrite the original automated log. Delivering an evidence pack does not mean the clinical review is done.

`engine.py` currently returns only the manual-review reason for I5, with empty evidence; the existing 8 outputs have no retrieval results. Longitudinal retrieval also needs `data/raw/` connected and reconciled with the study records; the two must not be stitched into a "complete history" without reconciliation. Scope, data conventions, division of work and tests: [I5 evidence retrieval and human review](I5_EVIDENCE_REVIEW.md).

## Re-running

From the project root:

```bash
python trials/nct07347678_sad/run.py
python trials/nct07347678_sad/test_demo.py
```

`run.py` first verifies the hashes of the rules, the source record and the input cases. `prepare.py` is for first-time preparation only and refuses to overwrite the frozen specification; changing a definition means creating a new version.

Command and environment used to generate the base patients:

```bash
java -jar tools/synthea-3.3.0/synthea-with-dependencies.jar -p 8 -s 20261009 -cs 20261009 -r 20261009 -e 20261009 -a 18-65 -c trials/nct07347678_sad/data/synthea.properties Massachusetts
```

Needs Java 11 and the Synthea jar. If raw data already exists, do not write to the same output directory (duplicate patients would mix in); reproduce in a fresh working copy / version directory.

## Current results and limits

8 cases, 88 evaluations in total (80 criteria + 8 age checks): computed part passes 2, clearly fails 4, missing data pending 1, conflict review 1. All 8 still carry the manual I5 item; the number of cases with complete eligibility confirmed is 0.

17 technical test methods (including several boundary / case sub-tests) pass; the 8 study bundles parse with the FHIR R4 model. This does not mean all US Core constraints, real-server integration or clinical validity are verified. The core cases have no independent clinical ground truth, so this evaluator reports no accuracy.

`outputs/` contains the JSON log, exception queue, summary, Markdown and HTML reports. Run on its own, this evaluator is a local deterministic loop. The screening pipeline adds the model-driven agent, AWS delivery and amendment re-screening around it while keeping the deterministic calculations and the human-exception boundaries.

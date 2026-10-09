# Trial Pre-Screening Agent: Project Brief

**Current implementation (2026-10-09).** Primary demo: NCT07347678, SAD cohort (T6). Secondary: NCT07610278 (T2), retained as a reference specification. T7 is archived. The T6 local deterministic workflow runs on eight deliberately constructed synthetic study records derived from Synthea demographics; full original histories are retained separately and have not been reconciled. See [README.md](README.md) for runnable commands and evidence-linked outputs. LLM agent orchestration, AWS delivery, independent clinical labels and amendment re-screening remain outstanding. The following sections describe the intended full project, not completed implementation.

Entry for the Agentic AI Hackathon, AWS Community Day Bay Area 2026 ("Hand it off" challenge).
Team: Ming (clinical data, AI application, evaluation) and Daisy (engineering).

Items in [brackets] are placeholders to fill in.

---

## 1. Task

**One line.** An agent that takes over a clinical research coordinator's weekly trial pre-screening, and automatically re-screens previously excluded patients whenever a trial's eligibility criteria are amended.

**The person.** A clinical research coordinator (CRC) at an academic cardiovascular trial site. Every week she reviews the charts of upcoming clinic patients against the eligibility criteria of two to three actively enrolling trials and writes a pre-screening log: who is likely eligible, who is excluded and by which criterion, and who cannot be assessed because data is missing.

**What it costs today.** About [X] hours per week for [N] patients. When a protocol amendment changes the criteria, patients excluded earlier may now qualify, but nobody has time to go back and re-check them.

**What the agent delivers.** The agent automatically completes and delivers the pre-screening records for computable criteria, plus an amendment impact report and an explicit exception queue. The CRC only handles the listed exceptions; routine records do not require manual reconstruction, rewriting, or delivery. Decisive verdicts carry supporting patient-record evidence; unresolved verdicts carry the available evidence and a specific explanation of what is missing or conflicting. No patient is contacted.

**Handoff boundary.** The completed deliverable is the pre-screening log, not an enrollment decision. Each exception identifies the patient and trial, affected criterion, reason, available evidence or query provenance, and the exact item requiring human review. Missing data, conflicting evidence, unsupported criteria, and unresolved tool failures are listed explicitly. Exceptions do not silently invalidate completed records or require the CRC to redo the entire batch. Passing computable criteria does not establish eligibility for criteria that still require human judgment.

**Scope.** T6 / NCT07347678 SAD as primary demo, T2 / NCT07610278 as secondary. Eight synthetic study cases currently run through T6; expansion to about 50 remains planned. T6 involves healthy-volunteer recruitment, so the demo role includes a clinical research center's screening coordinator. Criteria that need human judgment are labeled and left to the CRC by design.

**I5 evidence-assisted review (authorized, not implemented).** For T6 I5, the agent may perform patient-scoped, read-only FHIR searches and assemble hepatic/renal evidence for the human reviewer. Retrieval and evidence delivery are automated responsibilities; determining clinical significance remains a human responsibility. The current evaluator returns I5 as unknown with no evidence. The planned workflow and acceptance checks are documented in [I5 evidence review](t6_sad_demo/I5_EVIDENCE_REVIEW.md).

---

## 2. Goals

1. The CRC would accept the automatically completed and delivered log without redoing routine records: supported verdicts carry evidence, uncertain cases are flagged rather than guessed, and human work is limited to explicitly listed exceptions.
2. Never silently exclude an eligible patient. When data is missing or conflicting, answer "unknown" before answering "excluded".
3. Detect criteria amendments and report exactly which patients change status and why.
4. Behave sensibly when a tool fails, returns garbage, or disagrees with the model.
5. Run end to end from a clean clone using only public and synthetic data.

**Non-goals.** Contacting patients, making enrollment decisions, handling real patient data, covering every criterion type.

---

## 3. How it works (steps)

1. **Compile criteria.** Fetch each trial's eligibility text from the ClinicalTrials.gov API. The model converts each criterion into a structured predicate (concept, codes, operator, threshold, unit, time window, computable or not). Compiled once per trial version and cached.
2. **Retrieve patient data.** Query a FHIR server for only the resources each predicate needs. The model maps concepts to SNOMED, LOINC, and RxNorm codes and reads free-text notes.
3. **Evaluate.** Deterministic code performs every numeric and temporal comparison. Each criterion returns `met`, `not_met`, or `unknown`. Decisive verdicts include supporting record pointers; `unknown` includes available evidence, the missing or conflicting item, and query scope or tool-failure provenance where no supporting record exists.

   For I5, search tools retrieve actual observations, diagnoses and available reports/notes; the model may organize them but cannot invent values, infer absence from missing records, or decide clinical significance. Return `unknown` with manual review required even when the evidence package is complete. Preserve human conclusions, reasons, reviewer identity, review time and evidence version separately from the automatic log. Passing E1 does not establish I5. Search concepts and time ranges must be reviewed by Ming; they are retrieval aids, not additional eligibility thresholds.
4. **Aggregate.** Any unconflicted required inclusion not_met or exclusion met means fails_evaluated_criteria. Otherwise, unresolved conflicts mean review, missing computable evidence means pending, and all evaluated computable requirements passing means passes_evaluated_criteria. Keep manual-review requirements and conflicts as separate flags, including when an independent decisive failure exists. A pass of the evaluated subset does not establish complete trial eligibility.

   T6 E1 is an OR: a valid, unconflicted ALT or AST branch exceeding its own 1.5×ULN suffices for `met`, even when the other branch is unresolved. Retain that other branch's evidence and conflict flag without reversing the independently established failure. A conflicted candidate result cannot itself serve as the decisive branch. If no branch establishes failure and another remains unresolved, E1 is `unknown`.
5. **Monitor amendments and re-screen.** Snapshot each trial's criteria weekly and diff against the previous snapshot. Recompile only changed criteria, re-evaluate affected verdicts for all previously screened patients, and report status changes.
6. **Deliver.** Automatically write the completed pre-screening log, amendment impact report, and explicit exception queue to S3 and notify the CRC by email. Confirm that the artifacts were stored and record notification status; failed delivery is reported as incomplete rather than successful. The CRC receives the finished records and reviews only the named exceptions, without manually assembling or sending the output.

### Data contracts

```json
// Predicate
{"criterion_id": "", "trial_id": "", "type": "inclusion|exclusion",
 "concept": "", "codes": [], "operator": "", "value": null, "unit": "",
 "window_days": null, "computable": true, "source_text": ""}

// Verdict
{"patient_id": "", "criterion_id": "", "status": "met|not_met|unknown",
 "evidence": [{"resource_id": "", "value": "", "date": ""}], "note": ""}
```

### Failure paths

| Case | Trigger | Agent behavior |
|---|---|---|
| Tool fails | ClinicalTrials.gov API times out | Fall back to cached snapshot, stamp the log with its age, refuse to issue a log if too old |
| Tool returns garbage | Lab value in the wrong unit or outside a plausible range | Convert when unambiguous, otherwise mark the criterion `unknown` |
| Tool disagrees with model | Note reads "no prior MI", problem list contains an MI code | List both pieces of evidence, route the patient to review |
| Ambiguous amendment | Wording changes without a clear change in meaning | Flag for confirmation, do not re-screen on a guess |

### AWS services

Amazon Bedrock (model and agent reasoning), AWS Lambda (tool execution), Amazon S3 (snapshots and logs), Amazon EventBridge (weekly schedule), Amazon SES (notification).

---

## 4. Hackathon requirements

### The three checked requirements

| Requirement | How this project meets it |
|---|---|
| Name the person: a real role, and what the task costs them | Clinical research coordinator; [X] hours per week, from an interview |
| Call at least one tool you didn't build; the agent must act | ClinicalTrials.gov API, FHIR server, RxNorm API; the agent writes and delivers the log |
| Show the failure path in the demo video | Four cases in the table above |

### Standing rules

- At least two AWS services, one of them an AI service.
- No production data, PHI, or PII. Synthetic patients only.
- Work started on or after September 29.
- Not a chatbot, not a document Q&A app, not a pipeline where a human does the last step.

### Submission, due October 11, 11:59 AM PT

- [ ] Public GitHub repo, MIT or Apache 2.0, README that runs, opens while logged out
- [ ] 3-minute demo video (YouTube unlisted or Loom), including the failure path
- [ ] One-page writeup using the template from Slack
- [ ] Team roster with names and emails; no changes after the deadline

### Timeline

- October 12: judges score all submissions asynchronously.
- October 13: top 8 demo live, in person, 5 minutes hard stop, and are re-scored.
- Final score: 40% async, 60% live.

---

## 5. Evaluation criteria

### Judging rubric

| Criterion | Weight | What we show |
|---|---|---|
| Technical depth | 30% | Compiled predicates, deterministic evaluator, three-valued logic, amendment diff and partial re-screen, failure handling |
| Real-world usefulness | 25% | Named CRC, measured weekly cost, output in the format she already uses |
| Responsible AI | 20% | Synthetic data, supporting evidence or explicit uncertainty provenance, abstention over guessing, descriptive subgroup error analysis, path to production |
| Demo and communication | 15% | Person, happy path, failure path, amendment re-screen, results, in three minutes |
| Completeness | 10% | Clean-clone README run, all four submission items |

### Our own acceptance metrics

Measured against independently hand-labeled ground truth ([20-50] patients, computable criteria only). Patient-level metrics use patient-trial pairs, so screening one patient against multiple trials does not blur the denominator. "Eligible" below means satisfying the evaluated computable criteria, not confirmed trial eligibility or an enrollment decision.

The test set must include both determinable positive and negative cases, as well as missing-data and conflicting-evidence cases. Freeze labels and the expected determinable subset before evaluation. Ming prepares the reference labels from source criteria and patient evidence independently of agent outputs; Daisy cross-checks them, and unresolved labeling disagreements are documented before scoring. Model-generated labels are not the sole ground truth, and the same model must not both generate answers and serve as their sole judge.

| Metric | Definition | Target |
|---|---|---|
| Wrongful exclusions | Ground-truth eligible patient-trial pairs incorrectly marked excluded | 0 on the frozen test set; report count / all ground-truth eligible pairs, not a population-level guarantee |
| Automatic decision coverage | Pairs receiving a definite result on computable criteria / all evaluated pairs; also report the fraction of the frozen determinable subset receiving a definite result | Report both; determinable-subset target [>= 80%], to confirm before evaluation |
| Definite-decision accuracy | Correct definite patient-level results / all definite patient-level results | [>= 95%]; zero definite results is a failed gate, not 100% accuracy |
| Patient-level sensitivity | Ground-truth eligible pairs marked "likely eligible" / all ground-truth eligible pairs; pending and review do not count as successful positive determinations | [>= 95%] on the frozen determinable subset; also report the full-set result separately |
| Human review rate | Pairs with at least one exception requiring CRC action / all evaluated pairs, including non-computable criteria | Report count, percentage, and reasons; distinguish unavoidable exceptions from avoidable abstentions |
| Criterion-level accuracy | Correct `met` / `not_met` results / all ground-truth determinable criterion evaluations; `unknown` on a determinable criterion counts as a miss | [>= 90%] |
| Abstention rate | Share of criterion verdicts returned as `unknown` | Reported overall and on the determinable subset; justified case by case |
| Evidence coverage | Decisive criterion verdicts with resolvable supporting record pointers / all decisive criterion verdicts | 100% |
| Evidence correctness | Decisive criterion verdicts whose cited records actually support the conclusion for the correct patient, concept, value, and time window / all decisive criterion verdicts | 100% on the frozen test set |
| Uncertainty provenance | Unresolved verdicts with a specific reason, available evidence, and query scope, missing fields, or tool-failure details / all unresolved verdicts | 100%; no fabricated record pointer required for absent data |
| Amendment recall | Planted status changes detected after a simulated amendment | 100% |
| Failure paths | Cases reproducible with a config switch | 4 of 4 |

Acceptance requires the coverage, definite-decision accuracy, sensitivity, and wrongful-exclusion gates together. Returning `pending` or `review` for every patient cannot pass. Report every metric with its numerator and denominator; an empty denominator is N/A, never an automatic pass. Bracketed thresholds are proposed targets to confirm and freeze before evaluation, not measured results.

Report CRC review time and the number of routine records requiring correction when a user acceptance session is available; otherwise label the handoff acceptance as unvalidated. A completed handoff requires stored artifacts and a recorded notification outcome, not merely generated text.

Every error is assigned to one of four causes: criteria compilation, concept mapping, data problem, engine defect. Subgroup results on a small synthetic cohort are descriptive error analysis only; they do not establish demographic fairness or real-world clinical performance.

For I5, assess evidence retrieval separately from automatic criterion accuracy: verify patient identity, source pointers, values/dates, missing-data and conflict disclosure, and coverage against independently annotated available records. Include evidence-present, no-matching-evidence, conflicting-evidence and failed/partial-query cases. These checks do not validate automatic clinical-significance decisions; I5 remains a human decision. Complete evidence delivery is distinct from completed clinical review.

### Path to production (for the writeup)

1. Deployed inside the hospital's own AWS account under a BAA, using only HIPAA-eligible services.
2. One-way boundary: public knowledge flows in, patient data never leaves. External API calls carry trial IDs and drug names only.
3. The log is viewed inside an authenticated system, not sent by email, and stores record pointers instead of copied values.

# Trial Pre-Screening Agent: Project Brief

Entry for the Agentic AI Hackathon, AWS Community Day Bay Area 2026 ("Hand it off" challenge).
Team: Ming (clinical data, AI application, evaluation) and Daisy (engineering).

Version 2, updated October 8. Items in [brackets] are placeholders to fill in.

**Changes since version 1:** trials selected (section 1); new section separating agent decisions from deterministic computation (section 4); data contracts extended (section 5); retrieval recovery added as a failure path (section 6); supported scope and known limits stated (section 7); current status and remaining priorities added (section 10).

---

## 1. Task

**One line.** An agent that takes over a clinical research coordinator's weekly trial pre-screening, and automatically re-screens previously excluded patients whenever a trial's eligibility criteria are amended.

**The person.** A clinical research coordinator (CRC) at an academic cardiovascular trial site. Every week she reviews the charts of upcoming clinic patients against the eligibility criteria of the site's actively enrolling trials and writes a pre-screening log: who is likely eligible, who is excluded and by which criterion, and who cannot be assessed because data is missing.

**What it costs today.** About [X] hours per week for [N] patients. When a protocol amendment changes the criteria, patients excluded earlier may now qualify, but nobody has time to go back and re-check them.

**What the agent delivers.** The same pre-screening log the CRC writes by hand, plus an amendment impact report, with every verdict traceable to a patient record and every non-trivial decision explained. No patient is contacted.

**Trials in scope.**

| Trial | NCT ID | Criteria as posted | Predicates | C / P / N | Role |
|---|---|---|---|---|---|
| B: hypertension with hypercholesterolemia, ages 18-75 | [NCT] | 9 | 15 | 9 / 4 / 2 | First trial, outpatient setting, built end to end first |
| G: LDL-C lowering after ischemic stroke or TIA | [NCT] | 11 | 12 | 8 / 3 / 1 | Second trial, adds before/after-event logic |
| F: Lp(a) early-phase study | [NCT] | 10 | not compiled | | Optional, only if time allows |

C = computable; P = computable under a stated assumption; N = not computable, left to the CRC by design.

Eleven recruiting trials were reviewed. Selection rule: at least 5 criteria with an explicit number or time window, and no more than one third of criteria requiring human judgment.

**Patients.** About 50 synthetic patients (Synthea), with hand-injected boundary values, missing labs, wrong units, conflicting notes, and patients whose status flips under a simulated amendment.

---

## 2. Goals

1. The CRC would accept the log without redoing it: every verdict carries evidence, and uncertain cases are flagged, not guessed.
2. Never silently exclude an eligible patient. When data is missing or conflicting, answer "unknown" before answering "excluded".
3. Detect criteria amendments and report exactly which patients change status and why.
4. Recover sensibly when a tool fails, returns garbage, returns nothing, or disagrees with the model, and say what was tried.
5. Run end to end from a clean clone using only public and synthetic data.

**Non-goals.** Contacting patients, making enrollment decisions, handling real patient data, covering every criterion type.

---

## 3. How it works (steps)

1. **Compile criteria.** Fetch each trial's eligibility text from the ClinicalTrials.gov API. Split each criterion into atomic predicates and fill in data source, codes, operator, threshold, unit, time window, time anchor, and what a missing record means. Compiled once per trial version and cached.
2. **Retrieve patient data.** Query a FHIR server for only the resources each predicate needs.
3. **Evaluate.** Deterministic code performs every numeric and temporal comparison. Each predicate returns `met`, `not_met`, or `unknown`, with a pointer to the supporting record.
4. **Aggregate.** Three-valued logic at patient level: any exclusion met means excluded; all computable criteria passed means likely eligible; a blocking unknown means pending with the missing item named; conflicting evidence means review.
5. **Monitor amendments and re-screen.** Snapshot each trial's criteria weekly and diff against the previous snapshot. Recompile only changed criteria, re-evaluate affected verdicts for all previously screened patients, and report status changes.
6. **Deliver.** Write the pre-screening log and the amendment impact report to S3 and notify the CRC by email.

Steps 2, 3, 4 and 6 are tools. Section 4 describes the layer that decides how to use them.

---

## 4. What the agent decides

Compiling and querying alone would be a pipeline. The agent is the layer that decides which tool to call next, what to do when a result cannot be trusted, and when to stop and hand a case to the CRC. These are the exceptions a CRC handles from experience, and the reason she would not trust a plain script.

| # | Decision | Made by | Build priority |
|---|---|---|---|
| 1 | Is this criterion computable, how should it be split, what does a missing record mean | Model, human-reviewed | See disclosure below |
| 2 | A query returned nothing: try an equivalent code, then the free-text notes, then abstain and state what was tried | Model, tool-use loop | **1** |
| 3 | A tool timed out or returned an implausible value | Fixed rule (cache fallback, unit conversion, range check) | Rule, already designed |
| 4 | Structured data and a clinical note disagree | Model: present both, route to review | **3**, needs injected notes |
| 5 | Criteria text changed: substantive amendment or wording only, re-screen or flag | Model | **2** |
| 6 | Issue a verdict or route the patient to the CRC | Fixed aggregation rule | Rule |

Every model decision writes one line to a `trace` (section 5), which appears in the log and is shown in the demo.

**Example, decision 2.** A triglyceride query returns no results. A pipeline records `unknown` and moves on. The agent retries with an equivalent LOINC code, then searches the notes, and only then records `unknown` with the note "two codes and notes searched, no value found; recommend a lipid panel".

**Disclosure on decision 1.** The predicates for trials B and G were compiled by hand and reviewed, and serve as the reference answer for the compilation prompt. If the prompt does not reproduce them reliably by submission, the writeup states that the predicates were human-reviewed, not fully automatic.

---

## 5. Data contracts

Core fields are unchanged from version 1. Fields marked `+` are optional extensions, null when absent. **Both teammates must agree to these before the engine depends on them.**

```json
// Predicate
{"criterion_id": "", "trial_id": "", "type": "inclusion|exclusion",
 "concept": "", "codes": [{"system": "", "code": "", "display": ""}],
 "operator": "", "value": null, "unit": "",
 "window_days": null, "computable": true, "source_text": "",
 "+grade": "C|P|N",
 "+resource": "Condition|Observation|MedicationRequest|AllergyIntolerance|Patient.birthDate",
 "+anchor": {"event": "screening_date|index_event", "direction": "before|after"},
 "+aggregation": "most_recent|mean_of_last_3|count_distinct_active_ingredients",
 "+absence_means": "met|not_met|unknown",
 "+assumption": ""}

// Verdict
{"patient_id": "", "criterion_id": "", "status": "met|not_met|unknown",
 "evidence": [{"resource_id": "", "value": "", "date": ""}], "note": "",
 "+blocking": true,
 "+trace": [{"step": "", "tool": "", "result": "", "decision": ""}]}
```

Notes:

- **Operators supported:** numeric comparison (`<`, `<=`, `>`, `>=`), `exists`, `no_change`, `active_for_days`.
- **`anchor`** expresses "before or after the stroke". Trial G defines its index event as the most recent matching stroke or TIA.
- **`absence_means`** fixes what to return when no record exists. A missing diagnosis is `not_met`; a missing lab is `unknown`; a missing intolerance record is `unknown`, because unrecorded does not mean absent. For "no or up to 2 antihypertensives", no record is `met`.
- **`blocking: false`** marks an unknown that should not hold the patient in "pending" (for example, intolerance history in trial G). The patient stays "likely eligible" with a "confirm at visit" note.

### Three layers

| Layer | Contents | Specific to | Changes for a new trial |
|---|---|---|---|
| Schema and engine | Fields, operators, aggregation rules | Nothing | No |
| Predicates | Thresholds, codes, time windows | One trial, one version | Yes, by recompiling |
| Local mapping | Code accommodations, pre-screening proxies | One data source | Yes, per site |

Open item: some local accommodations are currently written into the predicates (accepting "Hyperlipidemia" for hypercholesterolemia and unspecified "Stroke" for ischemic stroke, because Synthea records those). They belong in a separate mapping table.

---

## 6. Failure paths

| Case | Trigger | Agent behavior | Type |
|---|---|---|---|
| Tool fails | ClinicalTrials.gov API times out | Fall back to cached snapshot, stamp the log with its age, refuse to issue a log if too old | Rule |
| Tool returns garbage | Lab value in the wrong unit or outside a plausible range | Convert when unambiguous, otherwise mark the criterion `unknown` | Rule |
| Tool returns nothing | Query finds no record for a concept that should exist | Retry with an equivalent code, search notes, then abstain and state what was tried | Model |
| Tool disagrees with model | Note reads "no prior MI", problem list contains an MI code | List both pieces of evidence, route the patient to review | Model |
| Ambiguous amendment | Wording changes without a clear change in meaning | Flag for confirmation, do not re-screen on a guess | Model |

Each case is reproducible with a config switch. The 3-minute video shows at least: one rule case, "tool returns nothing", and one of the last two.

---

## 7. Supported scope and known limits

**Supported.** Structured criteria built on diagnoses, labs, medications, and vital signs, with thresholds, time windows, and before/after-event logic. This covers most outpatient cardiometabolic trials.

**Not supported in this version.**

- Multiples of the upper limit of normal (needs the lab's reference range).
- Composite scores (for example, the Dutch Lipid Clinic Network score).
- OR logic across different concepts. Predicates are a flat list: inclusions are joined by AND. OR within one concept is handled by listing several codes.
- Cohort-dependent thresholds.
- Information found only in imaging reports or free text; oncology staging, lines of therapy, genomic variants.

**Open verification items.**

- All codes in the predicate files were proposed by hand and are not yet verified against a terminology service or the dataset.
- Medication criteria use ATC class codes, while Synthea uses RxNorm. Classes must be expanded to RxNorm ingredients (RxClass API) before matching, or medication predicates will all return `unknown`.
- Confirm that the synthetic data contains ALT, and inject stroke-within-30-days patients for trial G, since few or none will occur naturally in 50 patients.

---

## 8. AWS services

Amazon Bedrock (model and agent reasoning), AWS Lambda (tool execution), Amazon S3 (snapshots and logs), Amazon EventBridge (weekly schedule), Amazon SES (notification).

---

## 9. Hackathon requirements

### The three checked requirements

| Requirement | How this project meets it |
|---|---|
| Name the person: a real role, and what the task costs them | Clinical research coordinator; [X] hours per week, from an interview |
| Call at least one tool you didn't build; the agent must act | ClinicalTrials.gov API, FHIR server, RxNorm/RxClass API; the agent retries, re-screens, and delivers the log |
| Show the failure path in the demo video | Five cases in section 6 |

### Standing rules

- At least two AWS services, one of them an AI service.
- No production data, PHI, or PII. Synthetic patients only.
- Work started on or after September 29.
- Not a chatbot, not a document Q&A app, not a pipeline where a human does the last step. Section 4 is our answer to the last point.

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

## 10. Status and remaining priorities

### Status as of October 8

| Item | Status |
|---|---|
| Trials selected | Done (B, G); NCT IDs and recruiting status to confirm |
| Predicates for B and G | Compiled by hand, structure validated; codes unverified |
| Compilation prompt | Not started |
| Synthetic patients and injected cases | [confirm] |
| Ground-truth labels | [confirm] |
| FHIR server, tools, evaluation engine | [confirm with Daisy] |
| Agent orchestration and `trace` | [confirm with Daisy] |
| Amendment monitoring | [confirm with Daisy] |
| CRC interview | [confirm] |

### Order of work

1. **One trial end to end.** The engine runs trial B's predicates on the patients and writes a log. Nothing else matters until this works.
2. Agree the contract extensions in section 5; expand ATC classes to RxNorm.
3. Decision 2, retrieval recovery, with `trace`.
4. Decision 5, amendment judgment and re-screen.
5. Evaluation numbers on at least 20 labeled patients.
6. Decision 4, conflicting evidence, only if notes are injected in time.
7. Trial G, then video, writeup, and a README run from a clean clone.

### What to cut if behind

In order: trial F, eligibility rates by demographic group, email delivery (keep S3 only), decision 4, trial G.

Never cut: two failure paths including one model decision, a README that runs, evaluation numbers.

---

## 11. Evaluation criteria

### Judging rubric

| Criterion | Weight | What we show |
|---|---|---|
| Technical depth | 30% | Compiled predicates with time anchors, deterministic evaluator, three-valued logic, retrieval recovery, amendment diff and partial re-screen |
| Real-world usefulness | 25% | Named CRC, measured weekly cost, output in the format she already uses |
| Responsible AI | 20% | Synthetic data, evidence and trace for every verdict, abstention over guessing, stated limits, path to production |
| Demo and communication | 15% | Person, happy path, failure path with visible agent reasoning, amendment re-screen, results, in three minutes |
| Completeness | 10% | Clean-clone README run, all four submission items |

### Our own acceptance metrics

Measured against hand-labeled ground truth ([20-50] patients, computable criteria only). Targets are initial values, not measured results; replace them with actual numbers after evaluation.

| Metric | Definition | Target |
|---|---|---|
| Wrongful exclusions | Patients marked excluded who are truly eligible | 0 |
| Patient-level sensitivity | Truly eligible patients placed in "likely eligible" or "pending" | [>= 95%] |
| Criterion-level accuracy | Agreement with ground truth on `met` / `not_met` | [>= 90%] |
| Abstention rate | Share of verdicts returned as `unknown` | Reported; justified case by case |
| Evidence coverage | Verdicts with a valid record pointer | 100% |
| Trace coverage | Model decisions with a recorded reason | 100% |
| Recovery rate | Planted wrong-code cases resolved by retry | Reported |
| Amendment recall | Planted status changes detected after a simulated amendment | 100% |
| Failure paths | Cases reproducible with a config switch | 5 of 5 |

Every error is assigned to one of four causes: criteria compilation, concept mapping, data problem, engine defect.

### Path to production (for the writeup)

1. Deployed inside the hospital's own AWS account under a BAA, using only HIPAA-eligible services.
2. One-way boundary: public knowledge flows in, patient data never leaves. External API calls carry trial IDs and drug names only.
3. The log is viewed inside an authenticated system, not sent by email, and stores record pointers instead of copied values.

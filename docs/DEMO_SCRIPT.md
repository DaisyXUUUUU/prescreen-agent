# Three-minute demo video script

Recorded from the reviewer page (`docs/demo/index.html`, hosted copy linked in the README), built from a completed evaluation run. Nothing waits on a model call during recording.
Narration is about 420 words (about 150 words per minute). **画面** = what is on screen; **Say** = narration.

---

## 0:00–0:20 · The job we hand off

**画面** Top of the page: title, run chips (trial NCT07347678 SAD cohort, screening date 2026-10-09, 58 synthetic patients, execution mode `agent`).

**Say**
> Every week a clinical research coordinator checks upcoming patients against a trial's eligibility criteria and writes a pre-screening log: who is likely eligible, who is pending, who is excluded, and who needs a human decision. We handed that job to an agent. Everything here is synthetic data, and no patient is ever contacted.

## 0:20–0:45 · Inputs and the split between code and model

**画面** Scroll to "From criteria to a coordinator's log", then "Eligibility criteria" (point at the "Settled by" column). Then "What the agent does that rules cannot": the two panels "The model does" / "Code does".

**Say**
> Criteria come live from ClinicalTrials.gov and are snapshotted with a SHA-256 hash. Patients are FHIR R4 records. The rule here is simple: code decides, the model reads. Every threshold, unit and time window is plain Python. The model, Amazon Nova 2 Lite on Bedrock through Strands Agents, only handles what rules cannot read, and every decision it touches leaves a trace.

## 0:45–1:40 · Four things rules cannot do

**画面** The showcase cards, one at a time. Point at the trace box under each card.

**Say** (card 1, Missing result)
> One: an LDL result is filed under a different but equivalent code, so the rule query comes back empty. The agent may only try codes from the criterion's allowlist. The record goes back to the evaluator, which re-checks the method and the value.

**Say** (card 2, Free text and drug knowledge)
> Two: a patient writes "a twice-yearly cholesterol injection called Leqvio". The model extracts the drug and the date. NLM RxNav, not the model, says it is inclisiran, and code applies the 12-month window. Because the model did the reading, the patient goes to the coordinator for review instead of being excluded automatically.

**Say** (card 3, Fuzzy boundary)
> Three: "four or five cigarettes on a Friday or Saturday night". That is a range. We never turn a range into a point estimate. It stays unknown, with the quote, for the coordinator.

**Say** (cards 4–5, Conflict and I5)
> Four: two conflicting LDL results are tested both ways; when the choice changes the outcome, the patient goes to review with an explanation. And for the investigator-judgement criterion, the agent gathers kidney evidence that the rules alone would have missed.

## 1:40–2:10 · The log the coordinator receives

**画面** "The coordinator's pre-screening log": the four section buttons (Likely eligible 20, Pending 14, Excluded 14, Needs review 10, each with its "rules only" count). Click one patient row in the matrix (e.g. EXT04) to open the detail panel with quote, evidence and trace.

**Say**
> This is the output: the same four-section log a coordinator writes by hand. Every verdict links to the record, the value and the date behind it. Excluded patients were excluded by structured data and code only. Anything the model interpreted is routed to a person.

## 2:10–2:35 · When the protocol changes

**画面** "When the criteria change": the changes table (LDL threshold 70 → 100 classified substantive), then the flips sentence.

**Say**
> When the criteria change, we compare snapshots, diff them item by item, and classify each change. A changed number or operator is substantive by rule; the model only judges pure wording. Then we re-screen everyone with the amended rules and list exactly who changes status: 39 of 58 patients in this run.

## 2:35–3:00 · Failures and honest limits

**画面** "Baseline and four mandatory failure scenarios" table, then "Measured against the scenarios' design intent" metrics table.

**Say**
> We also inject failures: the registry timing out, codes going missing, wrong units, and an amendment. All four are handled; the system falls back, abstains, or routes to a person, and never guesses. Zero wrongful exclusions, one hundred percent sensitivity, and all four failure paths pass. Wherever the system made a call, it agreed with every label. On seven criteria it abstained and handed the call to a person. These labels describe the design intent of our test cases; independent clinical review is still pending. The agent prepares the log; the coordinator and investigator still make every enrollment decision.

---

## Recording checklist

- Open the page at full width in light mode. Record at 1080p.
- Pre-scroll once so the matrix and traces are already rendered.
- Keep the cursor on what is being named; no waiting for model calls.
- Total target 2:50–3:00. Trim the card 4–5 narration first if over time.

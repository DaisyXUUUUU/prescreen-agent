# SAD02 smoking evidence review

Review date: 2026-10-09. Conclusion: keep the LDL=69 scenario and the current interview; do not change it to current or intermittent smoking.

## Scope and source

Located SAD02's original Synthea synthetic chart (not a real patient) through `data/case_manifest.json`:

`data/raw/fhir/Celsa248_Zemlak964_717a30c9-adba-2d70-f1ba-28dcf0c048c4.json`

The original file's SHA-256 matches the manifest: `983852613d587612ae580fa42d2035d1b937dba371c3605aeccc0f6bfc266c16`.

Patient ID: `717a30c9-adba-2d70-f1ba-28dcf0c048c4`. Screening time: 2026-10-09 09:00 (-04:00); start of the three-month window: 2026-07-09.

## What the record shows

Two LOINC `72166-2` (Tobacco smoking status) records inside the window, both SNOMED `8517006`, text `Ex-smoker (finding)`:

- 2026-08-23 22:12:53 (-04:00), Observation `71cf2011-686c-f837-6763-80349b0fa4db`.
- 2026-09-06 22:12:53 (-04:00), Observation `a80ef3ac-2518-bb03-bcf1-7304d2a81682`.

The chart also has a hypertension lifestyle CarePlan from 2006-04-30, `82f343bc-b820-1977-c3da-5359897e2c68`, which includes smoking-cessation education. Education is not direct evidence of current smoking or of an amount smoked.

The presence of a smoking-status Observation, or a search hit for smoking/tobacco, is not enough to conclude that smoking happened in the window; valueCodeableConcept and the date must be read. These records do not support changing the interview to current or intermittent, and they give no cigarettes per day or per week.

## Relation to the interview

The current `current_smoker=false`, `smoking_pattern=none_in_window` and 0 per day / 0 per week are designed synthetic screening-interview answers, not values derived from the original record. `none_in_window` does not mean never smoked, so it does not directly contradict the Ex-smoker records inside the window.

Two Ex-smoker records cannot on their own prove continuous non-smoking for the whole window; keeping the interview does not mean the original chart has verified its completeness. The two records must not be presented as complete confirmation for the whole window.

## Scenario and later test boundaries

SAD02 keeps I2 (LDL=69, below 70) as its only clear failure; E3 is not triggered with the current synthetic interview input, and I5 stays for human review. The current evaluator does not yet use these longitudinal smoking records; this review does not claim structured-history merging or conflict detection is implemented.

When structured history is connected, test that "Ex-smoker record + no smoking in the window per interview" does not produce a false conflict merely because a smoking code appears; build a separate scenario for a conflict between current smoking and a denial in the interview, not reusing SAD02. The rest of the full original chart has not been reviewed in this round.

This review does not change the case, interview, manifest, rules or evaluator.

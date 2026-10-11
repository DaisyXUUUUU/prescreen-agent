# Extended SAD scenario set

Synthetic, and not clinical ground truth. Generated deterministically by `scripts/build_extended_cases.py` from core case SAD01 (structure, encounter, specimen, questionnaire), with fresh IDs and one deliberate change per case, to cover what the 8 core cases do not: every criterion on both sides of its threshold, exact boundaries, unit conversion, missing data, free text written in different ways, I5 evidence and conflicts. Free text was written by hand, not by a model, so the agent is not graded on its own phrasing.

`design_labels.csv` holds the design intent, written before any run: the target criterion's expected status (when unambiguous) and the patient's expected eligibility (when the intended category is excluded or likely eligible). It measures whether the pipeline does what the cases were built to test.

| Case | Purpose | Intended category | Target | Intended status |
|---|---|---|---|---|
| EXT01 | smoking described only in free text, intermittent weekend smoking (boundary of 'regular') | pending | E3 | - |
| EXT02 | smoking described only in free text, clearly daily | excluded | E3 | met |
| EXT03 | lipid-lowering history in free text: statin stopped before the window, OTC red yeast rice inside it | pending | E5 | - |
| EXT04 | advanced-therapy history in free text naming a brand (Leqvio = inclisiran, an siRNA) | excluded | E4 | met |
| EXT05 | lipid-lowering history in free text, negative with OTC supplements | likely_eligible | E5 | not_met |
| EXT06 | I5 evidence: normal ALT/AST but reduced kidney function, CKD diagnosis and hepatic steatosis note | needs_review | I5 | - |
| EXT07 | two conflicting LDL results that straddle the 70 mg/dL threshold | needs_review | I2 | - |
| EXT08 | smoking free text: about a pack a week, most days | excluded | E3 | met |
| EXT09 | smoking free text: quit years ago | likely_eligible | E3 | not_met |
| EXT10 | smoking free text: vapes nicotine daily, no cigarettes (protocol counts cigarettes) | ambiguous | E3 | - |
| EXT11 | smoking free text: one or two every day (<=2/day but >10/week) | excluded | E3 | met |
| EXT12 | smoking free text: one cigar at a wedding | likely_eligible | E3 | not_met |
| EXT13 | drug free text: brand statin stopped inside the 30-day window | excluded | E5 | met |
| EXT14 | drug free text: ezetimibe ongoing | excluded | E5 | met |
| EXT15 | drug free text: statin stopped well before the window | likely_eligible | E5 | not_met |
| EXT16 | drug free text: 'a cholesterol tablet', name unknown | pending | E5 | - |
| EXT17 | drug free text: Repatha (evolocumab, a PCSK9 antibody) inside the window | excluded | E5 | met |
| EXT18 | drug free text: gene therapy trial in 2023 (outside 12 months) | likely_eligible | E4 | not_met |
| EXT19 | drug free text: Kynamro (mipomersen, an ASO) until January 2026 | excluded | E4 | met |
| EXT20 | drug free text: explicitly none | likely_eligible | E4 | not_met |
| EXT21 | clean pass, LDL 120 | likely_eligible | I2 | met |
| EXT22 | clean pass, LDL 85 | likely_eligible | I2 | met |
| EXT23 | clean pass, age 30, LDL 140 | likely_eligible | I2 | met |
| EXT24 | BMI 36 (above 35) | excluded | I1 | not_met |
| EXT25 | BMI 17.5 (below 18) | excluded | I1 | not_met |
| EXT26 | BMI exactly 35 (inclusive) | likely_eligible | I1 | met |
| EXT27 | BMI exactly 18 (inclusive) | likely_eligible | I1 | met |
| EXT28 | LDL 1.81 mmol/L = protocol's own equivalent of 70 mg/dL | likely_eligible | I2 | met |
| EXT29 | LDL 1.80 mmol/L, just below | excluded | I2 | not_met |
| EXT30 | Lp(a) exactly 25 nmol/L | likely_eligible | I3 | met |
| EXT31 | Lp(a) 24 nmol/L | excluded | I3 | not_met |
| EXT32 | TG exactly 400 mg/dL (must be <400) | excluded | I4 | not_met |
| EXT33 | TG 4.5 mmol/L = 398.6 mg/dL | likely_eligible | I4 | met |
| EXT34 | ALT 61 U/L > 1.5 x ULN 40 | excluded | E1 | met |
| EXT35 | AST 55 U/L > 1.5 x ULN 35 | excluded | E1 | met |
| EXT36 | HbA1c exactly 6.5 % | excluded | E2 | met |
| EXT37 | HbA1c 6.4 % | likely_eligible | E2 | not_met |
| EXT38 | age 66 at screening | excluded | AGE | not_met |
| EXT39 | turns 65 on the screening day (inclusive) | likely_eligible | AGE | met |
| EXT40 | age 17 | excluded | AGE | not_met |
| EXT41 | fasting state not recorded for the lipid specimen | pending | I2 | - |
| EXT42 | HbA1c not drawn | pending | E2 | - |
| EXT43 | LDL recorded only as calculated LDL (13457-7), 95 mg/dL | likely_eligible | I2 | met |
| EXT44 | LDL 900 mg/dL (data-entry error) | pending | I2 | - |
| EXT45 | I5: total bilirubin 3.1 mg/dL (range 0.1-1.2) | needs_review | I5 | - |
| EXT46 | I5: cirrhosis on the problem list | needs_review | I5 | - |
| EXT47 | I5: normal creatinine and eGFR present (should not be flagged) | likely_eligible | I5 | - |
| EXT48 | two TG results 150 and 410 (choice changes I4) | needs_review | I4 | - |
| EXT49 | two BMI results 22 and 24 (choice does not matter) | likely_eligible | I1 | met |
| EXT50 | two ALT results 25 and 30 (choice does not matter) | likely_eligible | E1 | not_met |

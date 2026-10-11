# Engineering-authored SAD cases

Not Ming's data and not clinical ground truth. Generated deterministically by `scripts/build_eng_cases.py` from Ming's case SAD01 (structure, encounter, specimen, questionnaire), with fresh IDs and one deliberate change per case, to cover what her 8 cases do not: every criterion on both sides of its threshold, exact boundaries, unit conversion, missing data, free text written in different ways, I5 evidence and conflicts. Free text was written by hand, not by a model, so the agent is not graded on its own phrasing.

`design_labels.csv` holds the design intent, written before any run: the target criterion's expected status (when unambiguous) and the patient's expected eligibility (when the intended category is excluded or likely eligible). It measures whether the pipeline does what the cases were built to test.

| Case | Purpose | Intended category | Target | Intended status |
|---|---|---|---|---|
| ENG01 | smoking described only in free text, intermittent weekend smoking (boundary of 'regular') | pending | E3 | - |
| ENG02 | smoking described only in free text, clearly daily | excluded | E3 | met |
| ENG03 | lipid-lowering history in free text: statin stopped before the window, OTC red yeast rice inside it | pending | E5 | - |
| ENG04 | advanced-therapy history in free text naming a brand (Leqvio = inclisiran, an siRNA) | excluded | E4 | met |
| ENG05 | lipid-lowering history in free text, negative with OTC supplements | likely_eligible | E5 | not_met |
| ENG06 | I5 evidence: normal ALT/AST but reduced kidney function, CKD diagnosis and hepatic steatosis note | needs_review | I5 | - |
| ENG07 | two conflicting LDL results that straddle the 70 mg/dL threshold | needs_review | I2 | - |
| ENG08 | smoking free text: about a pack a week, most days | excluded | E3 | met |
| ENG09 | smoking free text: quit years ago | likely_eligible | E3 | not_met |
| ENG10 | smoking free text: vapes nicotine daily, no cigarettes (protocol counts cigarettes) | ambiguous | E3 | - |
| ENG11 | smoking free text: one or two every day (<=2/day but >10/week) | excluded | E3 | met |
| ENG12 | smoking free text: one cigar at a wedding | likely_eligible | E3 | not_met |
| ENG13 | drug free text: brand statin stopped inside the 30-day window | excluded | E5 | met |
| ENG14 | drug free text: ezetimibe ongoing | excluded | E5 | met |
| ENG15 | drug free text: statin stopped well before the window | likely_eligible | E5 | not_met |
| ENG16 | drug free text: 'a cholesterol tablet', name unknown | pending | E5 | - |
| ENG17 | drug free text: Repatha (evolocumab, a PCSK9 antibody) inside the window | excluded | E5 | met |
| ENG18 | drug free text: gene therapy trial in 2023 (outside 12 months) | likely_eligible | E4 | not_met |
| ENG19 | drug free text: Kynamro (mipomersen, an ASO) until January 2026 | excluded | E4 | met |
| ENG20 | drug free text: explicitly none | likely_eligible | E4 | not_met |
| ENG21 | clean pass, LDL 120 | likely_eligible | I2 | met |
| ENG22 | clean pass, LDL 85 | likely_eligible | I2 | met |
| ENG23 | clean pass, age 30, LDL 140 | likely_eligible | I2 | met |
| ENG24 | BMI 36 (above 35) | excluded | I1 | not_met |
| ENG25 | BMI 17.5 (below 18) | excluded | I1 | not_met |
| ENG26 | BMI exactly 35 (inclusive) | likely_eligible | I1 | met |
| ENG27 | BMI exactly 18 (inclusive) | likely_eligible | I1 | met |
| ENG28 | LDL 1.81 mmol/L = protocol's own equivalent of 70 mg/dL | likely_eligible | I2 | met |
| ENG29 | LDL 1.80 mmol/L, just below | excluded | I2 | not_met |
| ENG30 | Lp(a) exactly 25 nmol/L | likely_eligible | I3 | met |
| ENG31 | Lp(a) 24 nmol/L | excluded | I3 | not_met |
| ENG32 | TG exactly 400 mg/dL (must be <400) | excluded | I4 | not_met |
| ENG33 | TG 4.5 mmol/L = 398.6 mg/dL | likely_eligible | I4 | met |
| ENG34 | ALT 61 U/L > 1.5 x ULN 40 | excluded | E1 | met |
| ENG35 | AST 55 U/L > 1.5 x ULN 35 | excluded | E1 | met |
| ENG36 | HbA1c exactly 6.5 % | excluded | E2 | met |
| ENG37 | HbA1c 6.4 % | likely_eligible | E2 | not_met |
| ENG38 | age 66 at screening | excluded | AGE | not_met |
| ENG39 | turns 65 on the screening day (inclusive) | likely_eligible | AGE | met |
| ENG40 | age 17 | excluded | AGE | not_met |
| ENG41 | fasting state not recorded for the lipid specimen | pending | I2 | - |
| ENG42 | HbA1c not drawn | pending | E2 | - |
| ENG43 | LDL recorded only as calculated LDL (13457-7), 95 mg/dL | likely_eligible | I2 | met |
| ENG44 | LDL 900 mg/dL (data-entry error) | pending | I2 | - |
| ENG45 | I5: total bilirubin 3.1 mg/dL (range 0.1-1.2) | needs_review | I5 | - |
| ENG46 | I5: cirrhosis on the problem list | needs_review | I5 | - |
| ENG47 | I5: normal creatinine and eGFR present (should not be flagged) | likely_eligible | I5 | - |
| ENG48 | two TG results 150 and 410 (choice changes I4) | needs_review | I4 | - |
| ENG49 | two BMI results 22 and 24 (choice does not matter) | likely_eligible | I1 | met |
| ENG50 | two ALT results 25 and 30 (choice does not matter) | likely_eligible | E1 | not_met |

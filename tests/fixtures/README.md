# Test fixtures

Test data for the generic engine. **None of it is a screened trial and none of it is ground truth.**

| File | What it is |
|---|---|
| `patients/*.json` | Four hand-written Synthea-style bundles (complete record, over the age limit, LDL only in a note, LDL under an alternative LOINC code) |
| `sample_predicates.json`, `sample_predicates_v2.json` | Sample predicates for a hypertension + hypercholesterolemia trial; v2 raises the LDL-C threshold 100 → 140 |
| `snapshots/NCT02178098_v{1,2}.txt` | Public ClinicalTrials.gov criteria text and a hand-edited amendment (one substantive, one wording change) |
| `sample_labels.csv`, `sample_amendment_flips.txt` | Sample labels to check that `eval/evaluate.py` runs. The numbers they produce are **not** an evaluation. |

Criteria with no knowable truth (triglycerides for the two patients without a TG result) are deliberately left unlabelled.

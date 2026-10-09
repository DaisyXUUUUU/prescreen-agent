# Test fixtures

Written by engineering to exercise the code while trial B's data is pending. **None of this is trial B and none of it is ground truth.**

| File | What it is |
|---|---|
| `patients/*.json` | Four hand-written Synthea-style bundles (complete record, over the age limit, LDL only in a note, LDL under an alternative LOINC code) |
| `sample_predicates.json`, `sample_predicates_v2.json` | Predicates shaped like trial B; v2 raises the LDL-C threshold 100 → 140 |
| `snapshots/NCT02178098_v{1,2}.txt` | Public ClinicalTrials.gov criteria text and a hand-edited amendment (one substantive, one wording change) |
| `sample_labels.csv`, `sample_amendment_flips.txt` | Sample labels to check that `eval/evaluate.py` runs. The numbers they produce are **not** an evaluation. Real labels come from Ming. |

Criteria with no knowable truth (triglycerides for the two patients without a TG result) are deliberately left unlabelled.

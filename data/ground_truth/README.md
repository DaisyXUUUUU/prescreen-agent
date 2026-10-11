# Eight-case SAD ground truth

The user designated `sad_confirmed_labels_v1.csv` as the project reference on 2026-10-11 and changed the minimum validation scope from 20 complete patients to **8 complete cases: SAD01-SAD08**. The 50 EXT cases remain supplementary regression scenarios, not a required independent-validation cohort.

The supplied CSV is preserved byte-for-byte: 96 rows (88 criterion labels including 8 manual I5 rows, plus 8 overall decisions). Its value column is still named `ai_draft_expected`; reviewer names/dates are absent. Acceptance as user-designated ground truth does not itself certify independent annotation provenance. No reviewer signatures or labels have been invented.

Run from the repository root:

```bash
python -m eval.sad_reference --log out/prescreen_log_SAD_2026-10-09.csv
```

This requires all eight complete cases, ignores EXT cases in a combined log, and reports mismatches rather than changing reference values. It exits 1 if any criterion or patient category differs. This exact-reference check is distinct from the older percentage-based design-label targets.

Overall labels map as follows: `passes_evaluated_criteria` -> `likely_eligible`, `fails_evaluated_criteria` -> `excluded`, `pending` -> `pending`, and `review` -> `needs_review`. Passing this evaluated subset is not full clinical eligibility; I5 remains manual.

The primary criterion comparison covers 80 computable results and counts an expected/actual `unknown` pair as agreement. A separate binary-reference comparison covers the 78 met/not_met labels and counts actual unknowns as disagreement. Manual I5 is checked separately in mismatch details. These denominators must not be confused with the 37 labelled criteria in the extended design-label evaluation.

Evidence paths inside the supplied CSV are relative to `trials/nct07347678_sad/`, not the repository root. The source caveats, including the SAD02 smoking-history discrepancy, remain part of the reference.

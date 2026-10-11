# Delivery and acceptance status

This file separates engineering evidence from human deliverables. It is not a completion certificate.

## Engineering changes

- UTF-8/LF snapshot bytes and SHA agree across platforms; atomic writes retry Windows sharing violations and clean up unique temporary files.
- Evaluation defaults to one concurrent scenario. Missing, failed or mismatched-mode runs are recorded in execution_status.json and make the command fail. Reuse never starts missing runs.
- --no-agent disables all Bedrock paths, including amendment classification. It still uses public APIs; it is not an all-network-off flag.
- One model preflight fixes the effective mode for both versions. An unavailable model makes both versions rules-only, and requested-agent evaluation rejects this downgrade.
- Unchanged criteria reuse v1 evidence interpretation over the same patient data; changed criteria are recomputed. Agent errors invalidate amendment attribution instead of producing a misleading flip count.
- SAD is a fixed-encounter replay: --date must equal each case's screening_at. New dates require new, reviewed input contexts.
- The drop_codes injection now uses generic LDL 2089-1 to preserve the recorded direct method. The deliberately inconsistent EXT43 source and its design label remain unchanged for independent review.
- Model invocations have turn budgets and cooperative cancellation timers. Structured facts are returned as JSON and validated locally with at most one format repair within the same 60-second deadline, avoiding the observed SDK tool-schema repair loop. Invalid responses remain traced errors.
- Explicit smoking ranges and approximate quantities are detected from source text before model interpretation. EXT02's approximate quantity, as well as EXT01/EXT11 ranges, remains unknown.
- Regression result: 239 tests and 23 subtests passed on Windows with its default encoding. The frozen evaluator's original-file check passed after restoring 8 manifest-referenced source records from the existing local demo, with matching SHA hashes. Those ignored raw originals are not included in a clean Git clone.

## Ground truth - eight required cases

On 2026-10-11 the user designated `data/ground_truth/sad_confirmed_labels_v1.csv` as ground truth and changed the minimum from 20 to **8 complete cases, SAD01-SAD08**. The supplied CSV is preserved: 80 computable criteria, 8 manual I5 entries and 8 overall conclusions. The 50 extended cases are supplementary regression cases, not part of this required cohort. Reviewer identity and date are absent, so independent annotation provenance is not certified.

Run `python -m eval.sad_reference --log out/prescreen_log_SAD_2026-10-09.csv`. This checks all eight cases and preserves unknown/pending/review distinctions. Any reference mismatch returns a nonzero exit code. This is separate from the legacy design-label percentage gates.

The existing verified baseline agrees on 79/80 computable criteria (98.75%) and 6/8 overall conclusions (75%). SAD07/I2 is expected unknown but returned met; SAD04 is expected likely_eligible but returned needs_review; SAD07 is expected needs_review but returned likely_eligible. These discrepancies remain unresolved; eight complete cases do not imply all results pass.

`python scripts/prepare_independent_review.py` optionally creates blank review sheets for these eight cases and refuses to overwrite filled sheets. It does not replace the confirmed CSV or manufacture reviewer sign-off.

## Submission material - pending

- A real CRC interview and measured weekly time cost. The repository's generic "hours per week" is not measured evidence.
- A recorded 3-minute video. Use DEMO_SCRIPT.md as a recording outline; it is not a video.
- The official Slack writeup template and a completed, reviewed writeup. WRITEUP_DRAFT.md is provisional and must not be called template-compliant without the official template.
- Team member names and emails supplied by the team; do not infer them from Git author metadata.
Repository accessibility was verified on 2026-10-11: GitHub reports public visibility and an anonymous request returned HTTP 200.

The second trial, Lambda, EventBridge and SES remain optional under TASKS; their absence is not counted as a mandatory failure here. The optional note_conflict switch is separate from the four mandatory failure switches.

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

## Independent review - pending

The user confirmed no independent labels or teammate review results exist yet. Run:

```powershell
python scripts/prepare_independent_review.py
```

This creates a blank annotation sheet for all 58 patients (580 computable criteria plus 58 patient conclusions), source records and criteria under out/independent-review. It does not manufacture truth labels. Require at least 20 complete patients with reviewer, evidence, date and rationale. Resolve EXT11's range and EXT43's method/code discrepancy before using their labels to judge correctness.

The generator refuses to overwrite filled review sheets. Keep unknown/undetermined annotations in the review record; only export adjudicated binary labels for scoring. Blank, unsupported and duplicate scoring labels are rejected.

## Submission material - pending

- A real CRC interview and measured weekly time cost. The repository's generic "hours per week" is not measured evidence.
- A recorded 3-minute video. Use DEMO_SCRIPT.md as a recording outline; it is not a video.
- The official Slack writeup template and a completed, reviewed writeup. WRITEUP_DRAFT.md is provisional and must not be called template-compliant without the official template.
- Team member names and emails supplied by the team; do not infer them from Git author metadata.
- Anonymous repository accessibility. Authenticated git access is insufficient; a logged-out HTTP 404 needs the owner to check visibility and the exact URL. No visibility change or public release has been performed.

The second trial, Lambda, EventBridge and SES remain optional under TASKS; their absence is not counted as a mandatory failure here. The optional note_conflict switch is separate from the four mandatory failure switches.

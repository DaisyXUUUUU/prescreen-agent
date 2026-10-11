# Record of integrating Ming's materials

> Translated from Ming's Chinese original on 2026-10-11. State as of 2026-10-09, before integration. Since then: the branch is merged into `main`, SAD runs through `src/engine/sad_adapter.py` (Ming's evaluator unchanged), aggregation follows her fail-first rule, and the I5 evidence retrieval has a first implementation. See the [root README](../README.md).

Date: 2026-10-09.

## Git integration

- Remote repository: https://github.com/DaisyXUUUUU/prescreen-agent
- Local working branch: `ming/t6-sad-integration`, based on remote `main` commit `1c0b8af606ce8a34a1c1b10fcc4e5fd8e44bb8f2`.
- The original engineering files were fetched; my local original README was saved as `MING_DEMO.md`. The root `PROJECT_BRIEF.md` is the trial-demo description maintained in this conversation, while `docs/PROJECT_BRIEF.md` keeps the remote engineering background; the two have not been merged into one specification.
- When this record was created, the new local materials had not been committed or pushed. The remote branch was not modified.

## Human confirmation

The user confirmed explicitly in this conversation: "the trial text and the compiled rules have been verified as consistent". This record covers the current T6 SAD version `1.0.0` and is not extended to T2, the FHIR mapping, a full-protocol check, case labels or system performance.

The frozen rules and manifest stay unchanged. Independent case ground truth is still to be done; the I5 evidence-retrieval authorization and the human-judgement boundary are in the [dedicated agreement](../t6_sad_demo/I5_EVIDENCE_REVIEW.md).

The later FHIR review raised two open items: fasting is checked only as a duration above 0, which needs the protocol or an explicit demo policy for the lower bound and outlier handling; the method requirement disagrees with the code and needs per-lab requirements before a version update. Confirming that the text and the rules agree does not resolve these operational definitions. E1's OR semantics were added: one side validly confirmed high is enough to trigger the exclusion; a conflict on the other side is kept but does not overturn the independently established result. Details and the tests still to add: [T6 review items](../t6_sad_demo/README.md#fhir-mapping-review-open-items-2026-10-09). This record only documents the review; the evaluator, frozen rules and cases were not modified.

## Entry points

- [Full data-delivery list and target directories](DATA_DELIVERY.md), [file-level hash inventory](data_inventory.json). Destinations distinguish materials deliverable now from run inputs still to be adapted; nothing has been uploaded.
- [Local demo entry](../MING_DEMO.md)
- [T6 notes](../t6_sad_demo/README.md), [rules](../t6_sad_demo/rules/sad-1.0.0.json), [input cases](../t6_sad_demo/data/cases/), [runner](../t6_sad_demo/run.py)
- [T2 reference](../t2_backup/README.md)
- Daisy's engineering: `src/`, root `run.py`, `tests/`, `eval/`.

In Ming's materials T6/T2 are trial numbers, not the engineering task numbers in `docs/TASKS.md`. T6 was not automatically renamed to the remote placeholder trial B.

## Current boundary and next steps

Connecting the Git repository does not mean T6 is connected to the engineering pipeline. T6's nested predicates, screening context, interview fields, manual items and aggregation policy have not been converted or validated against the `src/` input contract. Two entry points are kept for now, to avoid copying the rules straight into `data/predicates/` and running them by mistake.

Next: check the two rule schemas, FHIR references / codes / time windows and unknown / manual-item aggregation semantics, then implement the adaptation and regress against the existing 8 cases; prepare independent human labels separately. I5 read-only search and evidence packs are still to be implemented; the existence of the remote recovery agent does not mean I5 is supported.

`tools/`, `archive/` and the full `data/raw/` are git-ignored and stay local; the lightweight study cases and manifests can be versioned. How the raw Synthea data was generated is in the T6 README; the raw-file hash test needs these local raw files, which a new clone does not have.

## Later decision: minimum fasting duration

On 2026-10-09 the user confirmed a minimum fasting duration of ≥6 hours for I2/I4 as a demo policy, pending sponsor / full-protocol confirmation. The lower bound is resolved; the evaluator is not updated yet, and the handling of absurd values and per-lab method requirements are still open. This decision updates the earlier "minimum duration to be decided" note and does not modify the frozen 1.0.0.

# Ming: T6 SAD development delivery

> Translated from Ming's Chinese original on 2026-10-11. State as of the handoff on 2026-10-09; the branch has since been merged and SAD runs through the engineering pipeline (see the [root README](../README.md)).

2026-10-09; target branch: `ming/t6-sad-integration`.

This delivery contains the rules for T6 / NCT07347678 / SAD, 8 synthetic screening cases with their contexts, the source list, a dedicated evaluator, 17 technical test methods, sample results and review notes; T2 / NCT07610278 is included as a reference for the second trial. The user checked that the trial text and the T6 rules agree. File list: [DATA_DELIVERY.md](DATA_DELIVERY.md).

## Differences from what the teammate asked for

- B/G and T6/T2 numbering is not unified yet; T6 was not renamed B on my own initiative.
- The current 10 criteria plus age use `rules[].predicate`; this is not the adapted 15-item `predicates[]` and cannot go straight into the root run.py.
- There are 8 development cases that reuse Synthea demographics with constructed screening tests and interviews; they are not full histories and not an independent ground truth of ≥20 people. The intended scenario outcomes live in prepare.py / test_demo.py and the patient IDs in the manifest; they are not yet connected to engineering's FAILURE_TARGETS.
- The extension field scope, ATC→RxNorm map, reviewed equivalent codes, a simulated v2 amendment and independent human labels are not yet delivered.
- Fasting ≥6 hours is confirmed as demo policy but the evaluator is not updated yet; the method requirement is still open. I5 stays a human judgement; agent evidence retrieval exists only as an agreed document and is not implemented.
- Daisy's adapter still needs to support specimens, questionnaires, medication statements, ULN and encounter binding, and to unify aggregation semantics and unit review.
- The GitHub account used is `Charlottttttte`; the S3 bucket name and the named user's read/write access were not verified in this delivery.

## What this upload contains

Lightweight files keep their original directories. The complete raw Synthea charts (about 61.73 MB), tool runtime dependencies and archive material are not in this commit. The manifest lists the raw sources and their hashes but not the raw files; they can be provided separately as a data attachment. The existing engineering `src/`, `tests/` and data input directories were not replaced.

Frozen rules and cases have line-ending conversion disabled through .gitattributes, so that SHA-256 does not change between Windows and Linux clones.

## Running it

```bash
python t6_sad_demo/run.py
```

The existing cases run directly, without AWS or regenerating Synthea. Expected: 8 people, 88 evaluations; computed part passes 2, fails 4, missing data pending 1, conflict review 1; all still have the manual I5 item.

The full technical tests are `python t6_sad_demo/test_demo.py`. `test_originals_unchanged` needs the raw files that are not in this commit; with raw available locally all 17 pass. Receiving this commit alone does not allow claiming all 17 tests reproduce. Sample outputs are not clinical accuracy or an independent reference answer.

# Ming's data delivery and engineering integration checklist

> Translated from Ming's Chinese original on 2026-10-11. This is the inventory as of 2026-10-09, before integration. Several items have since been resolved by engineering (SAD adapter around this evaluator, Specimen / Encounter / QuestionnaireResponse loading, fail-first aggregation for SAD, S3 bucket, I5 evidence retrieval); see the [root README](../README.md) and `CLAUDE.md`.

Compiled 2026-10-09. All paths are relative to the repository root. This records the state at inventory time; the scope of this lightweight Git delivery is in [MING_SUBMISSION.md](MING_SUBMISSION.md), and the remote branch is authoritative for what was uploaded. Nothing was uploaded to S3.

## Delivery principles

The primary trial is T6 / NCT07347678 / SAD; the secondary trial is T2 / NCT07610278. The local T6 must not be confused with engineering task T6 or with the default placeholder trial B. The user confirmed that the trial text and the current T6 rules agree; fasting ≥6 hours was confirmed afterwards as a demo policy and is not in the evaluator yet; the method requirement is still open.

GitHub holds code, public trial sources, lightweight synthetic screening cases, configuration, review records and independent labels. The complete raw Synthea charts are a separate data attachment and must not be mixed with the screening cases. AWS is not a prerequisite for delivering input files. Connecting repository directories does not mean the rule semantics have been adapted.

## Existing materials and destinations

| Material | Current path | Delivery / run destination | Status and handling |
|---|---|---|---|
| Primary / secondary trial identity | `demo_scope.json` | GitHub, same path; engineering registers it in `TRIALS` in `src/config.py`, or the NCT is passed explicitly on the CLI | T6 must be registered as an explicit SAD scope, not mapped to B on our own |
| Official full T6 source record | `t6_sad_demo/source/NCT07347678.json` | GitHub, same path | Deliverable directly; do not fake a download time |
| Engineering normalized trial snapshot | The existing full JSON is not in that format | `data/snapshots/NCT07347678/YYYY-MM-DD.txt` | Generate with `src/tools/ctgov.py`; contains the age/sex header and the criteria text. Keep the original JSON; do not rename it to pose as a snapshot; compare new fetches with the reviewed version |
| Frozen T6 rules and hashes | `t6_sad_demo/rules/` | GitHub, same path; after adaptation store separately as `data/predicates/trial_T6.json` | The original files are deliverable but cannot be used directly as root run.py input; a new version carries the 6-hour policy and must not overwrite the frozen 1.0.0 |
| 8 screening FHIR cases | `t6_sad_demo/data/cases/SAD01..08.json` | GitHub, same path; after adaptation and validation publish to `data/patients/t6_sad/` and pass `--patients` | Designed synthetic screening records, not full histories; usable now for testing the local T6 evaluator |
| 8 screening contexts | `t6_sad_demo/data/context/SAD01..08.json` | GitHub, same path; engineering adds a `data/contexts/t6_sad/` reading convention | Engineering has no such entry point yet; copying them does not mean they are connected; case_id, real Patient.id, Encounter, screening time and questionnaire ID must be kept |
| Case manifest / generation configuration | `t6_sad_demo/data/case_manifest.json`, `synthea.properties`, `generation.log` | GitHub, same path | Source hashes, seed and version delivered together; the manifest is not a clinical label |
| Complete raw Synthea charts | `t6_sad_demo/data/raw/fhir/*.json`, 8 files, about 61.73 MB | Separate GitHub Release data attachment (e.g. `synthea-t6-seed20261009.zip`), unpacked to the original path | Recommended delivery route, not yet created / uploaded; git-ignored locally. Use the existing files to keep exact hashes; byte-identical regeneration is not promised |
| T6 evaluator and technical tests | `t6_sad_demo/{engine,prepare,run,test_demo}.py` | GitHub, same path | Deliverable directly as the regression baseline; do not replace Daisy's src files |
| Existing logs and web report | `t6_sad_demo/outputs/` | GitHub, same path, as demo samples | Not ground truth; note the open fasting / method implementation gaps |
| I5 retrieval agreement, SAD02 review | `t6_sad_demo/I5_EVIDENCE_REVIEW.md`, `SAD02_REVIEW.md` and README | GitHub, same path | Deliverable directly; I5 retrieval still to implement; SAD02's original status is Ex-smoker and the case was not changed |
| T2 reference data | `t2_backup/` | GitHub, same path | Reference delivery; not yet placed in the executable predicates directory; the old source_locator depends on the archive and will be revised when adapted |
| Engineering run results | `out/` produced by the root `run.py` | Local out; once a bucket is configured, logs upload to `s3://<S3_BUCKET>/logs/<trial>/<date>/` | T6 not yet connected; existing T6 logs must not be passed off as engineering output |
| Engineering fetched snapshots | `data/snapshots/...` | Once a bucket is configured, upload to `s3://<S3_BUCKET>/snapshots/<NCT>/<file name>` | Existing engineering output convention; the bucket name was not verified in this round, so nothing is uploaded |

The complete raw charts are needed by reviewers or anyone running `test_originals_unchanged`; running `t6_sad_demo/run.py` on the existing screening cases does not need raw. The original bundle and the screening bundle of the same Patient must not be placed in the same engineering patient directory: the current FhirStore indexes by Patient.id, so a later file may overwrite an earlier one instead of merging.

## Materials still to prepare

- **Field / code mapping**: first produce a review record of labs, resources, fields, units, time anchors and method requirements; the confirmed equivalent-code table goes to `data/mappings/local_code_map.json`, which engineering already reads. The sample equivalence table must not be treated as a clinically confirmed mapping.
- **Human reference answers**: planned at `data/ground_truth/trial_T6.csv`; the existing engineering fields are `patient_id,criterion_id,expected`. First complete the 88 independent labels with evidence, reasons and reviewer. The contract for unknown, manual items, the four patient states and IDs after sub-predicate splitting needs agreeing first; the existing sample labels cannot replace clinical labels.
- **Amendment demo package**: prepare, clearly marked as a simulated amendment, `data/snapshots/NCT07347678/amendment_v2.txt`, `data/predicates/trial_T6_v2.json` and `data/ground_truth/trial_T6_amendment_flips.txt`. The real text is not modified; flipping patients are determined by independent checking.
- **Failure-injection case mapping**: register real Patient.id values (not case IDs such as SAD02) in `FAILURE_TARGETS` in `src/config.py`; build a separate smoking-conflict scenario. Keep LDL-boundary, missing-data and conflict cases apart in purpose.
- **I5 evidence pack / human review records**: suggested future locations `out/i5_evidence/` and `data/reviews/t6_sad/`; these are directories to implement, not entry points existing tools support. Review conclusions never overwrite the automated log.

## Engineering integration issues to resolve first

1. The current frozen format is `rules[].predicate`; engineering reads `predicates[]` with `operator/value/codes/resource`. Age/BMI ranges, E1 OR with per-lab ULN, quantified smoking and interview windows cannot be converted faithfully by renaming keys.
2. `src/adapters/fhir_store.py` does not load Specimen, Encounter, QuestionnaireResponse, MedicationStatement, DiagnosticReport or Provenance; Observation results do not include ULN, method, specimen or encounter references. Reading / linking / evidence return must be added so T6 decision prerequisites are not lost.
3. T6 requires an explicit screening encounter, the ≥6 h fasting policy and calendar-month windows; engineering has only window_days and generic most-recent behaviour, which must be checked item by item. 3 months must not be turned casually into 90 days, and the latest result must not be picked silently when results conflict.
4. Aggregation semantics are not unified: T6 is explicitly fail-first, while engineering configures `PENDING_BEFORE_INCLUSION_FAIL=True`. I5 must keep human review and evidence, and must not display complete eligibility just because it does not block the computation.
5. Ground truth and evaluation denominators are not unified. Engineering's sensitivity counts pending as a retained positive; Ming's project uses a stricter definition of a successful positive. Unify the metrics before reporting; do not compare the two percentages directly.

## Next steps, in order

1. Commit / push the existing lightweight materials as a separate GitHub branch for review; keep the current history.
2. Check the above data contract with Daisy, then implement the T6 adaptation; keep the case and evidence structure, and do not make the data "runnable" by deleting conditions.
3. Apply the new 6-hour version policy, settle the method scope, complete the 8-case regression and I5 evidence scenario tests.
4. Connect the evaluation after Ming's independent labels; then the simulated amendment. T2 comes later.

## Not delivered to GitHub

Local `tools/` dependencies, the old `archive/`, `.env` and any credentials, virtual environments and caches. The complete raw data is delivered as a separate data attachment, not mixed into regular commits. Inputs do not need to be uploaded to Bedrock by hand: the program calls the model, and inputs are still read through the FHIR tools.

The file-level inventory is in [data_inventory.json](data_inventory.json): paths, byte sizes and SHA-256 of the active materials; raw is only listed, not copied or uploaded. It is a delivery checklist and does not replace the frozen rules and case manifest.

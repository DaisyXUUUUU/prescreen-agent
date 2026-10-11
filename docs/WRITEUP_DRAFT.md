# SAD Pre-Screening Agent - provisional writeup

**Status:** Engineering draft. The official Slack template, CRC interview, independent labels, final video and team roster have not yet been supplied. Do not submit this as a completed acceptance record.

**User and task.** A clinical research coordinator checks patients against trial eligibility criteria and maintains a pre-screening log. This prototype produces a log for NCT07347678, SAD cohort, with likely eligible, pending, excluded and needs review categories. Quantified time savings have not been measured.

**Agent and deterministic rules.** A Python batch pipeline loads synthetic FHIR records and frozen, manually compiled trial predicates. Rules perform numeric comparisons, unit checks and time windows. Strands Agents with Amazon Nova 2 Lite on Bedrock handle missing-code retrieval, free-text extraction, conflict explanation and evidence collection. Model-interpreted failures require review; unsupported facts remain unknown. I5 remains an investigator judgement.

**Tools and cloud delivery.** ClinicalTrials.gov supplies trial criteria; NLM RxNav supplies drug terminology. Recovery is restricted to a system-qualified equivalent-code allowlist and the original patient/encounter. Bedrock and S3 have been exercised; logs and criteria snapshots are delivered to S3 when a bucket is configured. No patient is contacted.

**Failure handling.** Reproducible scenarios cover API timeout with fresh-cache fallback, missing codes, invalid units/values and simulated protocol amendment. Shared files use atomic UTF-8 writes with bounded retries. Evaluation fails on missing/failed scenarios. Both amendment versions use the same mode; unchanged evidence interpretations are reused and agent errors invalidate attribution.

**Evidence and limitations.** The engineering dataset contains 8 core and 50 extended synthetic cases. Existing design labels cover 38 patient conclusions and only 37 of 580 computable criterion decisions; independent accuracy is unmeasured. EXT11 and EXT43 require label/data review. Paste only the newest validated run metrics and video link after completing those steps. This is a pre-screening demonstration, not an autonomous clinical deployment or enrollment decision.

# Trial Pre-Screening Demo (Ming's local evaluator)

> Translated from Ming's Chinese original on 2026-10-11. This page describes Ming's standalone evaluator as handed off on 2026-10-09. The submission's main entry point is the [root README](README.md), which runs the same evaluator inside the full pipeline with the agent.

Current main demo: **T6 / NCT07347678 / SAD cohort**. Second trial: **T2 / NCT07610278**. T7 has left the main demo.

From the project root:

```bash
python t6_sad_demo/run.py
python t6_sad_demo/test_demo.py
```

The existing data re-runs directly, without AWS credentials or downloading Synthea again.

- [Run report](t6_sad_demo/outputs/REPORT.md)
- [Web report with expandable evidence](t6_sad_demo/outputs/report.html)
- [Pre-screening log JSON](t6_sad_demo/outputs/prescreening_log.json)
- [Manual / missing / conflict queue](t6_sad_demo/outputs/exception_queue.json)
- [T6 operation and limits](t6_sad_demo/README.md)
- [I5 evidence retrieval and human-judgement agreement](t6_sad_demo/I5_EVIDENCE_REVIEW.md)

Directories:

- `t6_sad_demo/`: the runnable SAD rules, 8 synthetic people, deterministic evaluator, tests and results.
- `t2_backup/`: the second trial's 9 reference rules and official source record, not connected to this evaluator.
- `tools/`: Synthea 3.3.0 and a local FHIR validation virtual environment (runtime dependency, not in git).
- `archive/2026-10-09-pre-sad/`: earlier comparison reports, T7 specification / data and old scripts (not in git). Old absolute paths inside may no longer work; the current run does not depend on them.

The local loop "read FHIR → evaluate against SAD rules → evidence-linked log → exception queue → local delivery" is complete. At handoff there was no LLM / Bedrock agent, FHIR service, AWS delivery or automatic amendment monitoring; these are now provided by the engineering pipeline. The current tests are author-designed technical tests, not an independent clinical-accuracy evaluation.

The authorized next step for I5: the agent searches the specified patient's FHIR record read-only and organizes liver- and kidney-related evidence for a human to judge; the automated result stays `unknown` and needs human review.

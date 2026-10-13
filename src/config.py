"""Project settings and failure-injection switches.

T4 needs the trial table and the `ctgov_timeout` switch; T9 fills in the rest
(CLI `--fail` wiring, the other switches' effects).
"""

import os
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DATA_DIR = ROOT / "data"
PATIENT_DIR = DATA_DIR / "patients"
SNAPSHOT_DIR = DATA_DIR / "snapshots"
CACHE_DIR = ROOT / "cache"

AWS_PROFILE = os.getenv("AWS_PROFILE") or None
# PRESCREEN_* names exist because hosts such as Vercel reserve the AWS_* variables for themselves.
AWS_REGION = os.getenv("PRESCREEN_AWS_REGION") or os.getenv("AWS_REGION", "us-west-2")
S3_BUCKET = os.getenv("S3_BUCKET", "")
BEDROCK_MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "")

# Primary trial: NCT07347678, SAD cohort only.
# NCT07610278 (hypertension + hypercholesterolemia) is kept as a reference rule set; no patients yet.
TRIALS: dict[str, str | None] = {
    "SAD": "NCT07347678",
    "T2": "NCT07610278",
}

# Public trial used by the test fixtures in tests/fixtures/. It is not a screened trial.
TEST_NCT_ID = "NCT02178098"

# Default anchor for time windows; override with SCREENING_DATE=YYYY-MM-DD.
SCREENING_DATE = os.getenv("SCREENING_DATE") or date.today().isoformat()

# Aggregation order for the generic engine. True: a blocking unknown is checked
# before a failed inclusion, so such a patient is "pending" rather than "excluded"
# (brief goal 2: answer unknown before excluded). False: failed inclusion wins.
PENDING_BEFORE_INCLUSION_FAIL = True

# Conflict where every candidate gives the same criterion status: resolve it to that status, keeping
# the conflict visible in the evidence (decided 2026-10-09). False keeps it in review.
IMMATERIAL_CONFLICT_RESOLVES = True

OUT_DIR = ROOT / "out"

# Cache older than this cannot back a log (brief section 6).
CTGOV_MAX_CACHE_AGE_DAYS = 14

FAILURES: dict[str, bool] = {
    "ctgov_timeout": False,
    "bad_units": False,
    "drop_codes": False,
    "amendment_v2": False,
    "note_conflict": False,
}


# Patients each data failure is applied to. Empty:
# src/failures.py picks the first patients with an LDL-C record, in ID order.
FAILURE_TARGETS: dict[str, list[str]] = {}


def enable_failure(name: str) -> None:
    if name not in FAILURES:
        raise ValueError(f"unknown failure switch {name!r}; choose from {sorted(FAILURES)}")
    FAILURES[name] = True


def failure_enabled(name: str) -> bool:
    return FAILURES.get(name, False)


def trial_nct(trial: str) -> str:
    """NCT ID for a trial letter; fails loudly rather than guessing."""
    if trial not in TRIALS:
        raise ValueError(f"unknown trial {trial!r}; known: {sorted(TRIALS)}")
    nct = TRIALS[trial]
    if not nct:
        raise ValueError(f"NCT ID for trial {trial} not set in src/config.py")
    return nct


def s3_enabled() -> bool:
    return bool(S3_BUCKET) and "CHANGEME" not in S3_BUCKET

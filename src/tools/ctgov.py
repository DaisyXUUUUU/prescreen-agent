"""T4: fetch trial eligibility criteria from ClinicalTrials.gov API v2.

Never raises to the caller. Returns a FetchResult whose status is
  ok     fresh from the API (cache and snapshot written)
  stale  API failed, served from cache no older than CTGOV_MAX_CACHE_AGE_DAYS
  error  API failed and no usable cache; the log must not be issued

    python -m src.tools.ctgov NCT02178098
    python -m src.tools.ctgov NCT02178098 --fail ctgov_timeout
"""

import argparse
import hashlib
import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import requests

from src import config

log = logging.getLogger(__name__)

API_URL = "https://clinicaltrials.gov/api/v2/studies/{nct_id}"
TIMEOUT_S = 10
ATTEMPTS = 2  # one try plus one retry
NCT_RE = re.compile(r"^NCT\d{8}$")


@dataclass
class FetchResult:
    status: str  # ok | stale | error
    nct_id: str
    criteria: dict | None = None  # eligibility_criteria, minimum_age, maximum_age, sex
    fetched_at: str | None = None  # when the returned data came from the API (UTC ISO)
    cache_age_days: float | None = None
    sha256: str | None = None
    snapshot_path: str | None = None
    error: str | None = None
    warnings: list[str] = field(default_factory=list)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _request(nct_id: str) -> dict:
    """One API call. Raises on any failure; ctgov_fetch turns that into a status."""
    if config.failure_enabled("ctgov_timeout"):
        raise requests.Timeout("injected ctgov_timeout")
    resp = requests.get(API_URL.format(nct_id=nct_id), timeout=TIMEOUT_S)
    resp.raise_for_status()
    return resp.json()


def _extract(study: dict) -> dict:
    elig = study.get("protocolSection", {}).get("eligibilityModule")
    if not elig or not elig.get("eligibilityCriteria"):
        raise ValueError("response has no protocolSection.eligibilityModule.eligibilityCriteria")
    return {
        "eligibility_criteria": elig["eligibilityCriteria"],
        "minimum_age": elig.get("minimumAge"),
        "maximum_age": elig.get("maximumAge"),
        "sex": elig.get("sex"),
    }


def snapshot_text(criteria: dict) -> str:
    """Canonical text that gets hashed. Age and sex are included so a change
    to them counts as an amendment too."""
    header = (
        f"Minimum age: {criteria.get('minimum_age')}\n"
        f"Maximum age: {criteria.get('maximum_age')}\n"
        f"Sex: {criteria.get('sex')}\n\n"
    )
    return header + criteria["eligibility_criteria"].strip() + "\n"


def _write_snapshot(nct_id: str, criteria: dict, fetched: datetime, snapshot_dir: Path) -> tuple[Path, str]:
    text = snapshot_text(criteria)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    path = snapshot_dir / nct_id / f"{fetched.date().isoformat()}.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path, digest


def _upload_snapshot(path: Path, nct_id: str) -> str | None:
    """Best effort copy to S3. Returns a warning string on failure or skip."""
    if not config.s3_enabled():
        return "S3_BUCKET not set; snapshot kept locally only"
    try:
        import boto3

        session = boto3.Session(profile_name=config.AWS_PROFILE, region_name=config.AWS_REGION)
        key = f"snapshots/{nct_id}/{path.name}"
        session.client("s3").upload_file(str(path), config.S3_BUCKET, key)
        log.info("uploaded s3://%s/%s", config.S3_BUCKET, key)
        return None
    except Exception as e:  # noqa: BLE001 - S3 must never break the fetch
        return f"S3 upload failed: {e}"


def _from_cache(nct_id: str, cache_path: Path, reason: str) -> FetchResult:
    if not cache_path.exists():
        return FetchResult("error", nct_id, error=f"{reason}; no cache")
    try:
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        fetched = datetime.fromisoformat(cached["fetched_at"])
        criteria = cached["criteria"]
    except (ValueError, KeyError) as e:
        return FetchResult("error", nct_id, error=f"{reason}; cache unreadable: {e}")

    age_days = round((_now() - fetched).total_seconds() / 86400, 2)
    if age_days > config.CTGOV_MAX_CACHE_AGE_DAYS:
        return FetchResult(
            "error", nct_id, fetched_at=cached["fetched_at"], cache_age_days=age_days,
            error=f"{reason}; cache is {age_days} days old (limit {config.CTGOV_MAX_CACHE_AGE_DAYS})",
        )
    digest = hashlib.sha256(snapshot_text(criteria).encode("utf-8")).hexdigest()
    return FetchResult(
        "stale", nct_id, criteria=criteria, fetched_at=cached["fetched_at"],
        cache_age_days=age_days, sha256=digest, error=reason,
    )


def ctgov_fetch(nct_id: str, *, cache_dir: Path | None = None, snapshot_dir: Path | None = None) -> FetchResult:
    nct_id = nct_id.strip().upper()
    if not NCT_RE.match(nct_id):
        return FetchResult("error", nct_id, error="not a valid NCT ID (expected NCT + 8 digits)")

    cache_dir = cache_dir or config.CACHE_DIR / "ctgov"
    snapshot_dir = snapshot_dir or config.SNAPSHOT_DIR
    cache_path = cache_dir / f"{nct_id}.json"

    criteria, reason = None, None
    for attempt in range(1, ATTEMPTS + 1):
        try:
            criteria = _extract(_request(nct_id))
            break
        except requests.HTTPError as e:
            reason = f"HTTP {e.response.status_code}"
            log.warning("ctgov %s attempt %d failed: %s", nct_id, attempt, reason)
            if e.response.status_code < 500:
                break  # 4xx will not fix itself on retry
        except requests.Timeout as e:
            reason = str(e) or f"timeout after {TIMEOUT_S}s"
            log.warning("ctgov %s attempt %d failed: %s", nct_id, attempt, reason)
        except (requests.RequestException, ValueError) as e:
            reason = f"{type(e).__name__}: {e}"
            log.warning("ctgov %s attempt %d failed: %s", nct_id, attempt, reason)
    if criteria is None:
        return _from_cache(nct_id, cache_path, reason)

    fetched = _now()
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps({"fetched_at": fetched.isoformat(), "criteria": criteria}, indent=2),
        encoding="utf-8",
    )
    path, digest = _write_snapshot(nct_id, criteria, fetched, snapshot_dir)
    result = FetchResult(
        "ok", nct_id, criteria=criteria, fetched_at=fetched.isoformat(),
        cache_age_days=0.0, sha256=digest, snapshot_path=str(path),
    )
    if warning := _upload_snapshot(path, nct_id):
        result.warnings.append(warning)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch trial eligibility criteria from ClinicalTrials.gov")
    parser.add_argument("nct_id", nargs="?", default=config.TEST_NCT_ID)
    parser.add_argument("--fail", action="append", default=[], help="enable a failure switch, e.g. ctgov_timeout")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    for name in args.fail:
        config.enable_failure(name)

    result = asdict(ctgov_fetch(args.nct_id))
    if result["criteria"]:
        text = result["criteria"]["eligibility_criteria"]
        result["criteria"]["eligibility_criteria"] = text[:300] + (f"... [{len(text)} chars]" if len(text) > 300 else "")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

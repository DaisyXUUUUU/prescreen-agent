import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest
import requests

from src import config
from src.tools import ctgov

STUDY = {
    "protocolSection": {
        "eligibilityModule": {
            "eligibilityCriteria": "Inclusion Criteria:\n\n* LDL-C >= 100 mg/dL\n",
            "minimumAge": "18 Years",
            "maximumAge": "75 Years",
            "sex": "ALL",
        }
    }
}
NOW = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)


class FakeResponse:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self._body = body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)

    def json(self):
        if self._body is None:
            raise requests.JSONDecodeError("bad", "", 0)
        return self._body


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Isolated dirs, fixed clock, S3 off, all failure switches off."""
    monkeypatch.setattr(ctgov, "_now", lambda: NOW)
    monkeypatch.setattr(config, "S3_BUCKET", "")
    monkeypatch.setattr(config, "FAILURES", {k: False for k in config.FAILURES})
    calls = []

    def respond_with(*responses):
        seq = list(responses)

        def fake_get(url, timeout):
            calls.append(url)
            r = seq.pop(0) if len(seq) > 1 else seq[0]
            if isinstance(r, Exception):
                raise r
            return r

        monkeypatch.setattr(ctgov.requests, "get", fake_get)

    def fetch(nct="NCT00000001"):
        return ctgov.ctgov_fetch(nct, cache_dir=tmp_path / "cache", snapshot_dir=tmp_path / "snap")

    def write_cache(nct="NCT00000001", age_days=1.0):
        d = tmp_path / "cache"
        d.mkdir(parents=True, exist_ok=True)
        fetched = NOW - timedelta(days=age_days)
        (d / f"{nct}.json").write_text(json.dumps({"fetched_at": fetched.isoformat(), "criteria": ctgov._extract(STUDY)}))

    return type("Env", (), {"respond_with": staticmethod(respond_with), "fetch": staticmethod(fetch),
                            "write_cache": staticmethod(write_cache), "calls": calls, "tmp": tmp_path})


def test_ok_writes_cache_and_snapshot(env):
    env.respond_with(FakeResponse(body=STUDY))
    r = env.fetch()
    assert r.status == "ok"
    assert r.criteria["minimum_age"] == "18 Years" and r.criteria["sex"] == "ALL"
    assert (env.tmp / "cache" / "NCT00000001.json").exists()
    snap = env.tmp / "snap" / "NCT00000001" / "2026-10-09.txt"
    assert r.snapshot_path == str(snap)
    assert r.sha256 == hashlib.sha256(snap.read_bytes()).hexdigest()
    assert "Maximum age: 75 Years" in snap.read_text()
    assert r.warnings == ["S3_BUCKET not set; snapshot kept locally only"]


def test_timeout_retries_once_then_uses_fresh_cache(env):
    env.write_cache(age_days=3)
    env.respond_with(requests.Timeout())
    r = env.fetch()
    assert len(env.calls) == 2
    assert r.status == "stale"
    assert r.cache_age_days == 3.0
    assert r.criteria["eligibility_criteria"].startswith("Inclusion Criteria")


def test_retry_succeeds_on_second_attempt(env):
    env.respond_with(requests.ConnectionError(), FakeResponse(body=STUDY))
    assert env.fetch().status == "ok"
    assert len(env.calls) == 2


def test_cache_older_than_limit_is_error(env):
    env.write_cache(age_days=config.CTGOV_MAX_CACHE_AGE_DAYS + 1)
    env.respond_with(requests.Timeout())
    r = env.fetch()
    assert r.status == "error"
    assert r.criteria is None
    assert "15.0 days old" in r.error


def test_no_cache_is_error(env):
    env.respond_with(requests.Timeout())
    r = env.fetch()
    assert r.status == "error" and "no cache" in r.error


def test_404_is_not_retried(env):
    env.respond_with(FakeResponse(status=404))
    r = env.fetch()
    assert len(env.calls) == 1
    assert r.status == "error" and "HTTP 404" in r.error


def test_malformed_response_falls_back(env):
    env.write_cache(age_days=0.5)
    env.respond_with(FakeResponse(body={"protocolSection": {}}))
    assert env.fetch().status == "stale"


def test_invalid_json_falls_back(env):
    env.respond_with(FakeResponse(body=None))
    assert env.fetch().status == "error"


def test_injected_timeout_never_hits_network(env):
    env.write_cache(age_days=1)
    env.respond_with(FakeResponse(body=STUDY))
    config.enable_failure("ctgov_timeout")
    r = env.fetch()
    assert env.calls == []
    assert r.status == "stale"


def test_bad_id_rejected_without_request(env):
    env.respond_with(FakeResponse(body=STUDY))
    r = env.fetch("12345")
    assert r.status == "error" and env.calls == []


def test_trial_without_nct_fails_loudly(monkeypatch):
    monkeypatch.setitem(config.TRIALS, "X", None)
    with pytest.raises(ValueError, match="not set"):
        config.trial_nct("X")


def test_primary_trial_is_sad():
    assert config.trial_nct("SAD") == "NCT07347678"

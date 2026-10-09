import csv
import sys
from pathlib import Path

import pytest

import run
from src import config
from src.engine.aggregate import aggregate
from src.engine.evaluate import Verdict
from src.tools.ctgov import FetchResult

FIX = Path(__file__).parent / "fixtures"

PREDS = [
    {"criterion_id": "I1", "type": "inclusion", "concept": "LDL"},
    {"criterion_id": "I2", "type": "inclusion", "concept": "Age"},
    {"criterion_id": "E1", "type": "exclusion", "concept": "TG"},
    {"criterion_id": "N1", "type": "exclusion", "concept": "Comply", "computable": False, "grade": "N"},
]


def verdicts(**statuses):
    """verdicts(I1="met", E1=("unknown", False)) -> list of Verdicts; tuple second item = blocking."""
    out = []
    for p in PREDS:
        s = statuses.get(p["criterion_id"], "unknown" if p["criterion_id"] == "N1" else
                         ("met" if p["type"] == "inclusion" else "not_met"))
        status, blocking = (s if isinstance(s, tuple) else (s, True))
        out.append(Verdict("p1", p["criterion_id"], status=status, blocking=blocking, note=f"{p['criterion_id']} note"))
    return out


@pytest.fixture(autouse=True)
def default_order(monkeypatch):
    monkeypatch.setattr(config, "PENDING_BEFORE_INCLUSION_FAIL", True)


def cat(vs):
    return aggregate("p1", PREDS, vs)


def test_all_met_is_likely_eligible_and_n_grade_does_not_block():
    r = cat(verdicts())
    assert r.category == "likely_eligible"
    assert r.crc_checks == ["N1 Comply"] and r.decisive == ["I1", "I2"]


def test_exclusion_met_wins_over_everything():
    r = cat(verdicts(E1="met", I1="unknown", I2="not_met"))
    assert r.category == "excluded" and r.decisive == ["E1"]


def test_conflict_goes_to_review():
    vs = verdicts()
    vs[0].conflict = True
    assert cat(vs).category == "needs_review"


def test_blocking_unknown_is_pending_with_missing_item():
    r = cat(verdicts(I1="unknown"))
    assert r.category == "pending" and r.missing == ["I1 LDL"]


def test_non_blocking_unknown_stays_eligible_with_confirm_note():
    r = cat(verdicts(E1=("unknown", False)))
    assert r.category == "likely_eligible" and r.confirm_at_visit == ["E1 TG"]


def test_failed_inclusion_alone_is_excluded():
    r = cat(verdicts(I2="not_met"))
    assert r.category == "excluded" and r.decisive == ["I2"]


def test_open_question_default_pending_but_shows_failed_inclusion():
    r = cat(verdicts(I2="not_met", E1="unknown"))
    assert r.category == "pending"
    assert r.also_fails and r.also_fails[0].startswith("I2")


def test_open_question_switch_excludes(monkeypatch):
    monkeypatch.setattr(config, "PENDING_BEFORE_INCLUSION_FAIL", False)
    r = cat(verdicts(I2="not_met", E1="unknown"))
    assert r.category == "excluded" and r.decisive == ["I2"]


# ---------- end to end through run.py (no network) ----------

def fake_fetch(status="ok"):
    return lambda nct: FetchResult(status, nct, criteria={}, fetched_at="2026-10-09T08:00:00+00:00",
                                   cache_age_days=0.0 if status == "ok" else 3.0, sha256="ab" * 32,
                                   error=None if status == "ok" else "injected ctgov_timeout")


def run_cli(monkeypatch, tmp_path, *extra, fetch_status="ok"):
    monkeypatch.setattr(run, "ctgov_fetch", fake_fetch(fetch_status))
    monkeypatch.setattr(config, "S3_BUCKET", "")
    argv = ["run.py", "--trial", "SAMPLE", "--nct", "NCT02178098", "--date", "2026-10-09",
            "--predicates", str(FIX / "sample_predicates.json"), "--patients", str(FIX / "patients"),
            "--out", str(tmp_path), *extra]
    monkeypatch.setattr(sys, "argv", argv)
    return run.main()


def test_every_patient_lands_in_exactly_one_section(monkeypatch, tmp_path):
    assert run_cli(monkeypatch, tmp_path) == 0
    md = (tmp_path / "prescreen_log_SAMPLE_2026-10-09.md").read_text()
    for pid in ["fixture-complete", "fixture-missing-ldl", "fixture-over-age"]:
        summary_rows = [l for l in md.splitlines() if l.startswith(f"| `{pid}` |")]
        assert len(summary_rows) == 1, pid
    rows = list(csv.DictReader((tmp_path / "prescreen_log_SAMPLE_2026-10-09.csv").open()))
    assert len(rows) == 3 * 9
    assert {r["patient_id"]: r["patient_category"] for r in rows} == {
        "fixture-complete": "likely_eligible", "fixture-missing-ldl": "pending", "fixture-over-age": "pending"}


def test_excluded_rows_trace_to_criterion_and_record(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "PENDING_BEFORE_INCLUSION_FAIL", False)
    assert run_cli(monkeypatch, tmp_path) == 0
    md = (tmp_path / "prescreen_log_SAMPLE_2026-10-09.md").read_text()
    excluded = md.split("## Excluded")[1].split("## Needs review")[0]
    row = next(l for l in excluded.splitlines() if l.startswith("| `fixture-over-age`"))
    assert "**S-I2**" in row and "`fixture-over-age` born 1944-11-02" in row


def test_stale_criteria_are_stamped(monkeypatch, tmp_path):
    assert run_cli(monkeypatch, tmp_path, fetch_status="stale") == 0
    md = (tmp_path / "prescreen_log_SAMPLE_2026-10-09.md").read_text()
    assert "**STALE**" in md and "3 days old" in md


def test_no_log_when_criteria_unavailable(monkeypatch, tmp_path):
    assert run_cli(monkeypatch, tmp_path, fetch_status="error") == 3
    assert not list(tmp_path.glob("*.md"))

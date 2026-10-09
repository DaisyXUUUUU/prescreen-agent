"""T10 tests without a model: diffing, the rule path, routing and the impact report.

The model's labels on the sample amendment are checked live (see T10 acceptance run).
"""

import json
import re
from pathlib import Path

import pytest

from src import config
from src.adapters import fhir_store
from src.adapters.fhir_store import FhirStore
from src.amendment import monitor, rescreen
from src.pipeline import screen
from src.tools.ctgov import FetchResult

FIX = Path(__file__).parent / "fixtures"
V1_TEXT = (FIX / "snapshots" / "NCT02178098_v1.txt").read_text()
V2_TEXT = (FIX / "snapshots" / "NCT02178098_v2.txt").read_text()
DATE = "2026-10-09"


def fake_classify(change, model=None):
    """Stand-in for the model: numbers changed -> substantive, otherwise wording."""
    nums = lambda t: re.findall(r"\d+", t or "")  # noqa: E731
    change.label = "substantive" if nums(change.old) != nums(change.new) else "wording"
    change.reason = "fake"
    return change


def test_split_items_by_section_and_bullet():
    items = monitor.split_items(V1_TEXT)
    assert items[0].section == "Header" and items[0].text == "Minimum age: 18 Years"
    assert ("Inclusion Criteria", "Fasting LDL-C between 100 and 220 mg/dL") in [(i.section, i.text) for i in items]
    assert len(items) == 12


def test_continuation_lines_join_their_bullet():
    items = monitor.split_items("Inclusion Criteria:\n\n* LDL-C >= 100 mg/dL\n  measured fasting\n* Age 18+\n")
    assert [i.text for i in items] == ["LDL-C >= 100 mg/dL measured fasting", "Age 18+"]


def test_diff_finds_the_two_modified_items():
    changes = monitor.diff_items(monitor.split_items(V1_TEXT), monitor.split_items(V2_TEXT))
    assert [(c.kind, c.section) for c in changes] == [("modified", "Inclusion Criteria"), ("modified", "Exclusion Criteria")]
    assert changes[0].new == "Fasting LDL-C between 140 and 220 mg/dL"


def test_added_and_removed_items():
    old = monitor.split_items("Exclusion Criteria:\n* A\n* B\n")
    new = monitor.split_items("Exclusion Criteria:\n* A\n* C\n* D\n")
    assert [(c.kind, c.old, c.new) for c in monitor.diff_items(old, new)] == [("modified", "B", "C"), ("added", None, "D")]


def test_identical_hash_means_no_change():
    r = monitor.check(V1_TEXT, V1_TEXT, "a", "b")
    assert not r.changed and r.changes == []


def test_punctuation_only_is_wording_by_rule_without_model():
    c = monitor.classify(monitor.Change("modified", "X", "LDL-C >= 100 mg/dL.", "LDL-C >=100 mg/dl"))
    assert c.label == "wording" and c.trace[0]["tool"] == "rule:normalize"


def test_model_failure_is_ambiguous_never_substantive():
    c = monitor.classify(monitor.Change("modified", "X", "LDL-C >= 100", "LDL-C >= 140"))  # no model in tests
    assert c.label == "ambiguous" and c.trace[0]["tool"] == "agent:error"


def test_predicate_changes():
    v1 = json.loads((FIX / "sample_predicates.json").read_text())["predicates"]
    v2 = json.loads((FIX / "sample_predicates_v2.json").read_text())["predicates"]
    ch = monitor.predicate_changes(v1, v2)
    assert list(ch) == ["S-I5"] and "value: 100 -> 140" in ch["S-I5"]


# ---------- orchestration ----------

@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "FAILURES", {k: False for k in config.FAILURES})
    monkeypatch.setattr(monitor, "classify", fake_classify)
    monkeypatch.setattr(config, "S3_BUCKET", "")
    fhir_store.set_store(FhirStore(FIX / "patients"))
    preds = json.loads((FIX / "sample_predicates.json").read_text())["predicates"]
    results, _, _ = screen(preds, DATE, use_agent=False)
    snap = tmp_path / "snap"
    snap.mkdir()
    (snap / "v1.txt").write_text(V1_TEXT)
    (snap / "v2.txt").write_text(V2_TEXT)
    fetch = FetchResult("ok", "NCT02178098", criteria={"eligibility_criteria": "x"}, fetched_at=f"{DATE}T08:00:00+00:00",
                        sha256="ab" * 32, snapshot_path=str(snap / "v1.txt"))

    def go(v2_preds=FIX / "sample_predicates_v2.json", v2_text=snap / "v2.txt"):
        config.enable_failure("amendment_v2")
        path = rescreen.run_amendment("SAMPLE", "NCT02178098", fetch, DATE, preds, results, tmp_path, use_agent=False,
                                      v1_snapshot=snap / "v1.txt", v2_snapshot=v2_text, v2_predicates=v2_preds)
        return path.read_text() if path else None

    return go, tmp_path


def test_substantive_change_rescreens_and_reports_flip(setup, tmp_path):
    go, out = setup
    # Offline the agent does not run, so use a threshold that flips a patient on rules alone:
    # fixture-complete has LDL-C 162.4 mg/dL.
    data = json.loads((FIX / "sample_predicates_v2.json").read_text())
    next(p for p in data["predicates"] if p["criterion_id"] == "S-I5")["value"] = 170
    v2 = tmp_path / "v2_preds.json"
    v2.write_text(json.dumps(data))
    md = go(v2_preds=v2)
    assert "substantive 1 · wording 1 · ambiguous 0" in md
    flips = md.split("## Patients whose status changes")[1].split("##")[0]
    row = next(l for l in flips.splitlines() if l.startswith("| `fixture-complete`"))
    assert "Likely eligible" in row and "**Excluded**" in row and "**S-I5** met → not_met" in row
    assert "value: 100 -> 170" in md
    assert (out / "prescreen_log_SAMPLE-amended_2026-10-09.md").exists()


def test_amended_predicates_missing_blocks_rescreen(setup, tmp_path):
    go, _ = setup
    md = go(v2_preds=tmp_path / "nope.json")
    assert "Re-screen: not run" in md and "needs human compilation" in md


def test_wording_only_does_not_rescreen(setup, tmp_path):
    go, _ = setup
    only_wording = V1_TEXT.replace("History or current type 1 diabetes or type 2 diabetes",
                                   "Current or past history of type 1 or type 2 diabetes")
    p = tmp_path / "w.txt"
    p.write_text(only_wording)
    md = go(v2_text=p)
    assert "substantive 0 · wording 1" in md and "no substantive change" in md


def test_unchanged_criteria_write_no_report(setup, tmp_path):
    go, _ = setup
    p = tmp_path / "same.txt"
    p.write_text(V1_TEXT)
    assert go(v2_text=p) is None

"""SAD adapter: the SAD evaluator inside the screening pipeline (offline, no model)."""

import json
from collections import Counter
from pathlib import Path

import pytest

from src import config, failures
from src.agent import agent as ag
from src.amendment import monitor, rescreen
from src.engine import sad_adapter as sa
from src.tools.ctgov import FetchResult

ROOT = Path(__file__).parent.parent
FIX = Path(__file__).parent / "fixtures" / "sad"


@pytest.fixture
def sad(monkeypatch):
    monkeypatch.setattr(config, "FAILURES", {k: False for k in config.FAILURES})
    cases = sa.load_cases()
    store = sa.install_store(cases)
    ids = {c.case_id: c.patient_id for c in cases}
    monkeypatch.setattr(config, "FAILURE_TARGETS",
                        {k: [ids[x] for x in v] for k, v in sa.DEFAULT_FAILURE_TARGETS.items()})
    return sa.load_spec(), cases, store


def by_case(results):
    return {r.patient_id: r for r in results}


def test_inputs_match_ming_manifests():
    assert sa.verify_inputs(sa.SPEC_PATH, sa.SAD_DIR / "data" / "cases") == []


def test_reproduces_ming_engine_exactly(sad):
    """Acceptance for the adapter: same decision per case and same status/conflict/reason per criterion."""
    spec, cases, _ = sad
    results, *_ = sa.screen(cases, spec, use_agent=False)
    reference = {x["case_id"]: x for x in json.loads((ROOT / "trials/nct07347678_sad/outputs/prescreening_log.json").read_text("utf-8"))}
    for r in results:
        assert r.category == sa.DECISION_TO_CATEGORY[reference[r.patient_id]["decision"]], r.patient_id
        rows = {c["criterion_id"]: c for c in reference[r.patient_id]["criteria"]}
        for v in r.verdicts:
            assert (v.status, v.conflict) == (rows[v.criterion_id]["status"], rows[v.criterion_id]["conflict"])
            assert rows[v.criterion_id]["reason"] in v.note
    assert Counter(r.category for r in results) == {"excluded": 4, "likely_eligible": 2, "pending": 1, "needs_review": 1}


def test_i5_is_left_to_the_crc_and_never_blocks(sad):
    spec, cases, _ = sad
    r = by_case(sa.screen(cases, spec, use_agent=False)[0])["SAD01"]
    assert r.category == "likely_eligible" and any(x.startswith("I5") for x in r.crc_checks)


def test_only_empty_queries_go_to_the_agent(sad):
    spec, cases, _ = sad
    results, *_ = sa.screen(cases, spec, use_agent=False)
    flagged = [(r.patient_id, v.criterion_id) for r in results for v in r.verdicts if v.needs_recovery]
    assert flagged == [("SAD06", "I3")]  # missing Lp(a); SAD07's duplicate LDL is a conflict, not a recovery case


def test_drop_codes_then_agent_tools_restore_the_verdict(sad):
    spec, cases, store = sad
    config.enable_failure("drop_codes")
    failures.inject(store)
    results, *_ = sa.screen(cases, spec, use_agent=False)
    sad04 = by_case(results)["SAD04"]
    v = next(v for v in sad04.verdicts if v.criterion_id == "I2")
    assert sad04.category == "pending" and v.needs_recovery

    case = next(c for c in cases if c.case_id == "SAD04")
    pred = {p["criterion_id"]: p for p in sa.predicates(spec)}["I2"]
    rc = ag.RecoveryCase("SAD04", pred, case.screening_date, query_patient_id=case.patient_id,
                         evaluate_records=lambda recs: sa.evaluate_with_records(case, spec, "I2", recs))
    t = {x.tool_spec["name"]: x for x in ag.build_tools(rc)}
    t["lookup_equivalent_codes"]()
    q = t["fhir_query_codes"](codes=["13457-7"])
    out = t["evaluate_with_records"](resource_ids=[q["records"][0]["resource_id"]])
    assert out["status"] == "met"  # 70 mg/dL >= 70, decided by the SAD evaluator
    final = ag.finalize(v, rc, "")
    assert final.status == "met" and "13457-7 -> 18262-6" in final.note
    assert "equivalent code 13457-7" in final.recovery


def test_bad_units_convert_and_implausible_guard(sad):
    spec, cases, store = sad
    config.enable_failure("bad_units")
    failures.inject(store)
    res = by_case(sa.screen(cases, spec, use_agent=False)[0])
    i2 = lambda c: next(v for v in res[c].verdicts if v.criterion_id == "I2")  # noqa: E731
    assert i2("SAD01").status == "met" and any(t["tool"] == "rule:unit_convert" for t in i2("SAD01").trace)
    # 690 mg/dL would pass the evaluator's >= 70 check; the plausibility guard makes it unknown instead
    assert i2("SAD02").status == "unknown" and "outside plausible range" in i2("SAD02").note
    assert res["SAD02"].category == "pending"


def test_sad_amendment_rescreen_reports_flips(sad, tmp_path, monkeypatch):
    spec, cases, _ = sad
    results, *_ = sa.screen(cases, spec, use_agent=False)

    def fake_classify(change, model=None):
        change.label = "substantive" if "LDL" in (change.new or "") else "wording"
        change.reason = "fake"
        return change

    monkeypatch.setattr(monitor, "classify", fake_classify)
    monkeypatch.setattr(config, "S3_BUCKET", "")
    config.enable_failure("amendment_v2")
    fetch = FetchResult("ok", "NCT07347678", criteria={"eligibility_criteria": "x"},
                        fetched_at="2026-10-09T08:00:00+00:00", sha256="ab" * 32,
                        snapshot_path=str(FIX / "NCT07347678_v1.txt"))

    def rescreen_fn(path):
        s2 = sa.load_spec(path)
        return sa.screen(cases, s2, use_agent=False)[0], sa.predicates(s2)

    path = rescreen.run_amendment("SAD", "NCT07347678", fetch, "2026-10-09", sa.predicates(spec), results, tmp_path,
                                  use_agent=False, v1_snapshot=FIX / "NCT07347678_v1.txt",
                                  v2_snapshot=FIX / "NCT07347678_v2.txt",
                                  v2_predicates=FIX / "sad-1.0.1-sample.json", rescreen_fn=rescreen_fn)
    impact = json.loads(path.with_suffix(".json").read_text())
    assert [c["label"] for c in impact["changes"]] == ["substantive", "wording"]
    # LDL 90 (SAD01), 70 (SAD04) and SAD06's value no longer reach 100; SAD06 goes from pending to excluded
    assert impact["flips"] == ["SAD01", "SAD04", "SAD06"]
    amended = (tmp_path / "prescreen_log_SAD-amended_2026-10-09.md").read_text()
    assert "amended criteria from" in amended and "fetched live" not in amended

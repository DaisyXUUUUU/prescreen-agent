"""Agent modules on SAD (free text, conflicts, I5 evidence), offline.

The model is replaced by canned structured outputs and RxNav by a fixed table, so these tests
check what the code does with the model's answers: quote checks, thresholds and windows applied
by code, terminology over model memory, and aggregation that never excludes on interpretation.
Cases are the engineering-authored ones in data/eng_cases/ (design intent, not ground truth).
"""

import pytest

from src import config
from src.agent import conflict, evidence, interpret, llm
from src.engine import sad_adapter as sa
from src.engine.aggregate import aggregate
from src.tools import rxnav

RXNAV = {
    "leqvio": {"status": "ok", "ingredients": ["inclisiran"], "classes": [["RNA, Small Interfering", "MEDRT"]]},
    "rosuvastatin": {"status": "ok", "ingredients": ["rosuvastatin"], "classes": [["HMG-CoA Reductase Inhibitor", "FDASPL"]]},
    "red yeast rice": {"status": "ok", "ingredients": ["red yeast rice"], "classes": [["ANTILIPEMIC AGENTS", "VA"]]},
    "fish oil": {"status": "ok", "ingredients": ["fish oils"], "classes": [["Dietary Supplements", "VA"]]},
}


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setattr(config, "FAILURES", {k: False for k in config.FAILURES})
    monkeypatch.setattr(rxnav, "lookup", lambda name: {"query": name, **RXNAV.get(name.lower(), {"status": "not_found", "ingredients": [], "classes": []})})
    monkeypatch.setattr(rxnav, "scan_text", lambda text, cid: [
        {"phrase": k, **e} for k, e in RXNAV.items() if k in text.lower() and rxnav.in_class(e, cid) == "yes"])
    spec, engine = sa.load_spec(), sa.load_engine()
    cases = {c.case_id: c for c in sa.load_cases() + sa.load_cases(config.DATA_DIR / "eng_cases" / "cases")}
    sa.install_store(list(cases.values()))
    rules = {r["id"]: r for r in spec["rules"]}

    def answer(obj):
        monkeypatch.setattr(llm, "structured_call", lambda *a, **k: obj)

    def run(case_id, cid):
        v0 = next(v for v in sa.evaluate_case(cases[case_id], spec, engine)[0] if v.criterion_id == cid)
        return interpret.interpret(cases[case_id], cid, rules[cid]["predicate"], rules[cid]["source_text"], v0)

    return type("E", (), {"spec": spec, "engine": engine, "cases": cases, "answer": staticmethod(answer),
                          "run": staticmethod(run)})


def smoking(**kw):
    base = dict(currently_smokes="yes", smokes_every_day="yes", cigarettes_on_a_smoking_day=10,
                smoking_days_per_week=None, quotes=["around 10 cigarettes, every day"], explanation="x")
    return interpret.SmokingFacts(**{**base, **kw})


def exposure(substance, quote, **kw):
    base = dict(in_class="no", prescription="yes", last_use_date=None, ongoing=False, why="w")
    return interpret.Exposure(substance=substance, quote=quote, **{**base, **kw})


# ---------- free text: smoking ----------

def test_daily_smoking_over_threshold_is_met_and_interpreted(env):
    env.answer(smoking())
    v = env.run("ENG02", "E3")
    assert v.status == "met" and v.interpreted and "10/day" in v.note


def test_intermittent_smoking_where_definitions_disagree_stays_unknown(env):
    env.answer(smoking(smokes_every_day="no", cigarettes_on_a_smoking_day=4.5, smoking_days_per_week=1.5,
                       quotes=["usually 4 or 5 cigarettes on a Friday or Saturday night"]))
    v = env.run("ENG01", "E3")
    assert v.status == "unknown" and "CRC to judge" in v.note


def test_fabricated_quote_is_not_used(env):
    env.answer(smoking(quotes=["smokes two packs a day"]))  # not in ENG02's text
    v = env.run("ENG02", "E3")
    assert v.status == "unknown" and "no supporting quote" in v.note


# ---------- free text: drug history ----------

def test_terminology_overrides_model_memory(env):
    # the model wrongly says Leqvio is not an siRNA; RxNav says inclisiran is
    env.answer(interpret.ExposureFacts(exposures=[exposure("Leqvio", "injection called Leqvio", in_class="no",
                                                            last_use_date="2026-03-12")], explicitly_none=False, explanation="x"))
    v = env.run("ENG04", "E4")
    assert v.status == "met" and "inclisiran" in v.note
    assert any(t["tool"] == "rxnav" and "model said no" in t["result"] for t in v.trace)


def test_drug_the_model_leaves_out_is_caught_by_the_terminology_scan(env):
    # observed live: the model omitted Leqvio entirely and claimed "explicitly none"
    env.answer(interpret.ExposureFacts(exposures=[], explicitly_none=True, explanation="x"))
    v = env.run("ENG04", "E4")
    assert v.status == "unknown" and "leqvio" in v.note.lower() and "not reported by the model" in v.note
    assert any(t["tool"] == "rule:terminology_scan" for t in v.trace)


def test_statin_before_window_and_otc_supplement_inside_it(env):
    env.answer(interpret.ExposureFacts(exposures=[
        exposure("rosuvastatin", "Stopped rosuvastatin 10 mg in early June 2026", in_class="yes", last_use_date="2026-06-01"),
        exposure("red yeast rice", "over-the-counter red yeast rice supplement every day", in_class="yes",
                 prescription="no", ongoing=True)], explicitly_none=False, explanation="x"))
    v = env.run("ENG03", "E5")
    assert v.status == "unknown"  # OTC lipid-lowering supplement in window: the CRC decides
    assert "needs CRC judgement: red yeast rice" in v.note and "not counted: rosuvastatin" in v.note


def test_negative_with_supplements_is_not_met(env):
    env.answer(interpret.ExposureFacts(exposures=[exposure("fish oil", "Takes fish oil capsules", prescription="no",
                                                            ongoing=True)], explicitly_none=False, explanation="x"))
    assert env.run("ENG05", "E5").status == "not_met"


def test_model_failure_keeps_rule_result(env, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("bedrock down")
    monkeypatch.setattr(llm, "structured_call", boom)
    v = env.run("ENG02", "E3")
    assert v.status == "unknown" and not v.interpreted and v.trace[-1]["tool"] == "agent:error"


# ---------- aggregation of interpreted verdicts ----------

def _screen_one(env, case_id, patch):
    verdicts = sa.evaluate_case(env.cases[case_id], env.spec, env.engine)[0]
    verdicts = [patch(v) if v.criterion_id in ("E3", "E4", "E5") and v.status == "unknown" else v for v in verdicts]
    return aggregate(case_id, sa.predicates(env.spec), verdicts, failed_first=True)


def test_interpreted_exclusion_goes_to_review_not_excluded(env):
    env.answer(smoking())
    r = _screen_one(env, "ENG02", lambda v: env.run("ENG02", "E3"))
    assert r.category == "needs_review" and "agent reading suggests exclusion" in r.reasons[0]


def test_interpreted_pass_keeps_patient_with_confirmation(env):
    env.answer(interpret.ExposureFacts(exposures=[], explicitly_none=True, explanation="x"))
    r = _screen_one(env, "ENG05", lambda v: env.run("ENG05", "E5"))
    assert r.category == "likely_eligible" and any("from free text" in c for c in r.confirm_at_visit)


# ---------- conflicts ----------

def _conflict(env, case_id):
    v = next(v for v in sa.evaluate_case(env.cases[case_id], env.spec, env.engine)[0] if v.conflict)
    return conflict.explain(env.cases[case_id], env.spec, v, env.engine)


def test_conflict_materiality_is_computed_by_the_engine(env):
    env.answer(conflict.ConflictNote(differences="d", likely_cause="c", what_to_check="w"))
    assert any(t["decision"] == "immaterial" for t in _conflict(env, "SAD07").trace)  # 90 and 110 both >= 70
    eng07 = _conflict(env, "ENG07")
    assert any(t["decision"] == "material" for t in eng07.trace) and eng07.conflict


def test_immaterial_conflict_resolves_material_one_stays_in_review(env, monkeypatch):
    env.answer(conflict.ConflictNote(differences="d", likely_cause="c", what_to_check="w"))
    monkeypatch.setattr(config, "IMMATERIAL_CONFLICT_RESOLVES", True)  # the decided default
    v = _conflict(env, "SAD07")
    assert v.status == "met" and not v.conflict and "resolved by rule" in v.note
    assert _conflict(env, "ENG07").status == "unknown" and _conflict(env, "ENG07").conflict
    monkeypatch.setattr(config, "IMMATERIAL_CONFLICT_RESOLVES", False)
    assert _conflict(env, "SAD07").status == "unknown"


# ---------- I5 evidence ----------

def _i5(env, case_id):
    v = next(v for v in sa.evaluate_case(env.cases[case_id], env.spec, env.engine)[0] if v.criterion_id == "I5")
    return evidence.evidence_pack(env.cases[case_id], v)  # conftest blanks the model: rules-only part


def test_abnormal_kidney_labs_route_to_review_even_without_the_model(env):
    v = _i5(env, "ENG06")
    assert v.status == "unknown" and v.review_reason
    assert "Creatinine" in v.recovery and any("1.9 mg/dL" in str(e["value"]) for e in v.evidence)


def test_missing_kidney_tests_are_listed_but_do_not_force_review(env):
    v = _i5(env, "SAD01")
    assert not v.review_reason and "no kidney function test" in v.recovery


def test_rules_only_still_matches_ming(env):
    results, *_ = sa.screen([env.cases[f"SAD0{i}"] for i in range(1, 9)], env.spec, use_agent=False)
    assert sorted(r.category for r in results) == sorted(
        ["likely_eligible"] * 2 + ["excluded"] * 4 + ["pending", "needs_review"])

import json
from pathlib import Path

import pytest

from src.adapters import fhir_store
from src.adapters.fhir_store import FhirStore

FIXTURES = Path(__file__).parent / "fixtures" / "patients"
LDL = [{"system": "http://loinc.org", "code": "18262-6", "display": "LDL-C"}]


@pytest.fixture(scope="module")
def store():
    return FhirStore(FIXTURES)


def test_loads_all_fixture_patients(store):
    assert store.list_patients() == ["fixture-alt-code", "fixture-complete", "fixture-missing-ldl", "fixture-over-age"]
    assert store.load_errors == []


def test_ldl_value_with_resource_id(store):
    r = store.fhir_query("fixture-complete", "Observation", LDL)
    assert r.status == "ok"
    assert [(x["resource_id"], x["value"], x["unit"]) for x in r.records] == [
        ("o-101", 162.4, "mg/dL"),  # most recent first
        ("o-102", 171.0, "mg/dL"),
    ]
    assert r.records[0]["date"].startswith("2026-08-20")


def test_unknown_code_is_empty_not_error(store):
    r = store.fhir_query("fixture-complete", "Observation", [{"system": "http://loinc.org", "code": "0000-0"}])
    assert r.status == "empty" and r.records == []


def test_missing_lab_is_empty(store):
    assert store.fhir_query("fixture-missing-ldl", "Observation", LDL).status == "empty"


def test_codes_are_or_and_system_aliases_work(store):
    codes = [{"system": "LOINC", "code": "13457-7"}, {"system": "loinc", "code": "18262-6"}]
    assert len(store.fhir_query("fixture-complete", "Observation", codes).records) == 2


def test_system_must_match(store):
    r = store.fhir_query("fixture-complete", "Observation", [{"system": "http://snomed.info/sct", "code": "18262-6"}])
    assert r.status == "empty"


def test_window_relative_to_anchor(store):
    r = store.fhir_query("fixture-complete", "Observation", LDL, window_days=180, anchor_date="2026-10-09")
    assert [x["resource_id"] for x in r.records] == ["o-101"]
    r = store.fhir_query("fixture-complete", "Observation", LDL, window_days=30, anchor_date="2026-10-09")
    assert r.status == "empty"


def test_bp_component_codes(store):
    r = store.fhir_query("fixture-complete", "Observation", [{"system": "http://loinc.org", "code": "8480-6"}])
    assert [(x["code"], x["value"], x["unit"]) for x in r.records] == [("8480-6", 142, "mm[Hg]")]
    panel = store.fhir_query("fixture-complete", "Observation", [{"system": "http://loinc.org", "code": "85354-9"}])
    assert sorted(x["code"] for x in panel.records) == ["8462-4", "8480-6"]


def test_condition_and_medication_carry_status(store):
    c = store.fhir_query("fixture-complete", "Condition", [{"system": "SNOMED", "code": "59621000"}])
    assert c.records[0]["resource_id"] == "c-101" and c.records[0]["status"] == "active"
    m = store.fhir_query("fixture-complete", "MedicationRequest", [{"system": "RxNorm", "code": "312961"}])
    assert m.records[0]["status"] == "stopped"


def test_patient_birth_date(store):
    r = store.fhir_query("fixture-over-age", "Patient.birthDate", [])
    assert r.records[0]["value"] == "1944-11-02"


def test_no_allergy_records_is_empty(store):
    r = store.fhir_query("fixture-complete", "AllergyIntolerance", [{"system": "SNOMED", "code": "293472002"}])
    assert r.status == "empty"


def test_search_notes_finds_value_in_text(store):
    r = store.search_notes("fixture-missing-ldl", ["LDL"])
    assert r.status == "ok"
    assert r.records[0]["resource_id"] == "d-301"
    assert "158 mg/dL" in r.records[0]["value"]
    assert store.search_notes("fixture-complete", ["LDL"]).status == "empty"


def test_bad_inputs_are_malformed_not_raised(store):
    assert store.fhir_query("nobody", "Observation", LDL).status == "malformed"
    assert store.fhir_query("fixture-complete", "Encounter", LDL).status == "malformed"
    assert store.fhir_query("fixture-complete", "Observation", []).status == "malformed"
    assert store.search_notes("fixture-complete", []).status == "malformed"


def test_observation_without_value_is_malformed(tmp_path):
    bundle = json.loads((FIXTURES / "fixture-complete.json").read_text())
    for e in bundle["entry"]:
        if e["resource"]["id"] in ("o-101", "o-102"):
            del e["resource"]["valueQuantity"]
    (tmp_path / "p.json").write_text(json.dumps(bundle))
    r = FhirStore(tmp_path).fhir_query("fixture-complete", "Observation", LDL)
    assert r.status == "malformed" and "o-101" in r.detail


def test_non_patient_bundles_are_skipped(tmp_path):
    (tmp_path / "hospitalInformation.json").write_text(json.dumps({"resourceType": "Bundle", "entry": []}))
    (tmp_path / "broken.json").write_text("{not json")
    s = FhirStore(tmp_path)
    assert s.list_patients() == [] and len(s.load_errors) == 2


def test_list_patients_since(store):
    assert store.list_patients(since_date="2026-08-01") == ["fixture-alt-code", "fixture-complete", "fixture-missing-ldl"]


def test_module_api_wraps_store(store):
    fhir_store.set_store(store)
    assert fhir_store.fhir_query("fixture-complete", "Observation", LDL).status == "ok"
    assert fhir_store.list_patients()[0] == "fixture-alt-code"

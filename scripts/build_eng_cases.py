"""Build engineering-authored SAD cases for the situations Ming's 8 cases do not cover.

Each case starts from Ming's passing case SAD01 (every structured criterion met), gets fresh
deterministic IDs, and then one deliberate change: free-text history answers her rule pack
cannot read, hepatic/renal evidence relevant to I5, or a conflict that changes the outcome.
Ming's files are only read. Output: data/eng_cases/{cases,context}/ENGxx.json.

    python scripts/build_eng_cases.py
"""

import copy
import json
import re
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "t6_sad_demo" / "data"
OUT = ROOT / "data" / "eng_cases"
NS = uuid.UUID("6f1c2d3e-0000-4000-8000-00000000e9c5")
LOINC, SNOMED, UCUM = "http://loinc.org", "http://snomed.info/sct", "http://unitsofmeasure.org"
TAG = {"tag": [{"system": "https://example.org/prescreen-agent", "code": "engineering-authored-synthetic"}]}

CASES = {
    "ENG01": "smoking described only in free text, intermittent weekend smoking (boundary of 'regular')",
    "ENG02": "smoking described only in free text, clearly daily",
    "ENG03": "lipid-lowering history in free text: statin stopped before the window, OTC red yeast rice inside it",
    "ENG04": "advanced-therapy history in free text naming a brand (Leqvio = inclisiran, an siRNA)",
    "ENG05": "lipid-lowering history in free text, negative with OTC supplements",
    "ENG06": "I5 evidence: normal ALT/AST but reduced kidney function, CKD diagnosis and hepatic steatosis note",
    "ENG07": "two conflicting LDL results that straddle the 70 mg/dL threshold",
}


def remap(bundle: dict, ctx: dict, case_id: str) -> tuple[dict, dict]:
    """Replace every UUID with a deterministic new one so cases never collide with Ming's."""
    text = json.dumps(bundle)
    ids = set(re.findall(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", text))
    mapping = {old: str(uuid.uuid5(NS, f"{case_id}:{old}")) for old in ids}
    for old, new in mapping.items():
        text = text.replace(old, new)
    ctx = dict(ctx, case_id=case_id, FHIR_file=f"cases/{case_id}.json",
               patient_id=mapping[ctx["patient_id"]], encounter_id=mapping[ctx["encounter_id"]],
               history_id=mapping[ctx["history_id"]],
               data_scope="Engineering-authored synthetic case derived from Ming's SAD01; not Ming's data")
    return json.loads(text), ctx


def resource(bundle: dict, rtype: str) -> list[dict]:
    return [e["resource"] for e in bundle["entry"] if e["resource"]["resourceType"] == rtype]


def questionnaire(bundle: dict) -> dict:
    return resource(bundle, "QuestionnaireResponse")[0]


def set_answers(qr: dict, drop: list[str], add: dict[str, str]) -> None:
    qr["item"] = [i for i in qr["item"] if i["linkId"] not in drop]
    qr["item"] += [{"linkId": k, "answer": [{"valueString": v}]} for k, v in add.items()]


def add(bundle: dict, res: dict, case_id: str) -> None:
    res["id"] = str(uuid.uuid5(NS, f"{case_id}:{res['resourceType']}:{len(bundle['entry'])}"))
    res["meta"] = TAG
    bundle["entry"].append({"fullUrl": f"urn:uuid:{res['id']}", "resource": res})


def lab(patient: str, encounter: str, when: str, code: str, display: str, value, unit: str, low=None, high=None) -> dict:
    rng = {}
    if low is not None:
        rng["low"] = {"value": low, "unit": unit, "system": UCUM, "code": unit}
    if high is not None:
        rng["high"] = {"value": high, "unit": unit, "system": UCUM, "code": unit}
    return {"resourceType": "Observation", "status": "final",
            "code": {"coding": [{"system": LOINC, "code": code, "display": display}]},
            "subject": {"reference": patient}, "encounter": {"reference": encounter}, "effectiveDateTime": when,
            "valueQuantity": {"value": value, "unit": unit, "system": UCUM, "code": unit},
            "referenceRange": [rng] if rng else []}


def build(case_id: str, bundle: dict, ctx: dict) -> None:
    qr = questionnaire(bundle)
    patient, encounter = f"urn:uuid:{ctx['patient_id']}", f"urn:uuid:{ctx['encounter_id']}"
    when = ctx["screening_at"]
    if case_id == "ENG01":
        set_answers(qr, ["current_smoker", "smoking_pattern", "cigarettes_day", "cigarettes_week"], {
            "smoking_pattern": "see_free_text",
            "smoking_free_text": "Quit daily smoking in July. Since then only smokes when out with friends, usually "
                                 "4 or 5 cigarettes on a Friday or Saturday night, most weekends."})
    elif case_id == "ENG02":
        set_answers(qr, ["current_smoker", "smoking_pattern", "cigarettes_day", "cigarettes_week"], {
            "smoking_pattern": "see_free_text",
            "smoking_free_text": "Smokes about half a pack a day, around 10 cigarettes, every day for the past five "
                                 "years. Has not tried to quit."})
    elif case_id == "ENG03":
        set_answers(qr, ["lipid_exposure"], {
            "lipid_free_text": "Stopped rosuvastatin 10 mg in early June 2026 because of muscle aches. Since August "
                               "takes an over-the-counter red yeast rice supplement every day."})
    elif case_id == "ENG04":
        set_answers(qr, ["advanced_exposure"], {
            "advanced_free_text": "Received a twice-yearly cholesterol injection called Leqvio at the cardiology "
                                  "clinic on 2026-03-12; the next dose was planned for September but not given."})
    elif case_id == "ENG05":
        set_answers(qr, ["lipid_exposure"], {
            "lipid_free_text": "No cholesterol medicines from a doctor. Takes fish oil capsules and vitamin D from "
                               "the supermarket."})
    elif case_id == "ENG06":
        add(bundle, lab(patient, encounter, when, "2160-0", "Creatinine [Mass/volume] in Serum or Plasma",
                        1.9, "mg/dL", 0.6, 1.2), case_id)
        add(bundle, lab(patient, encounter, when, "33914-3", "Glomerular filtration rate/1.73 sq M.predicted",
                        38, "mL/min/{1.73_m2}", 60, None), case_id)
        add(bundle, {"resourceType": "Condition",
                     "clinicalStatus": {"coding": [{"code": "active"}]},
                     "code": {"coding": [{"system": SNOMED, "code": "433144002",
                                          "display": "Chronic kidney disease stage 3"}]},
                     "subject": {"reference": patient}, "onsetDateTime": "2024-05-02"}, case_id)
        add(bundle, {"resourceType": "DocumentReference", "status": "current", "date": "2025-11-20T10:00:00-05:00",
                     "subject": {"reference": patient},
                     "content": [{"attachment": {"contentType": "text/plain", "data": __import__("base64").b64encode(
                         b"Abdominal ultrasound 2025-11-20: diffuse hepatic steatosis, no focal lesion. "
                         b"Kidneys slightly small bilaterally.").decode()}}]}, case_id)
    elif case_id == "ENG07":
        ldl = [o for o in resource(bundle, "Observation") if o["code"]["coding"][0]["code"] == "18262-6"][0]
        ldl["valueQuantity"]["value"] = 65
        second = copy.deepcopy(ldl)
        second["valueQuantity"]["value"] = 85
        add(bundle, second, case_id)


def main() -> None:
    template = json.loads((SRC / "cases" / "SAD01.json").read_text(encoding="utf-8"))
    template_ctx = json.loads((SRC / "context" / "SAD01.json").read_text(encoding="utf-8"))
    for d in ("cases", "context"):
        (OUT / d).mkdir(parents=True, exist_ok=True)
    for case_id, purpose in CASES.items():
        bundle, ctx = remap(copy.deepcopy(template), dict(template_ctx), case_id)
        ctx["purpose"] = purpose
        build(case_id, bundle, ctx)
        (OUT / "cases" / f"{case_id}.json").write_text(json.dumps(bundle, indent=2), encoding="utf-8")
        (OUT / "context" / f"{case_id}.json").write_text(json.dumps(ctx, indent=2), encoding="utf-8")
    (OUT / "README.md").write_text(
        "# Engineering-authored SAD cases\n\nNot Ming's data and not ground truth. Built by "
        "`scripts/build_eng_cases.py` from Ming's SAD01 to exercise what her 8 cases do not cover.\n\n"
        + "\n".join(f"- **{k}**: {v}" for k, v in CASES.items()) + "\n", encoding="utf-8")
    print(f"wrote {len(CASES)} cases to {OUT}")


if __name__ == "__main__":
    main()

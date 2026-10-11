"""Build the extended SAD scenario set: situations the 8 core screening cases do not cover.

Each case starts from core case SAD01 (every structured criterion met), gets fresh
deterministic IDs, and then one deliberate change: free-text history answers the rule pack
cannot read, hepatic/renal evidence relevant to I5, or a conflict that changes the outcome.
The core files are only read. Output: data/extended_cases/{cases,context}/EXTxx.json.

    python scripts/build_extended_cases.py
"""

import copy
import json
import re
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "trials/nct07347678_sad" / "data"
OUT = ROOT / "data" / "extended_cases"
NS = uuid.UUID("6f1c2d3e-0000-4000-8000-00000000e9c5")
LOINC, SNOMED, UCUM = "http://loinc.org", "http://snomed.info/sct", "http://unitsofmeasure.org"
TAG = {"tag": [{"system": "https://example.org/prescreen-agent", "code": "extended-scenario-synthetic"}]}

CASES = {
    "EXT01": "smoking described only in free text, intermittent weekend smoking (boundary of 'regular')",
    "EXT02": "smoking described only in free text, clearly daily",
    "EXT03": "lipid-lowering history in free text: statin stopped before the window, OTC red yeast rice inside it",
    "EXT04": "advanced-therapy history in free text naming a brand (Leqvio = inclisiran, an siRNA)",
    "EXT05": "lipid-lowering history in free text, negative with OTC supplements",
    "EXT06": "I5 evidence: normal ALT/AST but reduced kidney function, CKD diagnosis and hepatic steatosis note",
    "EXT07": "two conflicting LDL results that straddle the 70 mg/dL threshold",
}


# EXT08+ : (purpose, design-intended patient category under the current rules with the agent on,
#          target criterion, its design-intended status or None when the truth is genuinely ambiguous,
#          modifications). The intent is written down before running anything; it is the scenario's
#          design intent, not clinical ground truth.
SCENARIOS = {
    # free text: smoking (E3)
    "EXT08": ("smoking free text: about a pack a week, most days", "excluded", "E3", "met",
              {"smoking": "Smokes roughly a pack a week, a few cigarettes most days after work."}),
    "EXT09": ("smoking free text: quit years ago", "likely_eligible", "E3", "not_met",
              {"smoking": "Quit smoking in 2019 and has not had a cigarette since."}),
    "EXT10": ("smoking free text: vapes nicotine daily, no cigarettes (protocol counts cigarettes)", None, "E3", None,
              {"smoking": "Uses a nicotine vape every day; stopped cigarettes two years ago."}),
    "EXT11": ("smoking free text: one or two every day (<=2/day but >10/week)", "excluded", "E3", "met",
              {"smoking": "One or two cigarettes a day, every day."}),
    "EXT12": ("smoking free text: one cigar at a wedding", "likely_eligible", "E3", "not_met",
              {"smoking": "Smoked one cigar at a wedding last month; otherwise does not smoke."}),
    # free text: lipid-lowering drugs (E5, 30 days, prescription)
    "EXT13": ("drug free text: brand statin stopped inside the 30-day window", "excluded", "E5", "met",
              {"lipid": "Was on Lipitor 20 mg until 2026-09-25, then stopped on own."}),
    "EXT14": ("drug free text: ezetimibe ongoing", "excluded", "E5", "met",
              {"lipid": "Takes ezetimibe 10 mg every day."}),
    "EXT15": ("drug free text: statin stopped well before the window", "likely_eligible", "E5", "not_met",
              {"lipid": "Stopped simvastatin in May 2026 and has taken nothing for cholesterol since."}),
    "EXT16": ("drug free text: 'a cholesterol tablet', name unknown", "pending", "E5", None,
              {"lipid": "Takes a cholesterol tablet every morning but cannot remember the name."}),
    "EXT17": ("drug free text: Repatha (evolocumab, a PCSK9 antibody) inside the window", "excluded", "E5", "met",
              {"lipid": "Gets Repatha injections every two weeks; the last one was on 2026-10-01."}),
    # free text: advanced therapies (E4, 12 months)
    "EXT18": ("drug free text: gene therapy trial in 2023 (outside 12 months)", "likely_eligible", "E4", "not_met",
              {"advanced": "Took part in a gene therapy study for a blood disorder in 2023; nothing since."}),
    "EXT19": ("drug free text: Kynamro (mipomersen, an ASO) until January 2026", "excluded", "E4", "met",
              {"advanced": "Was given Kynamro injections until January 2026."}),
    "EXT20": ("drug free text: explicitly none", "likely_eligible", "E4", "not_met",
              {"advanced": "No injections or experimental treatments in the past year."}),
    # structured values
    "EXT21": ("clean pass, LDL 120", "likely_eligible", "I2", "met", {"obs": {"18262-6": 120, "43583-4": 80}}),
    "EXT22": ("clean pass, LDL 85", "likely_eligible", "I2", "met", {"obs": {"18262-6": 85}}),
    "EXT23": ("clean pass, age 30, LDL 140", "likely_eligible", "I2", "met", {"obs": {"18262-6": 140}, "birth": "1996-04-02"}),
    "EXT24": ("BMI 36 (above 35)", "excluded", "I1", "not_met", {"obs": {"39156-5": 36}}),
    "EXT25": ("BMI 17.5 (below 18)", "excluded", "I1", "not_met", {"obs": {"39156-5": 17.5}}),
    "EXT26": ("BMI exactly 35 (inclusive)", "likely_eligible", "I1", "met", {"obs": {"39156-5": 35}}),
    "EXT27": ("BMI exactly 18 (inclusive)", "likely_eligible", "I1", "met", {"obs": {"39156-5": 18}}),
    "EXT28": ("LDL 1.81 mmol/L = protocol's own equivalent of 70 mg/dL", "likely_eligible", "I2", "met",
              {"obs_unit": {"18262-6": (1.81, "mmol/L")}}),
    "EXT29": ("LDL 1.80 mmol/L, just below", "excluded", "I2", "not_met", {"obs_unit": {"18262-6": (1.80, "mmol/L")}}),
    "EXT30": ("Lp(a) exactly 25 nmol/L", "likely_eligible", "I3", "met", {"obs": {"43583-4": 25}}),
    "EXT31": ("Lp(a) 24 nmol/L", "excluded", "I3", "not_met", {"obs": {"43583-4": 24}}),
    "EXT32": ("TG exactly 400 mg/dL (must be <400)", "excluded", "I4", "not_met", {"obs": {"2571-8": 400}}),
    "EXT33": ("TG 4.5 mmol/L = 398.6 mg/dL", "likely_eligible", "I4", "met", {"obs_unit": {"2571-8": (4.5, "mmol/L")}}),
    "EXT34": ("ALT 61 U/L > 1.5 x ULN 40", "excluded", "E1", "met", {"obs": {"1742-6": 61}}),
    "EXT35": ("AST 55 U/L > 1.5 x ULN 35", "excluded", "E1", "met", {"obs": {"1920-8": 55}}),
    "EXT36": ("HbA1c exactly 6.5 %", "excluded", "E2", "met", {"obs": {"4548-4": 6.5}}),
    "EXT37": ("HbA1c 6.4 %", "likely_eligible", "E2", "not_met", {"obs": {"4548-4": 6.4}}),
    "EXT38": ("age 66 at screening", "excluded", "AGE", "not_met", {"birth": "1960-06-15"}),
    "EXT39": ("turns 65 on the screening day (inclusive)", "likely_eligible", "AGE", "met", {"birth": "1961-10-09"}),
    "EXT40": ("age 17", "excluded", "AGE", "not_met", {"birth": "2009-02-11"}),
    # missing data, recovery, guards
    "EXT41": ("fasting state not recorded for the lipid specimen", "pending", "I2", None, {"fasting": None}),
    "EXT42": ("HbA1c not drawn", "pending", "E2", None, {"drop": ["4548-4"]}),
    "EXT43": ("LDL recorded only as calculated LDL (13457-7), 95 mg/dL", "likely_eligible", "I2", "met",
              {"recode": {"18262-6": ("13457-7", 95)}}),
    "EXT44": ("LDL 900 mg/dL (data-entry error)", "pending", "I2", None, {"obs": {"18262-6": 900}}),
    # I5 evidence
    "EXT45": ("I5: total bilirubin 3.1 mg/dL (range 0.1-1.2)", "needs_review", "I5", None,
              {"lab": ("1975-2", "Bilirubin.total [Mass/volume] in Serum or Plasma", 3.1, "mg/dL", 0.1, 1.2)}),
    "EXT46": ("I5: cirrhosis on the problem list", "needs_review", "I5", None,
              {"condition": ("19943007", "Cirrhosis of liver")}),
    "EXT47": ("I5: normal creatinine and eGFR present (should not be flagged)", "likely_eligible", "I5", None,
              {"lab": ("2160-0", "Creatinine [Mass/volume] in Serum or Plasma", 0.9, "mg/dL", 0.6, 1.2),
               "lab2": ("33914-3", "Glomerular filtration rate/1.73 sq M.predicted", 95, "mL/min/{1.73_m2}", 60, None)}),
    # conflicts
    "EXT48": ("two TG results 150 and 410 (choice changes I4)", "needs_review", "I4", None, {"dup": ("2571-8", 410)}),
    "EXT49": ("two BMI results 22 and 24 (choice does not matter)", "likely_eligible", "I1", "met", {"dup": ("39156-5", 24)}),
    "EXT50": ("two ALT results 25 and 30 (choice does not matter)", "likely_eligible", "E1", "not_met", {"dup": ("1742-6", 30)}),
}
DESIGN_ENG = {  # design intent for the original seven
    "EXT01": ("pending", "E3", None), "EXT02": ("excluded", "E3", "met"), "EXT03": ("pending", "E5", None),
    "EXT04": ("excluded", "E4", "met"), "EXT05": ("likely_eligible", "E5", "not_met"),
    "EXT06": ("needs_review", "I5", None), "EXT07": ("needs_review", "I2", None),
}
GIVEN = ["Ana", "Ben", "Chen", "Dara", "Eli", "Fatima", "Gus", "Hana", "Ivan", "Jade", "Kofi", "Lena", "Mateo", "Nia"]
FAMILY = ["Okafor", "Silva", "Novak", "Haddad", "Tanaka", "Moreau", "Lindqvist", "Reyes", "Kowalski", "Osei"]


def remap(bundle: dict, ctx: dict, case_id: str) -> tuple[dict, dict]:
    """Replace every UUID with a deterministic new one so cases never collide with the core set."""
    text = json.dumps(bundle)
    ids = set(re.findall(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", text))
    mapping = {old: str(uuid.uuid5(NS, f"{case_id}:{old}")) for old in ids}
    for old, new in mapping.items():
        text = text.replace(old, new)
    ctx = dict(ctx, case_id=case_id, FHIR_file=f"cases/{case_id}.json",
               patient_id=mapping[ctx["patient_id"]], encounter_id=mapping[ctx["encounter_id"]],
               history_id=mapping[ctx["history_id"]],
               data_scope="Synthetic extended-scenario case derived from core case SAD01")
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
    if case_id == "EXT01":
        set_answers(qr, ["current_smoker", "smoking_pattern", "cigarettes_day", "cigarettes_week"], {
            "smoking_pattern": "see_free_text",
            "smoking_free_text": "Quit daily smoking in July. Since then only smokes when out with friends, usually "
                                 "4 or 5 cigarettes on a Friday or Saturday night, most weekends."})
    elif case_id == "EXT02":
        set_answers(qr, ["current_smoker", "smoking_pattern", "cigarettes_day", "cigarettes_week"], {
            "smoking_pattern": "see_free_text",
            "smoking_free_text": "Smokes about half a pack a day, around 10 cigarettes, every day for the past five "
                                 "years. Has not tried to quit."})
    elif case_id == "EXT03":
        set_answers(qr, ["lipid_exposure"], {
            "lipid_free_text": "Stopped rosuvastatin 10 mg in early June 2026 because of muscle aches. Since August "
                               "takes an over-the-counter red yeast rice supplement every day."})
    elif case_id == "EXT04":
        set_answers(qr, ["advanced_exposure"], {
            "advanced_free_text": "Received a twice-yearly cholesterol injection called Leqvio at the cardiology "
                                  "clinic on 2026-03-12; the next dose was planned for September but not given."})
    elif case_id == "EXT05":
        set_answers(qr, ["lipid_exposure"], {
            "lipid_free_text": "No cholesterol medicines from a doctor. Takes fish oil capsules and vitamin D from "
                               "the supermarket."})
    elif case_id == "EXT06":
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
    elif case_id == "EXT07":
        ldl = [o for o in resource(bundle, "Observation") if o["code"]["coding"][0]["code"] == "18262-6"][0]
        ldl["valueQuantity"]["value"] = 65
        second = copy.deepcopy(ldl)
        second["valueQuantity"]["value"] = 85
        add(bundle, second, case_id)


def obs_by_code(bundle: dict, code: str) -> list[dict]:
    return [o for o in resource(bundle, "Observation") if o["code"]["coding"][0]["code"] == code]


def apply(case_id: str, bundle: dict, ctx: dict, mods: dict) -> None:
    qr = questionnaire(bundle)
    patient, encounter = f"urn:uuid:{ctx['patient_id']}", f"urn:uuid:{ctx['encounter_id']}"
    when = ctx["screening_at"]
    n = int(case_id[3:])
    p = resource(bundle, "Patient")[0]
    p["name"] = [{"given": [GIVEN[n % len(GIVEN)]], "family": FAMILY[n % len(FAMILY)]}]
    p["gender"] = "female" if n % 2 else "male"
    if "birth" in mods:
        p["birthDate"] = mods["birth"]
    for key, field, drop in [("smoking", "smoking_free_text", ["current_smoker", "smoking_pattern", "cigarettes_day", "cigarettes_week"]),
                             ("lipid", "lipid_free_text", ["lipid_exposure"]),
                             ("advanced", "advanced_free_text", ["advanced_exposure"])]:
        if key in mods:
            extra = {"smoking_pattern": "see_free_text"} if key == "smoking" else {}
            set_answers(qr, drop, {**extra, field: mods[key]})
    for code, value in mods.get("obs", {}).items():
        obs_by_code(bundle, code)[0]["valueQuantity"]["value"] = value
    for code, (value, unit) in mods.get("obs_unit", {}).items():
        obs_by_code(bundle, code)[0]["valueQuantity"].update(value=value, unit=unit, code=unit)
    for code, (new_code, value) in mods.get("recode", {}).items():
        o = obs_by_code(bundle, code)[0]
        o["code"] = {"coding": [{"system": LOINC, "code": new_code, "display": "Cholesterol in LDL [Mass/volume] in Serum or Plasma by calculation"}]}
        o["valueQuantity"]["value"] = value
    for code in mods.get("drop", []):
        ids = {o["id"] for o in obs_by_code(bundle, code)}
        bundle["entry"] = [e for e in bundle["entry"] if e["resource"].get("id") not in ids]
    if "fasting" in mods:
        resource(bundle, "Specimen")[0]["collection"].pop("fastingStatusDuration", None)
    for key in ("lab", "lab2"):
        if key in mods:
            code, display, value, unit, low, high = mods[key]
            add(bundle, lab(patient, encounter, when, code, display, value, unit, low, high), case_id)
    if "condition" in mods:
        code, display = mods["condition"]
        add(bundle, {"resourceType": "Condition", "clinicalStatus": {"coding": [{"code": "active"}]},
                     "code": {"coding": [{"system": SNOMED, "code": code, "display": display}]},
                     "subject": {"reference": patient}, "onsetDateTime": "2025-02-14"}, case_id)
    if "dup" in mods:
        code, value = mods["dup"]
        second = copy.deepcopy(obs_by_code(bundle, code)[0])
        second["valueQuantity"]["value"] = value
        add(bundle, second, case_id)


def main() -> None:
    template = json.loads((SRC / "cases" / "SAD01.json").read_text(encoding="utf-8"))
    template_ctx = json.loads((SRC / "context" / "SAD01.json").read_text(encoding="utf-8"))
    for d in ("cases", "context"):
        (OUT / d).mkdir(parents=True, exist_ok=True)
    design = []
    for case_id in list(CASES) + list(SCENARIOS):
        bundle, ctx = remap(copy.deepcopy(template), dict(template_ctx), case_id)
        if case_id in CASES:
            ctx["purpose"] = CASES[case_id]
            build(case_id, bundle, ctx)
            category, target, status = DESIGN_ENG[case_id]
        else:
            ctx["purpose"], category, target, status, mods = SCENARIOS[case_id]
            apply(case_id, bundle, ctx, mods)
        ctx["design_category"], ctx["design_target"], ctx["design_target_status"] = category, target, status
        design.append((case_id, ctx["purpose"], category, target, status))
        (OUT / "cases" / f"{case_id}.json").write_text(json.dumps(bundle, indent=2), encoding="utf-8")
        (OUT / "context" / f"{case_id}.json").write_text(json.dumps(ctx, indent=2), encoding="utf-8")

    # Design-intent labels in the evaluation format (eval/evaluate.py). Only what the design settles:
    # the target criterion when its truth is unambiguous, and the patient when the intended category
    # is excluded or likely eligible.
    with (OUT / "design_labels.csv").open("w", encoding="utf-8") as f:
        f.write("patient_id,criterion_id,expected\n")
        for case_id, _, category, target, status in design:
            if status:
                f.write(f"{case_id},{target},{status}\n")
            if category in ("excluded", "likely_eligible"):
                f.write(f"{case_id},PATIENT,{'not_eligible' if category == 'excluded' else 'eligible'}\n")
    # Planted flips under the sample amendment (SAD LDL-C threshold 70 -> 100): every case designed to be
    # likely eligible whose LDL-C (mg/dL, after conversion) is below 100.
    def ldl(case_id):
        mods = SCENARIOS.get(case_id, (None,) * 5)[4] or {}
        if "18262-6" in mods.get("obs_unit", {}):
            v, unit = mods["obs_unit"]["18262-6"]
            return round(v * 38.67, 1)
        if "18262-6" in mods.get("recode", {}):
            return mods["recode"]["18262-6"][1]
        return mods.get("obs", {}).get("18262-6", 90)
    flips = [c for c, _, cat, _, _ in design if cat == "likely_eligible" and ldl(c) < 100]
    (OUT / "design_amendment_flips.txt").write_text("\n".join(flips) + "\n", encoding="utf-8")
    (OUT / "README.md").write_text(
        "# Extended SAD scenario set\n\n"
        "Synthetic, and not clinical ground truth. Generated deterministically by `scripts/build_extended_cases.py` "
        "from core case SAD01 (structure, encounter, specimen, questionnaire), with fresh IDs and one deliberate "
        "change per case, to cover what the 8 core cases do not: every criterion on both sides of its threshold, exact "
        "boundaries, unit conversion, missing data, free text written in different ways, I5 evidence and conflicts. "
        "Free text was written by hand, not by a model, so the agent is not graded on its own phrasing.\n\n"
        "`design_labels.csv` holds the design intent, written before any run: the target criterion's expected status "
        "(when unambiguous) and the patient's expected eligibility (when the intended category is excluded or likely "
        "eligible). It measures whether the pipeline does what the cases were built to test.\n\n"
        "| Case | Purpose | Intended category | Target | Intended status |\n|---|---|---|---|---|\n"
        + "\n".join(f"| {c} | {p} | {cat or 'ambiguous'} | {t} | {st or '-'} |" for c, p, cat, t, st in design) + "\n",
        encoding="utf-8")
    print(f"wrote {len(design)} cases to {OUT}")


if __name__ == "__main__":
    main()

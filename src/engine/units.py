"""T5: unit normalisation and plausibility ranges.

Factors and ranges are from docs/TASKS.md (T5) and still need Ming's review.
A value that cannot be converted, or lands outside its plausible range after
conversion, is rejected; the engine then returns `unknown` with the reason.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Analyte:
    name: str
    loinc: frozenset[str]
    unit: str  # standard unit
    convert: dict[str, float]  # other unit -> factor to standard
    low: float
    high: float


LIPID_MMOL_TO_MG = 38.67
TG_MMOL_TO_MG = 88.57

ANALYTES = [
    Analyte("LDL-C", frozenset({"18262-6", "13457-7", "2089-1"}), "mg/dL", {"mmol/L": LIPID_MMOL_TO_MG}, 10, 500),
    Analyte("Total cholesterol", frozenset({"2093-3"}), "mg/dL", {"mmol/L": LIPID_MMOL_TO_MG}, 10, 500),
    Analyte("HDL-C", frozenset({"2085-9"}), "mg/dL", {"mmol/L": LIPID_MMOL_TO_MG}, 10, 500),
    Analyte("Triglycerides", frozenset({"2571-8"}), "mg/dL", {"mmol/L": TG_MMOL_TO_MG}, 20, 5000),
    Analyte("Systolic BP", frozenset({"8480-6"}), "mmHg", {}, 60, 260),
    Analyte("Diastolic BP", frozenset({"8462-4"}), "mmHg", {}, 30, 160),
    Analyte("ALT", frozenset({"1742-6"}), "U/L", {}, 1, 2000),
]
_BY_CODE = {code: a for a in ANALYTES for code in a.loinc}

UNIT_SYNONYMS = {
    "mg/dl": "mg/dL",
    "mmol/l": "mmol/L",
    "mm[hg]": "mmHg", "mmhg": "mmHg", "mm hg": "mmHg",
    "u/l": "U/L", "iu/l": "U/L", "[iu]/l": "U/L",
    "kg/m2": "kg/m2", "kg/m^2": "kg/m2", "kg/(m2)": "kg/m2",
    "years": "years", "a": "years", "yr": "years",
}


def normalize_unit(unit: str | None) -> str | None:
    if unit is None:
        return None
    u = unit.strip()
    return UNIT_SYNONYMS.get(u.lower(), u)


def analyte_for(code: str | None) -> Analyte | None:
    return _BY_CODE.get(code or "")


@dataclass
class Converted:
    value: float | None
    reason: str | None = None  # set when value is None, or as a note on a successful conversion


def to_unit(value, unit: str | None, code: str | None, target_unit: str | None) -> Converted:
    """Convert one recorded value to the predicate's unit and range-check it."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return Converted(None, f"non-numeric value {value!r}")

    analyte = analyte_for(code)
    src = normalize_unit(unit)
    dst = normalize_unit(target_unit) or (analyte.unit if analyte else src)
    note = None

    if src == dst or (src is None and analyte is None):
        pass
    elif analyte and dst == analyte.unit and src in analyte.convert:
        factor = analyte.convert[src]
        note = f"converted {v:g} {src} x {factor} -> {round(v * factor, 2):g} {dst}"
        v = v * factor
    else:
        return Converted(None, f"cannot convert unit {unit!r} to {dst!r}")

    v = round(v, 2)  # keeps boundary comparisons stable after conversion
    if analyte and dst == analyte.unit and not (analyte.low <= v <= analyte.high):
        return Converted(None, f"{analyte.name} {v:g} {dst} outside plausible range {analyte.low:g}-{analyte.high:g}")
    return Converted(v, note)

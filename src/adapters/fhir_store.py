"""T3: file-based FHIR adapter over Synthea R4 bundles.

Reads data/patients/*.json (one transaction Bundle per patient) into memory and
answers FHIR-style queries. The function signatures mirror what a real FHIR
server client would expose, so this can be swapped out without touching the
engine.

Tools never raise to the caller: every query returns a QueryResult with
status ok | empty | timeout | malformed.

    python -m src.adapters.fhir_store                     # summary of loaded patients
    python -m src.adapters.fhir_store PATIENT_ID 18262-1  # LOINC lookup
"""

import argparse
import base64
import json
import logging
import re
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from pathlib import Path

from src import config

log = logging.getLogger(__name__)

LOINC = "http://loinc.org"
SNOMED = "http://snomed.info/sct"
RXNORM = "http://www.nlm.nih.gov/research/umls/rxnorm"
ATC = "http://www.whocc.no/atc"

# Predicates may name systems informally; normalise before matching.
SYSTEM_ALIASES = {
    "loinc": LOINC, LOINC: LOINC,
    "snomed": SNOMED, "snomedct": SNOMED, "snomed ct": SNOMED, "sct": SNOMED, SNOMED: SNOMED,
    "rxnorm": RXNORM, RXNORM: RXNORM,
    "atc": ATC, ATC: ATC,
}

QUERYABLE = {"Patient", "Condition", "Observation", "MedicationRequest", "AllergyIntolerance"}
LOADED = QUERYABLE | {"DocumentReference", "Medication"}


@dataclass
class QueryResult:
    status: str  # ok | empty | timeout | malformed
    records: list[dict] = field(default_factory=list)
    detail: str = ""


def norm_system(system: str) -> str:
    s = (system or "").strip()
    return SYSTEM_ALIASES.get(s.lower(), s)


def _day(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _first_code(concept: dict | None) -> str | None:
    for c in (concept or {}).get("coding", []):
        if c.get("code"):
            return c["code"]
    return None


def _matching_coding(concept: dict | None, wanted: set[tuple[str, str]]) -> dict | None:
    for c in (concept or {}).get("coding", []):
        if (norm_system(c.get("system", "")), str(c.get("code", "")).strip()) in wanted:
            return c
    return None


def _value(holder: dict) -> tuple[object, str | None] | None:
    """Value and unit from an Observation or one of its components."""
    if "valueQuantity" in holder:
        q = holder["valueQuantity"]
        if q.get("value") is None:
            return None
        return q["value"], q.get("unit") or q.get("code")
    if "valueCodeableConcept" in holder:
        cc = holder["valueCodeableConcept"]
        return cc.get("text") or _first_code(cc), None
    for key in ("valueString", "valueBoolean", "valueInteger"):
        if key in holder:
            return holder[key], None
    return None


def _when(res: dict) -> str | None:
    rt = res["resourceType"]
    if rt == "Observation":
        return res.get("effectiveDateTime") or (res.get("effectivePeriod") or {}).get("start") or res.get("issued")
    if rt in ("Condition", "AllergyIntolerance"):
        return res.get("onsetDateTime") or res.get("recordedDate")
    if rt == "MedicationRequest":
        return res.get("authoredOn")
    if rt == "DocumentReference":
        return res.get("date") or ((res.get("context") or {}).get("period") or {}).get("start")
    return None


def _status(res: dict) -> str | None:
    if "clinicalStatus" in res:
        return _first_code(res["clinicalStatus"])
    return res.get("status")


class FhirStore:
    def __init__(self, patient_dir: Path):
        self.patient_dir = Path(patient_dir)
        # patient_id -> resourceType -> [resources]
        self.index: dict[str, dict[str, list[dict]]] = {}
        self.load_errors: list[str] = []
        self._load()

    # ---------- loading ----------

    def _load(self) -> None:
        files = sorted(self.patient_dir.glob("*.json"))
        for path in files:
            try:
                bundle = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as e:
                self.load_errors.append(f"{path.name}: unreadable ({e})")
                continue
            resources = [e.get("resource") for e in bundle.get("entry", []) if isinstance(e.get("resource"), dict)]
            patients = [r for r in resources if r.get("resourceType") == "Patient"]
            if len(patients) != 1:
                # Synthea also writes hospital/practitioner bundles with no Patient.
                self.load_errors.append(f"{path.name}: {len(patients)} Patient resources, skipped")
                continue
            pid = patients[0]["id"]
            by_type: dict[str, list[dict]] = defaultdict(list)
            for r in resources:
                if r.get("resourceType") in LOADED:
                    by_type[r["resourceType"]].append(r)
            self.index[pid] = by_type
        log.info("loaded %d patients from %s (%d skipped)", len(self.index), self.patient_dir, len(self.load_errors))

    # ---------- queries ----------

    def list_patients(self, since_date: str | None = None) -> list[str]:
        """All patient IDs, or only those with any dated record on/after since_date."""
        if not since_date:
            return sorted(self.index)
        since = _day(since_date)
        out = []
        for pid, by_type in self.index.items():
            if any((d := _day(_when(r))) and d >= since for rs in by_type.values() for r in rs):
                out.append(pid)
        return sorted(out)

    def fhir_query(self, patient_id: str, resource: str, codes: list[dict],
                   window_days: int | None = None, anchor_date: str | None = None) -> QueryResult:
        resource = resource.split(".")[0]  # "Patient.birthDate" -> "Patient"
        if patient_id not in self.index:
            return QueryResult("malformed", detail=f"unknown patient {patient_id!r}")
        if resource not in QUERYABLE:
            return QueryResult("malformed", detail=f"unsupported resource {resource!r}; expected one of {sorted(QUERYABLE)}")
        by_type = self.index[patient_id]

        if resource == "Patient":
            p = by_type["Patient"][0]
            if not p.get("birthDate"):
                return QueryResult("malformed", detail="Patient has no birthDate")
            records = [
                {"resource_id": p["id"], "code": "birthDate", "value": p["birthDate"], "unit": None, "date": p["birthDate"]},
                {"resource_id": p["id"], "code": "gender", "value": p.get("gender"), "unit": None, "date": None},
            ]
            return QueryResult("ok", records)

        wanted = {(norm_system(c.get("system", "")), str(c.get("code", "")).strip()) for c in codes or [] if c.get("code")}
        if not wanted:
            return QueryResult("malformed", detail="no codes given")

        records, unparsable = [], []
        for res in by_type.get(resource, []):
            if resource == "Observation":
                found = self._observation_records(res, wanted)
            else:
                found = self._coded_record(res, wanted, by_type)
            if found is None:
                unparsable.append(res.get("id", "?"))
            else:
                records.extend(found)

        notes = []
        if unparsable:
            notes.append(f"matched but unparsable: {', '.join(unparsable)}")
        if window_days is not None:
            anchor = _day(anchor_date or config.SCREENING_DATE)
            if anchor is None:
                return QueryResult("malformed", detail=f"bad anchor_date {anchor_date!r}")
            start = anchor - timedelta(days=window_days)
            before = len(records)
            records = [r for r in records if (d := _day(r["date"])) and start <= d <= anchor]
            notes.append(f"window {start}..{anchor}: kept {len(records)} of {before}")

        records.sort(key=lambda r: r["date"] or "", reverse=True)
        detail = "; ".join(notes)
        if records:
            return QueryResult("ok", records, detail)
        if unparsable:
            return QueryResult("malformed", detail=detail)
        return QueryResult("empty", detail=detail or f"no {resource} with codes {sorted(c for _, c in wanted)}")

    def _observation_records(self, res: dict, wanted: set) -> list[dict] | None:
        """[] if nothing matches, None if a match has no readable value."""
        def record(coding: dict, value: tuple) -> dict:
            return {"resource_id": res.get("id"), "system": norm_system(coding.get("system")),
                    "code": coding.get("code"), "display": coding.get("display"),
                    "value": value[0], "unit": value[1], "date": _when(res),
                    "status": res.get("status"), "end_date": None}

        top = _matching_coding(res.get("code"), wanted)
        top_value = _value(res)
        # A matched panel (e.g. BP 85354-9) keeps its values in components: return all of them.
        panel_query = top is not None and top_value is None
        out = []
        if top and top_value is not None:
            out.append(record(top, top_value))
        for comp in res.get("component", []):
            c = _matching_coding(comp.get("code"), wanted)
            if c is None and panel_query:
                c = next(iter(comp.get("code", {}).get("coding", [])), {})
            if c is None:
                continue
            v = _value(comp)
            if v is None:
                return None
            out.append(record(c, v))
        if top and not out:
            return None
        return out

    def _coded_record(self, res: dict, wanted: set, by_type: dict) -> list[dict] | None:
        rt = res["resourceType"]
        concept = res.get("code")
        if rt == "MedicationRequest":
            concept = res.get("medicationCodeableConcept") or self._referenced_medication(res, by_type)
        c = _matching_coding(concept, wanted)
        if not c:
            return []
        end = res.get("abatementDateTime") if rt == "Condition" else (
            ((res.get("dispenseRequest") or {}).get("validityPeriod") or {}).get("end"))
        return [{"resource_id": res.get("id"), "system": norm_system(c.get("system")), "code": c.get("code"),
                 "display": c.get("display"), "value": c.get("display") or c.get("code"), "unit": None,
                 "date": _when(res), "status": _status(res), "end_date": end}]

    @staticmethod
    def _referenced_medication(res: dict, by_type: dict) -> dict | None:
        ref = (res.get("medicationReference") or {}).get("reference", "")
        mid = ref.rsplit(":", 1)[-1].rsplit("/", 1)[-1]
        for m in by_type.get("Medication", []):
            if m.get("id") == mid:
                return m.get("code")
        return None

    def search_notes(self, patient_id: str, keywords: list[str], context: int = 80) -> QueryResult:
        """Case-insensitive keyword match over note text; returns snippets with source IDs."""
        if patient_id not in self.index:
            return QueryResult("malformed", detail=f"unknown patient {patient_id!r}")
        kws = [k.strip() for k in keywords or [] if k.strip()]
        if not kws:
            return QueryResult("malformed", detail="no keywords given")
        pattern = re.compile("|".join(re.escape(k) for k in kws), re.IGNORECASE)

        records, searched = [], 0
        for res, text in self._note_texts(patient_id):
            searched += 1
            for m in pattern.finditer(text):
                lo, hi = max(0, m.start() - context), min(len(text), m.end() + context)
                records.append({"resource_id": res.get("id"), "code": m.group(0), "value": text[lo:hi].strip(),
                                "unit": None, "date": _when(res), "resource_type": res["resourceType"]})
        records.sort(key=lambda r: r["date"] or "", reverse=True)
        if records:
            return QueryResult("ok", records, f"{len(records)} hits in {searched} notes")
        return QueryResult("empty", detail=f"searched {searched} notes for {kws}")

    def _note_texts(self, patient_id: str):
        """DocumentReference text attachments, plus Annotation notes on any resource."""
        for rt, resources in self.index[patient_id].items():
            for res in resources:
                if rt == "DocumentReference":
                    for content in res.get("content", []):
                        att = content.get("attachment", {})
                        if att.get("data"):
                            try:
                                yield res, base64.b64decode(att["data"]).decode("utf-8", "replace")
                            except ValueError:
                                log.warning("DocumentReference %s: bad base64", res.get("id"))
                for n in res.get("note", []):
                    if n.get("text"):
                        yield res, n["text"]


# ---------- module-level API (what the engine and agent import) ----------

_store: FhirStore | None = None


def get_store() -> FhirStore:
    global _store
    if _store is None:
        _store = FhirStore(config.PATIENT_DIR)
    return _store


def set_store(store: FhirStore) -> None:
    global _store
    _store = store


def fhir_query(patient_id: str, resource: str, codes: list[dict],
               window_days: int | None = None, anchor_date: str | None = None) -> QueryResult:
    try:
        return get_store().fhir_query(patient_id, resource, codes, window_days, anchor_date)
    except Exception as e:  # noqa: BLE001 - tools never raise to the agent
        log.exception("fhir_query failed")
        return QueryResult("malformed", detail=f"{type(e).__name__}: {e}")


def search_notes(patient_id: str, keywords: list[str]) -> QueryResult:
    try:
        return get_store().search_notes(patient_id, keywords)
    except Exception as e:  # noqa: BLE001
        log.exception("search_notes failed")
        return QueryResult("malformed", detail=f"{type(e).__name__}: {e}")


def list_patients(since_date: str | None = None) -> list[str]:
    return get_store().list_patients(since_date)


def main() -> None:
    parser = argparse.ArgumentParser(description="Query the local FHIR store")
    parser.add_argument("patient_id", nargs="?")
    parser.add_argument("code", nargs="?", help="LOINC code (Observation)")
    parser.add_argument("--dir", type=Path, default=config.PATIENT_DIR)
    parser.add_argument("--window-days", type=int)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    set_store(FhirStore(args.dir))
    if not args.patient_id:
        print(json.dumps({"patients": list_patients(), "load_errors": get_store().load_errors}, indent=2))
        return
    result = fhir_query(args.patient_id, "Observation", [{"system": "LOINC", "code": args.code}], args.window_days)
    print(json.dumps(asdict(result), indent=2))


if __name__ == "__main__":
    main()

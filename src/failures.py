"""T9: failure injection on the loaded data, so each failure path can be shown on demand.

Mutates the in-memory FHIR store only; files on disk are never touched. Every
injection is described in one line that the log prints at the top, so an
injected value is never mistaken for real data.

  drop_codes  LDL observations of one patient recoded 18262-1 -> 13457-7 (an
              equivalent code): rule query comes back empty, the agent recovers it.
  bad_units   most recent LDL of one patient rewritten in mmol/L (rule converts it)
              and of another made implausible (rule returns unknown).
  ctgov_timeout is handled in src/tools/ctgov.py; amendment_v2 in T10.

Target patients come from config.FAILURE_TARGETS (Ming's injected-case list),
otherwise the first patients, in ID order, that have an LDL-C 18262-1 record.
"""

from src import config
from src.adapters.fhir_store import LOINC, FhirStore, _day, _when
from src.engine.units import LIPID_MMOL_TO_MG

LDL_CODE = "18262-1"
LDL_ALT = {"system": LOINC, "code": "13457-7", "display": "Cholesterol in LDL [Mass/volume] in Serum or Plasma by calculation"}


def _ldl_observations(store: FhirStore, pid: str) -> list[dict]:
    obs = [o for o in store.index[pid].get("Observation", [])
           if any(c.get("code") == LDL_CODE for c in o.get("code", {}).get("coding", []))]
    return sorted(obs, key=lambda o: _day(_when(o)) or _day("0001-01-01"), reverse=True)


def _targets(store: FhirStore, name: str, n: int, exclude: set[str]) -> list[str]:
    chosen = config.FAILURE_TARGETS.get(name)
    if chosen:
        return [p for p in chosen if p in store.index]
    candidates = [p for p in sorted(store.index) if p not in exclude and _ldl_observations(store, p)]
    return candidates[:n]


def inject(store: FhirStore) -> list[dict]:
    """Apply the enabled data failures. Returns one record per injection:
    {"switch", "patient_id", "resource_ids", "text"} where text is the line the log prints."""
    done, used = [], set()

    if config.failure_enabled("drop_codes"):
        for pid in _targets(store, "drop_codes", 1, used):
            obs = _ldl_observations(store, pid)
            for o in obs:
                o["code"] = {"coding": [dict(LDL_ALT)], "text": LDL_ALT["display"]}
            used.add(pid)
            done.append({"switch": "drop_codes", "patient_id": pid, "resource_ids": [o["id"] for o in obs],
                         "text": f"drop_codes: {pid} LDL-C {', '.join(o['id'] for o in obs)} recoded "
                                 f"{LDL_CODE} -> {LDL_ALT['code']}"})

    if config.failure_enabled("bad_units"):
        for i, pid in enumerate(_targets(store, "bad_units", 2, used)):
            o = _ldl_observations(store, pid)[0]
            q = o["valueQuantity"]
            before = f"{q['value']:g} {q.get('unit')}"
            if i == 0:  # convertible: same quantity expressed in mmol/L
                q.update(value=round(q["value"] / LIPID_MMOL_TO_MG, 2), unit="mmol/L", code="mmol/L")
            else:  # implausible: decimal slip, x10
                q.update(value=round(q["value"] * 10, 1))
            used.add(pid)
            done.append({"switch": "bad_units", "patient_id": pid, "resource_ids": [o["id"]],
                         "kind": "convertible" if i == 0 else "implausible",
                         "text": f"bad_units: {pid} LDL-C {o['id']} {before} -> {q['value']:g} {q['unit']}"})

    if config.failure_enabled("note_conflict"):
        done.append({"switch": "note_conflict", "patient_id": None, "resource_ids": [],
                     "text": "note_conflict: not implemented (optional)"})
    return done

"""Drug terminology from the NLM RxNav APIs (RxNorm + RxClass): name -> ingredients -> classes.

Used so that drug-class membership comes from a terminology service, not from the model's memory
(Nova 2 Lite called Leqvio "a PCSK9 inhibitor, not an siRNA"; MED-RT lists inclisiran as
"RNA, Small Interfering"). Typed status, never raises; results cached under cache/rxnav/.
"""

import json
import logging
import re
import urllib.parse

import requests

from src import config

log = logging.getLogger(__name__)

BASE = "https://rxnav.nlm.nih.gov/REST"
TIMEOUT_S = 10


def _get(path: str) -> dict:
    resp = requests.get(f"{BASE}/{path}", timeout=TIMEOUT_S)
    resp.raise_for_status()
    return resp.json()


def _resolve(rxcui: str, name: str) -> dict:
    groups = _get(f"rxcui/{rxcui}/related.json?tty=IN").get("relatedGroup", {}).get("conceptGroup", [])
    ings = [(p["rxcui"], p["name"]) for g in groups for p in g.get("conceptProperties", [])] or [(rxcui, name)]
    classes = set()
    for ing_rxcui, _ in ings:
        info = _get(f"rxclass/class/byRxcui.json?rxcui={ing_rxcui}").get("rxclassDrugInfoList", {})
        classes |= {(x["rxclassMinConceptItem"]["className"], x["relaSource"]) for x in info.get("rxclassDrugInfo", [])}
    return {"status": "ok", "query": name, "rxcui": rxcui, "ingredients": [n for _, n in ings],
            "classes": sorted(map(list, classes))}


def _cached(kind: str, name: str, find_rxcui) -> dict:
    key = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    cache = config.CACHE_DIR / "rxnav" / f"{kind}_{key}.json"
    if cache.exists():
        return json.loads(cache.read_text())
    out = {"status": "not_found", "query": name, "rxcui": None, "ingredients": [], "classes": []}
    try:
        rxcui = find_rxcui(name)
        if rxcui:
            out = _resolve(rxcui, name)
    except (requests.RequestException, ValueError, KeyError) as e:
        log.warning("rxnav %s lookup failed for %r: %s", kind, name, e)
        return {**out, "status": "error", "error": f"{type(e).__name__}: {e}"}
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(out, indent=2))
    return out


def lookup(name: str) -> dict:
    """Approximate match (brand names, misspellings). {"status": ok|not_found|error, "query", "rxcui", "ingredients", "classes"}"""
    def find(n):
        cand = (_get(f"approximateTerm.json?term={urllib.parse.quote(n)}&maxEntries=1")
                .get("approximateGroup", {}).get("candidate") or [])
        return cand[0]["rxcui"] if cand and float(cand[0].get("score", 0)) >= 5 else None
    return _cached("approx", name, find)


def exact(name: str) -> dict:
    """Exact / normalized RxNorm name match only; used to scan free text for drug names."""
    def find(n):
        ids = _get(f"rxcui.json?name={urllib.parse.quote(n)}&search=2").get("idGroup", {}).get("rxnormId") or []
        return ids[0] if ids else None
    return _cached("exact", name, find)


STOP = {"since", "about", "every", "from", "with", "that", "this", "were", "have", "takes", "taken", "stopped",
        "because", "after", "before", "years", "months", "weeks", "days", "daily", "called", "planned", "given",
        "next", "dose", "clinic", "patient", "reports", "only", "when", "usually", "most", "night", "early"}


def scan_text(text: str, criterion: str) -> list[dict]:
    """Drug names RxNorm recognises in the text (1-3 word phrases) whose class matches the criterion."""
    words = re.findall(r"[A-Za-z][A-Za-z\-]+", text)
    phrases = []
    for n in (3, 2, 1):
        for i in range(len(words) - n + 1):
            chunk = words[i:i + n]
            if n == 1 and (len(chunk[0]) < 4 or chunk[0].lower() in STOP):
                continue
            phrases.append(" ".join(chunk))
    hits, covered = [], set()
    for ph in dict.fromkeys(phrases):
        if any(ph.lower() in c for c in covered):
            continue  # "red yeast rice" already found; skip "yeast rice", "rice"
        entry = exact(ph)
        if entry["status"] == "ok" and in_class(entry, criterion) == "yes":
            hits.append({"phrase": ph, **entry})
            covered.add(ph.lower())
    return hits


# Class vocabularies for SAD E4 and E5. Matching is on the class names RxClass returns.
E4_TERMS = ["small interfering", "sirna", "antisense", "oligonucleotides, antisense", "gene therap", "genetic therap",
            "crispr"]
E5_TERMS = ["hmg-coa reductase", "hmg coa reductase", "lipid modifying", "antilipemic", "pcsk9",
            "cholesterol absorption inhibitor", "bile acid sequestrant", "fibrate", "lipid-lowering"]


def matched_class(entry: dict, criterion: str) -> str | None:
    """The terminology class name that put the drug in the criterion's class, e.g. 'RNA, Small Interfering (MEDRT)'."""
    terms = E4_TERMS if criterion == "E4" else E5_TERMS
    for name, source in entry.get("classes", []):
        if any(t in name.lower() for t in terms):
            return f"{name} ({source})"
    return None


def in_class(entry: dict, criterion: str) -> str | None:
    """'yes' / 'no' from the terminology, None when the terminology cannot tell."""
    if entry.get("status") != "ok" or not entry.get("classes"):
        return None
    terms = E4_TERMS if criterion == "E4" else E5_TERMS
    names = " | ".join(c[0].lower() for c in entry["classes"])
    return "yes" if any(t in names for t in terms) else "no"

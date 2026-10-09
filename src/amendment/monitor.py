"""T10: amendment detection, change classification (brief decision 5) and re-screen.

1. SHA-256 of old vs new criteria text; equal -> nothing to do.
2. Item-level diff (bullets / numbered lines, by section) with difflib.
3. Each changed item is classified substantive | wording | ambiguous. Changes that
   differ only in case, spacing or punctuation are wording by rule; everything else
   goes to the model, which only labels and explains. A model failure is ambiguous.
4. wording -> recorded; ambiguous -> flagged for the CRC, no re-screen on a guess;
   substantive -> re-screen with the amended predicate file (prepared by a human:
   automatic recompilation is out of scope, brief decision 1).
5. The amended screening is compared patient by patient with the current one.
"""

import difflib
import hashlib
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from src import config
from src.agent import trace
from src.engine.aggregate import PatientResult

log = logging.getLogger(__name__)

SECTION_RE = re.compile(r"^(inclusion|exclusion)\s+criteria\s*:?$", re.IGNORECASE)
BULLET_RE = re.compile(r"^(?:[*\-•]|\d+[.)])\s+(.*)$")
DATED_SNAPSHOT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\.txt$")

CLASSIFY_PROMPT = """You review amendments to clinical-trial eligibility criteria for a research coordinator.
You get one criterion item before and after an amendment (or an item that was added or removed).

Step 1. Restate the condition each version imposes, in plain terms (who it includes or excludes).
Step 2. Decide whether exactly the same patients meet the criterion before and after:
- "same": only phrasing, word order, synonyms, spelling or formatting changed.
- "different": a threshold, unit, time window, age, population, drug, diagnosis or requirement changed,
  or the item was added or removed.
- "unclear": the new wording could be read either way; a human must confirm.

Examples:
- "Prior myocardial infarction or stroke" -> "History of stroke or MI": same.
- "LDL-C >= 100 mg/dL" -> "LDL-C >= 130 mg/dL": different.
- "Within 6 months of screening" -> "Within 26 weeks of screening": same.
- "Uncontrolled hypertension" -> "Hypertension not adequately controlled in the investigator's opinion": unclear.

Do not decide anything about individual patients."""


class Classification(BaseModel):
    before_condition: str = Field(description="The condition the old item imposes, in plain terms")
    after_condition: str = Field(description="The condition the new item imposes, in plain terms")
    same_patients: Literal["same", "different", "unclear"]
    reason: str = Field(description="One sentence naming what changed, or why nothing material changed")


# The model judges whether the eligible population changes; code maps that to the action label.
LABEL_FOR = {"same": "wording", "different": "substantive", "unclear": "ambiguous"}


@dataclass
class Item:
    section: str
    text: str


@dataclass
class Change:
    kind: str  # modified | added | removed
    section: str
    old: str | None
    new: str | None
    label: str = "ambiguous"
    reason: str = ""
    trace: list[dict] = field(default_factory=list)


@dataclass
class AmendmentCheck:
    old_source: str
    new_source: str
    old_sha: str
    new_sha: str
    changes: list[Change] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return self.old_sha != self.new_sha

    def labelled(self, label: str) -> list[Change]:
        return [c for c in self.changes if c.label == label]


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def split_items(text: str) -> list[Item]:
    """One item per header line or bullet; continuation lines join the previous bullet."""
    items, section, in_bullets = [], "Header", False
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if SECTION_RE.match(line):
            section, in_bullets = line.rstrip(":").strip().title(), False
            continue
        m = BULLET_RE.match(line)
        if m:
            items.append(Item(section, m.group(1).strip()))
            in_bullets = True
        elif in_bullets and items and items[-1].section == section:
            items[-1].text += " " + line
        else:
            items.append(Item(section, line))
    return items


def diff_items(old: list[Item], new: list[Item]) -> list[Change]:
    key = lambda i: f"{i.section}|{i.text}"  # noqa: E731
    sm = difflib.SequenceMatcher(None, [key(i) for i in old], [key(i) for i in new], autojunk=False)
    changes = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            continue
        olds, news = old[i1:i2], new[j1:j2]
        for k in range(max(len(olds), len(news))):
            o = olds[k] if k < len(olds) else None
            n = news[k] if k < len(news) else None
            kind = "modified" if o and n else ("removed" if o else "added")
            changes.append(Change(kind, (n or o).section, o.text if o else None, n.text if n else None))
    return changes


def _normalised(text: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def make_model():
    from src.agent.agent import make_model as bedrock_model
    return bedrock_model()


def classify(change: Change, model=None) -> Change:
    if change.kind == "modified" and _normalised(change.old) == _normalised(change.new):
        change.label, change.reason = "wording", "identical apart from case, spacing or punctuation"
        trace.add(change.trace, "rule:normalize", change.reason, "wording")
        return change
    try:
        from strands import Agent

        agent = Agent(model=model or make_model(), system_prompt=CLASSIFY_PROMPT,
                      structured_output_model=Classification, callback_handler=None)
        prompt = (f"Section: {change.section}\nChange type: {change.kind}\n"
                  f"Before: {change.old or '(none)'}\nAfter: {change.new or '(none)'}")
        out = agent(prompt).structured_output
        change.label, change.reason = LABEL_FOR[out.same_patients], " ".join(out.reason.split())
        trace.add(change.trace, "classify_change", change.reason, change.label)
    except Exception as e:  # noqa: BLE001 - never re-screen on a guess
        log.warning("classification failed: %s", e)
        change.label, change.reason = "ambiguous", f"model unavailable ({type(e).__name__}); CRC to confirm"
        trace.add(change.trace, "agent:error", f"{type(e).__name__}: {str(e)[:200]}", "ambiguous")
    return change


def check(old_text: str, new_text: str, old_source: str, new_source: str, model=None) -> AmendmentCheck:
    result = AmendmentCheck(old_source, new_source, sha256(old_text), sha256(new_text))
    if not result.changed:
        return result
    result.changes = [classify(c, model) for c in diff_items(split_items(old_text), split_items(new_text))]
    return result


def previous_snapshot(nct: str, before: str | None = None) -> Path | None:
    """Latest dated snapshot for a trial, optionally strictly before a date (YYYY-MM-DD)."""
    folder = config.SNAPSHOT_DIR / nct
    dated = sorted(p for p in folder.glob("*.txt") if DATED_SNAPSHOT_RE.match(p.name)) if folder.exists() else []
    if before:
        dated = [p for p in dated if p.stem < before]
    return dated[-1] if dated else None


def predicate_changes(v1: list[dict], v2: list[dict]) -> dict[str, list[str]]:
    """criterion_id -> human-readable field changes between two predicate files."""
    a, b = {p["criterion_id"]: p for p in v1}, {p["criterion_id"]: p for p in v2}
    out = {}
    for cid in sorted(a.keys() | b.keys()):
        if cid not in a:
            out[cid] = ["added"]
        elif cid not in b:
            out[cid] = ["removed"]
        else:
            diffs = [f"{k}: {a[cid].get(k)!r} -> {b[cid].get(k)!r}" for k in sorted(a[cid].keys() | b[cid].keys())
                     if a[cid].get(k) != b[cid].get(k)]
            if diffs:
                out[cid] = diffs
    return out


@dataclass
class PatientChange:
    patient_id: str
    old_category: str
    new_category: str
    criteria: list[tuple[str, str, str, str]]  # (criterion_id, old status, new status, new note)


def compare(before: list[PatientResult], after: list[PatientResult]) -> list[PatientChange]:
    old = {r.patient_id: r for r in before}
    out = []
    for r in after:
        o = old.get(r.patient_id)
        if o is None:
            continue
        ov = {v.criterion_id: v for v in o.verdicts}
        crit = [(v.criterion_id, ov[v.criterion_id].status if v.criterion_id in ov else "-", v.status, v.note)
                for v in r.verdicts if v.criterion_id not in ov or ov[v.criterion_id].status != v.status]
        if crit or o.category != r.category:
            out.append(PatientChange(r.patient_id, o.category, r.category, crit))
    return out

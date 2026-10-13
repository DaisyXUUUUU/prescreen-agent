"""CRC workbench demo: pre-screen the patients a coordinator selects, live, and review the results.

    python app/server.py            # http://localhost:8765
    python app/server.py --build-replay   # refresh app/replay.js from out/eval/SAD/reviewer_data.json

Live mode runs the real pipeline (SAD rules + the Bedrock agent) on the selected patients.
When Bedrock is unreachable the page falls back to app/replay.js, the saved results of the
last full evaluation, and says so. Standard library only; no patient is ever contacted.
"""

import argparse
import io
import json
import re
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

APP = Path(__file__).resolve().parent
ROOT = APP.parent
sys.path.insert(0, str(ROOT))

from src import config  # noqa: E402
from src.agent.trace import actor  # noqa: E402
from src.engine import sad_adapter as sa  # noqa: E402

CRITERIA = ["AGE", "I1", "I2", "I3", "I4", "I5", "E1", "E2", "E3", "E4", "E5"]
FACT_CODES = [("BMI", "39156-5"), ("LDL-C", "18262-6"), ("Lp(a)", "43583-4"), ("TG", "2571-8"),
              ("ALT", "1742-6"), ("AST", "1920-8"), ("HbA1c", "4548-4")]
# Display names for the synthetic extended cases, which all reuse SAD01's Synthea identity.
EXT_NAMES = ["Ava Thompson", "Maya Patel", "Grace Kim", "Olivia Brooks", "Nora Alvarez", "Lena Fischer", "Chloe Nguyen",
             "Ruby Okafor", "Iris Morgan", "Hannah Weiss", "Sofia Rossi", "Leah Cohen", "Zoe Bennett", "Clara Jensen",
             "Mia Delgado", "Ellie Walsh", "Naomi Park", "Julia Novak", "Ivy Turner", "Alice Moreau", "Freya Lund",
             "Emma Sato", "Lucy Carter", "Ada Nwosu", "Tessa Byrne", "Vera Ivanova", "Eva Lindqvist", "Rosa Mendes",
             "Daisy Hughes", "Stella Romero", "Anna Kowalski", "Mila Hart", "Jade Wilson", "Lily Chen", "Sara Haddad",
             "Kate Murphy", "Elise Martin", "Nina Petrov", "Laura Silva", "Diana Reyes", "Paula Grant", "Helen Ward",
             "Amy Foster", "Beth Collins", "Cora Price", "Dora Fleming", "Erin Shaw", "Fay Lambert", "Gwen Harper",
             "Hope Sinclair"]


def _clean(name_part: str) -> str:
    return re.sub(r"\d+", "", name_part)


def load_world():
    spec = sa.load_spec()
    cases = sa.load_cases() + sa.load_cases(config.DATA_DIR / "extended_cases" / "cases")
    sa.install_store(cases)
    return spec, cases


def case_facts(case) -> dict:
    facts = {}
    pat = next(e["resource"] for e in case.bundle["entry"] if e["resource"]["resourceType"] == "Patient")
    facts["Birth date"] = pat.get("birthDate")
    raw = {}
    for e in case.bundle["entry"]:
        r = e["resource"]
        if r["resourceType"] == "Observation" and "valueQuantity" in r:
            q = r["valueQuantity"]
            raw.setdefault(r["code"]["coding"][0]["code"], []).append(f"{q['value']:g} {q.get('code') or q.get('unit')}")
        if r["resourceType"] == "QuestionnaireResponse":
            for item in r.get("item", []):
                if item["linkId"].endswith("_free_text"):
                    facts[item["linkId"].replace("_free_text", " (free text)").capitalize()] = item["answer"][0].get("valueString")
    for label, code in FACT_CODES:
        if raw.get(code):
            facts[label] = ", ".join(raw[code])
    return facts


def identity(case, index: int) -> dict:
    pat = next(e["resource"] for e in case.bundle["entry"] if e["resource"]["resourceType"] == "Patient")
    if case.case_id.startswith("SAD"):
        n = pat["name"][0]
        name = f"{_clean(n['given'][0])} {_clean(n['family'])}"
    else:
        name = EXT_NAMES[(index - 8) % len(EXT_NAMES)]
    birth = date.fromisoformat(pat["birthDate"])
    screen = date.fromisoformat(case.screening_date)
    age = screen.year - birth.year - ((screen.month, screen.day) < (birth.month, birth.day))
    return {"id": case.case_id, "name": name, "sex": pat.get("gender"), "age": age,
            "purpose": case.ctx.get("purpose", "core screening case"), "facts": case_facts(case)}


def serialize(result) -> dict:
    crit = {}
    for v in result.verdicts:
        steps = [{"tool": t["tool"], "actor": actor(t), "result": t["result"], "decision": t.get("decision", "")}
                 for t in v.trace]
        crit[v.criterion_id] = {"status": v.status, "note": v.note, "agent": v.recovery, "review": v.review_reason,
                                "interpreted": v.interpreted, "conflict": v.conflict,
                                "evidence": ";".join(e.get("resource_id", "") for e in v.evidence),
                                "agent_used": any(s["actor"] == "agent" for s in steps), "trace": steps}
    return {"category": result.category, "criteria": crit}


# ---------- live runs ----------

class _ThreadStdout(io.TextIOBase):
    """Routes print() from worker threads to that thread's job log; everything else to the console."""

    def __init__(self, real):
        self.real, self.local = real, threading.local()

    def write(self, s):
        sink = getattr(self.local, "sink", None)
        if sink is None:
            return self.real.write(s)
        sink["buf"] += s
        *done, sink["buf"] = sink["buf"].split("\n")
        sink["steps"].extend(x.strip() for x in done if x.strip())
        return len(s)

    def flush(self):
        self.real.flush()


class Workbench:
    def __init__(self):
        self.spec, self.cases = load_world()
        self.by_id = {c.case_id: c for c in self.cases}
        self.people = [identity(c, i) for i, c in enumerate(self.cases)]
        self.model, self.model_error, self.checked = None, "checking", False
        self.jobs = {}
        self.stdout = _ThreadStdout(sys.stdout)
        sys.stdout = self.stdout
        threading.Thread(target=self._preflight, daemon=True).start()

    def _preflight(self):
        from src.agent.agent import preflight
        self.model, self.model_error = preflight()
        self.checked = True
        print(f"[workbench] agent {'ready: ' + config.BEDROCK_MODEL_ID if self.model else 'unavailable: ' + str(self.model_error)}")

    def health(self):
        return {"live": self.model is not None, "checked": self.checked, "model": config.BEDROCK_MODEL_ID,
                "reason": None if self.model else self.model_error}

    def start(self, ids: list[str]) -> str:
        ids = [i for i in ids if i in self.by_id][:12]
        jid = uuid.uuid4().hex[:10]
        job = {"id": jid, "created": time.time(), "done": False,
               "patients": {i: {"state": "queued", "steps": [], "buf": "", "result": None, "error": None,
                                "started": None, "elapsed": None} for i in ids}}
        self.jobs[jid] = job
        threading.Thread(target=self._run, args=(job, ids), daemon=True).start()
        return jid

    def _run(self, job, ids):
        with ThreadPoolExecutor(max_workers=3) as pool:
            list(pool.map(lambda i: self._one(job, i), ids))
        job["done"] = True

    def _one(self, job, cid):
        st = job["patients"][cid]
        st["state"], st["started"] = "running", time.time()
        self.stdout.local.sink = st
        try:
            results, *_ = sa.screen([self.by_id[cid]], self.spec, use_agent=self.model is not None,
                                    model=self.model, preflight_done=True)
            st["result"], st["state"] = serialize(results[0]), "done"
        except Exception as e:  # noqa: BLE001 - one patient failing must not stop the others
            st["state"], st["error"] = "error", f"{type(e).__name__}: {str(e)[:200]}"
        finally:
            self.stdout.local.sink = None
            st["elapsed"] = round(time.time() - st["started"], 1)

    def status(self, jid):
        job = self.jobs.get(jid)
        if not job:
            return None
        return {"id": jid, "done": job["done"], "live": self.model is not None,
                "patients": {k: {x: v[x] for x in ("state", "steps", "result", "error", "elapsed")} |
                             {"current": v["buf"].strip(), "running_for": round(time.time() - v["started"], 1) if v["started"] and v["elapsed"] is None else None}
                             for k, v in job["patients"].items()}}


# ---------- replay data ----------

def build_replay():
    src = config.OUT_DIR / "eval" / "SAD" / "reviewer_data.json"
    data = json.loads(src.read_text(encoding="utf-8"))
    _, cases = load_world()
    people = [identity(c, i) for i, c in enumerate(cases)]
    results = {p["id"]: {"category": p["category"],
                         "criteria": {k: {**v, "conflict": "conflict" in (v.get("note") or "").lower()} for k, v in p["criteria"].items()}}
               for p in data["patients"]}
    payload = {"source": "saved results of the full evaluation run (agent mode, 2026-10-11)",
               "trial": data["trial"], "criteria": data["criteria"], "people": people, "results": results}
    out = APP / "replay.js"
    out.write_text("window.REPLAY = " + json.dumps(payload, ensure_ascii=False) + ";\n", encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size // 1024} KB, {len(results)} patients)")


class Handler(SimpleHTTPRequestHandler):
    bench: Workbench = None

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(APP), **kw)

    def log_message(self, fmt, *args):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/health":
            return self._json(self.bench.health())
        if self.path == "/api/people":
            return self._json(self.bench.people)
        if self.path.startswith("/api/jobs/"):
            s = self.bench.status(self.path.rsplit("/", 1)[-1])
            return self._json(s) if s else self._json({"error": "unknown job"}, 404)
        return super().do_GET()

    def do_POST(self):
        if self.path == "/api/screen":
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            if not self.bench.health()["live"]:
                return self._json({"error": "agent unavailable", "reason": self.bench.model_error}, 503)
            return self._json({"job": self.bench.start(body.get("ids", []))})
        self._json({"error": "not found"}, 404)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--build-replay", action="store_true")
    args = ap.parse_args()
    if args.build_replay:
        return build_replay()
    Handler.bench = Workbench()
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"[workbench] http://localhost:{args.port}  ({len(Handler.bench.cases)} synthetic patients)")
    srv.serve_forever()


if __name__ == "__main__":
    main()

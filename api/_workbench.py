"""Shared state for the Vercel functions: cases, rule pack and the Bedrock model, loaded once per instance."""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "app")]

import server as wb  # noqa: E402  (app/server.py)
from src.engine import sad_adapter as sa  # noqa: E402

_STATE = {}


def state(retry_model: bool = False) -> dict:
    if not _STATE:
        spec, cases = wb.load_world()
        _STATE.update(spec=spec, by_id={c.case_id: c for c in cases}, model=None, error="not checked")
    if _STATE["model"] is None and (retry_model or _STATE["error"] == "not checked"):
        from src.agent.agent import preflight
        _STATE["model"], _STATE["error"] = preflight()
    return _STATE


def screen_one(cid: str) -> tuple[int, dict]:
    st = state(retry_model=True)
    if st["model"] is None:
        return 503, {"error": "agent unavailable", "reason": st["error"]}
    case = st["by_id"].get(cid)
    if case is None:
        return 404, {"error": f"unknown patient {cid}"}
    t0 = time.time()
    results, *_ = sa.screen([case], st["spec"], use_agent=True, model=st["model"], preflight_done=True)
    return 200, {**wb.serialize(results[0]), "elapsed": round(time.time() - t0, 1)}

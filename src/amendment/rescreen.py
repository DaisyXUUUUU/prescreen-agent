"""T10 orchestration: compare criteria snapshots, classify changes, re-screen when substantive.

Normal weekly run: the fresh fetch is compared with the latest snapshot from an
earlier date. With the `amendment_v2` switch, a prepared v2 snapshot stands in
for the fetch (demo), compared with the latest snapshot.
"""

import dataclasses
import json
from datetime import datetime, timezone
from pathlib import Path

from src import config
from src.amendment import monitor
from src.pipeline import screen
from src.report import impact_writer
from src.report.log_writer import _upload, write_log
from src.tools.ctgov import snapshot_text


def _rel(p: Path) -> str:
    try:
        return str(p.resolve().relative_to(config.ROOT))
    except ValueError:
        return str(p)


def run_amendment(trial: str, nct: str, fetch, screening_date: str, predicates_v1: list[dict], results_v1, out_dir: Path,
                  use_agent: bool = True, v1_snapshot: Path | None = None, v2_snapshot: Path | None = None,
                  v2_predicates: Path | None = None) -> Path | None:
    if config.failure_enabled("amendment_v2"):
        new_path = v2_snapshot or config.SNAPSHOT_DIR / nct / "amendment_v2.txt"
        if not new_path.exists():
            print(f"amendment: amendment_v2 is on but {new_path} does not exist")
            return None
        new_text, new_source = new_path.read_text(encoding="utf-8"), _rel(new_path)
        old_path = v1_snapshot or monitor.previous_snapshot(nct)
    else:
        if fetch.status != "ok" or not fetch.snapshot_path or not (fetch.criteria or {}).get("eligibility_criteria"):
            print("amendment: criteria not fetched live this run; amendment check skipped")
            return None
        new_text, new_source = snapshot_text(fetch.criteria), _rel(Path(fetch.snapshot_path))
        old_path = v1_snapshot or monitor.previous_snapshot(nct, before=fetch.fetched_at[:10])

    if old_path is None:
        print("amendment: no earlier snapshot to compare with; this run's snapshot is the baseline")
        return None

    chk = monitor.check(old_path.read_text(encoding="utf-8"), new_text, _rel(old_path), new_source)
    if not chk.changed:
        print(f"amendment: criteria unchanged since {old_path.name} (SHA-256 match)")
        return None

    v2_path = v2_predicates or config.DATA_DIR / "predicates" / f"trial_{trial}_v2.json"
    substantive = chk.labelled("substantive")
    rescreened, blocked, patients, pred_changes, n = False, "", [], {}, len(results_v1)
    if not substantive:
        blocked = "no substantive change"
    elif not v2_path.exists():
        blocked = f"substantive change found but no amended predicate file {_rel(v2_path)} (needs human compilation)"
    else:
        data = json.loads(v2_path.read_text(encoding="utf-8"))
        preds_v2 = data["predicates"] if isinstance(data, dict) else data
        print(f"amendment: {len(substantive)} substantive change(s); re-screening with {_rel(v2_path)}")
        results_v2, _, _ = screen(preds_v2, screening_date, use_agent=use_agent, label=" (v2)")
        patients = monitor.compare(results_v1, results_v2)
        rescreened = True
        pred_changes = monitor.predicate_changes(predicates_v1, preds_v2)
        amended_fetch = dataclasses.replace(fetch, sha256=chk.new_sha)
        write_log(f"{trial}-amended", nct, amended_fetch, screening_date, results_v2, preds_v2, out_dir)

    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    text = impact_writer.render(trial, nct, screening_date, chk, rescreened, blocked, pred_changes, patients,
                                _rel(v2_path), generated, n)
    path = impact_writer.write(out_dir / f"amendment_impact_{trial}_{screening_date}.md", text)
    for w in _upload(trial, screening_date, [path]):
        print(f"warning: {w}")
    flips = sum(p.old_category != p.new_category for p in patients)
    print(f"amendment: {len(chk.changes)} changed item(s) "
          f"({', '.join(f'{c.label}' for c in chk.changes)}); "
          + (f"{flips} patient(s) change status" if rescreened else f"not re-screened: {blocked}"))
    return path

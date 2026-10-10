"""Write out/SAD_review/REVIEW.md from the runs in out/SAD_review/ (see the README's SAD section).

Compares, per case, what Ming's rules-only engine decides with what the agent pipeline decides,
and lists what the agent did. No model calls.

    python scripts/review_sad.py
"""

import csv
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import config  # noqa: E402
from src.engine import sad_adapter as sa  # noqa: E402

R = config.OUT_DIR / "SAD_review"
DATE = "2026-10-09"
LBL = {"likely_eligible": "可能合格", "excluded": "已排除", "pending": "待补", "needs_review": "需复核"}
RUNS = ["baseline", "ctgov_timeout", "drop_codes", "bad_units", "amendment_v2"]


def rows(run: str) -> list[dict]:
    return list(csv.DictReader(open(R / run / f"prescreen_log_SAD_{DATE}.csv", encoding="utf-8")))


def traces(run: str) -> dict:
    out = {}
    for line in open(R / run / f"trace_SAD_{DATE}.jsonl", encoding="utf-8"):
        t = json.loads(line)
        out.setdefault((t["patient_id"], t["criterion_id"]), []).append(t)
    return out


def main() -> None:
    spec, engine = sa.load_spec(), sa.load_engine()
    cases = sa.load_cases() + sa.load_cases(config.DATA_DIR / "eng_cases" / "cases")
    ming = {c.case_id: sa.DECISION_TO_CATEGORY[engine.evaluate(c.bundle, c.ctx, spec)["decision"]] for c in cases}
    purpose = {c.case_id: c.ctx.get("purpose", "Ming's case") for c in cases}

    base = rows("baseline")
    tr = traces("baseline")
    cat = {r["patient_id"]: r["patient_category"] for r in base}
    agent_lines = {}
    for (pid, cid), steps in tr.items():
        if any(t["actor"] == "agent" for t in steps):
            row = next((r for r in base if r["patient_id"] == pid and r["criterion_id"] == cid), {})
            note = row.get("agent_summary") or row.get("note", "")
            if row.get("review_reason"):
                note = f"**→ 需复核：{row['review_reason']}**。{note}"
            agent_lines.setdefault(pid, []).append((cid, note))

    # 1. per-case comparison
    comp = ["| 病例 | 来源 / 设计用途 | Ming 的程序（只有规则） | 加上 agent 之后 | 变化 |", "|---|---|---|---|---|"]
    for c in cases:
        a, b = ming[c.case_id], cat[c.case_id]
        comp.append(f"| {c.case_id} | {'Ming' if c.case_id.startswith('SAD') else '工程自造：' + purpose[c.case_id]} | "
                    f"{LBL[a]} | {LBL[b]} | {'—' if a == b else '**改变**'} |")

    # 2. what the agent did, per case
    did = []
    for c in cases:
        items = agent_lines.get(c.case_id, [])
        if not items:
            continue
        did.append(f"\n**{c.case_id}**（{LBL[ming[c.case_id]]} → {LBL[cat[c.case_id]]}）")
        for cid, note in sorted(items):
            steps = tr[(c.case_id, cid)]
            tools = " → ".join(dict.fromkeys(t["tool"] for t in steps if t["actor"] == "agent"))
            did.append(f"- {cid}：{note[:600]}  \n  <sub>agent 工具：{tools}</sub>")

    # 3. switches
    tbl = ["| 场景 | 可能合格 | 待补 | 已排除 | 需复核 | agent 任务 / 改变规则结果 | 与正常运行相比变化的病例 |", "|---|---|---|---|---|---|---|"]
    for run in RUNS:
        meta = json.load(open(R / run / f"run_SAD_{DATE}.json"))
        c2 = {r["patient_id"]: r["patient_category"] for r in rows(run)}
        diff = ", ".join(f"{p} {LBL[cat[p]]}→{LBL[c2[p]]}" for p in sorted(c2) if c2[p] != cat[p]) or "无"
        k, a = meta["counts"], meta["agent"] or {}
        tbl.append(f"| `{run}` | {k['likely_eligible']} | {k['pending']} | {k['excluded']} | {k['needs_review']} | "
                   f"{a.get('attempted', 0)} / {a.get('recovered', 0)} | {diff} |")
    caught = []
    for run in RUNS:
        for (pid, cid), steps in traces(run).items():
            for t in steps:
                if t["tool"] == "rule:terminology_scan":
                    caught.append(f"`{run}` {pid} {cid}: {t['result']}")
    safety = ("\n\n**安全网实际触发记录**（模型漏报、被 RxNorm 扫描拦下，判为需 CRC 判断）：\n" + "\n".join(f"- {c}" for c in caught)
              + "\n\n所以 ENG04 在不同运行之间会是\"需复核\"（模型报告了 Leqvio，按 siRNA 计入）或\"待补\"（模型漏报，被扫描拦下）。"
                "两种结果都不会把病人放成合格；变化来自模型本身的不稳定（temperature 0 也一样）。") if caught else ""
    injected = [i["text"] for run in RUNS for i in json.load(open(R / run / f"run_SAD_{DATE}.json"))["injections"]]

    impact = json.load(open(R / "amendment_v2" / f"amendment_impact_SAD_{DATE}.json"))
    changes = "\n".join(f"| {c['old']} | {c['new']} | **{c['label']}** | {c['reason']} |" for c in impact["changes"])

    # 4. Ming acceptance with the agent off is a test; report it from the baseline rows too
    ming_cases = [c.case_id for c in cases if c.case_id.startswith("SAD")]
    same_on_ming = sum(ming[c] == cat[c] for c in ming_cases)

    text = f"""# SAD 审查包：agent 版（{DATE}）

数据：**Ming 的 8 个 SAD 病例** + **工程自造的 7 个病例**（`data/eng_cases/`，专门覆盖 Ming 的病例没有的情况：自由文本、模糊边界、需要医学知识、I5 证据、会改变结论的冲突）。规则判定仍由 Ming 的引擎完成；agent 由 Amazon Nova 2 Lite（Bedrock）驱动，药物分类查询 NLM RxNav，快照上传 S3。

> 合成数据，没有 ground truth，本包不含准确率。工程自造病例的"设计用途"是我的设计意图，不是标签。修订 v2 是工程示例，不是 Ming 的。

## 1. 原则：模型理解，代码判定，agent 只能把人推向"复核"

| agent 做什么 | 代码做什么（不交给模型） |
|---|---|
| 读懂问卷里的自由文本，整理成事实，每条附原文引用 | 核对引用确实出现在原文里；按 Ming 的阈值和时间窗判定 |
| 从药名提取成分（品牌名也行） | 药物类别查 NLM RxNav（RxNorm / RxClass），不用模型的记忆 |
| 比较冲突的两条结果，说明可能原因和该核实什么 | 每条结果单独重跑 Ming 的引擎，判断冲突是否影响结论 |
| 自己决定查哪些肝肾化验、诊断、病历，标出值得研究者关注的地方 | 按参考范围判断化验是否异常；核对 agent 引用的记录真实存在；列出缺失的检查 |
| 给 CRC 写说明 | 汇总：agent 的解读不能单独排除病人，只能送到"需复核"；agent 解读后保留的病人列入"就诊时确认" |

## 2. 每个病例：Ming 的程序 vs 加上 agent 之后

{chr(10).join(comp)}

Ming 的 8 个病例中，有 {same_on_ming} 个分区没变。关闭 agent 时，15 个病例全部和 Ming 的程序一致（自动测试 `tests/test_sad.py`、`tests/test_agent_sad.py`）。

## 3. agent 在每个病例上做了什么（正常运行）

{chr(10).join(did)}

## 4. 五个场景

{chr(10).join(tbl)}

注入内容：{'; '.join(injected) or '无'}{safety}

## 5. 修订（工程示例 v2：SAD LDL 门槛 70 → 100，HbA1c 措辞改写）

| 修改前 | 修改后 | 分类 | 模型的理由 |
|---|---|---|---|
{changes}

状态翻转：{', '.join(impact['flips']) or '无'}

## 6. 建议的阅读顺序

1. [baseline/prescreen_log_SAD_{DATE}.md](baseline/prescreen_log_SAD_{DATE}.md)：展开 ENG01–ENG07、SAD06、SAD07 的明细，看每一步 trace
2. [drop_codes/prescreen_log_SAD_{DATE}.md](drop_codes/prescreen_log_SAD_{DATE}.md)：SAD04 用等价编码找回 LDL
3. [amendment_v2/amendment_impact_SAD_{DATE}.md](amendment_v2/amendment_impact_SAD_{DATE}.md)
4. [bad_units/prescreen_log_SAD_{DATE}.md](bad_units/prescreen_log_SAD_{DATE}.md)、[ctgov_timeout/prescreen_log_SAD_{DATE}.md](ctgov_timeout/prescreen_log_SAD_{DATE}.md)
5. `run_console.txt`：五次运行的控制台输出

## 7. 开发中发现、已经修正的问题

- **模型的医学知识会出错**：Nova 2 Lite 说 Leqvio"是 PCSK9 抑制剂，不是 siRNA"。实际上 Leqvio = inclisiran，MED-RT 分类为 "RNA, Small Interfering"。改为药物类别一律查 RxNav，模型说"不属于"而术语库查不到时，降级为"不确定"。
- **模型会漏报药物，而且同样输入结果不同**：同一个 ENG04，一次运行里模型列出了 Leqvio（被 RxNav 纠正为 siRNA → 计入），另一次运行里模型认定 Leqvio"无关"，干脆没列出来，并声称"明确没有"，病人被放成了可能合格。修复：代码用 RxNorm 精确匹配独立扫描原文里的药名；术语库认出、且属于该类别、但模型没报告的药，强制判为"需 CRC 判断"。之后连跑 3 次结果一致。
- **模型写给 CRC 的说明也会出错**：判定已经按 RxNav 改对，但模型的说明文字仍写"Leqvio 是反义寡核苷酸（ASO）"（实际是 siRNA）。药物相关的说明改为只用结构化事实和 RxNav 的分类名拼写，模型原话只进 trace 并标注"未经核实"。
- **模型对模糊边界过于武断**：ENG01（周末一晚四五支）第一版被模型直接判为"不规律、不计入"。改为模型只提取数量，代码分别按"每天 >2 支"和"每周 >10 支"计算，两者矛盾时交给 CRC。
- 冲突说明、I5 证据都不改变 Ming 规定由人判断的结论，只提供证据和下一步建议。

## 8. 已经做出的决定（2026-10-09）

| 问题 | 决定 | 谁定的 |
|---|---|---|
| 边界换算：原文 "≥70 mg/dL (1.81 mmol/L)"，但 1.81 × 38.67 = 69.99 | 换算后四舍五入到 0.1 mg/dL：1.81 → 70.0（满足），1.80 → 69.6（不满足）。取整到整数会让 1.80 也满足，所以用一位小数 | Daisy（四舍五入）；精度由工程定 |
| 冲突不影响结论（SAD07：90 和 110 都 ≥70） | 放行：按所有候选一致的结论处理，冲突仍保留在证据里；会改变结论的冲突（ENG07）照旧复核 | Daisy |
| 合理性范围 | 保留工程侧的宽范围（只拦录入错误，如 LDL 690） | 工程 |
| 红曲米等非处方降脂保健品在 E5 窗口内 | 交给 CRC 判断（原文写"处方"，但成分与洛伐他汀相同） | 工程 |
| 非每日吸烟，"每天 >2 支"与"每周 >10 支"结论矛盾 | 交给 CRC 判断 | 工程 |
| I5 证据检索 | 按 Ming 的约定实现第一版，I5 仍由研究者判断 | 工程 |

仍需 Ming 提供：ground truth、真实 v2、审核过的等价编码表（Lp(a) 没有等价编码）、注入病例与开关的对应；也请她复核上面工程侧做的四个决定。
"""
    (R / "REVIEW.md").write_text(text, encoding="utf-8")
    print(f"wrote {R / 'REVIEW.md'}")
    print("\n".join(comp))
    print("\n".join(tbl))


if __name__ == "__main__":
    main()

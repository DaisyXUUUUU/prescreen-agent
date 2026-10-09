# Trial Pre-Screening Agent：工程侧任务框架

Oct 9, 2026 · @Daisy Xu

## 总览

工程侧共 12 项任务，目标是周六晚上让试验 B 端到端跑通，周日上午 11:59 PT 前提交。本文基于 PROJECT\_BRIEF v2，对原 D1–D10 做了三处调整：FHIR 服务器改为本地文件适配层、Agent 只处理例外、邮件和定时降为可选。

**核心架构原则：确定性引擎先跑完所有病人，agent 只接手例外。**

1. 编译好的谓词（Ming 手工编译，试验 B 共 15 条）加载进来。
2. 确定性引擎对每个病人逐条求值，输出 `met` / `not_met` / `unknown`。
3. 汇总规则把结果归入四个区。
4. 只有两类情况交给 agent：查询为空需要检索恢复（brief 决策 2），以及标准文本发生变化需要判断（决策 5）。决策 4（证据冲突转交复核）时间允许再加。
5. 每个模型决策写一行 trace，随日志一起输出。

这样做的理由：让模型为 50 个病人 × 15 条谓词逐条决定会很慢、费钱，且每次结果不同，评估数字不可信；而例外情况正是 CRC 凭经验处理、脚本做不到的部分，仍然满足“不是流水线”的要求。模型**不对病人资格做最终裁决**，证据冲突一律转交 CRC。

**时间线**

| 时间 | 任务 | 必须达成 |
| --- | --- | --- |
| 周五 | T1 基础设施、T2 接口确认、T3 数据适配层、T4 ctgov\_fetch | 一次成功的 Bedrock 调用；能查出一个病人的 LDL 值 |
| 周六上午 | T5 判定引擎、T6 汇总与日志 | **试验 B 50 个病人出日志（生死线）** |
| 周六下午 | T7 Agent、T8 trace、T9 失败开关 | 决策 2 在 demo 中可见 |
| 周六晚上 | T10 修订重筛 | 改一份快照能触发重筛报告 |
| 周日上午 | T11 评估、T12 README 与提交 | 评估数字、可运行 README、3 分钟视频 |

**需要 Ming 提供的东西**（详见 T2）：试验 B 的谓词 JSON、Synthea 病人数据及注入病例清单、ground truth 标签、ATC→RxNorm 映射表、两个试验的 NCT 编号。

## T1 基础设施（周五，约 2 小时）

目标：两人都能推送的公开仓库，加上一次成功的 Bedrock 调用。

**具体做法**

- **仓库**：GitHub 建公开仓库，加 MIT 许可证，把 Ming 加为协作者。`.gitignore` 排除 `.env`、`__pycache__`、本地缓存目录。
- **AWS 区域**：统一用 `us-west-2` 或 `us-east-1`（选 Bedrock 上已开通 Claude 模型的那个），写进 `.env.example`。
- **Bedrock 权限**：控制台 → Bedrock → Model access，申请 Anthropic Claude 模型。可能要填用途表单，**今天第一件事做**。
- **预算告警**：AWS Budgets 设 $20 告警，邮件通知两人。
- **S3 桶**：建一个桶，如 `prescreen-hack-<随机后缀>`，下设 `snapshots/`、`logs/`、`cache/` 三个前缀。
- **README 骨架**：先写安装步骤和一条运行命令，之后每完成一个模块就补一段。

**目录结构**

```
prescreen-agent/
├── data/
│   ├── patients/          # Ming 的 Synthea FHIR JSON
│   ├── predicates/        # trial_B.json, trial_G.json
│   ├── mappings/          # atc_to_rxnorm.json, local_code_map.json
│   ├── snapshots/         # 试验标准文本快照（v1、v2 用于模拟修订）
│   └── ground_truth/      # Ming 的标签
├── src/
│   ├── adapters/fhir_store.py     # T3
│   ├── tools/ctgov.py             # T4
│   ├── engine/evaluate.py         # T5
│   ├── engine/units.py            # T5 单位换算与范围
│   ├── engine/aggregate.py        # T6
│   ├── report/log_writer.py       # T6
│   ├── agent/agent.py             # T7
│   ├── agent/trace.py             # T8
│   ├── amendment/monitor.py       # T10
│   └── config.py                  # T9 失败开关
├── eval/evaluate.py               # T11
├── tests/
├── run.py                         # 一条命令跑完整流程
├── requirements.txt
├── .env.example
└── README.md
```

**验收**：`python -c` 调用一次 Bedrock 返回文本；Ming 能 clone 并推送一次提交。

## T2 与 Ming 的接口确认（周五，约 1 小时，需两人一起）

目标：今天敲定所有引擎依赖的格式，之后双方不再单方面改动。

**需要确认的事项**

| 事项 | 需要 Ming 给出 | 工程侧的用途 | 最晚时间 |
| --- | --- | --- | --- |
| 谓词文件 | 试验 B 的 15 条谓词 JSON，按 brief 第 5 节 Predicate 结构 | T5 引擎输入 | 周五晚 |
| 扩展字段 | 确认 `grade`、`resource`、`anchor`、`aggregation`、`absence_means`、`assumption` 全部启用 | T5 必须实现这些字段 | 周五 |
| 病人数据 | Synthea 导出的 FHIR Bundle JSON，每人一个文件，放 `data/patients/` | T3 读取 | 周五晚，先给 5 个也行 |
| 注入病例清单 | 每个注入病例的病人 ID、注入了什么、预期结果 | T5 单元测试、T9 失败场景 | 周六上午 |
| ATC→RxNorm 映射 | 谓词中每个 ATC 类展开成的 RxNorm 成分编码列表 | 用药谓词匹配 | 周六上午 |
| 本地编码映射 | 如 Hyperlipidemia 视为 hypercholesterolemia，单独一张表 | 从谓词中拆出来 | 周六上午 |
| Ground truth | 至少 20 个病人，每人每条可计算谓词的 `met`/`not_met`，加病人级结论 | T11 评估 | 周六晚 |
| NCT 编号 | 试验 B、G 的真实 NCT ID | T4、T10 | 周五 |
| 修订快照 v2 | 试验 B 标准文本的手改版本，至少一处实质修改、一处纯措辞修改 | T10 演示 | 周六下午 |

**工程侧要先自己做的**：在等数据期间，手写 3 个最简病人 JSON（一个合格、一个排除、一个缺化验值），先让 T3、T5 开工，不阻塞。

**分工边界**：谓词内容、编码正确性、标签由 Ming 负责；谓词怎么被执行、结果怎么汇总和呈现由工程侧负责。发现谓词有问题时，工程侧提出，由 Ming 修改，不自己改谓词文件。

## T3 数据适配层（周五，约 3 小时）

目标：一个接口和 FHIR 查询一致、但直接读本地 Synthea JSON 的数据层。替代原 D2 的 HAPI FHIR 服务器，省掉部署时间；接口不变，生产环境可直接换成真实 FHIR 服务。

**加载**

- 启动时读入 `data/patients/*.json`（FHIR Bundle），按 `patient_id → resourceType → [resources]` 建内存索引。
- 需要的资源类型：`Patient`、`Condition`、`Observation`、`MedicationRequest`、`AllergyIntolerance`，以及注入病历文本用的 `DocumentReference`（或 Ming 约定的文本字段）。

**对外函数**

```python
def fhir_query(patient_id: str, resource: str, codes: list[dict],
               window_days: int | None = None,
               anchor_date: str | None = None) -> QueryResult

def search_notes(patient_id: str, keywords: list[str]) -> QueryResult

def list_patients(since_date: str | None = None) -> list[str]
```

- `codes` 按 `system + code` 匹配，同一概念的多个编码视为 OR。
- `window_days` 和 `anchor_date` 一起决定时间窗；默认锚点是筛选日期。
- `search_notes` 是给 agent 做检索恢复用的，做简单的关键词匹配即可，返回命中片段和来源 ID。

**返回结构（错误分类型，agent 才能区别处理）**

```python
QueryResult = {
  "status": "ok" | "empty" | "timeout" | "malformed",
  "records": [ {"resource_id", "code", "value", "unit", "date"} ],
  "detail": ""   # 出错时的说明
}
```

- `empty`：查询正常但没有记录，这是触发决策 2 的信号。
- `timeout` / `malformed`：由 T9 的开关模拟，引擎按规则处理。

**验收**：能对一个手写病人查出 LDL-C 值并带回 `resource_id`；用一个不存在的编码查询返回 `empty` 而不是报错。

## T4 ctgov\_fetch 工具（周五，约 1.5 小时）

目标：从 ClinicalTrials.gov API v2 获取试验入排标准，这是满足“调用别人的工具”的主要依据。

**函数**

```python
def ctgov_fetch(nct_id: str) -> FetchResult
# GET https://clinicaltrials.gov/api/v2/studies/{nct_id}
# 取 protocolSection.eligibilityModule 下的
#   eligibilityCriteria, minimumAge, maximumAge, sex
```

**健壮性**

- 超时 10 秒，失败重试 1 次。
- 成功后写缓存：`cache/ctgov/{nct_id}.json`，附抓取时间。
- 仍然失败时回退到缓存，返回 `status: "stale"` 和缓存年龄。缓存超过 14 天则返回 `status: "error"`，日志拒绝生成（brief 第 6 节规则）。
- 返回值同样分类型：`ok` / `stale` / `error`，附 `fetched_at`。

**快照（供 T10 使用）**

- 每次成功抓取时，把标准文本存成 `snapshots/{nct_id}/{YYYY-MM-DD}.txt` 并计算 SHA-256。
- 本地和 S3 各存一份。

**验收**：用真实 NCT 编号能取回标准文本；断网（或打开 T9 的超时开关）时返回缓存并标注 `stale`。

## T5 判定引擎（周六上午，约 4 小时）

目标：纯函数，输入一条谓词和一个病人，输出一条 Verdict。不调用 LLM，相同输入永远相同输出。这是技术深度分的核心。

**函数**

```python
def evaluate(predicate: dict, patient_id: str, screening_date: str) -> Verdict
```

**处理步骤**

1. 若 `computable == false` 或 `grade == "N"`：直接返回 `unknown`，note 写“留给 CRC 判断”。
2. 确定时间锚点：`anchor.event == "index_event"` 时，先查最近一次符合的卒中或 TIA 作为锚点（试验 G 才需要，B 可以先不做）。
3. 调用 `fhir_query`，按 `resource`、`codes`、`window_days` 取记录。
4. 结果为 `empty`：按 `absence_means` 返回（诊断缺失 → `not_met`，化验缺失 → `unknown`，过敏缺失 → `unknown`），并在 Verdict 上标记 `needs_recovery: true`，供 T7 的 agent 接手。
5. 数值类：先过单位换算和合理性范围检查（见下），再按 `aggregation` 取值（`most_recent` / `mean_of_last_3` / `count_distinct_active_ingredients`），最后按 `operator` 比较。
6. 填 `evidence`：每条用到的记录写 `resource_id`、`value`、`date`。
7. 设 `blocking`：取谓词上的值，缺省为 `true`。

**第一版只实现试验 B 用到的运算符**：`<`、`<=`、`>`、`>=`、`exists`。`no_change`、`active_for_days` 等试验 G 或时间允许再做。

**单位换算与范围检查（`engine/units.py`）**

| 指标 | 标准单位 | 可换算单位 | 合理范围 |
| --- | --- | --- | --- |
| LDL-C / 总胆固醇 / HDL-C | mg/dL | mmol/L × 38.67 | 10–500 |
| 甘油三酯 | mg/dL | mmol/L × 88.57 | 20–5000 |
| 收缩压 | mmHg | 无 | 60–260 |
| 舒张压 | mmHg | 无 | 30–160 |
| ALT | U/L | 无 | 1–2000 |

换算系数和范围请 Ming 复核。单位无法识别或换算后超出范围 → 该谓词返回 `unknown`，note 写明原因（brief 失败路径“工具返回垃圾”）。

**测试（`tests/test_evaluate.py`）**

- 用 Ming 的注入病例逐个写测试：边界值（刚好等于阈值）、缺化验、错单位、时间窗外的记录。
- 每个测试断言 `status` 和 `evidence` 中的 `resource_id`。

**验收**：试验 B 全部可计算谓词对 3 个手写病人返回预期结果；注入病例测试全部通过。

## T6 汇总与日志（周六上午，约 2 小时）

目标：把每个病人的谓词结果汇总成病人级结论，输出 CRC 能直接用的预筛日志。**完成这一项，试验 B 就端到端跑通了。**

**汇总规则（`engine/aggregate.py`，固定规则，不用模型）**

按以下顺序判断，命中即停：

1. 任一排除标准 `met` → **已排除**，注明是哪条。
2. 任一谓词带冲突标记（T7 决策 4 产生）→ **需复核**。
3. 任一 `blocking: true` 的谓词为 `unknown` → **待补**，列出缺少的数据项。
4. 所有可计算的入组标准 `met` → **可能合格**；若有 `blocking: false` 的 `unknown`，附“就诊时确认”备注。
5. 任一入组标准 `not_met` → **已排除**。

注意第 3 条排在第 5 条之前的顺序要和 Ming 确认，它体现 brief 目标 2：“宁可答未知，不轻易排除”。

**日志格式（`report/log_writer.py`）**

- 输出两份：`prescreen_log_{trial}_{date}.md`（给人看）和 `.csv`（给评估脚本用）。
- Markdown 顶部：试验编号、标准抓取时间（缓存时标注 stale 及天数）、各区人数统计。
- 四个区：可能合格、待补、已排除、需复核。每行：病人 ID、结论、关键证据（`resource_id` + 值 + 日期）、备注、该病人相关的 trace 条目。
- 写入本地 `out/` 并上传 S3 `logs/{trial}/{date}/`。

**入口**

```bash
python run.py --trial B --date 2026-10-12
```

**验收**：50 个病人全部出现在日志的某一个区，没有遗漏；每条“已排除”都能追溯到具体谓词和记录。

## T7 Agent 例外处理层（周六下午，约 4 小时）

目标：用 Strands Agents + Bedrock 实现 brief 决策 2（检索恢复）。这是 demo 中最能体现“agent 而非流水线”的部分。

**触发方式**

T5 跑完后，收集所有 `needs_recovery: true` 的 Verdict，逐条交给 agent。agent 不碰其他已有结论的谓词。

**Agent 可用的工具**

| 工具 | 作用 | 来源 |
| --- | --- | --- |
| `get_predicate(criterion_id)` | 读谓词定义，包括概念、编码、阈值 | 谓词文件 |
| `lookup_equivalent_codes(concept, system)` | 返回同一概念的等价编码（LOINC、SNOMED 等） | Ming 的本地映射表 |
| `fhir_query(...)` | 用新编码重查 | T3 |
| `search_notes(patient_id, keywords)` | 在病历文本中搜索 | T3 |
| `evaluate_with_records(criterion_id, records)` | 把找到的记录交回确定性引擎判定，模型自己不做数值比较 | T5 |
| `record_decision(...)` | 写 trace，并给出最终状态 | T8 |

**系统提示词要点**

- 你在帮临床研究协调员处理“查询为空”的情况。
- 按顺序尝试：等价编码 → 病历文本 → 放弃。每一步都要调用 `record_decision` 说明做了什么、为什么。
- 找到记录后必须交给 `evaluate_with_records`，**不得自行比较数值或下结论**。
- 病历文本中的描述（如“患者自述 LDL 偏高”）不能当作化验值，只能作为“建议补查”的依据。
- 放弃时返回 `unknown`，note 写清楚查过哪些编码、哪些关键词，并给出建议（如“建议补查血脂四项”）。

**骨架**

```python
from strands import Agent
from strands.models import BedrockModel

recovery_agent = Agent(
    model=BedrockModel(model_id=os.environ["BEDROCK_MODEL_ID"]),
    tools=[get_predicate, lookup_equivalent_codes, fhir_query,
           search_notes, evaluate_with_records, record_decision],
    system_prompt=RECOVERY_PROMPT,
)

for v in pending_recovery:
    recovery_agent(f"病人 {v.patient_id} 的谓词 {v.criterion_id} 查询为空，请处理。")
```

**控制成本和稳定性**：每个 Verdict 新建一次对话（不累积上下文）；设最大工具调用次数 6 次；temperature 设为 0。

**时间允许再加：决策 4（证据冲突）**——当结构化数据和病历文本矛盾时，agent 列出双方证据，状态设为冲突，由 T6 归入“需复核”。模型只呈现，不裁决。

**验收**：Ming 埋入的“错编码”病例中，agent 能通过等价编码找回数值；完全没有数据的病例返回 `unknown` 并附可读的说明。

## T8 trace 记录（周六下午，约 1 小时，与 T7 同时做）

目标：每个模型决策留下一行可读的记录，出现在日志里，也是 demo 画面的主角。brief 指标要求 trace 覆盖率 100%。

**结构**（对应 brief Verdict 的 `trace` 字段）

```python
{"step": 1,
 "tool": "lookup_equivalent_codes",
 "result": "找到 LOINC 13457-7（计算 LDL）",
 "decision": "用等价编码重查，因原编码 18262-6 无记录"}
```

**实现**

- `record_decision` 工具把 trace 追加到当前 Verdict 上。
- 规则类处理（缓存回退、单位换算）也写 trace，`tool` 字段写 `rule:cache_fallback`、`rule:unit_convert`，方便评审区分模型决策和固定规则。
- 同时把完整 trace 存成 `out/trace_{trial}_{date}.jsonl`，供评估脚本统计覆盖率。

**在日志中的呈现**：病人行下方缩进显示，例如：

```
P-017  待补  LDL-C 无法评估
  ↳ 原编码无记录 → 换等价编码重查，无记录 → 搜索病历“LDL / cholesterol”，无化验值
  ↳ 结论：unknown；建议补查血脂四项
```

**验收**：每个经过 agent 的 Verdict 至少有一条 trace；日志里能直接读懂 agent 做了什么。

## T9 失败注入开关（周六下午，约 1.5 小时）

目标：每种失败场景都能用一个配置开关稳定复现，录视频和现场演示不依赖真实故障碰巧发生。

**配置（`config.py`，也可用命令行参数覆盖）**

```python
FAILURES = {
    "ctgov_timeout": False,   # ctgov_fetch 直接抛超时
    "bad_units": False,       # 指定病人的 LDL 改成错误单位或离谱值
    "drop_codes": False,      # 指定病人的 LDL 记录改用非常规编码
    "amendment_v2": False,    # T10 读取 v2 快照替代真实抓取
    "note_conflict": False,   # 可选：注入与结构化数据矛盾的病历文本
}
```

```bash
python run.py --trial B --fail ctgov_timeout
```

**场景与预期表现**

| 开关 | brief 场景 | 类型 | 预期表现 | 优先级 |
| --- | --- | --- | --- | --- |
| `ctgov_timeout` | 工具失败 | 规则 | 用缓存，日志顶部标注 stale 及天数 | 必做 |
| `bad_units` | 工具返回垃圾 | 规则 | 能换算则换算，否则 `unknown`，trace 写原因 | 必做 |
| `drop_codes` | 工具返回空 | 模型 | agent 换编码找回数值，trace 可见 | **必做，demo 主角** |
| `amendment_v2` | 模糊修订 | 模型 | 见 T10 | 必做 |
| `note_conflict` | 工具与模型分歧 | 模型 | 两份证据并列，转需复核 | 可选 |

视频最低要求：一个规则场景 + `drop_codes` + 修订或冲突中的一个。

**验收**：每个开关各跑一次，输出符合上表预期；关闭所有开关时结果和正常运行一致。

## T10 修订监测与重筛（周六晚上，约 3 小时）

目标：标准文本变化时，判断是否实质修改，并输出“哪些病人状态变了、为什么”的报告。实现 brief 决策 5。

**流程**

1. **检测**：新抓取文本的 SHA-256 与上一份快照比较，一致则结束。
2. **条目级 diff**：把两版文本按条目切分（按换行和编号），用 `difflib` 找出新增、删除、修改的条目。
3. **模型分类**：每个变化条目交给 Bedrock，输出三选一：`substantive`（实质修改，如阈值、时间窗改变）/ `wording`（仅措辞）/ `ambiguous`（无法判断），附一句理由，写 trace。
4. **处理**：
   - `wording` → 记录，不重筛。
   - `ambiguous` → 标记“需 CRC 确认”，不重筛（brief：不凭猜测重筛）。
   - `substantive` → 进入第 5 步。
5. **重编译**：实质修改的条目需要更新谓词。**演示版由 Ming 预先准备好 v2 谓词文件**，与 v2 快照配套；自动编译属于 brief 决策 1，已披露为人工复核，不做。
6. **重筛**：用 v2 谓词对该试验全部病人重新跑 T5–T6，再与上一次结果逐病人对比。不做“只重跑受影响判定”的依赖追踪，引擎够快，全量重跑产出相同。
7. **影响报告**：`amendment_impact_{trial}_{date}.md`，列出修改了哪些条目及分类，以及每个状态变化的病人：旧状态 → 新状态，原因指向具体条目和证据。

**演示准备**（依赖 T2 中 Ming 的 v2 快照）：v2 至少包含一处实质修改（例如 LDL 阈值下调，使之前被排除的病人变为可能合格）和一处纯措辞修改。

**验收**：打开 `amendment_v2` 开关运行，报告正确识别两处修改的类型；Ming 预埋的状态翻转病人全部出现在报告中（brief 指标：修订召回率 100%）。

## T11 评估脚本（周日上午，约 2 小时）

目标：把引擎输出和 Ming 的 ground truth 对比，算出 brief 第 11 节的指标。brief 写明评估数字“绝不能砍”。

**输入**：T6 的 CSV、T8 的 trace JSONL、Ming 的标签文件、T9 各开关的运行结果。

**输出指标**

| 指标 | 计算方式 | 目标 |
| --- | --- | --- |
| 误排除数 | 标签为合格、输出为已排除的病人数 | 0 |
| 病人级敏感度 | 标签合格者中被归入“可能合格”或“待补”的比例 | ≥ 95% |
| 谓词级准确率 | 可计算谓词上 `met`/`not_met` 与标签一致的比例 | ≥ 90% |
| 弃权率 | 输出 `unknown` 的谓词占比 | 报告即可 |
| 证据覆盖率 | 带有效 `resource_id` 的 Verdict 占比 | 100% |
| trace 覆盖率 | 经过 agent 的 Verdict 中有 trace 的占比 | 100% |
| 恢复率 | `drop_codes` 埋入病例中被 agent 找回的比例 | 报告即可 |
| 修订召回率 | 预埋状态翻转病人被报告检出的比例 | 100% |
| 失败场景 | 可用开关复现的场景数 | 实际数 / 5 |

**错误归因**：每个与标签不一致的结果，输出一行明细（病人、谓词、期望、实际），由 Ming 归入四类原因之一：谓词编译、概念映射、数据问题、引擎缺陷。

**运行**

```bash
python eval/evaluate.py --trial B --labels data/ground_truth/trial_B.csv
```

输出 `eval_report.md`，数字直接用于 writeup 和视频。**验收**：一条命令出完整指标表。

## T12 README 验证、演示与提交（周日上午，截止 11:59 PT）

目标：四项提交物全部到位，评审在未登录状态下能打开仓库并照 README 跑通。

**README 必须包含**

- 一段话说明：为谁（CRC）、解决什么、产出什么。
- 安装：Python 版本、`pip install -r requirements.txt`、`.env.example` 中各变量的含义（AWS 区域、Bedrock 模型 ID、S3 桶名）。
- 一条命令跑通：`python run.py --trial B`，以及每个失败开关的命令。
- 架构图或简短说明：确定性引擎 + agent 例外处理，模型决策和固定规则的边界。
- 数据声明：仅使用 Synthea 合成数据和公开 API，无 PHI。
- 已知限制：照搬 brief 第 7 节。

**验证**

- [ ] 在一个全新目录（或新的虚拟环境）从 `git clone` 开始，严格照 README 走一遍。
- [ ] 用无痕窗口打开仓库链接，确认不是 404。
- [ ] 仓库根目录有 LICENSE 文件。

**视频（3 分钟，与 Ming 一起录）**：CRC 是谁和每周成本（20 秒）→ 正常运行出日志（40 秒）→ `drop_codes` 展示 agent trace（50 秒）→ 一个规则失败场景（20 秒）→ 修订重筛报告（30 秒）→ 评估数字（20 秒）。工程侧负责准备好每段要跑的命令和预先生成的输出，避免录制时等待。

**writeup 中工程侧负责的段落**：架构、agent 决策与固定规则的边界、失败处理、AWS 服务使用。

## 可选项（按顺序，有余力再做）

1. **决策 4 证据冲突**：见 T7 末尾。
2. **EventBridge 定时**：配置每周一 8:00 触发的规则，截图放进 README 即可，不必真的跑起来。
3. **Lambda 封装**：把 `run.py` 打包成一个 Lambda，由 EventBridge 触发。
4. **SES 邮件**：沙盒模式下收发地址都要先验证，提前做；做不完就只保留写入 S3。
5. **试验 G**：需要实现 `index_event` 锚点和 `no_change`、`active_for_days` 运算符。
6. **本地 HAPI FHIR**：把 T3 的文件适配层换成 Docker 版 HAPI FHIR，接口不变。

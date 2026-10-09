# Ming数据交付与工程对接清单

整理日期：2026-10-09。所有路径相对仓库根目录。本文记录盘点时状态；本次轻量Git交付范围见[MING_SUBMISSION.md](MING_SUBMISSION.md)，是否已上传以远程分支为准。未上传S3。

## 交付原则

主试验为T6 / NCT07347678 / SAD，次试验为T2 / NCT07610278。不得将本地T6误认作工程任务T6或默认占位试验B。试验原文与当前T6规则一致性已由用户确认；空腹≥6小时是随后确认的demo policy，尚未进入执行器；method要求仍待明确。

GitHub保存代码、公开试验源、轻量合成筛查病例、配置、审核记录与独立标签。完整原始Synthea病历作为单独数据附件；不能与筛查病例直接混放。AWS目前不是输入文件交付的前提。仓库目录接通不代表规则语义已经适配。

## 现有材料与目的地

| 材料 | 当前路径 | 交付/运行目的地 | 状态与处理 |
|---|---|---|---|
| 主/次试验身份 | `demo_scope.json` | GitHub原路径；工程注册到`src/config.py`的TRIALS，或显式CLI指定NCT | T6需注册为明确SAD范围，不擅自映射B |
| T6官方完整源记录 | `t6_sad_demo/source/NCT07347678.json` | GitHub保留原路径 | 可直接交付；不要伪造下载时间 |
| 工程规范化试验快照 | 现有完整JSON不是该格式 | `data/snapshots/NCT07347678/YYYY-MM-DD.txt` | 用`src/tools/ctgov.py`生成；含年龄/性别头及标准正文。保留原JSON，不把它改后缀冒充快照；新抓取需与已审核版本对比 |
| T6已冻结规则和哈希 | `t6_sad_demo/rules/` | GitHub原路径；适配后另存`data/predicates/trial_T6.json` | 原文件可交付，但不能直接作为根run.py输入；新版本纳入6小时政策，不能覆盖已冻结1.0.0 |
| 8份筛查FHIR病例 | `t6_sad_demo/data/cases/SAD01..08.json` | GitHub原路径；适配验证后发布至`data/patients/t6_sad/`并传`--patients` | 数据为设计的合成筛查记录，非完整病史；当前可供本地T6执行器测试 |
| 8份筛查上下文 | `t6_sad_demo/data/context/SAD01..08.json` | GitHub原路径；工程新增`data/contexts/t6_sad/`读取约定 | 工程当前没有这个入口，不能复制后声称已接入；须保留case_id、真实Patient.id、Encounter、筛查时间和问卷ID |
| 病例manifest/生成配置 | `t6_sad_demo/data/case_manifest.json`、`synthea.properties`、`generation.log` | GitHub原路径 | 来源哈希、种子和版本一并交付；清单不等于临床标签 |
| 完整原始Synthea病历 | `t6_sad_demo/data/raw/fhir/*.json`，8份约61.73 MB | 单独GitHub Release数据附件（如`synthea-t6-seed20261009.zip`）；解压还原原路径 | 建议交付方式，尚未创建/上传；本地Git已忽略。使用现有文件以保持精确哈希，不承诺重新生成字节一致 |
| T6执行器和技术测试 | `t6_sad_demo/{engine,prepare,run,test_demo}.py` | GitHub原路径 | 可直接交付，作为回归基线；不要替换Daisy的src文件 |
| 现有日志和网页报告 | `t6_sad_demo/outputs/` | GitHub原路径，作为演示样例 | 不是ground truth；标明仍有空腹/method实现缺口 |
| I5检索约定、SAD02复核 | `t6_sad_demo/I5_EVIDENCE_REVIEW.md`、`SAD02_REVIEW.md`及README | GitHub原路径 | 可直接交付；I5检索仍待实现；SAD02原始状态为Ex-smoker，未改病例 |
| T2参考数据 | `t2_backup/` | GitHub原路径 | 参考交付；暂不放入可执行谓词目录，旧source_locator依赖归档，未来适配时修订引用 |
| 工程运行结果 | 根`run.py`生成的`out/` | 本地out；配置桶后日志上传`s3://<S3_BUCKET>/logs/<trial>/<date>/` | T6尚未接入；不要将现有T6日志冒充工程输出 |
| 工程抓取快照 | `data/snapshots/...` | 配置桶后上传`s3://<S3_BUCKET>/snapshots/<NCT>/<文件名>` | 为已有工程的输出约定；桶名未在本次核验，不进行上传 |

完整原始病历需分发给复核者或要执行`test_originals_unchanged`的人员；只用现有筛查病例运行`t6_sad_demo/run.py`不需要raw。不得把同一Patient的原始Bundle和筛查Bundle放进同一个工程患者目录：当前FhirStore按Patient.id赋值，后载入文件可能覆盖前者，并不会自动合并。

## 还需要准备的材料

- **字段/编码映射**：先形成指标、资源、字段、单位、时间锚点、方法要求的审核记录；经确认的等价编码表放`data/mappings/local_code_map.json`，工程已有读取入口。不能把样例等价表直接当作经过临床确认的映射。
- **人工参考答案**：拟放`data/ground_truth/trial_T6.csv`，现有工程基础字段为`patient_id,criterion_id,expected`。先完成88项独立标注，并保留证据、理由、审核人。unknown、人工项、患者四态和子谓词拆分后的ID对应需要先统一契约；现有示例标签不能代替临床标签。
- **改版演示包**：准备明确标为模拟修订的`data/snapshots/NCT07347678/amendment_v2.txt`、`data/predicates/trial_T6_v2.json`、`data/ground_truth/trial_T6_amendment_flips.txt`。真实原文不修改；翻转患者由独立核查确定。
- **失败注入病例映射**：用实际Patient.id而非SAD02等case_id登记`src/config.py`的FAILURE_TARGETS；另建吸烟冲突场景。LDL边界、缺失与冲突病例目的要分开。
- **I5证据包/人工审核记录**：建议未来分别放`out/i5_evidence/`及`data/reviews/t6_sad/`；这是待实现目录，不是现有工具已支持的入口。审核结论不覆盖自动日志。

## 必须先解决的工程对接问题

1. 当前冻结格式是`rules[].predicate`；工程读取`predicates[]`及`operator/value/codes/resource`。年龄/BMI区间、E1 OR与逐实验室ULN、吸烟定量和访谈窗口不能靠改键名保真转换。
2. `src/adapters/fhir_store.py`当前不载入Specimen、Encounter、QuestionnaireResponse、MedicationStatement、DiagnosticReport、Provenance；Observation返回字段不含ULN、method、specimen及encounter引用。需补充读取/关联/证据返回，避免丢失T6判定前提。
3. T6要求明确筛查就诊、空腹≥6小时政策和日历月窗口；工程只有window_days及最新记录等通用行为，必须逐项核对。不能把3个月随意转换为90天，或在冲突结果中静默选最新。
4. 聚合语义尚未统一：T6明确失败优先，工程配置`PENDING_BEFORE_INCLUSION_FAIL=True`。I5应保留人工审核及证据，不因不阻塞计算就显示为完整资格成立。
5. ground truth与评估分母尚未统一。现有工程敏感度把pending计入保留的阳性；Ming项目说明采用更严格的成功阳性定义。报告前应统一指标，不直接比较两个百分比。

## 下一步顺序

1. 将现有轻量材料作为GitHub独立分支的待审核交付，另行提交/推送；保留当前历史。
2. 与Daisy核对上述数据契约，再实现T6适配；优先保留病例和证据结构，不通过删掉条件使数据“能跑”。
3. 应用6小时新版本政策、确定method范围，完成8例回归及I5证据场景测试。
4. Ming完成独立标签后接评估；再接模拟修订。T2后续进行。

## 不交付到GitHub的内容

本地`tools/`依赖、旧`archive/`、`.env`和任何凭据、虚拟环境、缓存。完整raw通过单独数据附件交付，不混入常规提交。无需手工将输入上传Bedrock：模型由程序调用，输入仍由FHIR工具读取。

文件级盘点见[data_inventory.json](data_inventory.json)：列出当前活动材料的路径、字节数与SHA-256；raw仅列清单，不复制或上传。它是交付清单，不替代冻结规则和病例manifest。

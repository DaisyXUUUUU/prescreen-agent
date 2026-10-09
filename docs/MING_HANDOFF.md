# Ming材料接入记录

日期：2026-10-09。

## Git接入

- 远程仓库：https://github.com/DaisyXUUUUU/prescreen-agent
- 本地工作分支：`ming/t6-sad-integration`，基于远程`main`提交`1c0b8af606ce8a34a1c1b10fcc4e5fd8e44bb8f2`。
- 原仓库工程文件已取回；本地原README保存为`MING_DEMO.md`。根目录`PROJECT_BRIEF.md`为本对话维护的试验演示说明，`docs/PROJECT_BRIEF.md`保留远程工程背景；二者尚未合并成统一规格。
- 本记录创建时尚未提交或推送本地新增材料。远程分支未修改。

## 人工确认

用户在本对话中明确确认：“试验原文与编译规则已验证一致”。本次记录对应当前T6 SAD版本`1.0.0`，不将其扩大为T2、FHIR映射、完整方案核查、病例标签或系统性能的确认。

保持冻结规则及manifest不变。独立病例ground truth仍待完成；I5证据检索授权及人工判断边界见[专门约定](../t6_sad_demo/I5_EVIDENCE_REVIEW.md)。

后续FHIR复核提出两项未关闭问题：空腹仅检查时长大于0，需要方案或明确demo policy确定下限及异常值处理；method要求与代码不一致，需要按指标确定要求后更新版本。原文与规则一致的确认不代表这些操作定义已解决。E1的OR语义已补充：一侧有效确认超标足以触发排除，另一侧冲突保留但不推翻独立成立的判定。详情与待补测试见[T6复核事项](../t6_sad_demo/README.md#fhir映射复核未关闭事项2026-10-09)。本次仅记录复核，未修改执行器、冻结规则或病例。

## 文件入口

- [完整数据交付清单与目标目录](DATA_DELIVERY.md)、[文件级哈希盘点](data_inventory.json)。目的地分为当前可交付资料和待适配运行输入，尚未上传。

- [本地演示入口](../MING_DEMO.md)
- [T6说明](../t6_sad_demo/README.md)、[规则](../t6_sad_demo/rules/sad-1.0.0.json)、[输入病例](../t6_sad_demo/data/cases/)、[运行器](../t6_sad_demo/run.py)
- [T2参考](../t2_backup/README.md)
- Daisy工程：`src/`、根目录`run.py`、`tests/`、`eval/`。

T6/T2在Ming材料中是试验编号，不是`docs/TASKS.md`中的工程任务编号。没有自动把T6改名为远程占位试验B。

## 当前边界与下一步

Git仓库接入不等于T6已接入工程流水线。T6的嵌套predicate、筛查上下文、访谈字段、人工项和聚合策略，尚未转换或验证为`src/`的输入契约。当前保留两个入口，避免直接复制规则到`data/predicates/`导致误执行。

下一步先核对两套规则schema、FHIR引用/编码/时间窗口及unknown/人工项聚合语义，再实现适配并用既有8例回归验证；独立人工标签另行准备。I5只读搜索及证据包仍待实现，不能因远程已有recovery agent就声称支持I5。

`tools/`、`archive/`和完整`data/raw/`已设为Git忽略项，仍保留本地；轻量研究病例与manifest可进入版本管理。Synthea原始数据生成方式见T6 README，原始文件哈希测试需要这些本地raw文件；新克隆不会自动带有它们。

## 后续决定：空腹最低时长

2026-10-09用户确认I2/I4的最低空腹时长为≥6小时，作为demo policy记录，待申办方/完整方案确认。下限定义已解决；执行器尚未更新，极端大值处理和按指标的method要求仍待明确。此前“最低时长待定”的记录由本决定更新，不修改冻结1.0.0。

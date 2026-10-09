# SAD02吸烟证据复核

复核日期：2026-10-09。结论：保留LDL=69场景及现有问卷，不改为当前/间歇吸烟。

## 核对范围与来源

依据`data/case_manifest.json`定位SAD02的原始Synthea合成病历（不是真实患者）：

`data/raw/fhir/Celsa248_Zemlak964_717a30c9-adba-2d70-f1ba-28dcf0c048c4.json`

原文件SHA-256与manifest一致：`983852613d587612ae580fa42d2035d1b937dba371c3605aeccc0f6bfc266c16`。

患者ID：`717a30c9-adba-2d70-f1ba-28dcf0c048c4`。筛查时间：2026-10-09 09:00（-04:00）；三个月窗口起点：2026-07-09。

## 实际记录

窗口内两条LOINC `72166-2`（Tobacco smoking status）均记录SNOMED `8517006`、原文`Ex-smoker (finding)`：

- 2026-08-23 22:12:53（-04:00），Observation `71cf2011-686c-f837-6763-80349b0fa4db`。
- 2026-09-06 22:12:53（-04:00），Observation `a80ef3ac-2518-bb03-bcf1-7304d2a81682`。

病历另有自2006-04-30开始的高血压生活方式CarePlan `82f343bc-b820-1977-c3da-5359897e2c68`，其中包含戒烟教育。教育活动不是当前吸烟或吸烟量的直接证据。

不能仅因出现吸烟状态Observation、或搜索命中smoking/tobacco，就认定窗口内发生吸烟；必须读取valueCodeableConcept及日期。上述记录不支持将问卷改为current或intermittent，也不提供每日/每周吸烟量。

## 与问卷的关系

现有`current_smoker=false`、`smoking_pattern=none_in_window`及0支/日、0支/周是设计的合成筛查访谈答案，不是从原始记录推导出的数值。`none_in_window`不表示终身从未吸烟，因此与窗口内的Ex-smoker记录没有直接矛盾。

两次Ex-smoker记录不能独立证明整个窗口持续未吸烟；保留问卷不等于原始病历已验证其完整性。不得把两条记录写成对整个窗口的全面确认。

## 场景与后续测试边界

SAD02继续以I2（LDL=69，未达到70）为唯一明确不满足项；E3在现有合成访谈输入下不触发，I5仍人工待审。现有执行器尚未接入这些纵向吸烟记录，本复核不声称已实现结构化史合并或冲突检测。

接入结构化史时，应测试“Ex-smoker记录＋窗口未吸烟访谈”不会仅因出现吸烟编码而产生假冲突；另建独立的当前吸烟与否认访谈冲突场景，不复用SAD02。完整原始病历中其他病史尚未完成本轮复核。

本次不改变病例、问卷、manifest、规则或执行器。

# Ming：T6 SAD开发材料交付

2026-10-09；目标分支：`ming/t6-sad-integration`。

本次提交T6 / NCT07347678 / SAD的规则、8份合成筛查病例及上下文、来源清单、专用执行器、17个技术测试方法、示例结果和复核说明；T2 / NCT07610278为第二试验参考。原文与T6规则一致性已由用户核对。详细文件清单见[DATA_DELIVERY.md](DATA_DELIVERY.md)。

## 与队友要求的差别

- B/G与T6/T2编号尚未统一；本次不擅自把T6改为B。
- 当前10条标准加年龄，采用`rules[].predicate`；不是已适配的15条`predicates[]`，不能直接送入根目录run.py。
- 有8名开发病例，复用Synthea人口学并构造筛查检查/访谈；非完整病史，也不是≥20人独立ground truth。场景预期分布于prepare.py/test_demo.py，患者ID在manifest中，尚未接工程FAILURE_TARGETS。
- 扩展字段范围、ATC→RxNorm映射、审核后的等价编码、v2模拟修订和独立人工标签尚未交付。
- 空腹≥6小时已确认为demo policy，但执行器尚未更新；method要求仍待明确。I5保持人工判断，Agent证据检索仅有约定文档，尚未实现。
- Daisy适配器尚需支持标本、问卷、用药陈述、ULN及就诊关联，并统一聚合语义和单位审核。
- GitHub当前认证账号为`Charlottttttte`；S3桶名及指定用户读写权限未在本次验证。

## 本次上传范围

轻量文件保留原目录。完整原始Synthea病历（约61.73 MB）、tools运行依赖、archive历史材料不在此次提交中。manifest包含raw来源及哈希，但不包含raw文件；这些可另行作为数据附件提供。原有工程src/、tests/和data输入目录未被替换。

冻结规则和病例使用.gitattributes禁用换行转换，避免Windows/Linux克隆时SHA-256变化。

## 接收方运行

```powershell
python t6_sad_demo/run.py
```

现有病例可直接运行，无需AWS或重新生成Synthea。预期8人、88项评价：计算部分通过2、不满足4、缺失待补1、冲突待审1；全部仍有I5人工项。

完整技术测试命令为`python t6_sad_demo/test_demo.py`。其中`test_originals_unchanged`需要未包含在此次提交的原始raw文件；本地具备raw时17项通过。仅接收本次提交不能声称完整17项测试已可直接复现。样例输出不是临床准确率或独立参考答案。

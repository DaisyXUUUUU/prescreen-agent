# Trial Pre-Screening Demo

当前主演示：**T6 / NCT07347678 / SAD队列**。第二试验：**T2 / NCT07610278**。T7已退出主演示。

从项目根目录运行：

```powershell
python t6_sad_demo/run.py
python t6_sad_demo/test_demo.py
```

现有数据可直接重跑，无需AWS凭据或重新下载Synthea。

- [本次运行报告](t6_sad_demo/outputs/REPORT.md)
- [可展开证据的网页报告](t6_sad_demo/outputs/report.html)
- [预筛选日志JSON](t6_sad_demo/outputs/prescreening_log.json)
- [人工/缺失/冲突队列](t6_sad_demo/outputs/exception_queue.json)
- [T6操作与限制](t6_sad_demo/README.md)
- [I5证据检索与人工判断约定（待实现）](t6_sad_demo/I5_EVIDENCE_REVIEW.md)

当前目录：

- `t6_sad_demo/`：当前可运行的SAD规则、8人合成数据、确定性执行器、测试和结果。
- `t2_backup/`：第二试验的9条规则参考及官方源记录，尚未接入此执行器。
- `tools/`：Synthea 3.3.0及本地FHIR验证虚拟环境，属于运行依赖。
- `archive/2026-10-09-pre-sad/`：早期比较报告、T7规格/数据及旧脚本。归档未删除；内部旧绝对路径可能失效，当前运行不依赖它们。

本地闭环已经完成“读取FHIR→按SAD规则评价→带证据日志→例外队列→本地交付”。尚未接入LLM/Bedrock Agent、FHIR服务、AWS交付或自动改版监控。当前测试是作者设计的技术测试，不是独立临床准确率评估。

I5的下一步已授权为：Agent在指定患者的FHIR记录中只读检索、整理肝肾相关证据并交给人工判断；自动结果仍为`unknown`且需要人工复核。目前I5代码只返回人工待审原因，尚未实现该证据检索。

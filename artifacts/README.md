# 验证证据说明

这里保留 1.0.0 与 1.1.0 的历史教学验证记录。原验证环境的项目绝对路径已统一替换为 `<project-root>`，除此之外保留测试计数、状态、错误原因及事实结果。

- `verification-v11.json` / `tests-v11.txt`：2026-10-03 的 73 项测试，65 通过、8 项活体隔离集成跳过
- `sandbox-report.json`：真实 Bubblewrap probe 被宿主拒绝；没有 host fallback
- `all-results-v11.json`：原十版达到预期，V11 为 `blocked_sandbox`
- `eval-report-v11-legacy.json`：旧 V10 toy evaluator 的行为检查，不能视为 V11 隔离或真实模型 benchmark
- `v11-checkpoint.json`：路径清理后的示例，不是可直接恢复的运行目录

复现命令见根目录 README 与 CONTRIBUTING。支持完整 sandbox profile 的不同环境可以得到不同结果；需要实际运行后再记录结论，不能把这些历史记录当作当前机器状态。

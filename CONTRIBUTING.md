# 维护与验证

本项目优先保持教学骨架简单、可读、可复现。版本配方放在 `versions/`，共享组件在 `simple_agent/`；新增机制应保留此前各版的教学差异与回归。

## 提交改动前

```bash
python -m unittest discover -s tests -v
python -m compileall -q simple_agent versions tests run.py evaluate.py sandbox_check.py
python run.py --legacy-all
python evaluate.py
python sandbox_check.py
python -m versions.v11
```

前四条检查原有机制与回归。最后两条需要 Linux、Bubblewrap 和宿主允许完整 namespace profile；在不支持的环境中，必须保留 `blocked_sandbox`/非零退出与准确原因，不能回退 host 或写成隔离通过。完整活体集成的 skip 与 pass 分开报告。

不要执行陌生仓库或敌对样本验证旧版 host runner；不要用真实凭据测试边界。真实模型适配器默认关闭，不需要 API key 或付费调用。

## 文档与证据

- 改动对应 lesson、架构、安全边界和 `simple_codingagent.context.md`
- 能力/结果变化时同步版本号与 `CHANGELOG.md`
- `artifacts/` 是带验证日期的历史教学证据，不是每次 clone 的实时运行状态
- 新验证需记录环境、实际结果、失败/跳过范围；不能覆盖历史结论后假装已完成活体验收
- 发布日志时清除机器绝对路径、真实秘密与无关个人信息；保留失败原因和测试计数
- 不提交 `.venv`、`runs`、Python 缓存、凭据或私人配置

使用独立分支与可审阅的 pull request，说明范围、测试结果和残余限制。涉及 sandbox 参数、执行输入、网络、恢复或证据规则的变更应特别复核。不要把审批等同于系统隔离，也不要把资源 rlimits 写成 cgroup 聚合配额。

仓库当前没有 LICENSE；此文不新增或选择任何许可证。

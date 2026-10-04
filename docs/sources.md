# 官方依据

查阅日期：2026-10-02。以下资料用于确认“现代 coding agent 的主要机制”，不代表本项目复刻产品内部代码，也不用于主张本项目具有 SOTA 得分。具体版本拆分、精确字符串 patch、demo reviewer 与路由策略是本项目的教学设计。

1. **OpenAI — Unrolling the Codex agent loop**
   https://openai.com/index/unrolling-the-codex-agent-loop/
   依据：模型与工具循环、工具 schema、仓库环境说明、计划、缓存与压缩；不同工具有独立安全边界。

2. **Claude Code — How Claude Code works**
   https://code.claude.com/docs/en/how-claude-code-works
   依据：收集上下文、行动和验证，文件/搜索/终端工具，项目说明、技能按需加载、会话恢复和上下文压缩。

3. **Anthropic — Beyond permission prompts**
   https://www.anthropic.com/engineering/claude-code-sandboxing
   依据：应用层批准不同于系统级隔离；文件系统、网络、子进程都需要限制。文中历史默认设置不作为今天产品默认设置的保证。

4. **Claude Code — Checkpointing**
   https://code.claude.com/docs/en/checkpointing
   依据：检查点与回退需要明确覆盖范围；不能假定所有命令写入或外部 API 副作用都可回滚。

5. **Claude Code — Create custom subagents**
   https://code.claude.com/docs/en/sub-agents
   依据：独立上下文、工具权限、结果回传、代码工作区隔离。额外角色仍消耗 tokens；worktree 不等于安全沙箱。

6. **OpenAI Agents SDK — Running agents**
   https://openai.github.io/openai-agents-python/running_agents/
   依据：模型/工具循环、turn 限制、停止恢复、错误处理和 tracing。

7. **Anthropic — Demystifying evals for AI agents**
   https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents
   依据：轨迹和环境最终结果不同；能力/回归评测、多次 trials、确定性 grader 和资源成本需要分别观察。

8. **OpenAI — Function calling**
   https://developers.openai.com/api/docs/guides/function-calling
   依据：Responses API function 工具定义、参数 schema、调用结果结构；用于可选适配器边界。

## 使用 SOTA 一词的边界

现代 coding agent 的效果依赖模型、执行器、工具、环境、提示、可用预算和评测设置。此项目的 mock 只能验证协议和编排行为。没有跑 SWE-bench、没有固定真实模型的大规模测试、没有排名比较，因此不能声称达到任何榜单 SOTA。更多组件不保证结果单调提高。

## V11 补充来源（2026-10-03）

- [Bubblewrap 官方项目](https://github.com/containers/bubblewrap)：namespace 与 mount profile 的边界
- [Bubblewrap v0.12.0 参数定义](https://github.com/containers/bubblewrap/blob/v0.12.0/bwrap.xml)：mandatory namespace、json-status-fd、die-with-parent
- [Python resource](https://docs.python.org/3/library/resource.html)：rlimit 接口
- [Linux getrlimit](https://man7.org/linux/man-pages/man2/getrlimit.2.html)：CPU/AS/NPROC 等限制的准确作用范围

这些来源支持设计取舍，不是本环境成功运行隔离的证据。实际状态以 `artifacts/sandbox-report.json` 和 `tests-v11.txt` 为准。

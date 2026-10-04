# 最小架构与组件职责

## 先看真正的内核

```text
用户目标
   |
   v
State 当前可见事实 ---> Model 决定下一步
   ^                       |
   |                       v
   +---- Observation <-- Decision
                           |
                  +--------+--------+
                  |                 |
                final            tool call
                  |                 |
           检查完成证据          Policy 审批/限制
                  |                 |
             结束或拒绝       Tool Registry 分发
                                    |
                           Workspace 文件/测试
```

模型不能直接“想一下就改磁盘”。模型输出结构化意图；执行器验证；host 决定权限；工具才产生副作用；结果作为新观察送回模型。这个循环是 Codex 官方工程说明与 Agents SDK 都公开描述的基本机制。[Codex agent loop](https://openai.com/index/unrolling-the-codex-agent-loop/)、[Agents SDK running agents](https://openai.github.io/openai-agents-python/running_agents/)

下面是概念代码；可运行实现见 `simple_agent/runtime.py`：

```python
while budget_available():
    decision = model.next(state.context(), allowed_tools)
    if decision.final is not None:
        return finish_only_with_current_evidence(decision)
    check_schema_and_permissions(decision)
    observation = execute(decision)
    state.observe(observation)
```

## V10 的完整教学架构

```text
                       用户 / CLI Host
                  目标、恢复、精确批准、停止
                              |
                              v
    +--------------------------------------------------+
    | Engine 控制循环                                   |
    |                                                  |
    | State + Plan <-> Context <-> Router -> Model      |
    |      |          repo/skill      fast/careful      |
    |      |                                           |
    |      +-> Checkpoint + 文件指纹                   |
    |                                                  |
    | Decision -> Validation -> Policy -> Registry     |
    |                                      |           |
    |       +----------+---------+---------+           |
    |       v          v         v                     |
    |   search/read   patch   run_tests                 |
    |       |          |         |                     |
    |       +----------+---------+                     |
    |                 Workspace 样例副本               |
    |                                                  |
    | delegate_review -> Reviewer 独立 State            |
    |                     仅 read/search，无写权限       |
    |                     返回结构化结论                |
    +--------------------------------------------------+
             |                          |
         Trace JSONL               Shared Budget
      事实/工具/停止原因       主/子角色共用调用配额
             |
             v
       外部 outcome grader
       独立检查结果，不信最终文字

V11 在 run_tests 下新增：
  [BubblewrapExecutor -> 只读快照 / 独立 namespace / 资源限制]
  [probe 或 setup 失败 -> blocked_sandbox，禁止 host 降级]
完整 sandbox 集成验收受本次云宿主限制；cgroups/seccomp/VM 等仍待补充
```

## 必要组件

| 组件 | 文件 | 最小职责 |
| --- | --- | --- |
| Model | `models.py` | 根据已见上下文决定工具调用或结束；默认是可重复的手写 demo policy |
| Decision | `protocol.py` | 统一动作结构；工具名、参数、最终回答互斥 |
| State | `protocol.py` | 当前文件快照、测试事实、计划、角色反馈；不保存私有思维过程 |
| Engine | `runtime.py` | 控制循环、解释动作、错误反馈、完成检查 |
| Registry | `Engine.tools` | 只暴露本版本拥有的工具 |
| Workspace | `workspace.py` | 路径约束、精确补丁、固定测试命令、指纹 |
| Policy | `policy.py` | host 授权、一次性精确审批、只读 reviewer |
| Context | `repo_context/load_skill/compact` | 限量检索、来源标注、按需规则、旧历史压缩 |
| Plan | `set_plan` | 显式任务步骤；验收仍依赖真实测试 |
| Checkpoint | `save_checkpoint/restore` | JSON 状态、预算、工作区一致性检查 |
| Reviewer | `review` | 独立上下文、有限工具、结果回传；不是再开一个写入者 |
| Budget / Router | `Budget/RoutedModel` | 达到上限则停；失败后切换另一种 demo policy |
| Trace / Eval | `emit/evaluate.py` | 记录发生了什么；独立检查最终环境结果 |
| Executor | `execution.py` / `_sandbox_launcher.py` | V11 必需 Bubblewrap；旧版可信 host；快照、启动探测、限额和失败关闭 |
| Provider adapter | `openai_adapter.py` | 可替换模型接口，不改变权限决定权 |

## 工具扩展点

`register(name, callable)` 是唯一需要先理解的扩展口。可加入 Git diff、语法分析、LSP 诊断或经过授权的外部 MCP 工具。扩展工具不自动继承 shell 的沙箱保护；网络请求、远端文件和第三方服务需要各自的权限与数据传输控制。Codex 官方说明也特别指出不同工具的边界不能混为一谈。[官方 agent loop 说明](https://openai.com/index/unrolling-the-codex-agent-loop/)

本项目不实现 MCP 传输协议、IDE/LSP、远程浏览器或 Git 托管集成，因为它们是接在同一工具边界上的产品选择。工具注册与安全接口已留出；没有把这些未实现功能列入测试通过的能力。

## 为什么先不加更多框架

同一个模型配上更复杂的计划、多角色或记忆，不一定更好。先让一个循环可运行、可验收、可停止，再用固定任务和预算比较改动。V09 的 reviewer 是对“独立上下文 + 最少工具 + 清晰返回值”的演示，并非多 Agent 必然胜过单 Agent。[子 Agent 官方文档](https://code.claude.com/docs/en/sub-agents)

## V11 执行边界

详见 [第 11 课](11_sandbox.md)。模型、审批、host 文件工具仍在沙箱外；仅仓库 Python 测试运行于隔离后端。调用前后文件指纹、快照 hash、backend 身份共同约束验收证据。Checkpoint 不跨后端恢复。系统隔离失败是运行环境阻塞，不交给模型通过改代码“修复”，也不触发 host 回退。

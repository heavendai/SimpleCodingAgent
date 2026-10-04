> V11 已追加 sandbox 执行接口，但当前云宿主阻塞了真实隔离集成测试。先完成 [V11 活体验收](11_sandbox.md) 与生产威胁评估，再接真实模型；API 网络与源码传输需要单独授权。

# 可选真实模型接入

默认十一版演示不使用任何 API。本适配器只是把 `Model.next(context, tools)` 接到 OpenAI Responses API 的 function calling，用标准库实现，且真实网络路径未运行验收。

## 在做这一步前

先建立真正的代码执行隔离环境，尤其不能让模型生成的 Python 代码以宿主机权限直接运行。确认模型 ID、账户权限、费用预算，以及同意把任务、选中源码、仓库说明和工具输出发送给 OpenAI。通过自己的安全凭据环境提供 `OPENAI_API_KEY`，不把密钥写进代码、命令历史或聊天。

下面是集成形状，不是默认执行命令：

```python
from pathlib import Path
from simple_agent.cli import build, fresh_run
from simple_agent.openai_adapter import OpenAIModel

# 仅在真正隔离的执行环境中，由你明确选择运行
run_dir = fresh_run(6)
agent = build(6, run_dir / "workspace", require_approval=True)
agent.model = OpenAIModel("你有权限使用的模型ID", allow_network=True)
state = agent.run()
print(state.status)
```

选 V06 是为了先验证一个实际模型与工具循环，再逐层加入计划与角色；不要把十层一次接满之后再找问题。真实模型不保证一次完成，也可能请求被拒绝的动作、产生无法匹配的 patch 或触发预算。

## 已实现与未验证

- 实现了 Responses `POST /v1/responses`、function schema、单工具调用、最终文本解析
- 请求 `parallel_tool_calls=False` 和 `store=False`，每次最多 1200 输出 tokens
- 读取 API 返回 usage 到 `last_usage`；没有把字符预算伪装成计费预算
- 本地测试仅 stub 网络 transport 验证参数和解析，不证明真实账户可调用或具体模型兼容
- 网络/HTTP 错误会停止，不自动重试可能已计费的请求
- 每步重新发送当前上下文，不使用服务端 session、reasoning item 的跨轮续接或缓存优化
- 若自行把 V09/V10 的 worker 换为此适配器，默认 reviewer 仍是手写规则；需要另接 reviewer model factory 才是完整的多模型系统

适配器只改变“谁做决策”，不改变“谁决定权限”。不要把 repo/skill 文本加入 host 权限白名单。

官方参考：[Function calling](https://developers.openai.com/api/docs/guides/function-calling)。模型与 API 随时间变化，真实接入前应再次核对官方文档。

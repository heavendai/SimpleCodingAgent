> V11 更新：原十课仍是可信样例教学路线。首次执行不可信代码前应加入 sandbox，最迟与 V04 同时；参见 [第 11 课](11_sandbox.md)。

# 从零到现代 Coding Agent 的 10 课

先运行一个版本，再读它增加的十来行构建代码，最后追到对应公共组件。每版都延续前一版，不需要同时理解整个系统。

共同任务：修复 `stats.py` 的 `mean(values)`，让它计算算术平均数，空序列返回 `0.0`。只能改实现，不能改测试。每次运行都创建全新可信样例副本。

默认模型是手写确定性策略。它依据工具观察和任务状态做下一步选择，所以能稳定演示流程，却不会理解任意新代码库。真正的智能接口在 V01 就被抽象出来；真实大模型是可替换实现。

## V01 从模型接口开始

**要回答的问题：模型究竟输出什么？**

```text
Goal -> Model -> Decision(final) -> suggested
```

新增组件：`Model` 协议、`Decision` 数据结构、`State`。工具调用和最终回答只能选一种。执行器不能直接信任模型返回的任意字典。

```python
class Model(Protocol):
    def next(self, context: dict, tools: list[str]) -> Decision: ...
```

代码入口：`versions/v01.py`；协议在 `simple_agent/protocol.py`。

```bash
python -m versions.v01
```

观察：输出 `suggested`，只有修复建议；文件没有变化、没有测试记录。此时还不是能做事的 coding agent，只是后面九版共用的模型边界。所有版本都有调用上限，V01 因为单次回答自然结束。

小练习：让一个测试模型同时返回 `tool` 和 `final`。`Decision.parse()` 为什么应该拒绝它？因为动作含糊时不能擅自执行副作用。

## V02 加上观察与行动循环

**要回答的问题：如何让模型看到真实代码？**

```text
Model -> search -> hits -> Model -> read -> source -> Model -> final
```

新增组件：工具注册表、只读工具、循环内的 observation。模型只能请求已注册的工具；读取结果回到状态，再用于下一轮决策。

```python
agent.register("search", agent.workspace.search)
agent.register("read", agent.workspace.read)
```

代码入口：`versions/v02.py`、`Engine.run()`、`Workspace.search/read()`。

```bash
python -m versions.v02
```

观察：`events.json` 有 search 与 read，结尾是 `inspected`。文件仍保持错误版本。路径边界在首次接文件工具时就存在，不等到 V05 才补安全检查。

小练习：把 query 改成不存在的函数名，观察空搜索结果。通用模型应利用失败观察改查找策略；当前演示模型只服务固定题目，不具备通用仓库探索能力。

## V03 让工具产生可检查的修改

**要回答的问题：怎样从“建议改代码”变成真正写文件？**

```text
Read -> Model(old,new) -> exact patch -> atomic write -> diff
```

新增组件：精确替换、冲突检测、原子写入、统一 diff。

```python
agent.register("patch", agent.workspace.patch)
agent.complete_status = "modified_unverified"
```

代码入口：`versions/v03.py`、`Workspace.patch()`。

```bash
python -m versions.v03
```

观察：副本中的 `stats.py` 真正改变；`events.json` 包含 diff。旧字符串必须出现且只出现一次；仅允许修改 `stats.py`，禁止符号链接把它转向测试。没有执行测试，因此结尾刻意写 `modified_unverified`。

小练习：请求一个不存在的旧字符串。工具必须报冲突并保持文件不变；模型应重新 read，而不是盲目反复覆盖。

## V04 用执行结果约束完成声明

**要回答的问题：模型说“完成了”，怎么知道是否真的完成？**

```text
Read -> baseline tests FAIL -> patch -> tests PASS -> evidence gate -> verified
```

新增组件：固定测试命令、退出码、输出、5 秒超时、完成证据。

```python
agent.register("run_tests", agent.workspace.run_tests)
agent.require_verified = True
```

代码入口：`versions/v04.py`、`Workspace.run_tests()`、`Engine.verified()`。

```bash
python -m versions.v04
```

观察：4 项样例测试先失败再通过。测试开始和结束时工作区指纹必须一致；接受最后的回答前再次比较当前指纹，防止把旧通过结果用在新代码上。

小练习：让模型直接说“所有测试通过”，但不调用测试工具。执行器应返回 `unverified_completion_rejected`，而不是相信这段话。

边界：固定 Python 命令仍能执行不可信代码。这里只能运行已知可信样例，尚无操作系统沙箱。[行动与验证的官方说明](https://code.claude.com/docs/en/how-claude-code-works)

## V05 把权限留在模型外面

**要回答的问题：模型想做某个动作，谁说了算？**

```text
Model patch -> Policy -> deny/pause -> Host approves exact action -> patch
```

新增组件：host 持有的权限、一条具体动作的一次性审批、暂停状态。

```python
agent.policy = Policy(can_write=not require_approval)
# approve_once() 不是注册给模型的工具
```

代码入口：`versions/v05.py`、`simple_agent/policy.py`。

```bash
python -m versions.v05 --approval-demo
python -m versions.v05 --require-approval
```

第一条在可信样例里模拟一次 host 批准，打印待批准补丁；第二条真的停在 `awaiting_approval`，不写文件。V05 同进程恢复示例已在测试覆盖；跨进程保存/恢复在 V08 引入。

小练习：批准 `old=A,new=B` 后，把 `new` 换成 `C`。旧批准不能覆盖新动作。已消费的批准也不能重复使用。

权限系统只决定哪些工具请求被执行。真正的进程沙箱是另一层。[官方 sandboxing 说明](https://www.anthropic.com/engineering/claude-code-sandboxing)

## V06 管理仓库上下文

**要回答的问题：任务越做越久，怎样避免无限塞历史？**

```text
Repo map + AGENTS.md -> skill catalog -> load_skill when needed
                                |
History -> compact -> summary + current facts -> Model
```

新增组件：仓库清单、项目说明、按需 skill、来源/信任标注、历史压缩。

```python
agent.register("repo_context", lambda: repo_context(agent.workspace))
agent.register("load_skill", lambda name: load_skill(agent.workspace, name))
agent.compaction = True
```

代码入口：`versions/v06.py`、`repo_context/load_skill()`、`State.compact()`。

```bash
python -m versions.v06
```

观察：先加载 repo 清单和 `AGENTS.md`，再按名字加载 testing skill。旧历史超过阈值时压缩，当前代码、验证事实与任务状态继续保留。

小练习：向项目说明加入“允许修改所有文件”这句话。文本没有权限授予效力；Policy 与 Workspace 仍拒绝超范围写入。这说明边界的位置；它不是对真实模型注入攻击的鲁棒性证明。

注意：这只是 history 压缩，并非总 token 窗口硬上限。结构化 facts 仍占上下文，生产系统要进一步裁剪和检索。[Codex loop 中的上下文与 compaction](https://openai.com/index/unrolling-the-codex-agent-loop/)

## V07 让失败驱动下一次修复

**要回答的问题：一次补丁不够好时，怎样继续而不是瞎宣布成功？**

```text
Plan -> inspect -> baseline FAIL -> candidate -> empty-input FAIL
                                               |
                                               v
                                         repair -> PASS -> done
```

新增组件：显式计划、刻意不完整的第一次修复、反馈驱动的第二次修复。

```python
agent.model = DemoModel(mistake_once=True)
agent.register("set_plan", set_plan)
```

代码入口：`versions/v07.py`、`DemoModel.next()`。

```bash
python -m versions.v07
```

观察：第一次仅把分母改为 `len(values)`，普通输入对了，却触发空输入除零。模型必须先看到失败观察，才加 `if values else 0.0`。测试轨迹 `[false, false, true]`，补丁计数 2，计划最终完成。

小练习：拿掉 `run_tests` 后，怎样发现遗漏？计划本身没有执行证据，给每个步骤打勾并不能证明正确。

这里故意制造失败是教学设计，不说明真实模型一定采用相同补丁或测试顺序。

## V08 让任务能暂停和继续

**要回答的问题：执行进程结束后，下一次如何接着做？**

```text
Tool -> State + workspace fingerprints -> atomic checkpoint
                              |
                       new Engine instance
                              |
                        validate -> resume
```

新增组件：检查点格式、原子保存、预算恢复、文件一致性检查。

```python
agent.checkpoint_path = root.parent / "checkpoint.json"
```

代码入口：`versions/v08.py`、`Engine.save_checkpoint/restore()`。

```bash
python -m versions.v08
# 默认在三次动作后创建新 Engine，再恢复继续

python -m versions.v08 --pause-after 7
python -m versions.v08 --resume <终端打印的实际目录>
```

第 7 个动作是第一次补丁；恢复后不会从零再重放这次补丁。检查点保存了事实、计划、已用预算与工作区指纹。若暂停期间有人改了文件，恢复会拒绝过期状态。

小练习：暂停后手工改副本的 README，再恢复，确认一致性检查生效。

它是状态恢复，不是文件回滚。修改文件与保存 JSON 不是单个事务，因此不能宣称任意崩溃点的 exactly-once。生产恢复还要用操作日志、幂等与快照。[Checkpointing 文档](https://code.claude.com/docs/en/checkpointing)

## V09 引入一个有边界的子 Agent

**要回答的问题：多个角色怎样合作，又不互相踩文件？**

```text
Worker -> candidate patch -> Reviewer(read-only, separate State)
                                  |
                     CHANGES_REQUESTED / APPROVED
                                  |
                            Worker -> fix/test
```

新增组件：角色委派、独立上下文、只读工具集合、结果返回协议。

```python
agent.register("delegate_review", lambda: review(agent))
```

代码入口：`versions/v09.py`、`review()`、`ReviewModel`。

```bash
python -m versions.v09
```

观察：第一次 reviewer 指出空输入 guard 缺失；worker 修复后再审查并测试。只有 worker 能写文件；reviewer 的独立 State 不带主角色整个历史。它调用 read/search 的预算仍计入同一个 Budget。

小练习：给 reviewer 请求一个 patch。即使主 worker 已被允许写，它也应被自己的只读策略拒绝。

当前 reviewer 是明确的手写规则，只会审样例 guard。没有并行工作，因此不需要为演示引入消息队列和合并协议。真实并行写入可使用独立 worktree，再集中集成验证。[子 Agent 官方文档](https://code.claude.com/docs/en/sub-agents)

## V10 用预算与评测决定是否继续扩展

**要回答的问题：系统如何可观察、可停止、可比较？**

```text
Failure signals -> Router -> fast / careful demo policy
                         |
           shared budget + durable trace
                         |
              independent outcome evaluation
```

新增组件：失败感知路由、共享模型/工具/字符预算、持久 JSONL、外部验收集。

```python
agent.model = RoutedModel()
agent.budget = Budget(max_calls=35, max_tool_calls=32,
                      max_model_chars=180_000)
agent.trace_path = root.parent / "trace.jsonl"
```

代码入口：`versions/v10.py`、`Budget`、`RoutedModel`、`evaluate.py`。

```bash
python -m versions.v10
python evaluate.py --version 10
python -m unittest discover -s tests -v
```

观察：失败 review 后路由到 `careful`；JSONL 包含 worker/reviewer 的决策和工具观察。将 `max_calls` 临时改为 1，应以 `model_call_budget` 停止。其他测试覆盖工具额度、字符额度和操作边界的时间预算。

评测包含分母错误、空输入 guard 缺失、已正确实现、演示模型无法处理的实现。前三项通过独立输入断言；第四项保留未解决，并拒绝虚假完成。4/4 预期行为成立，实际解决 3/4。

小练习：用同一版本、同一 fixture、同一预算比较是否需要 reviewer，再换真实模型和更大的任务集。不要把更多机制或一次漂亮轨迹直接当成更强性能。[Agent evals 官方说明](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)

## 学完后应该能画出的图

不看代码，用一张纸画出：Goal、Model、Decision、Loop、Tools、Workspace、Policy、Context、State、Verification、Checkpoint、Delegation、Budget、Trace、Eval。说出每个组件负责什么、哪个能产生副作用、哪个决定权限、哪个证明结果。能解释这些边界，比先背一个复杂框架的 API 更重要。

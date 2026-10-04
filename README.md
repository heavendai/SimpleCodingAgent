# SimpleCodingAgent

用原始 10 个递进版本，加上新增 V11 sandbox，看懂一个 coding agent 怎样从“给建议”变成“能读取、修改、验证、恢复和评测”的工程系统。

**定位：最简教学骨架，覆盖现代 coding agent 的主要工程机制。默认模型是离线确定性演示策略，不是通用大模型，不宣称达到 Codex、Claude Code 或 SWE-bench SOTA 性能。** 真正执行的部分包括文件搜索、读取、原子补丁、Python 单元测试、审批拦截、状态恢复、角色委派、预算和轨迹记录。

## 一分钟运行

需要 Python 3.10+；已在 host Python 3.12.14 验证。零第三方 Python 依赖，不需要 API key，默认不调用网络或付费服务。V11 另需 Linux + Bubblewrap + /usr/bin/python3，并要求宿主允许所需 namespace。

```bash
cd SimpleCodingAgent
python run.py --legacy-all
python -m unittest discover -s tests -v
python evaluate.py
```

可选的独立环境：

```bash
python -m venv --without-pip .venv
# Linux/macOS
.venv/bin/python run.py --legacy-all
# Windows 用 .venv\Scripts\python.exe 替换上面的解释器
```

每次运行都把项目内的已知样例复制到新的 `runs/vXX-随机值/workspace/`，不会覆盖之前的练习，也不会直接修改 `examples/buggy_repo/`。终端会打印实际输出目录。

## 11 个 milestone

| 版本 | 本次真正增加的能力 | 运行后应看到 |
| --- | --- | --- |
| V01 | Model / Decision 模型接口 | `suggested`，只给建议 |
| V02 | search / read 与观察行动循环 | `inspected`，定位问题但不改文件 |
| V03 | 精确补丁、冲突检测、原子写入、diff | `modified_unverified`，补丁写入但未验证 |
| V04 | 固定测试执行器与完成证据 | `verified`，测试先失败再通过 |
| V05 | host 控制的一次性精确写入授权 | 可见 `awaiting_approval`，授权后继续 |
| V06 | repo map、AGENTS.md、按需 skill、历史压缩 | 加载上下文，保留当前文件与事实 |
| V07 | 显式计划与失败后修复 | 测试轨迹 `[false, false, true]` |
| V08 | 原子检查点、文件指纹、暂停与恢复 | 新执行器恢复同一次任务 |
| V09 | 独立只读 reviewer、单一写入者 | 先拒绝遗漏空输入的补丁，再通过 |
| V10 | 失败路由、共享预算、JSONL 轨迹、外部评测 | reviewer 和 worker 共享配额；产出评测结果 |
| V11 | Bubblewrap 执行后端、快照、资源边界、fail-closed | 支持时 sandbox 验证；不可用时 `blocked_sandbox`，不降级 |

这些版本是**累加式的构建配方**：每个 `versions/vXX.py` 继承上一版，只增加一组机制。公共组件集中在 `simple_agent/`，避免复制十份执行器。能力与结果会真实改变，并不是仅更换提示词。

## 阅读顺序

1. [原始 10 课逐版讲解](docs/10_lessons.md)：每版新增组件、架构、代码入口、操作、观察点和练习
2. [整体架构与组件职责](docs/architecture.md)：区分模型、控制循环、工具和权限边界
3. [安全与生产差距](docs/safety_and_production.md)：哪些做了，哪些不能当成安全保证
4. [官方来源](docs/sources.md)：现代架构依据与查阅日期
5. [项目上下文](simple_codingagent.context.md)：可独立阅读的角色、目标、版本、验证证据和后续路线
6. [维护与验证](CONTRIBUTING.md)：修改前检查、安全证据和文档同步
7. [版本记录](CHANGELOG.md)：能力与验证状态的演进

## V11：什么时候加入 sandbox？

首次执行不可信代码/测试/依赖脚本之前，最迟在 V04 的执行层。V03 的路径限制和 V05 的审批不能代替 OS 隔离。V11 是追加教学实现，不代表可以把安全推迟到最后。

```bash
python sandbox_check.py          # 只探测环境，不执行仓库代码
python -m versions.v11           # 使用必需的 sandbox 后端
python run.py --all              # V01–V11；sandbox 被阻塞时非零退出
```

本次云端的 Bubblewrap 0.12.0 在建立网络 namespace 时被宿主拒绝（NETLINK_ROUTE socket: Operation not permitted）。V11 正确停在 `blocked_sandbox`，模型调用/补丁/仓库测试均为 0。8 项真实隔离集成测试未运行；没有改宿主安全设置或回落 host。完整设计和边界见 [第 11 课](docs/11_sandbox.md)。

## 三个值得亲手做的实验

```bash
# 1. 观察同一个错误如何从测试失败反馈回修改
python -m versions.v07

# 2. 在可信样例里演示一次精确审批；这里的批准由 host 代码模拟
python -m versions.v05 --approval-demo

# 3. 分两次进程运行 V08
python -m versions.v08 --pause-after 7
# 把终端的 Artifacts 路径填到下面，不能原样使用占位符
python -m versions.v08 --resume <上一步的实际运行目录>
```

需要真正停下来等你批准时：

```bash
python -m versions.v08 --require-approval
python -m versions.v08 --resume <实际运行目录> --approve-pending
```

`--approve-pending` 只批准检查点里那个具体补丁。V07 以后默认故意先做不完整修复，因此后续第二个补丁会再次等待批准；再审阅并运行同一条恢复命令即可。审批不等于给模型所有写权限。

## 结果该如何理解

V01–V03 的目标是展示一个能力阶段，不能把它们输出的“建议/已改文件”算成通过验收。V04 起，当前文件指纹必须对应一次真实通过的测试，执行器才接受 `verified`。

最新回归：73 项中 65 通过，8 项活体隔离测试因环境限制 skip，原始 40 项回归全部保留通过。原始输出见 `artifacts/tests-v11.txt`。外部 toy 评测 4/4 满足预期，其中 3/4 任务被修复，剩下 1 项刻意超出演示模型能力并正确拒绝完成声明。**4/4 是回归行为符合预期，不是四题全修好，也不是模型 benchmark。** 原始证据在 `artifacts/`。

## 真实大模型接入

可选适配器位于 `simple_agent/openai_adapter.py`，按 Responses API 的 function calling 边界编写，只做了模拟传输单测，没有真实联网验收。默认 CLI 不会启用它。

阅读 [真实模型接入](docs/real_model.md) 后再决定是否开启。模型推理需要传输任务、选中源码和工具结果，也可能产生 API 费用；不要在聊天、源码或日志中填入密钥。

## 重要限制

V01–V10 的路径校验、固定命令与审批不是 OS 沙箱，只用于本项目可信样例。V11 实现 Linux Bubblewrap profile，但本次宿主阻塞了真实隔离集成验收。其 rlimits 不是 cgroup 聚合配额，也未提供自定义 seccomp 或 VM 隔离。不要据此宣称可安全执行任意敌对代码；详见 [安全与生产差距](docs/safety_and_production.md)。

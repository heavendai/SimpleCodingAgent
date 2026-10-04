# SimpleCodingAgent 项目上下文

更新日期：2026-10-04（UTC，发布准备）；验证记录日期仍为 2026-10-03。项目版本：1.1.0，新增 V11 sandbox。

## 角色与目标

名称：**SimpleCodingAgent**。角色：coding agent 最简骨架设计师。

用 Python 和简单架构图展示 coding agent 的逐步建设。初始路线包含十个递进版本；V11 继续加入 sandbox 支持。优先保持组件名称、职责、代码和验证结论清楚可读，保留原十版教学与回归。

这是教学骨架，覆盖模型接口、工具循环、编辑、验证、审批、上下文/skills、计划修复、恢复、角色协作、预算评测，以及新增的 OS 执行边界。**不宣称达到 Codex、Claude Code 或任何 benchmark 的 SOTA 性能。** 默认模型是固定练习的确定性 demo policy，不具备通用代码推理能力；没有真实 API 调用或费用。

## 什么时候需要 sandbox

首次执行不可信仓库代码、测试、模型生成代码或依赖安装脚本之前。按本教程的阶段：V03 应有写入范围限制，最迟 V04 加入执行工具时就要同时加入 sandbox；V05 审批不能代替 OS 隔离。V11 是追加教学实现，不是建议到第十一阶段才补安全。

V01–V10 保留可信 toy 样例的 host runner，便于独立理解旧机制；移植到真实业务时不能照搬这种执行方式。V11 强制选择 Bubblewrap，不允许因能力不可用自动退回 host。

## 环境与交付

- 验证环境：受限 Linux 环境
- 项目路径：本文中的 `<project-root>` 代表 clone/解压后的项目根目录
- Host Python：3.12.14，项目最低 Python 3.10+
- Python 第三方依赖：0；项目 `.venv` 用 `--without-pip` 创建
- V11 系统依赖：Linux、Bubblewrap、`/usr/bin/python3`、宿主允许所需 unprivileged namespaces
- 当前检出 Bubblewrap 0.12.0；sandbox 内指定系统 Python，可能不同于 host venv，只有 probe 成功后才报告其版本
- 本仓库包含完整源码与本文；此前独立交付的 ZIP/context 副本不纳入 Git
- 未改宿主安全设置、提权运行、安装系统软件或调用真实模型

仓库排除 `.venv`、临时 `runs` 和缓存；源码、教学文档、样例、回归测试和验证 artifacts 全部包含。

## 当前最重要的验证结论

**V11 已实现 Bubblewrap 后端与 fail-closed，但本次环境没有通过真实隔离集成验收。**

完整 profile 在启动网络 namespace 时被宿主拒绝：

```text
bwrap: loopback: Failed to create NETLINK_ROUTE socket: Operation not permitted
```

V11 实际结果是 `blocked_sandbox`：模型调用 0、补丁 0、仓库测试 0，CLI 返回 1。没有把普通 subprocess 冒充 sandbox，没有回落 host，也没有尝试绕开限制。

2026-10-03 最终回归：

- 73 项测试被发现：**65 通过，8 项 live sandbox integration 因上述环境限制跳过**
- 8 项未运行的活体验证涉及 namespace/runtime、只读挂载、host canary、host loopback 网络、环境/fd、hard rlimits、派生 setsid 后代清理和 V11 完整演示
- 原 V01–V10：10/10 达到各自里程碑
- `run.py --all`：V01–V10 正常、V11 `blocked_sandbox`，整体 exit 1，符合拒绝降级要求
- `compileall` 通过
- 旧版外部 toy evaluator 仍为行为符合预期 4/4、实际解决 3/4；它使用 V10 可信 host 样例，不冒充 V11 sandbox 评测
- 可信 helper 的实际独立单测确认继承的 hard limits 有限且生效；这不等于 namespace/网络/后代清理活体验收
- 真实模型适配器仍只做 stub transport 测试，没有联网 API 验收

证据文件：

- `artifacts/tests-v11.txt`：73 项测试逐项结果与 skip 原因
- `artifacts/sandbox-report.json`：完整 profile probe，含 host Python、bwrap 版本和真实阻塞原因
- `artifacts/v11-run.txt`：V11 blocked 结果
- `artifacts/all-results-v11.json`、`all-versions-v11.txt`：全部十一版实际结果
- `artifacts/legacy-versions-v11.txt`：原十版回归
- `artifacts/eval-report-v11-legacy.json`：原 V10 独立 toy 评测
- 原始 V1.0.0 验证 artifacts 仍保留，不代表 V11 活体通过

## 架构

```text
Goal -> Context/State/Plan -> Router -> Model -> Decision
             ^                                  |
             |                    +-------------+------------+
             |                    |                          |
             |                  tool                        final
             |                    |                          |
             |              Policy / Registry          Evidence gate
             |                    |                          |
             +--- Observation <---+                 verified / rejected
                                  |
                   read/search/patch/test/reviewer
                                  |
                     Workspace + current fingerprint
                                  |
                         Host-selected Executor
                         /                    \
             V01-V10 TrustedHost          V11 Bubblewrap
             仅可信样例                   probe -> safe snapshot
                                         -> readonly/runtime/namespaces
                                         -> limits/status/hash evidence
                                         -> blocked_sandbox on setup failure

横向：Checkpoint、Shared Budget、Trace、外部 toy Eval
```

## 十一个 milestone

| 版本 | 新增机制 | 核心组件 | 预期状态 |
| --- | --- | --- | --- |
| V01 | 模型接口 | Model / Decision / State | suggested |
| V02 | 只读工具循环 | Engine / Registry / search / read | inspected |
| V03 | 可靠编辑 | exact patch / atomic write / diff | modified_unverified |
| V04 | 执行与完成证据 | run_tests / fingerprint / evidence gate | verified |
| V05 | host 一次性精确审批 | Policy / approve_once / pending | 可等批准 |
| V06 | 上下文 | repo map / AGENTS.md / lazy skill / compact | 上下文驱动 |
| V07 | 计划与修复 | set_plan / failed-test feedback | 两次补丁后通过 |
| V08 | 检查点恢复 | atomic checkpoint / integrity check | 暂停后继续 |
| V09 | 角色边界 | separate State / read-only reviewer | reviewer 先拒后通过 |
| V10 | 配额、路由、追踪、评测 | router / budget / JSONL / grader | 额度可停、结果可验 |
| V11 | 系统执行边界与拒绝降级 | Executor / Bubblewrap / snapshot / limits | 支持时 verified；本环境 blocked_sandbox |

每版继承上一版的构建配方，只增加差异；通用组件在 `simple_agent/`。V01–V03 的阶段成果不能当作通过验收。

## V11 的具体边界

### 授权、快照和文件

- 后端由 host recipe 配置，模型不能切 backend、开网、加 mount 或修改 limits
- 执行输入固定为 `stats.py` 与 `tests/test_stats.py`，不挂整个仓库
- Linux descriptor 相对打开 + `O_NOFOLLOW` 拒绝每层符号链接；只接受普通文件，每文件 <=64 KiB，按读取上限再检查
- 一次性快照只读挂载到 `/workspace`；保存所执行 bytes 的 hash，并与执行前/后工作区指纹比较
- 系统 `/usr/bin`、`/usr/lib`、可用的 `/usr/lib64` 和兼容路径只读；部署者必须信任这些系统目录
- 独立 `/proc` 和 root 只读；最小 `/dev/null`、`/dev/urandom`，没有整个 host `/dev`、TTY、`/dev/shm`
- 仅 `/tmp` 是普通可写目录，16 MiB tmpfs；不暴露 host home、凭据、socket、原仓库路径、checkpoint
- host read/search/patch 仍是教学文件边界，按单写入者假设工作；执行沙箱不自动保护其他工具

### 进程、网络、资源

- 必须成功创建 user/PID/network/IPC/UTS namespace；禁止 `--*-try` 与共享 host network
- drop capabilities、new session、die-with-parent、禁止额外 user namespace；只读 `/proc`
- 无 host/外部网络，sandbox 内部 loopback 仍可用；没有联网依赖安装功能
- helper 用 host Python `-I -S` 先设置 inherited hard rlimits，再 exec Bubblewrap
- sandbox 用 `/usr/bin/python3 -I -S -B`；先 import 标准库再加入工作区
- 环境清空后只有固定 PATH/HOME/TMPDIR/LC_ALL，stdin DEVNULL，无无关 inherited fd
- 默认：5 秒 wall、3 秒每进程 CPU、256 MiB 每进程虚拟地址空间、1 MiB 单文件、64 fd、64 real-UID processes/threads、64 KiB 流式总输出、core=0
- 现有更低 hard limit 不提高；超时/输出超限杀 launcher 进程组，并依赖 Bubblewrap/PID init 传播终止
- JSON status fd 与 payload stdout 分离，setup 状态不可由任意打印文本冒充

### 状态与验收

- 全 profile preflight 在模型调用之前运行；失败 `blocked_sandbox`，写入 checkpoint/trace/result 并非零退出
- 测试中出现 sandbox setup/status 失败也直接阻塞，不交给模型改代码绕过
- 通过证据要求当前输入指纹、补丁序号、backend=`bubblewrap`、isolated=True
- checkpoint backend 不同一律拒绝，包括 sandbox→host 降级；旧缺 backend 的 checkpoint 仅视为旧 host 数据
- 保留完成状态的 checkpoint 也不能跳过 V11 的证据检查

## 快速运行

```bash
cd simple_codingagent
python run.py --legacy-all
python sandbox_check.py
python -m versions.v11
python run.py --all
python -m unittest discover -s tests -v
python evaluate.py
```

如已创建虚拟环境，也可用 `.venv/bin/python`。`sandbox_check.py` 只探测，不执行仓库代码。`--all` 包含 V11，因此本环境返回 1 是明确报告阻塞；`--legacy-all` 只跑旧可信教学样例。

每次演示复制已知样例到新 `runs/vXX-随机值/workspace`，保留原样例；打印实际目录。该目录含 result/events；V08+ 含 checkpoint，V10+ 含 trace。

旧机制重点实验：

```bash
python -m versions.v07
python -m versions.v05 --approval-demo
python -m versions.v08 --pause-after 7
python -m versions.v08 --resume <实际目录>
python -m versions.v08 --require-approval
python -m versions.v08 --resume <实际目录> --approve-pending
```

`--approval-demo` 是 host 模拟一次精确批准，仅可信练习；`--approve-pending` 仅批准当前 checkpoint 的具体补丁，不同补丁需要新批准。V11 也保留审批机制，但 sandbox 不可用时会更早停止。

## 文件导航

```text
README.md                         快速开始、十一版路线、真实阻塞说明
simple_codingagent.context.md      本文
run.py                            统一 CLI
sandbox_check.py                  V11 只读能力探测
versions/v01.py ... v11.py         累加配方
simple_agent/protocol.py           Decision / State / 证据
simple_agent/runtime.py            循环、预算、验证、恢复、委派
simple_agent/workspace.py          文件/补丁/指纹/执行依赖
simple_agent/execution.py          TrustedHost / Bubblewrap / 快照 / collector
simple_agent/_sandbox_launcher.py  可信 hard rlimits helper
simple_agent/policy.py             host 精确授权
simple_agent/models.py             离线 worker/router/reviewer
simple_agent/openai_adapter.py     可选、未联网验收的真实模型接口
simple_agent/cli.py                演示、暂停恢复、状态与退出码
evaluate.py                       旧 V10 独立 toy outcome grader
examples/buggy_repo/               固定练习样例
tests/test_project.py             原 40 项回归（版本数与 mock 位置随新增更新）
tests/test_sandbox.py             V11 单测、collector 和活体集成
docs/10_lessons.md                原十课
docs/11_sandbox.md                加入时机、威胁模型、实现、操作、验收
docs/architecture.md / .mmd       组件职责与可编辑架构图
docs/safety_and_production.md     各版本安全界限与生产缺口
docs/real_model.md                真实模型接入约束
docs/sources.md                   官方参考
artifacts/                        验证证据
```

## 不能夸大的限制

1. V11 未在本次宿主完成活体 namespace/network/mount/descendant 验收。65 passed + 8 skipped 不能表述为 sandbox 全通过
2. rlimits 是每进程或 real UID 计数，不是 cgroup 聚合 CPU/内存/pids 配额；fork 总资源仍可放大。无自定义 seccomp、VM 隔离、内核漏洞防护或多租户安全承诺
3. 固定 manifest 只支持此两文件 unittest 样例；没有通用 shell/build/deps/git 操作，不能直接给任意项目使用
4. 系统运行时和 host 编排代码受信；允许输入文件里的秘密仍会被程序读到。没有生产级日志脱敏
5. 通过测试不证明敌对代码诚实执行测试，`os._exit(0)`/进程内篡改等不能仅凭 returncode 防范；隔离和独立不可作弊验收是不同问题
6. 默认模型仍是固定策略；真实模型接入、源码传输、费用预算均未启用
7. 上下文压缩不保证总 token cap；字符预算不是 token 或美元预算；全局 wall budget 在动作边界检查
8. checkpoint 不回滚文件、不撤销外部副作用、不保证 exactly-once；host 文件工具不承诺并发敌对修改安全
9. reviewer 是独立上下文的只读规则策略，不是通用代码审查；没有并行写入/合并
10. MCP、IDE/LSP、PR、VM/cgroup 平台等仍是后续扩展，不列入本次实现能力

## 官方依据与后续

已查阅：

- [Bubblewrap 官方项目](https://github.com/containers/bubblewrap)
- [Bubblewrap v0.12.0 参数](https://github.com/containers/bubblewrap/blob/v0.12.0/bwrap.xml)
- [Python resource](https://docs.python.org/3/library/resource.html)
- [Linux getrlimit](https://man7.org/linux/man-pages/man2/getrlimit.2.html)
- [Anthropic sandboxing](https://www.anthropic.com/engineering/claude-code-sandboxing)
- 原十版 agent loop、function calling、checkpoint、subagent、eval 来源仍保留在 `docs/sources.md`

下一步应在获准且支持完整 profile 的专用 Linux 环境运行 live tests，保留实际证据；不通过关闭宿主安全机制来追求演示成功。然后按风险补 cgroups/seccomp/VM、可信镜像和秘密管理，再考虑真实模型与更广泛独立验收集。这些是后续路线，不代表已经实现或部署。

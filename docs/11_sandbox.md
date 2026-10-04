# 第 11 课：真正的执行边界与 fail-closed

## 什么时候必须加入 sandbox？

**首次执行不可信仓库代码、测试、生成代码或依赖安装脚本之前。** 对原教程而言，V03 开始写文件时已有路径/写入范围限制；最迟 V04 加入执行工具时，就必须把运行放进 sandbox。V05 的审批回答“允许做什么”，sandbox 限制“代码实际能碰到什么”。不能等到 V10 或接入付费模型才考虑。

原 V01–V10 为隔离讲解机制而保留可信 toy 样例的 host runner。V11 是新增的执行后端，不代表安全可以最后补。拿走 V04 应用于业务项目时，也要同时拿走 V11 的边界，并完成真实环境验收。

## 一个新增接口，两种明确后端

```text
V01–V10：Workspace.run_tests -> TrustedHostExecutor -> 可信样例
V11：
Host preflight -> Model / Engine -> Policy -> Workspace.run_tests
                                              |
                                     BubblewrapExecutor
                                      /              \
                          安全快照 + 资源限制       setup 不可用
                                  |                    |
                         Bubblewrap 隔离子进程     blocked_sandbox
                                  |               不调用 host
                      结果 + backend + 输入指纹
                                  |
                          当前文件/证据校验
```

1. `Executor.run_tests(root)` 使执行隔离与模型选择解耦
2. `BubblewrapExecutor.preflight()` 在任何模型调用和补丁之前探测完整 profile；失败立即停止
3. `Workspace` 负责执行前后文件指纹、快照 hash 与实际源文件的一致性
4. `Engine` 要求 passing evidence 来自 `bubblewrap` 且 `isolated=True`；checkpoint 拒绝跨后端恢复，包括向 host 降级
5. 模型没有参数能关闭沙箱、增加挂载、开启网络或改变限制

代码入口：`simple_agent/execution.py`、`_sandbox_launcher.py`、`versions/v11.py`。V11 recipe 只替换执行依赖，V01–V10 的计划、权限、恢复与追踪继续复用。

## 文件边界：先减小输入，再限制挂载

本课的固定 manifest 只有 `stats.py` 和 `tests/test_stats.py`，不是整个工作目录。每个组件都用 Linux `dir_fd` + `O_NOFOLLOW` 打开，拒绝符号链接/特殊文件；每文件最多 64 KiB，读取时也用上限加 1 检查。复制出的输入 hash 必须匹配执行前指纹。

隔离进程可见：

- 只读 `/workspace`：一次性的两文件快照
- 只读系统运行时目录 `/usr/bin`、`/usr/lib`、存在时的 `/usr/lib64` 及对应 `/bin`、`/lib`、`/lib64`
- 独立、只读 `/proc`；根文件系统只读
- 最小设备 `/dev/null` 与 `/dev/urandom`，没有整个 host `/dev`、TTY 或 `/dev/shm`
- 唯一普通可写目录 `/tmp`：16 MiB 临时 tmpfs，结束后销毁

不挂载 home、`.env`、`.git`、原仓库路径、agent 源码、checkpoint、Docker socket 或用户凭据。系统运行时目录属于信任基；部署者仍需保证其中没有应用秘密或恶意工具。放在两个允许输入文件里的秘密仍会被程序读取，sandbox 不是内容脱敏器。

补丁仍由 host 的受限工具执行，测试只能读快照。没有把整个执行器或外部 MCP 工具都罩进此 sandbox。Host 的 read/search/patch 仍按单写入者教学假设工作，不能声称具有通用抗并发竞态保证。

## 进程、网络与启动

Bubblewrap 必须成功创建 user、PID、network、IPC 和 UTS namespace。使用 `--disable-userns` 禁止代码再建 user namespace、`--cap-drop ALL`、`--new-session`、`--die-with-parent`。不使用 `--*-try`、`--share-net`、特权运行或“不是安全边界”选项。

网络默认关闭对 host 和外部网络的访问；独立 namespace 内部的 loopback 仍可使用。这里没有域名 allowlist/proxy，也没有给依赖安装或真实模型 API 开网络。

Host 先用绝对路径启动可信 helper（Python `-I -S`），设置 hard rlimits，然后 `exec` Bubblewrap。隔离内明确使用 `/usr/bin/python3 -I -S -B`；它可能与 host/venv 的 Python 版本不同。固定 bootstrap 先加载标准库，再加入 `/workspace`，避免 repository `sitecustomize` 或同名启动模块在边界设置前被导入。

环境清空后只放回固定 PATH/HOME/TMPDIR/LC_ALL。stdin 来自 DEVNULL，不继承无关文件描述符。Bubblewrap 的 JSON status fd 独立于代码 stdout，未建立/未完成隔离的状态不能被一行伪造输出冒充。Probe 还检查 PID/network namespace 不同、有效 capabilities 为零、NoNewPrivs 为 1、Python >=3.10。

## 资源和终止的准确含义

| 项目 | 默认值 | 范围 |
| --- | --- | --- |
| 墙钟截止 | 5 秒 | host 监督一次 sandbox 启动/执行 |
| CPU | 3 秒 | `RLIMIT_CPU`，每进程继承 |
| 虚拟地址空间 | 256 MiB | `RLIMIT_AS`，每进程；不是 RSS/cgroup 总内存 |
| 单文件 | 1 MiB | `RLIMIT_FSIZE`；不是总文件系统配额 |
| fd | 64 | `RLIMIT_NOFILE` |
| 进程/线程 | 64 | `RLIMIT_NPROC` 按 real UID 计数，可能受 host 同 UID 的进程影响 |
| 输出 | 64 KiB | stdout/stderr 合流，边读边限制，超限终止 |
| `/tmp` | 16 MiB | 一次 sandbox 的 tmpfs mount 大小 |
| core dump | 0 | 禁止 core 文件 |

现有更低 hard limit 不会被提高。Host 监督超时/输出限额并杀掉 launcher 进程组；Bubblewrap 的父进程死亡传播和独立 PID init 用于清理 sandbox 后代。活体验证包含派生 `setsid` 子进程的超时场景，但本次云环境无法运行该测试。

**这不是 cgroup 级聚合 CPU/内存/pids 配额，也不是强多租户隔离。** 多进程总资源仍可能放大；未添加自定义 seccomp syscall allowlist；共享宿主内核，不能防御未知内核漏洞。高风险代码应在专用受控 VM/container 服务里运行，并补 cgroups、只读镜像、审计和独立验收。不要用本教学 profile 执行任意敌对样本。

## 运行与判断结果

```bash
# 原十课的可信样例回归
python run.py --legacy-all

# 只探测，不运行仓库代码
python sandbox_check.py

# 第十一课
python -m versions.v11

# 原十课 + V11；如果本机不支持沙箱，整体返回非零
python run.py --all

# 单元回归 + 活体集成；不支持时逐项明确 skip
python -m unittest discover -s tests -v
```

需要 Linux、可用的 unprivileged user namespaces、足够新的 Bubblewrap（本次检出 0.12.0）和 `/usr/bin/python3`。Python 包仍零第三方依赖，Bubblewrap 是额外系统依赖。macOS/Windows 仍可运行旧版可信样例；V11 会停止，不自动换成不安全模式。

此项目不会安装软件、改宿主 sysctl、安全设置、请求特权、禁用宿主安全机制，或为了演示成功而绕开限制。安装/环境治理应由管理者根据自己的安全要求完成。不要为了通过本课关闭系统防线。

可能结果：

- `ready`：probe 成功，只证明 profile 能启动，仍需独立跑集成测试
- `verified`：V11 本次测试通过、输入指纹一致且有匹配的 sandbox 证据
- `blocked_sandbox`：能力缺失、设置失败或 status 不可靠；没有 host fallback，CLI 非零退出
- 测试失败、wall/output limit：返回失败观察，不能被当成通过证据

## 本次验证记录（2026-10-03）

Host Python 3.12.14；检出 Bubblewrap 0.12.0。真实 probe 被当前云宿主拒绝：`bwrap: loopback: Failed to create NETLINK_ROUTE socket: Operation not permitted`。

因此本次验证了拒绝路径和本地单元回归，**没有完成真实 namespace/network/只读挂载/后代清理的集成验收，V11 没有跑成 verified**。8 项活体测试显式跳过。准确计数与原始输出在 `artifacts/tests-v11.txt`，独立 probe 在 `artifacts/sandbox-report.json`。不能把 unittest 的 `OK (skipped=8)` 写成所有隔离测试通过。

审批与隔离测试分开：批准 patch 不等于批准扩大挂载/开网。通过测试也只说明指定测试报告成功；敌对代码仍可能 `os._exit(0)` 或篡改进程内测试逻辑。安全沙箱与不可作弊的验收器是两项不同工程工作。

## 建议练习

1. 隐藏 bwrap（在单测里 mock discovery），验证未发生任何模型调用、补丁或 host runner 调用
2. 在 manifest 外放一个假 `.env`/普通文件，检查快照没有它；不要用真实秘密做测试
3. 在允许隔离的专用 Linux 环境运行 8 项活体集成并记录通过/失败，再更新验证结论
4. 对比 `Policy` 与 `Executor`：模型批准自己、工作区越界、sandbox setup 错误分别在哪一层被挡住
5. 后续若扩展成可写 build/deps 工具，显式设计输入、输出导出、网络和包安装授权，不要直接增加整个仓库的可写挂载

## 官方资料

- [Bubblewrap 官方项目](https://github.com/containers/bubblewrap)：隔离能力与 profile 决定边界的原则
- [Bubblewrap 参数定义](https://github.com/containers/bubblewrap/blob/v0.12.0/bwrap.xml)：namespace、父进程退出与 JSON status fd
- [Python resource](https://docs.python.org/3/library/resource.html)：资源限额接口
- [Linux getrlimit](https://man7.org/linux/man-pages/man2/getrlimit.2.html)：各限制的作用范围
- [Anthropic sandboxing](https://www.anthropic.com/engineering/claude-code-sandboxing)：审批与执行隔离的分工

# Nori_Live2D_Chat · 可复用资产勘察报告

**给谁看**：需要在这个项目上继续工作、或要把它的某一块搬到别的项目里的会话/人。
**解决的问题**：不必通读 13,457 行源码，就能知道"哪一块能直接拿走、拿的时候会踩什么"。

| 项 | 值 |
|---|---|
| 勘察对象 | `D:\Nori_Live2D_Chat`（活跃开发副本，非 git 工作树） |
| 快照时间 | 2026-10-20 17:0x（以 `data/`、`data/logs/` 最新写入为准） |
| 源码规模 | 120 个 `.py` / 13,457 行（其中主程序 34 文件 9,896 行） |
| 勘察方式 | 4 路并行精读（编排层 / GUI / 记忆与人格 / 服务与集成）+ 主会话交叉核对；全部**只读**，未改动目标项目 |
| 证据标准 | 结论一律给 `文件:行号`；读代码能确认的写"已核实"，不能确认的单列"未确认"，**不把推测写成结论** |
| 已交叉核对掉的问题 | 行数统计口径（`Measure-Object -Line` 漏空行）、`PetWindow` 整条链是死代码（`main.py:392`）、`live2d/index.html` 不存在、`fallback_on_error` 是死配置、`persona.control_rule` 在代码里没有实现 |

## 阅读顺序

**第一次来（5 分钟）** → [`00-brief.md`](00-brief.md)：单页速览 + 关键数字 + 三条硬约束。

**要搬代码** → [`02-reusable-assets.md`](02-reusable-assets.md) 的三级清单 + §6 三步抽取路线；需要细节再翻 `detail/`。

**要改 Live2D / 接自己的渲染器** → [`03-live2d-bridge.md`](03-live2d-bridge.md)（含 20 行最小客户端、三条技术路线对比、5 条红线）。

**要排障 / 改行为** → [`04-pitfalls.md`](04-pitfalls.md)：28 条已核实问题，按安全/并发/状态/提示词/桥接/环境分类。

**接手前建心智模型** → [`01-source-map.md`](01-source-map.md)：哪份副本是准的、每个文件多少行、值钱的东西在哪。

## 文件清单

| 文件 | 行数 | 内容 | 什么时候读 |
|---|---|---|---|
| [`00-brief.md`](00-brief.md) | ~60 | 一页纸：项目形态、五件最值得拿的资产、三条硬约束、关键数字表 | 每次新会话开头 |
| [`01-source-map.md`](01-source-map.md) | ~150 | 三份副本的判定、体量、分层地图（带 ★ 评级）、非代码资产、`data/` 结构、漂移清单 | 需要定位文件时 |
| [`02-reusable-assets.md`](02-reusable-assets.md) | ~200 | **核心**：一级/二级/三级可复用清单、8 个搬之前必须修的缺陷、依赖图、三步抽取路线、改名清单、自检清单 | 决定"搬什么"时 |
| [`03-live2d-bridge.md`](03-live2d-bridge.md) | ~170 | 原生桌宠 HTTP 契约（10 端点 + JSON 形状）、Python 客户端方法表、启动时序、标签链路、口型同步、复用配方、红线 | 碰形象/渲染时 |
| [`04-pitfalls.md`](04-pitfalls.md) | ~130 | 横切坑汇总：真实 Key、无鉴权端口、主线程阻塞、SQLite 跨进程、非原子写、prompt 无预算、记忆去重失效、死配置… | 改行为前 |
| [`detail/01-main-orchestration.md`](detail/01-main-orchestration.md) | ~450 | `main.py` 深读：启动三条路径、线程原语层、12 条可复用清单、61 个信号契约、坑 | 要抄编排骨架时 |
| [`detail/02-gui-components.md`](detail/02-gui-components.md) | ~400 | GUI 深读：10 个类的关系、16 条组件清单、信号/方法契约、DPI/透明窗/线程坑、抽取优先级 | 要抄界面组件时 |
| [`detail/03-memory-persona-heart.md`](detail/03-memory-persona-heart.md) | ~365 | 记忆五层 schema 与评分公式、人格占位符实现、压缩器、Heart 状态机、20 条可复用清单 | 做记忆/人格/自主行为时 |
| [`detail/04-services-integrations.md`](detail/04-services-integrations.md) | ~500 | 服务层：`AgentCore`/`ServiceManager` 装配、Live2D 时序与降级矩阵、LLM 封装、TTS 适配器、MCP/Skills、搜索、视觉 MCP、17 条可复用清单 | 做集成时 |

> **v0.3.0_bata（2026-10-26）新增**：自主性三件套 `agent/pet_director.py`（493 行，秒级反射层）、`agent/presence.py`（209 行，本地环境感知）、`agent/heart_events.py`（86 行，事件流）与重写后的 `heart.py`（492 行）。设计取舍、成本测算与路线图见项目内的 **`docs/autonomy-plan.md`**；实现要点见 [`detail/03`](detail/03-memory-persona-heart.md) 的 §4.7 与 [`04-pitfalls.md`](04-pitfalls.md) 的 §9。

## 怎么用这份报告（约定）

1. **行号会漂**：目标项目不是 git 仓库、且仍在被改动。引用行号前用一句话复核对，例如
   `Select-String -Path agent\memory.py -Pattern 'def add_memory'`。
2. **`detail/` 是证据，`00`~`04` 是结论**。两者冲突时以 `detail/` 的原文行号为准，并回来修这份报告。
3. **新增/修改过的资产**：改完源码后同步改 `02`（可复用清单）与 `04`（坑），否则下一个会话会被旧结论误导。
4. **标注"未确认"的地方不要当结论用**。已核实的都给了机制说明；只有推断的会明写"未确认"。

## 边界

- 本次勘察是**静态阅读 + 只读核对**，没有运行项目、没有启动桌宠、没有实测 WebEngine 透明/多屏/DPI 表现（这些在 `detail/02` 的"未确认"里列了 6 条）。
- .NET 桌宠宿主只读了 `PetControlServer.cs`、`LipSyncBehavior.cs`、`StartupOptions.cs` 等关键文件，未通读整个 Avalonia 工程。
- `data/voices/nori/` 的微调权重（277 MB）只记录存在与用途，未评估音质/授权范围。

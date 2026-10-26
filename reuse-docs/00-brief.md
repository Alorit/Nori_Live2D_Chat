# 00 · 单页速览（新会话先读这页）

**这是什么**：`D:\Nori_Live2D_Chat` 是一个可运行的 Windows AI 桌面宠物（灰发猫娘 "Nori"）。本目录是它的**可复用资产勘察报告**，供不同会话在不读全仓库的前提下，快速知道"哪一块能直接拿走用、拿的时候要注意什么"。

**技术形态一句话**：Python 3.14 + PySide6 负责编排/记忆/语音/聊天窗口；Live2D 渲染交给一个自包含的 .NET Avalonia 桌宠进程，两边只通过 `http://127.0.0.1:47835` 的裸 HTTP JSON 通信。

## 五件最值得拿走的东西
| # | 资产 | 位置 | 拿走后的收益 |
|---|---|---|---|
| 1 | **重建规格书**（含 SQLite 表结构、AgentCore 12 步流程、GUI 页签规格、验收标准） | `D:\Nori_Live2D_Chat\Nori_Recreation_Prompt.md` | 430 行，可整份喂给任何模型重造同类项目 |
| 2 | **长期记忆存储**（SQLite + BM25/jieba + 重要性衰减 + 反思整合 + 按人格隔离） | `agent\memory.py`（798 行） | 表结构 + 检索 + 遗忘策略完整，见 `detail/03-memory-persona-heart.md` |
| 3 | **原生 Live2D 桥接契约**（10 个端点 + JSON 形状 + 口型同步线程） | `agent\live2d_native.py` + `D:\Nori-Desktop-Pet-Fork\...\PetControlServer.cs` | 见 `03-live2d-bridge.md`，含 20 行最小客户端 |
| 4 | **TTS 后端工厂 + 冷启动排队 + 90s 回落**（GPT-SoVITS 克隆音色 / SAPI5 兜底） | `agent\tts\*` + `agent\services.py` | "本地大模型服务还没起来时怎么排队"的完整解法 |
| 5 | **Heart 自主唤醒进程**（定时醒来 → LLM 私人思考 → 驱动表情/说话 → 写状态文件） | `heart.py`（306 行） | 让桌宠"没人在时也活着"，见 `detail/03-*` |

补充：GUI 侧值得抄的是**聊天气泡渲染 + 深色霓虹 QSS + 无边框透明窗口 + Windows 标题栏暗色化**（`detail/02-gui-components.md`）；工程侧值得抄的是 **`QRunnable`+`WorkerSignals` 统一模板**与**"所有外部 HTTP 一律后台化"**（`detail/01-main-orchestration.md`）。

## 三条硬约束（违反必踩坑）
1. **人格只在 `persona/*.md`**：`.md` 就是完整 System Prompt；`config.yaml` 只放表情/动作的技术映射，绝不拼人格文本。`.md` 里不写占位符时，记忆/规则/时间要靠程序在末尾追加（`memory.inject_context: true`）。
2. **记忆按「人格 + 会话」双键隔离**：`messages` 表有 `persona` 和 `conversation_id`；每个 persona 只有一个 `is_main=1` 的主对话。跨人格读写是 v0.2.2 修过的严重 bug。
3. **Live2D 端口写死 47835、无鉴权**：Python 与 .NET 两端都硬编码；任何本机进程都能控制你的桌宠。别暴露到局域网。

> 附带一条：原生模式下**没有兜底形象**（`main.py:392` `self.pet = None`，`PetWindow`/`FallbackPet` 整条内嵌链已停用），所以 `live2d.fallback_on_error: true` 是死配置——桌宠进程起不来就是"只有聊天窗口、没有角色、也不报错"。

## 关键数字（照抄用）
| 项 | 值 |
|---|---|
| LLM | DeepSeek，OpenAI 兼容，`https://api.deepseek.com`，`temperature 1.0`，`max_tokens 300` |
| 工作记忆 | `working_memory_size: 30` 条；压缩保留近 `window_size: 20` 条，摘要 ≤ `max_chars: 300` |
| 记忆检索 | `top_k: 8`；`consolidate_interval: 10` 轮；`max_memories: 5000`；`importance_threshold: 0.15`；相似合并 `0.85`；定时回顾 `30` 分钟 |
| 表情/动作 | 白名单 7 表情 + 5 动作；`emotion_map` / `motion_map` 映射到模型真名 |
| Heart | 轮询 `20s`；默认醒来 `15min`；可设范围 `2~120min`；主人说话后安静 `90s` |
| TTS | GPT-SoVITS `127.0.0.1:9880`；冷启动期间消息排队；首选后端约 `90~270s` 不就绪则回落 SAPI5（阈值 18 次 × 但计数器被 5s/15s 两个定时器共同递增） |
| Live2D | `127.0.0.1:47835`；缩放 `0.1~2.0`（GUI 滑条 `0.5~2.0`）；口型推送 `0.06s/次` |
| 数据 | `data/memory.db`（6 张表）；`data/heart.json`；`data/settings_overrides.json`（⚠️ 含真实 Key） |

## 文档导航
- `01-source-map.md` — 源码地图：哪份副本是准的、每个文件多少行、值钱的在哪儿
- `02-reusable-assets.md` — **可复用资产清单**（按"能不能直接搬"分为三级，含抽取配方）
- `03-live2d-bridge.md` — 原生 Live2D 桥接契约（端点表、JSON、口型同步、红线）
- `04-pitfalls.md` — 坑与红线（含工作副本与发布版的漂移、真实安全项）
- `detail/01-main-orchestration.md` — `main.py` 编排层深读
- `detail/02-gui-components.md` — PySide6 GUI 组件深读
- `detail/03-memory-persona-heart.md` — 记忆 / 人格 / 自主唤醒深读
- `detail/04-services-integrations.md` — 服务层与外部集成（TTS、MCP、搜索、视觉）深读

## 一句话结论
**代码里真正稀缺的不是 GUI，而是「记忆 + 人格 + 自主唤醒 + 语音 + 原生渲染」这五件事的接缝**；接缝处已经有踩过坑的正确答案，`Nori_Recreation_Prompt.md` 与 `agent/` 就是这套答案的成文版本，直接复用比重新设计便宜一个数量级。

# 04 · 坑与红线（跨模块汇总）

> 只收**已核实**的：读代码或看数据得到的结论，每条给位置。推测性内容一律标注"未确认"，不要当结论用。
> 单模块内部的细节坑见 `detail/` 对应章节，这里是复用/改行为前必须知道的横切面。

## 1. 安全（先处理，再谈复用）

| # | 问题 | 位置 | 影响 |
|---|---|---|---|
| S1 | **真实 API Key 落在会被打包/备份的文件里**：DeepSeek Key、百度 Key | `data/settings_overrides.json` | 任何"备份 data/""压缩整个项目"都会带走密钥；`config.yaml` 里 `api_key: ""` 只是占位，**真正的 Key 不在这里** |
| S2 | 视觉 Key 在 `vision_mcp/config.json` 里，且**已被提交进仓库** | `vision_mcp/config.json` | 与 `README.md:162`「分发不含 config.json」的承诺矛盾 |
| S3 | Live2D 控制服务**无鉴权**，`POST /model/import` 可从任意路径导入模型 | `PetControlServer.cs:26, 215-229` | 同机任意进程都能控制桌宠、隐藏窗口、导入模型。仅本机使用，别开防火墙端口 |
| S4 | 百度搜索把 Key 拼进 **URL query** | `agent/search.py:37-39` | Key 会进代理日志、抓包记录 |

## 2. 并发与线程（本项目最大的历史事故源）

| # | 问题 | 位置 | 说明 |
|---|---|---|---|
| C1 | **任何外部 HTTP 都不能在主线程同步调用** | `main.py:972` `_live2d_call` + `LipSyncPusher`（`:250-278`） | v0.2.2 的事故：口型同步用 QTimer 在主线程每 60ms 发一次 HTTP，本地服务无响应时每 tick 阻塞 5s，UI 直接冻死。现在的纪律是"一律丢 `QThreadPool` 或后台线程" |
| C2 | **GUI 包内零线程封送** | `gui/chat_window.py` 全文件 | `append_*` / `set_*` 全是裸 widget 操作；只能由主线程调用。目前能正常工作**全靠** `WorkerSignals` 信号回主线程，任何 worker 里直接改 UI 都会踩 Qt 红线（偶发崩溃/花屏，不一定立刻报错） |
| C3 | SQLite 跨进程并发无保护：单连接 + `check_same_thread=False` + RLock，**无 WAL、无 timeout** | `agent/memory.py:62-65`；`heart.py:51` | GUI 进程与 heart 进程各开一条连接写同一 `data/memory.db`；默认 5s 忙等，长写即 `database is locked`。且 `_touch()` 每次检索都 `UPDATE+commit`（`:441-453`），一轮 8 条记忆 = 8 次提交 |
| C4 | 在已有事件循环里 `asyncio.run(...)` | `agent/core.py:138, 241, 260` | 只有 `handle_user_text` 永远在线程池里跑这个**隐式前提**才不炸；直接在 async 上下文里调用会 `RuntimeError` |
| C5 | `QTimer.singleShot` 回调基本不检查对象存活 | `pet_window.py:139`、`fallback_pet.py:132` | 窗口销毁后触发抛异常；只有 `splash.py:80/87`、`chat_window.py:2659` 用 `RuntimeError` 兜了 |

## 3. 状态文件与原子性

| # | 问题 | 位置 | 后果 |
|---|---|---|---|
| A1 | **所有 JSON 状态都是非原子写**（`Path.write_text`） | `heart.py:76-81`、`persona.py:114-117`、`config.py:121-122`、`persona.py:217-219` | 崩溃/断电落在 truncate 之后 → 半截 JSON。**2026-10-25 已修** `heart.py` / `config.py` / `persona.py`（临时文件 + `os.replace`）；`scripts/` 下的辅助脚本仍是 `write_text` |
| A2 | `heart.json` 解析失败时**静默回落 default**，而 default 的 `next_wake_at = now` | `heart.py:62-74` | 状态文件一旦反复损坏，就退化成**每 20 秒调一次 LLM**（这正是 v0.2.2 修过的事故同型）。**2026-10-25 已补 warning 日志 + 损坏文件另存 `.broken.json`**，但 `next_wake_at` 仍会立即醒一次（是设计而非 bug） |
| A3 | TTS 排队队列上限 8，超了**丢最早的一条** | `main.py:946-948` | 冷启动期间连续对话会静默丢朗读文本 |
| A4 | `summary` 表只增不删，`ctx:*` 每换窗口/指纹就留一行 | `agent/memory.py:524-534`；`compressor.py` | 无 TTL、无清理，长期膨胀 |

## 4. Prompt 与记忆（功能"看起来有、实际没有"的重灾区）

| # | 问题 | 位置 | 后果 |
|---|---|---|---|
| P1 | **system prompt 完全没有长度预算** | `agent/prompts.py:40-58` | 人格 .md 约 9k 字符 + 8 条记忆（单条合并后可达 2000 字）+ 15 条规则 + 300 字摘要，最坏放大到十几万字符；`compressor` 只管历史消息，不管 system |
| P2 | 规则表只注入最新 15 条 | `prompts.py:49` | 实测 `rules` 已积 210 条全部 enabled，195 条永久沉底：既不参与推理，也不被清理 |
| P3 | **记忆去重从未生效**：`INSERT OR IGNORE` 的唯一键是每次新生成的 `uuid4()` | `memory.py:322-324` | 同一句话可无限入库；语义去重只有每 30 分钟一次的 `merge_similar_memories`（O(n²)）。**2026-10-25 已修**：`add_memory` 先按 `content` 查重，命中则只提升重要度 / 刷新时间并返回原 id |
| P4 | 人格切换后**摘要丢失** | `prompts.py:58` 只读 `working:{persona}` | 切人格后新人格从空白摘要开始（`persona_active.json` 已切到 V3.5.2，旧摘要没人读） |
| P5 | `heart` 的私人思考**不产生任何记忆** | `heart.py` 只写 `heart.json` | "自主时间想到的事"无法在白天聊天里被召回；要这个能力必须自己把 `thought` 写成 `episodic` |
| P6 | 文档漂移：`persona.control_rule` 在代码里不存在 | `README.md:134, 358`；真实规则在 `agent/core.py:221-234` | 按 README 删配置**不会**关掉 `[expr:]` 标签；`scripts/smoke_new_features.py:20` 也还在用旧键 |
| P7 | 视觉服务靠**名字含 "vision"** 识别 | `agent/core.py:101` | 改个名视觉就静默失效 |
| P8 | `_deep_merge` 对数组是**整体替换** | `agent/config.py:25-32` | overrides 里的 `llm.custom_models` 会顶掉 `config.yaml` 的数组，不是合并 |

## 5. Live2D 与 TTS 的"看起来能用"

| # | 问题 | 位置 | 说明 |
|---|---|---|---|
| L1 | `look_at` / `set_parameter` / `reset` 是 `return True` 空壳 | `live2d_native.py:178-185` | 调用方会以为成功，服务端根本没有这些端点 |
| L2 | 端口 47835 前后端都写死；`DEFAULT_PORT` 定义但未使用 | `live2d_native.py:19, 32`；`PetControlServer.cs:26` | 换端口必须同时改两端；cfg 里的配置读不到 |
| L3 | `play_motion(..., priority=...)` 的 `priority` 从不发送 | `live2d_native.py:103-109` | 参数是装饰 |
| L4 | `r.json()` 的 `ValueError` 不在 `except requests.RequestException` 覆盖内 | `live2d_native.py:56` | 服务返回非 JSON 的 200 时冒出未包装异常 |
| L5 | 原生模式下**没有兜底形象**：`self.pet = None` | `main.py:392`（残留分支 `:1468, 1474`） | `live2d.fallback_on_error: true` 是死配置；桌宠起不来 = 只有聊天窗口、无报错 |
| L6 | Nori 模型**没有 motion 文件** | `README.md:217` | `[motion:*]` 全部被安全忽略，视觉上只有表情会变 |
| T1 | TTS 兜底时间**不确定**：`_TTS_FALLBACK_AFTER=18` 这个计数器被**两个定时器共同递增** | `main.py:685, 693, 1003, 1013, 425` | 消息在排队时 5s 重试定时器（`:1003`）也在调 `_check_preferred_tts`，与 15s 探测定时器（`:425`）一起递增计数器 → 两者都在跑时约 **90s** 触发，只有探测定时器在跑时约 **270s**。注释写"每轮 5 秒"，`config.yaml:107` 写"约 90 秒"，实际取决于排队状态 |
| T2 | `gsv_is_running()` 探 `/docs`，`available()` 探 TCP 端口 | `services.py:263`；`tts/gpt_sovits_tts.py:46` | 两套判据不一致 → 可能"服务看着在跑，合成必然失败" |
| T3 | `mcp_manager.skill_instructions()` 每轮对话都触发一次 `save()` | `mcp_manager.py:213` + `core.py:213` | 每轮聊天多一次磁盘写 |
| T4 | MCP 每次工具调用都重建 session（stdio 会重启子进程） | `mcp_manager.py:161-185` | 多工具轮次开销大；transport 三分支还重复实现了两遍 |
| T5 | 日志源表里的 `live2d` 指向 `live2d_native.log`，而实际落盘的是旧 MCP 应用的 `live2d_mcp.log` | `utils/console_logs.py:7-15` | GUI 控制台「Live2D」页签永远显示"没有匹配的日志"。**2026-10-25 已修**：`Live2DNativeClient.ensure_running` 现在把桌宠进程的 stdout/stderr 重定向进 `data/logs/live2d_native.log`（`agent/live2d_native.py` 的 `_open_pet_log()`），映射改回 `live2d_native.log` |

## 6. 仓库与环境的坑

| # | 问题 | 说明 |
|---|---|---|
| R1 | **工作副本不是 git 仓库**，且与发布版有未提交差异 | `D:\Nori_Live2D_Chat` 无 `.git`；`agent/prompts.py`、`agent/services.py`、`agent/tts/factory.py`、`heart.py`、`utils/tts_voices.py` 与 HEAD `bc4fa8a` 不一致，且**无法回滚**。要读"发布版行为"请看 `D:\Nori_Live2D_Chat_github` |
| R2 | 源码全是 UTF-8，PowerShell 5.1 默认按 ANSI 解 | 直接 `Get-Content` 会把 `README.md`、`requirements.txt`、`ACKNOWLEDGEMENTS.md` 显示成乱码，**不是文件损坏** |
| R3 | 依赖不 pin 版本 | `requirements.txt` 只有 `>=`（`PySide6>=6.10`、`openai>=1.50`、`mcp>=2.0`）；`mcp` 的 `MCPServer` / `streamable_http_client` 都是较新 API，换版本可能直接 ImportError |
| R4 | venv 是 **Python 3.14**（`__pycache__/*.cpython-314.pyc`） | 与 `requirements.txt` 注释推荐的 3.11~3.13 不一致；第三方轮子可用性受 3.14 限制 |
| R5 | `PySide6.QtWebEngineWidgets` 是**独立 wheel** | 老方案 `live2d_view.py` 依赖它，缺了直接 `ImportError`（`pet_window.py:75-87` 有兜底）；当前 native 模式已不需要 |
| R6 | `live2d/` 目录不存在 | `live2d_view.py:20-22` 指向 `<repo>/live2d/index.html` 与 `live2d/js`，仓库里没有；`ensure_qwebchannel_js()` 还会**往项目目录写文件**（`:59`） |
| R7 | 40 多个 `scripts/inori_*.py` + `data/inori_*.txt` | 对另一个 Web 应用的逆向探测残留（登录/WebSocket/协议函数表等），与桌宠主流程无关，搬项目时整目录排除 |

## 7. 复用红线（别做的事）

1. **别把 `data/` 一起分发给别人**（S1/S2 的 Key，还有 300 MB 语音权重与 246 KB 个人对话）。
2. **别在 GUI 线程直接调用 `live2d_native` 的任何方法**（C1）。
3. **别在 worker 线程里直接 `chat.append_*`**（C2）。
4. **别依赖 `look_at / set_parameter / reset / priority`**（L1/L3），它们是壳。
5. **别照抄 `memory.py` 的入库去重就以为有去重**（P3）—— 本工作副本已于 2026-10-25 改为按内容去重，但发布版 `v0.2.2` 及其之前的代码里仍然没有。
6. **别按 README 改 `persona.control_rule` 来关标签**（P6）。
7. **别假设 `data/settings_overrides.json` 里的路径在换机后还有效**（全是绝对路径）。
8. **别把 `data/memory.db` 当只读快照用**——heart 进程可能正在写（C3）。

## 8. 2026-10-25 这轮改了什么（文档对应关系）

本轮只做「轻量修 bug + GUI 局部打磨」，不动配色与整体风格。改动后 `chat_window.py` 的行号整体下移（STYLE 末尾追加了 4 条规则，设置页初始化重写），下面这些原文档里的行号**已经偏移**：

| 主题 | 改法 | 落点（新行号） |
|---|---|---|
| 设置页滚动 | 每个子页各包一层 `QScrollArea`，页签栏固定在顶部；`settings_scroll` 属性已删除，改成 `_settings_scrolls` 列表 | `chat_window.py:755-776`；`_current_settings_page()` `:798` |
| `_fit_to_screen` 未定义函数 | 改用 `QApplication.primaryScreen()` | `:788` |
| 气泡时间戳 | `MessageBubble(..., ts=)` 参数化，`_format_ts()` 当天 `HH:MM` / 跨天 `MM-DD HH:MM` / 跨年日期 | `:446`、`:534` |
| 字号替换 | 删掉 `QLineEdit#MessageInput` 里写死的 `font-size: 13px`，`_style_for_font` 的 `replace(..., 1)` 仍只命中 `QWidget#ChatWindow` | STYLE `:74-439`，`_style_for_font` `:849` |
| 宠物大小钳位 | `set_current_settings` 由 `min(3.0, …)` 改为 `min(2.0, …)`，与滑块 `50~200` 对齐 | `:2565` |
| 会话卡片 | 新增 `QWidget#HistoryCard` / `#HistoryCardActive` 两条 QSS + `WA_StyledBackground`，卡片内边距 `(14,10,14,10)` | STYLE `:414-423`，`_render_history_list` `:2273-2290` |
| 基础设置排版 | 内容包一层 `maxWidth 1040` 容器居中；`QGridLayout` 补 `setColumnStretch`；「应用并保存」类按钮不再被拉满整行 | `_build_basic_settings_page` `:1628` 起 |
| MCP/Skills 空态 | 空列表插入灰色占位项（`_add_list_placeholder`） | `:1458`、`:1470`、`:1475` |
| 控制台刷新 | 新增公开方法 `refresh_console()`（`main.py:1959` 不再直接调私有 `_refresh_console`） | `:1578` |

`reuse-docs/detail/02-gui-components.md` 里提到的「气泡最大宽 620 / 头像 36 / 缩略图 300×240」等常量本轮**没有改**；`PetWindow` / `fallback_pet.py` 仍是未接线的孤儿代码，本轮未动。

## 9. 2026-10-26 自主性升级（A/B/C 落地）带来的新坑

本轮把「心脏只会定时醒来发一个动作」改成「秒级导演 + 分钟级 LLM 意图」。改完 `heart.py` 是**重写**（约 535 行），旧的行号引用全部作废，以本节为准。方案与实测数据见 `docs/autonomy-plan.md` 第 10 节。

### 9.1 新增文件

| 文件 | 作用 |
|---|---|
| `agent/pet_director.py` | 秒级反射层（body lock、微动作权重表、作息、剧本队列、说话预算） |
| `agent/presence.py` | 纯本地 Win32 感知（`GetLastInputInfo` / `GetForegroundWindow`），不联网、不截图 |
| `data/heart_events.jsonl` | heart 写、GUI 增量读的内心 OS / 情绪事件流 |
| `data/heart_persona_digest.json` | 人格摘要缓存（按人格内容哈希失效） |

### 9.2 新坑（都已踩过）

| # | 坑 | 表现 | 对策 |
|---|---|---|---|
| A3 | **`deepseek-flash` 是推理模型，reasoning 吃 `max_tokens`** | `finish_reason=length`、`content` 为空字符串；人格摘要 2000 token 预算直接失败（思考就花掉 2000） | 摘要上限提到 8000；思考上限 2400 且首次返回空 content 时**预算翻倍重试一次**（实测会成功）。`finish_reason=stop` 但 content 为空的情况也存在，同样靠这次重试兜住 |
| A4 | **配置里的动作/表情名指向旧模型** | `emotion_map` 7/7 解析失败（爱心眼/圈圈眼/黑化…都是旧 `nori` 模型的），`motion_map` 的挥手/鞠躬也不存在 | 全部换成 `arg-nori` 真名：表情 `happy troubled surprised shy angry serious doubt`、动作 `wakuwaku nod`。改完必须用别名解析器 + `ARGNori.model3.json` 对一遍 |
| C4 | **GUI 托管 Live2D 时 heart 拿不到客户端** | `NORI_HEART_SKIP_LIVE2D=1` 时原代码 `self.live2d = None`，导演的所有 `play_motion` 静默变成空操作 —— 主用法下「自主性」完全失效 | 改成 **attach 模式**：客户端永远创建（`self.live2d_owned = False`），只跳过 `ensure_running()` / `shutdown()` / 口型；导演照常往 47835 发 `/motion`、`/expression` |
| C5 | **1 Hz 循环里不能有慢请求** | 桌宠没起来时 HTTP 连不上；若超时设成 5 秒，心跳会被拖住 | 连不上的端口在 Windows 上立即 ECONNREFUSED，`_send` 捕获异常后返回 False，不影响节拍；**禁止**在这里加 `time.sleep` 或重试 |
| G1 | **`QLabel` 开 `wordWrap` 后宽度会塌成「最长的词」** | 内心 OS 气泡被挤成一条竖长条 | 用 `fontMetrics().horizontalAdvance(text)` 算出理想宽度再 `setFixedWidth(min(560, max(200, ideal)))` |
| G2 | **多个来源抢同一个身体** | 聊天里的 `[motion:...]`、导演的剧本、微动作会互相打断，1 Hz 下看起来抽帧 | `PetDirector` 单一 body lock：优先级 speak 100 > intent 60 > micro 20，且每个动作有最短驻留（motion 3s / expr 0.4s / speak 4s） |

### 9.3 调参入口

全部在 `config.yaml` 的 `autonomy:` 段：`micro_lambda_day/night`（微动作频率）、`quiet_hours`（作息）、`speak_budget_per_hour` / `speak_cooldown_sec`（打扰预算）、`away_sec`（多久算离开）、`inner_os`（内心 OS 是否上屏）、`persona_digest`（人格摘要开关）、`emotion_baseline`（情绪基线）。GUI 里没有开关，改完配置重启 `run.bat` 生效。

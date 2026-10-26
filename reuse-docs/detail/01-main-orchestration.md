# main.py 编排层里值得复用的部分

> 分析对象：`D:\Nori_Live2D_Chat`
> 本次只读范围：`main.py`、`run.bat`、`run_console.bat`、`run_chat_only.bat`、`utils/console_logs.py`、`utils/audio.py`
> 所有行号均为**实际读取到的行号**；凡是没有在本范围内看到实现的地方，一律写「未确认」，不做推测。

## 0. 先说三个会影响复用判断的前提

**0.1 行数校正。** `main.py` 实测 **2132 行 / 96,822 字节**，与任务描述里的「1933 行」不符。下文行号以 2132 行版本为准；如果对方文件后来又改过，行号会整体漂移，请以函数名为锚点而不是纯行号。

**0.2 它只是一层「接线板 + 线程隔离层」。** main.py 自己没有 OpenAI 客户端、没有 prompt 拼装、没有标签正则、没有流式解析，这些都 import 自 `agent/`（`main.py:28-49`）。因此「LLM 调用封装 / 多轮 tool-call 循环 / 流式输出 / `[expr:...]` 标签解析」在本文件里**找不到实现**，详见 3.0。本文的价值集中在另一类东西：**把会阻塞的 I/O 从 GUI 线程里赶出去的各种模式**，这才是可以直接搬到别的 PySide6 项目里的资产。这层「骨架」被集中拆解在 **2.4**，是全篇最值得移植的部分。

**0.3 代码风格特征。** 全文件没有一处 `TODO/FIXME/HACK` 注释，但存在大量「同一个动作有两种执行路径」的演化痕迹（见第 5 节），这是判断「哪段能照抄」的主要依据。

---

## 1. 启动流程：从双击 bat 到 `app.exec()`

### 1.1 路径 A：`run.bat`（无控制台，日常使用）

| 步 | 位置 | 做什么 |
|---|---|---|
| 1 | `run.bat:2-3` | `chcp 65001` 切 UTF-8 + `cd /d "%~dp0"`（双击时 cwd 是 `system32`，必需） |
| 2 | `run.bat:12-20` | 没有 `.venv` 就先 `call setup_venv.bat`，失败则 `pause` + `exit /b 1` |
| 3 | `run.bat:23-27` | 优先 `start "" .venv\Scripts\pythonw.exe main.py %*`，`pythonw` 缺失则降级 `python.exe`。`start` 让 bat 立刻退出、进程脱离控制台，所以 `run.bat:8-9` 提前告知「日志在 GUI 的 Console 页」 |
| 4 | `main.py:20-22` | `PROJECT_ROOT` 插入 `sys.path[0]`，保证任意 cwd 都能 `import agent` / `gui` |
| 5 | `main.py:2058-2064` | `argparse`：`--config` / `--no-pet` / `--no-services` / `--no-splash` |
| 6 | `main.py:2066-2067` | `load_config(args.config)` → `setup_logging(cfg.log_file)`（见 3.9、5.4） |
| 7 | `main.py:2069-2085` | `QApplication` + `setApplicationName` → Windows `SetCurrentProcessExplicitAppUserModelID("Alorit.Nori.Live2DChat.1")`（try/except 静默）→ 全局图标 `gui/assets/nori_icon.png` → `setQuitOnLastWindowClosed(args.no_pet)` |
| 8 | `main.py:2087-2092` | 非 `--no-splash` 时建 `SplashWindow`，`show()` + **手动 `app.processEvents()`**，保证 splash 先画出来再进构造函数 |
| 9 | `main.py:2094-2101` | `AppController(cfg, app, enable_pet=, autostart_services=, progress=splash.set_progress)`；异常时先 `splash.finish()` 再 `raise` |
| 10 | `main.py:331-435` | `AppController.__init__` 分阶段初始化，进度点 8→16→24→30→38→48→60→78→86→92→100（见 1.3） |
| 11 | `main.py:2103-2123` | 定义 `_on_quit()` 并 `app.aboutToQuit.connect(_on_quit)`：`pool.clear()` → `waitForDone(3000)` → `memory.close()` → 条件性 `stop_heart()` |
| 12 | `main.py:2124-2127` | `controller.show()` → `QTimer.singleShot(150, splash.finish)`：先铺主窗再撤 splash，避免闪一帧空桌面 |
| 13 | `main.py:2128` | `sys.exit(app.exec())` |

### 1.2 路径 B / C：`run_console.bat` 与 `run_chat_only.bat`

`run_console.bat:7-9` 是同一入口的**前台版**：`activate.bat` → `python main.py %*`（不加 `start`）→ `pause`；差别只是可见 stdout，于是 `main.py:66-67` 的 `StreamHandler` 分支成立。`run_chat_only.bat:4` 只有一行 `call run.bat --no-pet %*`，`--no-pet` 连锁影响三处：`setQuitOnLastWindowClosed(True)`（2085）、`enable_pet=False`、`start_heart(skip_live2d=not self.enable_pet)`（607）。

### 1.3 `AppController.__init__` 内部阶段表（`main.py:331-435`）

| 进度 | 行号 | 动作 | 是否阻塞 UI |
|---|---|---|---|
| 8 / 16 / 30 | 362 / 364 / 367-371 | `MemoryStore` → `Brain` → `BaiduSearchClient` + `MCPManager` → `AgentCore(4 依赖)` | 是 |
| 24 | 365 | `_stage(24, "正在检查视觉 MCP…")` | **纯装饰**：24 与 30 之间没有任何实际工作（真探测在 `_vision_mcp_available()`，712-720） |
| 38 | 380-386 | `create_tts(cfg, allow_fallback=not gsv_expected_to_start(cfg))`，失败只 warning | 是，被 try 包住 |
| 48 | 391 | `ChatWindow(cfg, quit_on_close=not enable_pet, live2d_mode=live2d_enabled)` | 是（最重的一步） |
| 60 | 396-399 | 建 `Live2DNativeClient`，只置 `start_live2d_async` | 否 |
| — | 401-404 | `_wire()` 接 56 个信号 → 起后台线程连 Live2D | 否 |
| 78 | 406 | `_load_gui_data()`：人格 / 记忆 / TTS 语音包 / MCP / Live2D 模型 | 是 |
| 86 | 409-411 | `_autostart_services()`：起 Heart、按 `auto_start` 起 GPT-SoVITS | 是（见 5.3） |
| 92 | 413-414 | `_startup_message()`：往聊天区刷状态行 | 否 |
| — | 417-431 | 三个 `QTimer`：记忆回顾(417-419)、TTS 探测 15s(423-425)、服务状态 3s(428-431) | 否 |
| 100 | 432 | `_stage(100, "Nori 已就绪")` | — |
| — | 435 | `QTimer.singleShot(600, self._maybe_first_run_wizard)` | 否 |

---

## 2. main.py 的内部结构

### 2.1 三层划分

- **第 1 层：线程原语（`main.py:76-324`）** —— 9 个 `QRunnable` 子类 + 1 个 `threading.Thread` 子类，全部共用同一个 `WorkerSignals`。这层是**唯一真正通用、可以整块搬走**的东西。
- **第 2 层：`AppController`（`main.py:328-2054`）** —— 约 140 个方法，其中 72 个带 `@Slot`、60 个是 `on_*` 入口；真正的逻辑只有约 8 个（TTS 状态机、Live2D 命令分发、退出编排、启动编排、人格/会话一致性守卫），其余是 `_refresh_*` / `_load_*` 同步 UI 的胶水。
- **第 3 层：`main()`（`main.py:2057-2128`）** —— 60 行纯装配。

### 2.2 线程原语层（第 1 层）

| 名称 | 行号 | 职责 | 性质 |
|---|---|---|---|
| `setup_logging` | 62-72 | FileHandler + 条件 StreamHandler | 可复用（坑见 5.4） |
| `WorkerSignals` | 76-78 | `result=Signal(object)` / `error=Signal(str)` | **可复用核心** |
| `SendWorker` / `TTSWorker` | 81-101 / 104-122 | 后台跑 `core.handle_user_text()` / `tts.speak()` | 模板 |
| `Live2DWindowWorker` / `Live2DCallWorker` | 125-146 / 149-163 | 前者后台 `ensure_running()`（docstring：忙等最多 30 秒，绝不能进 GUI 线程）+ `control_window`；后者把任意 `fn(*args)` 丢进池 | **最值得抄** |
| `ServiceActionWorker` / `ShutdownWorker` | 166-191 / 194-220 | 前者按 action 字符串分发服务启停；后者顺序停 Heart→GSV→Live2D，每步独立 try/except | 胶水 / **可复用** |
| `LLMFetchModelsWorker` | 223-247 | 后台 `OpenAI(...).models.list()`，兼容 str 与对象两种返回 | 可复用 |
| `LipSyncPusher` | 250-278 | `threading.Thread`，每 60ms 推一帧嘴型电平 | **可复用** |
| `ServiceStatusWorker` / `TTSPreferredWorker` | 281-300 / 303-324 | 后台 `services.status()` / `backend.available()` 探测 | 模板 |

### 2.3 `AppController` 关键方法

**核心逻辑（值得读、值得抄思路）**

| 方法 | 行号 | 一句话职责 |
|---|---|---|
| `__init__` | 331-435 | 全部分阶段装配 + 三个定时器 |
| `_wire` | 462-523 | 信号总接线（**这是整个项目的接口清单**） |
| `_connect_live2d_async` | 525-541 | 后台连 Live2D，结果通过 `live2d_connection_done` 回 UI 线程 |
| `_autostart_services` | 603-616 | 按 `heart.enabled` / `gpt_sovits.auto_start` 决定起什么 |
| `_check_preferred_tts` | 642-657 | 每 15s 探测首选 TTS 后端 |
| `_maybe_activate_fallback` | 687-710 | 连续 N 次探测失败后降到兜底后端 |
| `speak` / `_speak_now` / `_flush_tts_pending` / `_schedule_tts_retry` / `_on_tts_retry` | 940-1015 | **TTS 冷启动排队状态机**（见 3.2） |
| `_live2d_call` | 972-976 | 一行把任意 Live2D 调用后台化 |
| `_start_lip_sync` / `_stop_lip_sync` | 978-991 | 嘴型线程的开关，收尾时补一帧 `audio_level(0)` |
| `_apply_live2d_commands` / `_map_name` | 860-879 | 把 `(kind, name)` 命令映射成人格配置里的资源名再下发 |
| `_prepare_media_paths` | 820-850 | 图片校验 + 复制进 `data/chat_media` 持久化 + 去重 + 上限 4 张 |
| `on_quit_requested` | 2031-2045 | 完全退出编排 + 12 秒兜底强制 `app.quit` |
| `_maybe_first_run_wizard` | 438-459 | 首次运行向导（`user_name` + `first_run_done` 双条件） |
| `_switch_active_persona` | 1587-1608 | 人格/会话一致性守卫（docstring 讲了一个真实的数据一致性陷阱） |

**胶水方法（列表式，不必细看）**

`_refresh_tts_voices`(589) `_refresh_service_status`(618) `_refresh_status_pill`(722) `_startup_message`(732) `_load_gui_data`(553) `_reload_current_chat_history`(1123) `_refresh_history_page`(1621) `_refresh_persona_page`(1627) `_refresh_memory_page`(1764) `_refresh_mcp_page`(1851) `_refresh_live2d_models`(1968) `memory_table_count`(1780) `_apply_speed`(1452)；以及 `on_*` 系列设置类槽函数：`on_avatar`(1131) `on_agent_avatar`(1161) `on_user_name`(1188) `on_agent_name`(1197) `on_font_size`(1112) `on_chat_font_size`(1118) `on_speed`(1449) `on_scale`(1461) `on_always_on_top`(1472) `on_llm_model_rename`(1390) `on_llm_model_delete`(1416) `on_memory_*`(1784-1848) `on_mcp_*`(1864-1895) `on_skill_*`(1898-1920) `on_persona_*`(1635-1697) `on_conversation_*`(1708-1761) `on_tts_voice_*`(1342-1386)。这 40+ 个方法的结构完全一样：`try: 调 agent 层 → self.chat.append_system("✅/⚠ ...") except Exception as e: self.chat.append_system(f"⚠ ...：{e}")`，属于**可批量生成的样板**。

**疑似死代码**

- `_consolidate_in_thread`（`main.py:901-903`）：全文件只有定义，没有任何调用点（grep 确认），实际被 `_memory_review_in_thread`(913) 取代。
- `self.pet` 恒为 `None`（`main.py:392` 注释「完全替换：不再使用内嵌 Live2D 渲染」），因此 `784-785`、`1468-1469`、`1474-1476`、`2049-2050` 五个 `if self.pet:` 分支永远不执行 —— 旧「Qt 内嵌宠物窗口」方案残留。
- `toggle_chat`（`main.py:930-937`）：文件内无调用，gui 侧是否连接未确认。

### 2.4 编排层骨架四件套（全篇最有复用价值的部分）

这一节不看业务，只看「一个 PySide6 应用该怎么被装配起来」。四件套是：**启动顺序 / worker 组织 / 信号槽契约 / 退出清理顺序**。

#### (a) 启动顺序：哪些是硬约束，哪些只是习惯

| 顺序约束 | 行号 | 为什么不能换 |
|---|---|---|
| `QApplication` 早于任何 `QWidget` / `QTimer` / `QObject+Signal` | 2069 → 2095 | 没有 app 实例时建 widget 会直接崩；`AppController` 里的三个 `QTimer(self)`（417/423/428）也依赖 app 已存在 |
| `load_config` + `setup_logging` 早于 `QApplication` | 2066-2067 → 2069 | 配置失败/日志目录不可用时要能在**没有 GUI** 的情况下报错 |
| `splash.show()` + `app.processEvents()` 早于 `AppController(...)` | 2087-2092 → 2095 | `AppController.__init__` 是同步阻塞 2~5 秒的；不手动 `processEvents()` 的话 splash 根本没机会绘制，用户看到的是「双击后没反应」 |
| splash 先建好，`progress=splash.set_progress` 才传得进去 | 2089 → 2097 | `--no-splash` 时传 `None`，由 `AppController` 内部降级为 no-op（352） |
| 依赖对象先于依赖者：`MemoryStore` → `Brain` → `AgentCore` | 362-371 | `AgentCore(cfg, memory, brain, search=, mcp_manager=)` 四个依赖全要已构造 |
| `ChatWindow` 早于 `_wire()` | 391 → 401 | `_wire` 的每一条 `.connect` 都打在 chat 实例上 |
| `_wire()` 早于任何会产生回调的动作 | 401 → 402 起 | `_autostart_services`（409）末尾会 `_refresh_service_status()`（616），其结果槽会写 chat；`_connect_live2d_async`（404）会 emit `live2d_connection_done` |
| 阻塞项一律延后到后台：Live2D 连接（404）、首个服务状态刷新（431） | 402-404 | 「先让窗口出现，再让功能就绪」是这套启动的基本取舍 |
| `aboutToQuit` 连接早于 `app.exec()` | 2123 → 2128 | 晚于 exec 就永远不会被触发 |
| `controller.show()` 早于 `splash.finish` | 2124 → 2127 | 先让主窗口铺好，再撤 splash，避免中间闪一帧空桌面 |

**可直接照抄的最小启动骨架（10 步）**：`cfg → logging → QApplication(+AppID/icon/quitOnLastWindowClosed) → splash+processEvents → 构造 controller(progress 回调) → 构造完成后再 show 主窗 → singleShot(150, splash.finish) → aboutToQuit 挂清理 → exec`，中间所有 I/O 用 `_stage()` 打点。

#### (b) worker 组织方式：四类，别混用

| 类型 | 代表 | 有无结果回调 | 生命周期 | 适用 |
|---|---|---|---|---|
| ① fire-and-forget | `Live2DCallWorker`（149-163） | **无**（调用方根本不 connect） | 单次，跑完即弃 | 幂等、可失败、不影响状态的「装饰性」外部调用（表情、动作、音量） |
| ② 单次带结果 | `SendWorker`(81) `TTSWorker`(104) `Live2DWindowWorker`(125) `ServiceActionWorker`(166) `LLMFetchModelsWorker`(223) `ServiceStatusWorker`(281) `TTSPreferredWorker`(303) | 有，`connect(result)` + `connect(error)` 成对 | 单次 | 所有需要回写 UI 的阻塞操作 |
| ③ 常驻周期线程 | `LipSyncPusher`（250-278，裸 `threading.Thread`） | 无 | 由外部 `stop()` + `Event` 控制 | 固定频率推送（口型、性能采样、心跳） |
| ④ 一次性 Python 线程 | `_connect_live2d_async`(404)、记忆回顾(902/914) | 通过 `Signal` 回 GUI 线程 | 单次，`daemon=True` | 只需「跑完通知一声」，不需要池的排队语义 |

**照抄这 5 条约定，worker 层就不会失控**：①每个 worker 实例自带一个 `WorkerSignals()`，绝不用类属性；②`run()` 内层 try 包业务异常、外层 try 包 `emit` 的 `RuntimeError`（程序退出时信号源已销毁）；③worker 内**绝不碰任何 Qt 控件**，只 emit；④并发控制在**调用方**用 `_xxx_busy` 阀（GUI 线程读写），不在 worker 里加锁；⑤长任务统一用 `QThreadPool.globalInstance()`（336），特殊顺序需求才另建池。

#### (c) 信号槽契约：三条硬规则

1. **`@Slot` 声明必须与 emit 的实际类型一致**：`media_send_requested` 在 main 侧是 `@Slot(object, str)`（798-799）而不是 `list[str]`——PySide6 里给容器类型声明 `Signal` 容易踩坑，退化成 `object` 是务实的做法。
2. **单向数据流**：gui 只 emit「意图」（全部以 `*_requested` 结尾，462-522，共 56 条 `.connect`），main 负责执行、并把结果用 `chat.append_system(...)` 回写；**gui 从不直接调 agent/**。这条规则让 60 个 `on_*` 槽的实现方式高度一致（见 2.3 胶水清单）。
3. **线程归属**：worker → main 的槽是 `AutoConnection`，因为 `AppController` 在 GUI 线程构造（2095），所以跨线程 emit 会自动排队到 GUI 线程执行——整个「后台干活、主线程改 UI」的安全性**完全建立在这一条上**。任何把 controller 挪到非 GUI 线程构造的改动都会立刻破坏它。

#### (d) 退出清理顺序（可直接照抄的 7 步）

| 步 | 行号 | 动作 | 理由 |
|---|---|---|---|
| 1 | 2033-2035 | `_quitting` 阀挡住重复点击 | 退出流程本身要跑十几秒，用户会连点 × |
| 2 | 2037 | `_full_quit = True` | 后面 `aboutToQuit` 靠它**跳过**重复停服务（2118） |
| 3 | 2038-2040 | 停 `_lip_pusher` | 它是唯一会持续产生新 HTTP 请求的源头，必须先掐掉 |
| 4 | 2041-2043 | 后台 `ShutdownWorker`：停 Heart → 停 GPT-SoVITS → `live2d.shutdown()`，每步独立 try/except | 串行 + 隔离：前一个失败不能导致后一个残留进程（204-216） |
| 5 | 2045 | `QTimer.singleShot(12000, self.app.quit)` 硬兜底 | 清理卡死也必须能退出，这是「用户永远关得掉」的保证 |
| 6 | 2105-2113 | `pool.clear()`（丢弃未开始的任务）→ `pool.waitForDone(3000)`（等在飞的任务）→ `memory.close()` | **先排空、再关库**；反过来会让在飞任务的最后一条消息静默丢失（注释 2104） |
| 7 | 2118-2119 | 仅在「不是完全退出」且 `heart.stop_with_gui` 为真时才 `stop_heart()` | 完全退出已在步 4 停过；重复停要跑 tasklist + PowerShell，白等 8~12 秒（注释 2115-2117） |

顺序的通用原则可以抽象成一句话：**先掐产生新任务的源头 → 再排空队列 → 最后关资源；兜底定时器独立于任何一步。**

---

## 3. 可复用清单

每条固定五栏：**可复用的是什么 / 源位置 / 依赖 / 注意事项 / 照抄还是重写**。

### 3.0 先排除四个「不在本文件」的主题

| 主题 | main.py 里的实情 | 结论 |
|---|---|---|
| LLM 调用封装 | 只 `from agent.brain import Brain` / `AgentCore`（`main.py:28-31`），从不直接发对话请求。唯一 `openai` 用法在 `LLMFetchModelsWorker`（`main.py:235-238`），只用于 `models.list()` | **落点在 `agent/brain.py`，本次范围外，未确认** |
| 多轮 tool-call 循环 | 文件内无 `tool_call` 字样 | **落点在 `agent/`，未确认** |
| 流式输出 | 文件内无 `stream` 字样；`SendWorker` 是**整段返回**（`main.py:92-94` 一次 emit 完整 reply） | **本项目编排层不走流式**；若换项目要做流式，需自己设计增量信号 |
| `[expr:...]` / `[motion:...]` 标签解析 | 无正则、无 `import re`。`_on_reply`（857）拿到的 `reply.commands` 已是 `list[(kind, name)]`，`_apply_live2d_commands`（860-873）只做消费 | **解析在 `agent/`，未确认；main.py 侧只贡献「命令 → 资源名映射」这半段（3.5）** |

### 3.1 `WorkerSignals` + `QRunnable` 统一模板 ★★★★★

- **可复用的是什么**：给每个后台任务配一个独立 `QObject` 信号载体，`run()` 里用两层 try 把「业务异常」和「程序退出导致的 `RuntimeError: Signal source has been deleted`」分开处理。后者在 PySide6 里是真实高频问题（窗口销毁后后台线程 emit 会抛）。
- **源位置**：`main.py:76-78`（信号定义）、`main.py:81-101`（标准范式）、同样结构复用于 `104-122`、`137-147`、`158-163`、`176-191`、`203-220`、`233-247`、`289-300`、`312-324`。
- **依赖**：`PySide6.QtCore.QRunnable / QObject / Signal`、`QThreadPool`。
- **注意**：`WorkerSignals` 是**每个 worker 实例各自 new 一个**（如 `main.py:88`），不是类属性 —— 这点必须照抄，类级单例会导致多任务信号串号。另外 emit 失败只吞掉、不记录日志，调试期建议加 `logging.debug`。
- **照抄**：

```python
class WorkerSignals(QObject):
    result = Signal(object)
    error = Signal(str)

class Live2DCallWorker(QRunnable):
    """把任意 fn(*args) 丢到后台执行；本地服务无响应时也不卡界面。"""
    def __init__(self, fn, *args):
        super().__init__()
        self.fn, self.args = fn, args
        self.signals = WorkerSignals()

    def run(self):
        try:
            self.fn(*self.args)
            self.signals.result.emit(True)
        except Exception as e:
            self.signals.error.emit(str(e))
```

### 3.2 TTS 冷启动排队 + 兜底切换状态机 ★★★★☆

- **可复用的是什么**：「音频后端可能几十秒后才可用」这件事的完整处理方案：待播队列（上限 8，超了丢最旧）→ 定时重试（5s）→ 独立探测器（15s）→ 连续 N 次失败降级兜底 → 就绪后回灌队列。这套逻辑可以原样搬到任何「可选重后端 + 有轻量降级后端」的场景（TTS、STT、视觉模型、本地 embedding 都成立）。
- **源位置**：队列与入口 `speak`(940-954)、真正播放 `_speak_now`(956-969)、回灌 `_flush_tts_pending`(993-997)、重试定时器 `_schedule_tts_retry`(999-1006)/`_on_tts_retry`(1008-1015)、结束 `_on_tts_done`(1017-1028)、失败 `_on_tts_error`(1030-1042)、探测器 `_check_preferred_tts`(642-657)、降级 `_maybe_activate_fallback`(687-710)、阈值常量 `_TTS_FALLBACK_AFTER = 18`(685)。
- **依赖**：`QTimer`（必须在 GUI 线程创建，`parent=self`）、`QThreadPool`、`create_tts/create_backend/probe_backends`（`agent/tts/factory.py`，未读）、`gsv_expected_to_start`（`agent/services.py`，未读）。
- **注意**：`_tts_busy` 是**唯一并发闸门**，但它在 GUI 线程读写、在 worker 完成后经信号回写，没有加锁 —— 依赖 Qt 的「槽在接收者线程执行」语义才安全；如果把它挪到非 Qt 环境需要自己加 `threading.Lock`。另外阈值注释写「每轮 5 秒 × 18」，但探测定时器实际是 **15 秒**（`main.py:425`），注释与实现不一致（见 5.2）。
- **重写**（业务绑定太重，建议保留骨架重写）：队列 + busy 标志 + 三级定时器这三件事照抄，`create_tts` / `gsv_*` 换成自己的后端探测函数。

### 3.3 口型同步推送线程 ★★★★☆

- **可复用的是什么**：一个「按固定帧率向外部渲染进程推参数」的守护线程，带 `Event` 停止语义和 `Event.wait(interval)` 节拍（比 `time.sleep` 更可中断）。以及一个容易被忽略的收尾动作：停止时补发一帧 0，防止嘴永远张着。
- **源位置**：`LipSyncPusher`（`main.py:250-278`）、开关 `_start_lip_sync`(978-984)/`_stop_lip_sync`(986-991)、在 `_speak_now`(965) 与 `_on_tts_done`(1020)/`_on_tts_error`(1033) 挂载。
- **依赖**：`threading`、`math`、`live2d.audio_level(level: float)`。**不依赖 Qt**，可独立移植。
- **注意**：电平是**用正弦波伪造的包络**，不是真实音频分析（`main.py:272` 注释也承认「模拟语音包络」）。要真实口型需要把 TTS 输出的 PCM 接进来算 RMS。另外 `interval=0.06` 是硬编码，不同机器/服务端会需要调。
- **照抄**（这是全文最干净、零业务耦合的一段）：

```python
class LipSyncPusher(threading.Thread):
    def __init__(self, client, interval: float = 0.06):
        super().__init__(daemon=True, name="lip-sync")
        self.client = client
        self.interval = interval
        self._stop_event = threading.Event()

    def stop(self):
        self._stop_event.set()

    def run(self):
        counter = 0
        while not self._stop_event.is_set():
            counter += 1
            phase = counter * 0.55
            level = 0.35 + 0.45 * abs(math.sin(phase)) + 0.12 * math.sin(phase * 2.7)
            level = max(0.0, min(1.0, level))
            try:
                self.client.audio_level(level)
            except Exception:
                pass
            self._stop_event.wait(self.interval)
```

### 3.4 「所有外部 HTTP 一律后台化」的一行封装 ★★★★★

- **可复用的是什么**：`_live2d_call(fn, *args)` 把「任何函数 + 参数」丢进 `QThreadPool`，调用点因此可以保持「同步写法」而实际异步执行。这是把一棵已经写满同步调用的代码树**低成本**改造为不卡 UI 的最小侵入方案。
- **源位置**：`main.py:972-976`（封装）、`main.py:149-163`（worker）、调用点示例 `main.py:792`、`814`、`868`、`871`、`991`。
- **依赖**：`QThreadPool.globalInstance()`（`main.py:336`）。
- **注意**：**没有返回值、没有错误回传、没有顺序保证**。同一角色的 `set_expression` 和 `play_motion` 连发时，池里多线程并发，到达顺序不确定；对顺序敏感的场景必须改用单线程队列（`QThreadPool.setMaxThreadCount(1)` 的专用 `QThreadPool` 实例）。另外它把 `fn is None` 当作 no-op（`main.py:974-975`），所以调用点敢写 `getattr(obj, "method", None)`。
- **照抄**（3 行版本，零依赖）。

### 3.5 命令 → 资源名映射（标签解析的消费端） ★★★☆☆

- **可复用的是什么**：LLM 输出的语义命令（`expr`/`motion`）与美术资源实际名字之间加一层配置映射，避免改 prompt 就得改代码。`_map_name` 只用 5 行，是「配置驱动的资源别名」的标准写法。
- **源位置**：`main.py:860-873`、`main.py:875-879`；映射表读 `cfg.persona["emotion_map"]` / `cfg.persona["motion_map"]`。
- **依赖**：`cfg.persona`（dict）。
- **`reply.commands` 的契约（跨模块，最重要）**：
  - 形态：**可迭代的二元组序列**，`for kind, name in commands`（`main.py:864`）——这是唯一的解包证据。元素是 tuple 还是 list、外层是 list 还是其他序列，**未确认**（三元组会当场 `ValueError`）。
  - `kind` 取值域：**`"expr"` 与 `"motion"`**。这是从 `main.py:866-871` 的两个 `if/elif` 分支反推的；没有第三个分支，也没有 else。
  - `name` 取值来源：**`cfg.persona["emotion_map"]` / `cfg.persona["motion_map"]` 的键**。依据是 `_map_name`（875-879）的 `mapping.get(name, name)`——`name` 被当作映射表的键去查。
  - 由此推出两条隐含契约：①**LLM 侧必须输出映射表里登记过的键名**（否则只是原样透传，可能打到不存在的资源名）；②**未登记的 name 会原样发给 Live2D 服务**，因此本地服务端必须能容忍未知名字而不报错（`_apply_live2d_commands` 的 try/except 只兜住客户端异常）。
  - 反向证据：`main.py:792`、`814` 在「思考中播放待机动作」时**直接**调 `play_motion("idle")`，**未经 `_map_name`**——说明 `"idle"` 是 Live2D 模型侧真实存在的动作 ID，且「待机动作名 = idle」在 main.py 里是硬编码约定。
- **注意**：`_apply_live2d_commands` 里每个命令各自 try/except（`main.py:865-873`），一条失败不影响后续 —— 这个粒度值得保留。未知 kind（除 expr/motion 外）被**静默忽略**，没有 else 分支，调试时容易误以为命令丢失。
- **直接照抄**。

### 3.6 配置热加载：「运行时 dict」+「落盘 overrides」双层 ★★★★☆

- **可复用的是什么**：`cfg.set_runtime(section, key, value)` 改内存 + `cfg.save_overrides({...})` 只把用户改过的项写进 `data/settings_overrides.json`，**`config.yaml` 保持原样（注释不丢）**，下次启动 overrides 覆盖 yaml。这是「带注释的默认配置 + 用户增量修改」的经典解法，任何 YAML/TOML 配置项目都能用。
- **源位置**：`main.py:450-451`、`1048`、`1085-1086`、`1114`、`1120`、`1137-1138`、`1152-1153`、`1190-1191`、`1209-1211`、`1241-1244`、`1252-1254`、`1310-1311`、`1403`、`1406-1408`、`1419-1428`、`1437-1438`、`1453`、`1462`、`1473`、`1515-1548`、`560-562`。
- **依赖**：`cfg.set_runtime` / `cfg.save_overrides` / `cfg.llm|tts|gui|memory|live2d|heart|persona` 属性字典（`agent/config.py`，未读）。`save_overrides` 返回写入路径（`main.py:1548` 用作提示文案）。
- **注意**：**必须成对调用**，漏掉 `save_overrides` 就是「本次会话生效、重启丢失」；漏掉 `set_runtime` 就是「重启生效、当前不生效」。这两类 bug 在本文件里确实存在漏配对（例如 `on_context_compression` 只 `set_runtime` 不保存，`main.py:1209-1213`）。`on_save_settings`（1508-1563）是唯一一处批量快照所有 UI 控件的落盘入口，它**同时**写了 `vision_mcp/config.json` 这个独立文件（1553-1560），形成第二处配置写点。
- **照抄思路，重写实现**（`set_runtime` 的合并语义要看 `agent/config.py`，本次未读）。

### 3.7 启动进度回调（可降级为 no-op） ★★★☆☆

- **可复用的是什么**：把「启动阶段汇报」抽象成一个 `progress(value: int, text: str)` 回调，splash 存在就传 `splash.set_progress`，不存在就传 `None` → 内部替换为 `lambda v, t: None`，再用 `_stage()` 包一层 try/except 吞异常。于是业务代码里可以无脑写 `_stage(48, "...")`。
- **源位置**：`main.py:352-358`（回调 + `_stage` 定义）、`main.py:331-332`（`progress=None` 参数）、`main.py:2095-2097`（传入 `splash.set_progress if splash else None`）、调用点 360-432 共 11 处。
- **依赖**：`gui/splash.py` 的 `SplashWindow.set_progress(value, text)`（未读）。
- **注意**：进度值（8/16/24/…) 是**硬编码的审美值**，与实际耗时无关（24 那一档甚至没有工作，见 1.3）。`_stage` 吞掉所有异常这点是对的，但意味着 splash 崩了也不会有人发现。
- **直接照抄**。

### 3.8 退出编排：后台停服务 + 硬兜底 ★★★★☆

- **可复用的是什么**：三件事的组合拳 ——（a）退出时的清理全部丢后台（`ShutdownWorker`），GUI 立刻响应；（b）`QTimer.singleShot(12000, self.app.quit)` 兜底，清理卡死也能退出；（c）`aboutToQuit` 里 `pool.clear()` + `pool.waitForDone(3000)` + 关库，并**用一个 `_full_quit` 标志避免重复停止服务**（重复停会跑 `tasklist` + PowerShell，白等 8~12 秒，注释在 `main.py:2115-2117`）。
- **源位置**：`main.py:2031-2045`（`on_quit_requested`）、`main.py:194-220`（`ShutdownWorker`）、`main.py:2103-2123`（`_on_quit` + connect）、`main.py:339`（`_full_quit` 初始化）。
- **依赖**：`services.stop_heart/stop_gpt_sovits`、`live2d.shutdown`、`memory.close`、`app.quit`。
- **注意**：`ShutdownWorker` 里每步独立 try/except 是必需的（`main.py:204-216`），否则前一个服务停失败会导致 Live2D 残留进程。`waitForDone(3000)` 用的是**全局池**，如果别的模块也往全局池丢长任务，这 3 秒会被白等。
- **照抄骨架**，服务名换成自己的。

### 3.9 日志：`setup_logging` + `console_logs` 多源聚合 ★★★★☆

- **可复用的是什么**：两件事。①`setup_logging`（`main.py:62-72`）：FileHandler 固定 `encoding="utf-8"`（Windows 必加），StreamHandler **只在 `sys.stdout is not None` 时添加** —— 这一行就是 `pythonw.exe` 无控制台启动不崩的关键。②`utils/console_logs.py` 整体：把 5 个来源（`SOURCES`，7-13 行）按时间戳归并成一个视图。
- **逐条可复用点**：`_tail_lines`(16-29) 先 `stat` 取大小、`seek(max(0, size - min(size, 1_000_000)))` 只读末尾 ≤1MB、再 `decode("utf-8", errors="replace")`、取 `lines[-max_lines:]`，解决「日志几十 MB 全量读入卡死 GUI」；`_ts_prefix`(32-39) 用 `strptime(line[:19], "%Y-%m-%d %H:%M:%S")` 解析行首时间，失败返回 `None`，配合 `datetime.min` 兜底排序（73、75 行 `e[0] or datetime.min`）；过滤(57-61) 是子串 + `f"[{level}]"`/`f" {level} "` 双形态；展示(76-77) 在「全部」模式给每行加 `[来源] ` 前缀。
- **依赖**：纯标准库（`datetime`、`pathlib`）+ 调用方传入 `root: Path`；`SOURCES` 的键与 GUI 下拉文案一致（`"全部"` 是魔法字符串）。
- **注意**：`basicConfig` **只在 root 还没有 handler 时生效**，先被第三方库配置过就静默失效（详见 5.4）。`console_logs:67` 的 `if source == "全部" and not entries and lines` 判断的是**全局** `entries`，前一来源已有内容时后一个空来源拿不到占位。`console_logs:54,64` 的 `parsed` 是死变量；从字节中间 `seek` 可能切在多字节 UTF-8 字符中间（被 `replace` 兜住）；只支持「行首 19 字符时间戳」一种格式，与 `%(asctime)s` 强耦合。main.py 日志文件不在 `SOURCES` 里（无 "main" 键），`cfg.log_file` 是否与之同文件**未确认**。
- **照抄**（`console_logs.py` 78 行可整文件搬走，只需改 `SOURCES`）。

### 3.10 音频写出 / 播放双后端 ★★★☆☆

- **可复用的是什么**：`samples_to_wav`（`audio.py:13-25`）把 float32[-1,1] 或 int16 统一写成 16bit 单声道 PCM WAV；`play_wav`(28-43) 在 Windows 上用 `winsound.PlaySound(SND_FILENAME | SND_NODEFAULT)`（零依赖、阻塞），其它平台降级 `sounddevice` + `wave`；`play_samples`(46-56) 走临时文件 + `finally` 清理。
- **依赖**：`numpy`、`wave`；非 Windows 需 `sounddevice`。
- **注意**：`play_wav` 是**阻塞**的，必须放 worker 线程（`TTSWorker`，`main.py:104-122` 即此用途）。`play_samples` 的临时文件名写死为 `neuro_tts_tmp.wav`（48 行，还带着上一个项目的 `neuro_*` 前缀），多线程/多实例并发会互相覆盖。`samples_to_wav` 假定**单声道**（`setnchannels(1)` 是常量），传二维数组会得到错误时长。`play_wav` 拿不到播放完成回调，只能靠 `speak()` 阻塞时长反推 —— 这也是口型只能用模拟包络的原因之一。
- **照抄**（顺手把临时文件名参数化）。

### 3.11 防重入阀（busy flag） ★★★★☆

- **可复用的是什么**：所有可能被连点/被定时器重入的操作，都用「一个 bool + 入口 early-return + 回调复位」的极简阀，不加锁，全靠「读写在 GUI 线程」这一约束成立。
- **源位置**：`_service_status_busy`(341, 620-626, 629, 639)、`_tts_probe_busy`(342, 644-657, 660, 681)、`_tts_busy`(343, 951, 957-959, 1019, 1032)、`_service_action_busy`(348, 1926-1934, 1938, 1963)、`_fetch_models_busy`(350, 1263-1266, 1275, 1302)、`_quitting`(347, 2033-2035)。
- **注意**：**复位路径必须穷尽**。`on_service_action`(1924) 依赖 worker 的 `except` 发 error 信号复位（190-191）；若信号对象已销毁，阀会永久卡死，重复执行类操作建议加超时复位。

### 3.12 无控制台启动 + UTF-8 + 依赖自检（bat 层） ★★★☆☆

- **可复用的是什么**：`run.bat` 28 行就是一个 PySide6 启动器模板：UTF-8 → `cd /d "%~dp0"` → venv 自检并 `call setup_venv.bat` → 优先 `pythonw.exe` 并降级 → `%*` 透传 → 立刻 `exit /b 0`；配套 `run_console.bat`（前台调试）与 `run_chat_only.bat`（单参数薄封装）。
- **注意**：`chcp 65001` 只影响 bat 自己的控制台；`pythonw` 下没有 stdout，`main.py:66` 那个 `if` 是必要配套，缺了直接 `AttributeError`。`start ""` 让进程脱离控制台，用户看不到任何 traceback —— 必须有文件日志兜底。

---

## 4. 关键契约（main.py ↔ gui/ ↔ agent/）

> 以下全部以 **main.py 侧的调用点**为准（这是本次唯一读到的一侧）。`gui/chat_window.py`、`agent/core.py` 里的 `Signal` 声明与函数实现**未读，未确认**。

### 4.1 gui/ → main.py：`_wire()` 里连接的 56 个信号（`main.py:462-523`）

槽函数签名（从 `@Slot` 装饰器与 def 签名读出的**唯一权威**）。只列"非平凡"的 12 条，其余约 40 条全部是 `xxx_requested` → `on_xxx` 一一对应、参数为单个 `str`/`int`/`bool` 或空，命名规则见 `main.py:462-523`：

| 信号（`chat.xxx_requested`） | main 侧槽 | 签名 / 取值域 |
|---|---|---|
| `media_send_requested` | `on_media_send` | `(object, str)` ← 路径列表 + 文本 |
| `live2d_window_requested` | `on_live2d_window` | `(str)`，`show/hide/toggle`（`1497`） |
| `service_action_requested` | `on_service_action` | `(str)`，`start_heart/stop_heart/start_gsv/stop_gsv`（`178-188`） |
| `avatar_requested` | `on_avatar` | `(str role, str path)`，role ∈ `nori/agent` 转 `on_agent_avatar`（`1132-1134`） |
| `llm_config_requested` | `on_llm_config` | `(str api_key, str base_url, str model)` |
| `llm_model_rename_requested` | `on_llm_model_rename` | `(str old, str new)` |
| `context_compression_requested` | `on_context_compression` | `(str mode, int window, int max_chars)` |
| `vision_config_requested` | `on_vision_config` | `(str, str, str, int)` |
| `memory_auto_review_requested` | `on_memory_auto_review` | `(bool, int)` |
| `memory_refresh_requested` | `on_memory_refresh` | `(str query, str 类型)` |
| `memory_add_requested` / `memory_update_requested` | `on_memory_add` / `on_memory_update` | `(str, str, float)` / `(int, str, str, float)` |
| `mcp_add_requested` | `on_mcp_add` | `(str name, str transport, str url, str command, str args)` |

其余需要精确签名时，直接看 `_wire()` 的连接行（`462-523`）与对应 `@Slot` 即可；`persona_*` 是 `(str name, str text)` 或 `(str name)`，`conversation_*` 是 `(int conv_id)` 或 `(int, str)`，`memory_rule_*` / `mcp_toggle` / `skill_*` 都是 `(int)` 或 `(str)`。

main → gui 的**反向**调用全部是方法调用（无信号）：`append_system(str)`、`append_assistant(str)`、`clear_chat()`、`set_chat_history(list)`、`set_input_enabled(bool)`、`set_thinking(bool)`、`set_status(str)`、`set_service_status(str, bool)`、`set_tts_voices(list, str)`、`set_avatar(str role, str path)`、`set_user_name(str)`、`set_agent_name(str)`、`set_persona_list(list, str)`、`set_persona_text(str, str, str)`、`set_history_personas(list, str)`、`set_conversations(list, int)`、`set_current_conversation_label(str)`、`set_memories(list)`、`set_rules(list)`、`set_mcp_servers(list)`、`set_skills(list)`、`set_live2d_models(list, str)`、`set_voice_export_dir(str)`、`set_current_settings(**5)`、`apply_font_size(int)`、`apply_chat_font_size(int)`、`add_custom_model(str)`、`remove_custom_model(str)`、`_refresh_console()`。

**main.py 直接读写的 gui 内部控件/私有属性（强耦合，见 5.1）**：`speed_slider`、`scale_slider`、`scale_label`、`backend_combo`、`api_key_edit`、`api_base_edit`、`api_model_combo`、`search_api_edit`、`top_check`、`font_combo`、`chat_font_combo`、`compression_mode_combo`、`compression_window_spin`、`compression_chars_spin`、`mem_auto_review_check`、`mem_review_spin`、`mem_search`、`mem_type_combo`、`memory_table`、`vision_api_edit`、`vision_base_edit`、`vision_model_combo`、`vision_port_spin`、`_user_name`、`_user_avatar`、`_agent_name`。
**信号总规则**：56 条连接全是「名字即协议」（`xxx_requested` → `on_xxx`），参数顺序即 `@Slot` 声明，没有 request/response 关联 id；因此同一类操作天然串行、不允许并发（并发由 3.11 的 busy 阀挡住）。

### 4.2 main.py → agent/ 及其它模块：契约总表

| 被调方 | 方法 / 属性（签名） | 行号 | 返回 / 用途 |
|---|---|---|---|
| `AgentCore` | `handle_user_text(text, image_paths=[...])` | 92 | 必须有 `.text: str` 和 `.commands`（可迭代的 `(kind, name)`） |
| | `.current_conversation_id`（可写） | 1571, 1717, 1730 | int |
| | `apply_feedback(float)` / `export_training_data(path)` / `consolidate_now()` | 889, 896, 902/928 | 前两个返回值被直接展示 |
| `MemoryStore` | `stats()` → `{messages,memories,rules}` | 733-735 | dict |
| | `ensure_main_conversation(persona)` → int | 1569 | 「每个自有人格一个主会话」 |
| | `get_recent_messages(200, persona=, conversation_id=)` / `get_conversation(id)` / `list_conversations(persona)` | 1615, 1611, 1622 | 注意 1590-1592 的注释：**写库用生效人格、读库用会话人格** |
| | `create_conversation/rename_conversation/delete_conversation` | 1727, 1740, 1752 | bool（主会话受保护） |
| | `add_memory/update_memory/delete_memory/list_memories/list_rules/set_rule_enabled/delete_rule/merge_similar_memories/close` | 1786-1846, 924, 2111 | — |
| `ServiceManager` | `start_heart(skip_live2d=bool)` / `stop_heart()` / `start_gpt_sovits()` / `stop_gpt_sovits()` | 179-185, 607-615, 205-211 | 前四个返回 bool |
| | `status()` → `{"heart": bool, "gpt_sovits": bool}` | 291, 633-634 | dict |
| | `gsv_is_running()` | 1346 | bool |
| `Live2DNativeClient` | `ensure_running()` / `control_window(action)` / `show_window()` / `shutdown()` | 139, 143, 532, 214 | bool / — |
| | `set_expression(name)` / `play_motion(name)` / `set_speaking(bool)` / `audio_level(float)` / `set_scale(float)` | 868, 871, 962, 275, 1465 | — |
| | `list_models()` → `{"models": [...], "current": str}` / `get_state()` → `{"scale": float}` / `switch_model(path)` / `import_model(source)` → list[str] | 1973-1984, 2004, 2017 | — |
| | `.base_url` | 535 | str |
| TTS 后端 | `.name` / `.speak(text)` / `.available()` / `.set_speed(float)`（有 `hasattr` 保护） | 384, 113, 315, 1454 | — |
| `Brain` | `.reload()` | 1249, 1405, 1425 | 配置改完必须调，否则模型不换 |
| `MCPManager` | `list_servers()` / `list_skills()` / `add_server(5 参数)` / `import_server_config(path)` / `get_server(name)` / `set_server_enabled(name, bool)` / `remove_server(name)` / `import_skill(path)` / `set_skill_enabled` / `remove_skill` | 715, 1852-1920 | — |
| `BaiduSearchClient` | `.enabled` | 727 | bool |
| `ChatWindow` | `append_system` / `append_assistant` / `set_*` 全家族 | 553-1968 | 面板回填；完整清单见 4.1 末段 |
| `agent.persona` | `save_persona_text` / `create_persona` / `delete_persona` / `set_active_persona` / `list_personas` / `load_persona_meta` / `save_persona_meta` / `persona_path` | 1567-1697 | 人格 CRUD 与切换 |
| `utils.tts_voices` | `apply_voice_to_config` / `list_voices` / `import_voice` / `export_voice` | 1345-1384 | 语音包 CRUD |
| `utils.stickers` | `copy_to_chat_media(root, path)` | 841 | → Path 或 None |
| `cfg` | `set_runtime(section, key, value)` / `save_overrides(dict) -> str` | 全篇 30+ 处 | 改内存 / 落盘（3.6） |
| 文件系统 | 写 `vision_mcp/config.json`、`data/avatars/*`、`data/chat_media/*` | 1172-1176, 1332, 1553 | 头像 / 图片 / 视觉配置 |
| `QThreadPool` | `clear()` / `waitForDone(3000)` | 2106-2107 | 关库前排空（2.4d） |
| `openai` | `OpenAI(api_key, base_url, timeout).models.list()` | 235-238 | 唯一直接 openai 用法 |

### 4.3 配置对象 `cfg` 的契约

`cfg.root` / `cfg.data_dir` / `cfg.db_path` / `cfg.log_file` / `cfg.api_key` / `cfg.base_url` / `cfg.model` / `cfg.is_local_llm`（`main.py:919` 用 `getattr(..., False)` 保护）/ 各分节 dict `cfg.llm` `cfg.tts` `cfg.gui` `cfg.memory` `cfg.live2d` `cfg.heart` `cfg.persona` / 方法 `set_runtime(section, key, value)`、`save_overrides(dict) -> str`。

---

## 5. 坑（按严重度排序）

### 5.1 强耦合：main.py 直接读写 `chat` 的 23 个控件与 3 个私有字段

`_refresh_live2d_models` 直接 `self.chat.scale_slider.blockSignals(True)` + `setValue` + `scale_label.setText(...)`（1981-1984）；`_on_fetch_models_done` 直接操作 `api_model_combo`（1280-1295）；`on_save_settings`（1510-1546）从 21 个控件/字段读值拼 overrides；`_refresh_tts_voices` 反向读 `cfg.tts.gpt_sovits.ref_audio_path` 再**靠路径层级猜**语音包名（596-599：`p.parent.parent.name == "voices"`）。控件一改名，main.py 就静默出错。

### 5.2 阈值注释与实现不一致（真实 bug 级）

`main.py:684` 注释写「失败这么多轮（**每轮 5 秒**）后启用兜底」，`_TTS_FALLBACK_AFTER = 18`（685）按注释应是 ~90 秒；但探测定时器是 `start(15 * 1000)`（425），即**每轮 15 秒**，18 轮 ≈ **270 秒**。这 4.5 分钟里用户只看到「冷启动中，消息将排队」（738）而没有任何声音。何况 `_maybe_activate_fallback` 只在 `_tts_pending` 非空时才累加（693-694），没说过话就永远不会降级。

### 5.3 「一律后台化」的规则没有贯彻到底（UI 卡顿风险）

`_live2d_call` 的 docstring 说「Live2D 的 HTTP 调用**一律**丢后台」（973），但下列是**同步直调**：`set_speaking`（962、1023、1036）、`on_scale` 的 `set_scale`（1465）、`_refresh_live2d_models` 的 `list_models()`/`get_state()`（1973、1979）、`switch_model`（2004）、`import_model`+`switch_model`（2017、2023）。服务层更明显：`on_tts_voice_switch`（1346-1350）在 **GUI 线程**里跑 `gsv_is_running()` → `stop_gpt_sovits()` → `start_gpt_sovits()`，而 `on_service_action` 的同类操作被明确放后台（1925 注释：「tasklist/PowerShell 单次最长 8~12 秒」）；`1095-1096` 也承认 `gsv_is_running()` 会同步删过期 pid 文件。

### 5.4 `logging.basicConfig` 的幂等陷阱

`setup_logging`（62-72）用 `basicConfig(handlers=...)`：只要 root 已有 handler（任何 import 期先调用过），**这次配置完全不起作用**，日志丢失或格式不符，且不报错。复用时应显式清空再 `addHandler`。

### 5.5 硬编码

- 路径：`gui/assets/nori_icon.png`(2081)、`data/avatars`(1147/1172)、`data/chat_media` 与 `data/stickers`(822-823)、`data/training.jsonl`(896)、`data/logs`(`console_logs.py:44`)、`vision_mcp/config.json`(1332/1553)；下载目录用 `Path.home()/"Downloads"`（1378-1379），被重定向过的系统会错。
- URL / 模型 ID：`https://api.deepseek.com`(1230)、`deepseek-v4-flash`(1231/1422)、`https://ark.cn-beijing.volces.com/api/v3` 与 `doubao-seed-2-1-pro-260628`(1327-1328)。
- 常量：AppUserModelID(2078)、口型 `interval=0.06`(257)、队列上限 8(946)、重试 5000ms(1003)、探测 15000ms(425)、状态 3000ms(430)、退出兜底 12000ms(2045)、`waitForDone(3000)`(2107)、图片 20MB/4 张(837/850)、首启 600ms(435)、切模型后 5000/1500ms(2006/2025)。

### 5.6 线程 / UI 安全

- `self.chat.*` 信号默认 `AutoConnection`：跨线程 emit 会排队到 GUI 线程，worker → 槽因此安全（整套设计的前提）。但 `Live2DCallWorker`(149-163) 是 fire-and-forget，异常只 emit 到没人连的 `signals.error` —— 静默失败。
- `LipSyncPusher`(250-278) 在 GUI 线程 `start()/stop()`，内部只碰 `client.audio_level`，安全；但 `_lip_pusher` 赋值与线程读 `_stop_event` 之间无锁，靠 GIL 侥幸。
- `_connect_live2d_async`(525-541) 在纯 Python 线程里写 `self.live2d_ready`（529/539），随后在 GUI 线程读（583/791/980…）：**无锁跨线程共享 bool**，无内存屏障保证。
- `_memory_review_in_thread`(913-915) 每次触发都 new Thread，**没有防御阀**（对比 3.11）：手动「立即回顾」连点会并发出多个 `consolidate_now()`。
- `on_quit_requested`(2031-2045) 设 `_full_quit` 后丢 `ShutdownWorker`，同时 `singleShot(12000, app.quit)`；worker 若超 12 秒完成，`_on_quit` 已 `memory.close()` —— 靠 `ShutdownWorker` 不碰 db 才没出事。

### 5.7 数据一致性陷阱（文档价值高）

`_switch_active_persona` 的 docstring（1590-1592）记录了一个真实踩过的坑：**写库用「生效人格」、读库用「会话人格」，两者不一致时消息写进去却读不出来**，表现为「聊天记录消失」，所以 `on_conversation_open`（1714-1715）必须先切人格再加载。任何「多身份 + 多会话 + 单库」的项目都会遇到同一个问题，这段注释值得原样搬进设计文档。

### 5.8 其它 hack / 残留

- `_stage(24, "正在检查视觉 MCP…")`（365）是假进度；死代码有 `_consolidate_in_thread`(901)、`self.pet` 五处分支(784/1468/1474/2049)、`toggle_chat`(931)。
- 异常处理不一致：约 40 个设置槽用 `append_system(f"⚠ ...：{e}")`，但 `_maybe_first_run_wizard`(458-459)、`_connect_live2d_async`(539-541) 只 `logging.warning`，用户看不到 —— 诊断困难。
- `_llm_provider_from_base`(1215-1224) 已存在，`on_llm_config`(1232-1240) 又内联复制了同样四行 if/elif，两处必然不同步。
- `run.bat:24` 的 `start ""` 让任何启动期异常都不可见（无控制台、日志可能还没配好），排查只能靠 `run_console.bat`。

---

## 6. 未确认清单（不要当成结论使用）

1. **单实例锁**：grep `QLockFile` / `QSharedMemory` / `QLocalServer` / 「单实例」在本文件**均无匹配**，`main()`(2057-2128) 里也没有；是否在 `agent/` 或 GUI 层实现**未确认**，连点两次 `run.bat` 是否会双开并抢同一个 SQLite / Live2D 端口也**未确认**。
2. **LLM 调用封装、多轮 tool-call 循环、流式输出、`[expr:]` 解析**：见 3.0，全部在 `agent/`，**未读、未确认**。
3. **后台子进程的真正启停细节**：`ServiceManager.start_heart/start_gpt_sovits/status` 的实现（是否 `CREATE_NO_WINDOW`、pid 文件位置、超时）在 `agent/services.py`，**未确认**；main.py 只提供「放后台线程 + bool 回传」的外壳。
4. **`cfg.log_file` 与 `console_logs.SOURCES` 的关系**：`SOURCES` 里没有 main 条目（只有 agent/heart/gpt_sovits/live2d/train），main 日志落到哪个文件名**未确认**。
5. **`gui/chat_window.py` 里信号的真实 `Signal(...)` 类型**：本文 4.1 的签名来自 main.py 侧 `@Slot` 声明，声明侧**未读**。
6. **`reply.commands` 的确切类型**：只有 `main.py:864` 的 `for kind, name in commands` 作为证据，元素是 tuple 还是 list **未确认**（三元组会当场 `ValueError`）。
7. **`_on_reply` 的线程归属**：`SendWorker.signals.result.connect(self._on_reply)`(794) 未指定连接类型，依赖 controller 构造于 GUI 线程（2095，**已确认**）；若有人搬到非 GUI 线程构造会立刻破。
8. **`pythonw.exe` 下 `logging.FileHandler` 的权限**：装到 `C:\Program Files` 之类只读目录时行为**未确认**。

## 7. 给下一个会话的最小可移植骨架

按此顺序搬：①`WorkerSignals` + `Live2DCallWorker`（76-78、149-163）原封不动，30 行零业务耦合；②`LipSyncPusher`（250-278）换成自己的 `client.push_param()`；③`utils/console_logs.py` 整文件只改 `SOURCES`；④`speak` 系列（940-1042）+ `_check_preferred_tts`(642-657) + `_maybe_activate_fallback`(687-710) 的状态机照抄结构、换后端探测；⑤退出三段式照抄（2031-2045 + 194-220 + 2103-2121）；⑥配置双层、`_stage` 回调、`_busy` 阀照抄模式。

**不要搬**：40+ 个 `on_*` 设置槽、`on_save_settings`(1508-1563)、`_wire`(462-523) —— 与 `ChatWindow` 的 23 个控件逐字绑定，换项目等于重写。**搬走前先修**：5.2、5.3、5.4。
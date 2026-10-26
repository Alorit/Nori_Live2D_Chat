# 服务层与外部集成：可复用的适配器

> 分析对象：`D:\Nori_Live2D_Chat`（Nori，PySide6 + DeepSeek + Live2D + 本地 TTS）。只读分析，行号为当前副本实测值。
> **行号校正**：与任务描述不符，实测 `agent/core.py` **376 行**（非 341）、`agent/services.py` **396 行**（非 344）、`agent/mcp_manager.py` **267 行**（非 239）、`agent/live2d_native.py` **200 行**（非 171）。其余：`brain.py` 171、`config.py` 178、`search.py` 98、`tts/base.py` 13、`tts/factory.py` 86、`tts/gpt_sovits_tts.py` 84、`tts/system_tts.py` 47、`utils/tts_voices.py` 255、`utils/console_logs.py` 78、`vision_mcp/server.py` 211。

> **主会话交叉核对（补记，2026-10-20）** —— 下列 §9 的"未确认"项已在主会话里查到答案，**以本块为准**：
> - **#21 服务端路由 → 已确认**。服务端源码不在本仓库，在 `D:\Nori-Desktop-Pet-Fork\app\desktop\Nori.Desktop\Live2D\PetControlServer.cs`（330 行，`HttpListener`，`const Prefix = "http://127.0.0.1:47835/"`），10 个端点与 JSON 字段的权威契约见 `03-live2d-bridge.md`。此前"DLL 里找不到路由字面量"是因为路由是 `switch (path)` 的字面量比较，且发布 DLL 用了不同的字符串堆。
> - **#24 `fallback_on_error` → 已确认是死配置**。`main.py:392` 置 `self.pet = None`，`PetWindow` / `Live2DView` / `FallbackPet` 全仓库无第二个 import；`:1463-1469` 的 `self.pet.set_scale` 是残留分支。原生模式下桌宠起不来 = 只有聊天窗口、无报错。
> - **#25 `/mouth` 的 level → 已确认是线性直写**：`PetRuntime.SetMouthOpen`（`PetRuntime.cs:913`）→ `LipSyncBehavior.SetMouthOpen` 做 `Clamp(0,1)`（`LipSyncBehavior.cs:21`）→ 直接 `SetParameterValue("ParamMouthOpenY", value)`（`:35`）；非说话时另一分支把参数归 0（`:44`），说话时还会与动作值混合（`:52-55`）。
> - **#23 `--pet-only` → 仅部分确认**：由 `Diagnostics/StartupOptions.cs` 解析（`StartupOptions(bool SafeMode, bool PetOnly, ...)`），具体行为细节仍未确认。
> - **#10 补正**：计数器被 **两个**定时器共同递增——15s 探测定时器（`main.py:425`）与消息排队时的 5s 重试定时器（`main.py:1003` → `:1013`）。两者都在跑时约 **90s** 触发兜底，只有探测定时器在跑时约 **270s**。所以"约 90 秒"只在其一条件下成立。

---

## 1. 分层与装配

| 层 | 文件 | 职责 | 状态 |
|---|---|---|---|
| 编排 | `agent/core.py` | 单轮流水：搜索增强 → 视觉增强 → 组 messages → LLM+function calling 循环 → 写记忆 → 后台反思整合 | `turn_count` / `last_reply` / `current_conversation_id` |
| 进程服务 | `agent/services.py` | `pythonw.exe` 无窗口启停 Heart / GPT-SoVITS，PID 校验 + 孤儿清理 | `heart_proc` / `gsv_proc` / `gsv_external` |
| 外部适配 | `brain.py`、`search.py`、`mcp_manager.py`、`live2d_native.py`、`tts/*` | 每个外部系统一个薄客户端，统一「失败降级返回」 | 少量 |
| 工具 | `utils/tts_voices.py`、`utils/console_logs.py` | 纯函数式文件操作 | 无 |

设计要点：**编排层不 new 任何外部客户端**，全部由 `main.py` 注入；`AgentCore` 的两个可选依赖可为 `None`（`core.py:44-45`），因此无 MCP / 无搜索也能跑。

### 1.1 `AgentCore`

`core.py:36` 定义类，`core.py:39-50` 构造签名：`__init__(self, cfg, memory: MemoryStore, brain: Brain, search=None, mcp_manager=None)`。内部自建 `ContextCompressor(brain, memory, cfg)`（`core.py:49`），无需外部装配。公开入口只有 `handle_user_text(user_text, image_paths=None) -> AgentReply`（`core.py:172-289`）。

`AgentReply` 在 `brain.py:18-24`：`text / commands / raw / user_msg_id / assistant_msg_id`，`commands: list[tuple[str, str]]`，`kind ∈ {"expr","motion"}`。

`handle_user_text` 流水线（可照抄）：

1. `_augment_with_search`（`core.py:183`，定义 154-170）
2. `_augment_with_vision`（`core.py:184`，定义 107-152）
3. `build_system_prompt`（190）→ 取历史（198-199）→ 可选压缩（206-207）
4. 追加 system：Skills 指令（211-219）、Live2D 动作标签指令（221-234，仅 `live2d.controller == "native"`）
5. `build_tool_schemas()` → `brain.chat_message(messages, tools)`（238-246）
6. tool_call 循环，**最多 5 轮**（247），结果截断 **4000** 字符（265-266）
7. `parse_commands(raw)`（269）→ 写记忆（276-281）→ `_maybe_consolidate_async()`（288）

### 1.2 `ServiceManager`

`services.py:151` 定义类，`services.py:152-159` 仅收 `cfg`（用 `cfg.root` / `cfg.data_dir` / `cfg.tts`），构造时 `data/logs/` 就 `mkdir`（155-156）。

| 能力 | 方法（行号） |
|---|---|
| Heart | `start_heart(skip_live2d=False)` 183-208、`stop_heart()` 210-236、`heart_is_running()` 166-181、PID 文件 `data/heart.pid` 162-164 |
| GPT-SoVITS | `start_gpt_sovits()` 324-360、`stop_gpt_sovits()` 362-389、`gsv_is_running()` 252-269、PID 文件 `data/gpt_sovits.pid` 239-241 |
| 汇总 | `status() -> {"heart": bool, "gpt_sovits": bool}` 392-396 |

三个可复用实现细节：

- **PID 验明正身**：`_pid_is_heart`/`_pid_is_gsv`（111-122）用 PowerShell `Get-CimInstance Win32_Process` 取命令行（`_windows_command_line` 80-92），确认含 `heart.py` / `gpt_sovits_service.py` 才敢 kill。
- **孤儿兜底 + 以终态为准**：`_find_pids_by_command`（95-108）用 CIM `-like '*heart.py*'` 全表扫（pid 文件会丢，227-230、382-384）；kill 后循环 30×0.1s 复查（138-142、232-236、385-389），不信 `taskkill` 返回码。

`gsv_expected_to_start(cfg)`（21-39）是给 GUI 的布尔判据：`auto_start` 且 `runtime_dir` 下有 `api_v2.py` + `runtime/pythonw.exe|python.exe`、参考音频文件存在。它决定冷启动期是否允许用系统音色顶替。

### 1.3 装配点（`main.py`，作调用关系证据）

入口 `main.py:2057-2128`，`load_config(args.config)` 在 `main.py:2066`。`AppController.__init__`（331-435）顺序：

| 顺序 | 代码 | 说明 |
|---|---|---|
| 记忆 | `main.py:362` `MemoryStore(cfg.db_path, cfg.memory)` | SQLite |
| 大脑 | `main.py:364` `Brain(cfg)` | §3 |
| 搜索 | `main.py:367` `BaiduSearchClient(cfg)` | §6 |
| MCP | `main.py:368` `MCPManager(cfg.root)` | 只吃 `root: Path` |
| 核心 | `main.py:369-371` `AgentCore(cfg, memory, brain, search=..., mcp_manager=...)` | 注入 |
| 服务 | `main.py:374` `ServiceManager(cfg)` | §1.2 |
| TTS | `main.py:383` `create_tts(cfg, allow_fallback=not gsv_expected_to_start(cfg))` | §4 |
| Live2D | `main.py:398` `Live2DNativeClient(cfg)` | 仅当 `live2d.enabled` |

线程模型（不卡界面的关键）：

| 组件 | 行号 | 作用 |
|---|---|---|
| `SendWorker(QRunnable)` | 81 | `core.handle_user_text` |
| `TTSWorker(QRunnable)` | 104 | 阻塞式 `tts.speak()` |
| `Live2DWindowWorker` | 125-146 | `ensure_running()`（忙等 30s） |
| `Live2DCallWorker(fn, *args)` | 149-163 | 任意一次 Live2D HTTP |
| `LipSyncPusher(threading.Thread)` | 250-278 | 每 60ms 推 `audio_level` |
| `ServiceStatusWorker` | 281 | tasklist / HTTP 探测 |

统一入口 `_live2d_call(fn, *args)`（972-976）：所有 Live2D 调用一律进线程池；`fn is None` 直接返回（974）。

---

## 2. Live2D 原生桥接（重点）

### 2.1 架构

`agent/live2d_native.py` 不加载 Live2D 运行时，它只是 **.NET Avalonia 桌宠的 HTTP 客户端 + 进程看守**：

| 层 | 实体 | 说明 |
|---|---|---|
| Python 侧 | `Live2DNativeClient`（200 行，仅依赖 `requests` + `subprocess`） | JSON in / JSON out，端口 47835 |
| 进程 | `vendor/nori_desktop_pet/Nori.Desktop.exe --pet-only` | .NET + Avalonia + Live2DCubismCore，内含 Kestrel |

常量（`live2d_native.py:19-22`）：`DEFAULT_PORT = 47835`；`DEFAULT_APP_PATH = PROJECT_ROOT/"vendor"/"nori_desktop_pet"/"Nori.Desktop.exe"`；`DEFAULT_DOTNET_PATH = "dotnet"`。

注意 `DEFAULT_PORT` **定义但未使用**：`__init__` 里 `self.base_url = "http://127.0.0.1:47835"` 是硬编码（`live2d_native.py:32`）；config 只开放 `native_app_path` / `native_dotnet_path`（33-38）。**端口不可配置，是复用第一处要改的耦合点。**

### 2.2 端口与鉴权

- 固定 `127.0.0.1:47835`；`_request`（46-58）只发 `json=` 体，**无 token / 无自定义 header** → **无鉴权**：同机任意进程均可控制桌宠，反之客户端零配置即可接入。
- 服务端 `PetControlServer` 在编译产物 `Nori.Desktop.dll` 中：`PetControlServer` 仅出现在 UTF-8 元数据堆（15 次），而 `/state`、`/mouth` 等路由字面量在 `Nori.Core.dll` / `Nori.Desktop.dll` 的 UTF-16 字符串表里**均未找到** → **服务端路由注册方式未确认**。下文端点表以客户端实际发出的请求为准。

### 2.3 端点表（照抄客户端实现）

| 方法 | 路径 | 请求体 JSON | 响应用途 | 行号 |
|---|---|---|---|---|
| GET | `/state` | — | `r.json()`；健康检查 + `models` / `modelId` / `scale` | 100-101、60-65、122-128 |
| POST | `/motion` | `{"name": group}`（index 为 None） | `{"ok": bool}` | 103-109 |
| POST | `/motion` | `{"group": group, "index": int}` | `{"ok": bool}` | 103-109 |
| POST | `/expression` | `{"name": expression}` | `{"ok": bool}` | 111-115 |
| POST | `/model` | `{"modelId": model_id}` | `{"ok": bool, "modelId": ...}` | 117-120 |
| POST | `/model/import` | `{"path": path}` | `{"models": [...]}` | 130-133 |
| POST | `/mouth` | `{"level": float, "speaking": bool}` | 忽略响应体 | 135-141、151-157 |
| POST | `/scale` | `{"scale": float}`（夹紧 0.1~2.0） | 忽略 | 143-149 |
| POST | `/window` | `{"action": "show"\|"hide"\|"toggle"}` | 忽略 | 159-176 |

补充约定：

- `switch_model` 裁路径：`model_id = model_path.split("/")[0] if "/" in model_path else model_path`（118），传 `"nori/scene.model3.json"` 只发 `"nori"`。
- `list_models()`（122-128）返回 `{"models": [...], "current": state.get("modelId", "arg-nori")}`；`models` 缺失时回退常量表 `[{"path":"arg-nori","name":"arg-nori"}, {"path":"nori","name":"nori"}]`（40-43）。
- `/state` 完整响应 schema **未确认**，客户端只用到 `models` / `modelId` / `scale`（`main.py:1980`）。
- 超时：`_request` 缺省 **5.0s**（46-47），`available()` **1.0s**（60），`shutdown()` 复查 **0.5s**（200）。

### 2.4 进程启动 `ensure_running(wait_sec=30.0)`（67-97）

1. `available()` 通过即返回 `True`；
2. `Path(app_path).is_file()` 不成立 → warning + `False`（**不抛异常**）；
3. 拼命令：`.dll` 结尾用 `[dotnet_path, app_path, "--pet-only"]`，否则 `[app_path, "--pet-only"]`（77-80）；
4. `Popen(..., cwd=exe 目录, creationflags=CREATE_NO_WINDOW)`（81-85；Windows 值 `0x08000000`，74-76）；
5. 每 0.5s 轮询 `available()`，超时返回 `False`（90-97）。**忙等**，因此只能后台线程调用（`main.py:128-146` 注释明示）。

### 2.5 一次「说话」的调用时序

| # | 动作 | 请求 | 位置 |
|---|---|---|---|
| 1 | 收到用户输入，播待机动作 | `POST /motion {"name":"idle"}` | `main.py:791-792`、`813-814` |
| 2 | 回复落地，应用标签 | `expr` → `POST /expression {"name": emotion_map[name]}`；`motion` → `POST /motion {"name": motion_map[name]}` | `main.py:857`、860-873 |
| 3 | 进入说话态 | `POST /mouth {"level":0.0,"speaking":true}` | `main.py:960-964`、`live2d_native.py:138` |
| 4 | 启动口型线程 | 每 60ms `POST /mouth {"level":L,"speaking":L>0.01}` | `main.py:978-984`、250-278、`live2d_native.py:151-157` |
| 5 | 合成并阻塞播放 | `tts.speak()` 在线程池 | `main.py:966-969` |
| 6 | 结束/失败收尾 | `pusher.stop()` → `audio_level(0)` → `POST /mouth {"speaking":false}` | `main.py:986-991`、1021-1025、1034-1038 |

要点：

- **口型不是真波形，是模拟包络**：`level = 0.35 + 0.45*|sin(φ)| + 0.12*sin(2.7φ)`，`φ = counter*0.55`，夹紧 0..1（`main.py:270-273`）。接真实电平是最容易的提升点。
- 标签→真名映射在 **config**：`persona.emotion_map` / `persona.motion_map`（`config.yaml:58-74`），由 `_map_name` 应用（`main.py:875-879`）。标签清单硬编码在 system prompt 字符串（`core.py:226-232`）。
- 切换模型后 UI 等 5s 再刷列表（`main.py:2006`），导入后 1.5s（2025）——经验值。
- 退出：`ShutdownWorker`（`main.py:194-220`）→ `shutdown()` 用 `taskkill /PID <pid> /T /F`（190-194），末尾 `return not self.available(timeout=0.5)`（200）。

### 2.6 失败降级矩阵

| 失败点 | 行为 | 行号 |
|---|---|---|
| 连接被拒/超时 | `Live2DNativeError("Live2D 控制服务请求失败：…")` | 57-58 |
| HTTP ≥ 400 | `Live2DNativeError(f"HTTP {code}: {body[:200]}")` | 54-55 |
| 响应非 JSON | `r.json()` 抛 `ValueError`，**不被 `except requests.RequestException` 捕获** | 56-58 |
| `get_state`/`play_motion`/`set_expression`/`switch_model`/`import_model` | **抛异常给调用方** | 100-133 |
| `set_speaking`/`set_scale`/`audio_level`/`show_window`/`control_window` | 内部吞异常，返回 `False` | 135-176 |
| `look_at`/`set_parameter`/`reset` | **空实现 `return True`**（假成功） | 178-185 |
| UI 未连上 | `live2d_ready=False` 时跳过口型（`main.py:980-981`）、模型页提示未连接（1969-1972） | — |
| 进程起不来 | `ensure_running()==False` → 「⚠ 原生 Live2D 未连接」（`main.py:536-537`） | — |

### 2.7 最小客户端契约（可复用）

```python
class Live2DNativeClient:  # 依赖 requests；异常统一 Live2DNativeError(RuntimeError)
    def __init__(self, base_url="http://127.0.0.1:47835", app_path=None, dotnet="dotnet") -> None
    def available(self, timeout: float = 1.0) -> bool        # GET /state，异常→False
    def ensure_running(self, wait_sec: float = 30.0) -> bool # 忙等，必须后台线程
    def shutdown(self) -> bool                               # taskkill /T /F
    def get_state(self) -> dict                              # 抛 Live2DNativeError
    def list_models(self) -> dict                            # {"models":[...],"current":"arg-nori"}
    def switch_model(self, model_path: str) -> dict          # {"ok":bool,"modelId":str}
    def import_model(self, path: str) -> list[str]
    def play_motion(self, group, index=None, priority=None) -> bool   # priority 未发送
    def set_expression(self, expression: str) -> bool        # 空串→False
    def set_scale(self, scale: float) -> bool                # 夹紧 0.1~2.0，吞异常
    def set_speaking(self, speaking: bool) -> bool           # /mouth，level 恒 0.0
    def audio_level(self, level: float) -> bool              # /mouth，speaking = level > 0.01
    def show_window(self) -> bool                            # 先 ensure_running
    def control_window(self, action: str) -> bool            # show|hide|toggle
```

契约必须保留的三处坑位：`priority` **从不进请求体**（103-109）；`look_at/set_parameter/reset` 是 `True` 空壳；`/mouth` 的 `speaking` 与 `level` 语义重叠（上层用 `set_speaking` 开门、`audio_level` 灌电平）。

---

## 3. LLM 客户端封装

### 3.1 配置读取优先级

`load_config`（`config.py:156-178`）：

1. `config.yaml`（缺省 `PROJECT_ROOT/config.yaml`，`config.py:12`）→ `yaml.safe_load`；
2. 同级 `data/settings_overrides.json` 存在 → `_deep_merge(data, overrides)`（170-176），**override 覆盖 yaml**；
3. 包成 `Config(data, root=cfg_path.parent, config_path=cfg_path)`（178）。

`_deep_merge`（25-32）递归合并 dict，非 dict 值直接替换 → **数组是整体替换**（如 `llm.custom_models` 会顶掉而非合并）。

`Config`（35-59）把每个顶层 section 包成 `_DictObj`（126-153，支持 `.attr` / `[]` / `.get()`），并派生 `live2d_model_path` / `data_dir` / `db_path` / `log_file` 绝对路径。

本仓库实际生效链路：`config.yaml:15` `base_url: "https://api.deepseek.com"`、`config.yaml:17` `model: "deepseek-v4-flash"` 被 `data/settings_overrides.json:11-12` 同名键覆盖为同值，并注入 `provider: "deepseek"`（overrides:13）。**真实 LLM Key 只在 `data/settings_overrides.json:10`**（`config.yaml:9` 的 `api_key: ""` 是刻意分发占位）。

| 属性 | 行号 | 优先顺序 |
|---|---|---|
| `api_key` | 65-74 | `llm.api_key` → 环境变量 `DEEPSEEK_API_KEY` → 若 provider 为 ollama 或 base_url 含 `localhost`/`127.0.0.1` 则返回字面量 `"ollama"` → 否则空串 |
| `model` | 76-78 | `llm.model`，缺省 `"deepseek-chat"` |
| `base_url` | 80-82 | `llm.base_url`，缺省 `"https://api.deepseek.com"` |
| `is_local_llm` | 84-89 | `provider == "ollama"` 或 base_url 含 localhost/127.0.0.1 |
| `temperature` / `max_tokens` | 91-97 | 缺省 1.0 / 300 |
| `working_memory_size` | 61-63 | 缺省 30 |

`is_local_llm` 很好用：`core.py:192-197` 把历史砍到 10 条并关闭压缩；`core.py:292-295` 关后台反思整合；`main.py:917-921` 跳过自动记忆回顾。**本地小模型场景可直接抄这三处降级。**

运行时改配置不落盘：`set_runtime(section, key, value)`（100-109）；落盘用 `save_overrides(overrides)`（111-123，先与已有 JSON 递归合并再写，`ensure_ascii=False, indent=2`）。

### 3.2 客户端生命周期

`Brain`（`brain.py:45`）：`__init__`（48-54）有 key 就立即 `OpenAI(api_key=cfg.api_key, base_url=cfg.base_url)`，否则只 warning；`_ensure_client()`（56-62）key 为空抛 `RuntimeError("还没有配置 DeepSeek API Key…")`，`client is None` 时懒创建；`reload()`（64-69）GUI 改 key/base_url 后重建。

### 3.3 超时 / 重试 / 流式

- **超时与重试：项目未显式设置**。`OpenAI(...)` 三处（52、61、67）都不传 `timeout` / `max_retries`，走 SDK 默认值（SDK 默认 `600s`、`max_retries=2`；**本仓库未 pin 版本，实际数值未核实**）。无自建退避/熔断，唯一软化点是 `consolidate` 遇 `response_format` 不支持时降级（149-155）。
- **流式：明确关闭**。`brain.py:83`、`97` 均 `stream=False`；全仓库无 `stream=True`、无 SSE 解析 → **没有打字机效果**，是复用空白点（改流式要改 `chat_message` 返回语义 + `core.py:246-267` 工具循环）。参数固定为 `temperature=cfg.temperature`、`max_tokens=cfg.max_tokens`，有 tools 时补 `tool_choice="auto"`（99-101）。
- 其它调用点固定值：`consolidate` 0.3/800（143-148）、`score_importance` 0/10（109-119）、`core._update_summary` 0.3/500（`core.py:354-358`，绕过 `Brain` 直接用 `brain._ensure_client()`）。
- JSON 三级兜底：`json.loads` → 正则抠 `{...}` → 空结构（160-171）。

### 3.4 最小封装（可复用）

```python
class Brain:
    def __init__(self, cfg) -> None        # 用 .api_key/.base_url/.model/.temperature/.max_tokens
    def _ensure_client(self)               # 无 key 抛 RuntimeError；延迟创建 OpenAI
    def reload(self) -> None               # 换 key/base_url 后调用
    def chat(self, system_prompt, history, user_text) -> AgentReply   # stream=False
    def chat_message(self, messages, tools=None)                      # 返回原始 message，供 tool_calls 循环
    def consolidate(self, recent_messages) -> dict   # {"facts":[],"episodes":[],"rules":[]}
    def score_importance(self, user_text, reply_text) -> float        # 异常统一 0.5
```

真正有用的是 `chat_message` 而非 `chat`：`core.py:246-267` 的 function calling 循环需要 `message.tool_calls` 与 `tc.function.arguments`（JSON 字符串，解析失败按 `{}`，`core.py:254-257`）。

---

## 4. TTS 适配器

### 4.1 接口定义

`agent/tts/base.py`（13 行）是最小接口：类 `TTSBackend`，`name = "base"`，两个方法 `available(self) -> bool`（8-9）与 `speak(self, text: str) -> None`（11-13，阻塞式合成并播放，在调用方线程执行）。

`agent/tts/__init__.py` 是**空文件**，import 必须走具体模块（`agent.tts.factory` / `agent.tts.base`），无包级导出。`set_speed()` 不在基类但两个后端都实现（`gpt_sovits_tts.py:51-52`、`system_tts.py:32-33`），靠鸭子类型调用（`main.py:1070-1071`）；复用时建议提到基类。

### 4.2 工厂选择逻辑

`factory.py:19-22` 注册表仅两项：`{"system": SystemTTS, "gpt_sovits": GPTSoVITSTTS}`。

`candidate_names(cfg, allow_fallback=True)`（45-65）：

1. `order = cfg.tts.order`（缺省 `["gpt_sovits","system"]`，`config.yaml:107`）；
2. `wanted = cfg.tts.backend`（`config.yaml:105` = `"gpt_sovits"`）；
3. `wanted == "auto"` → 用 `order`；否则 `[wanted] + [x for x in order if x != wanted]`；
4. `allow_fallback=False` → **只返回首个**（冷启动排队用）；
5. `tts.allow_system_fallback`（缺省 `True`，`config.yaml:109`）为真时把 `system` 追加到末尾。

`create_tts(cfg, allow_fallback=True)`（68-86）逐个 `available()`，首个可用即返回；全失败抛 `RuntimeError`，消息含「冷启动约需 1 分钟」与逐项原因（83-86）。`probe_backends()`（25-34）供启动日志，异常一律 `False`。

### 4.3 GPT-SoVITS 本地 API

`GPTSoVITSTTS`（`gpt_sovits_tts.py:20`），配置来自 `cfg.tts.gpt_sovits`（23-35）：`api_url`（缺省 `http://127.0.0.1:9880`，尾部 `/` rstrip）、`text_lang`（`"auto"`）、`ref_audio_path`、`prompt_text`、`prompt_lang`（`"zh"`）、`speed`（缺省回退 `tts.speed`）；`self.timeout = 120` **硬编码**（35）。

`available()`（37-49）两个条件：参考音频文件存在 **且** `socket.create_connection((host, port), timeout=1.0)` 通。不请求 `/docs`，故「端口开了但模型没加载完」也算可用。

`speak()`（54-84）请求 `POST {api_url}/tts`，`timeout=120`，body 照抄：

```python
{"text": text, "text_lang": self.text_lang, "ref_audio_path": self.ref_audio_path,
 "prompt_text": self.prompt_text, "prompt_lang": self.prompt_lang,
 "speed_factor": self.speed_factor, "streaming_mode": False}
```

非 200 → `RuntimeError(f"GPT-SoVITS 合成失败（HTTP {code}）：{body[:200]}")`（71-72）。响应体**当二进制 WAV**：`tempfile.mkstemp(suffix=".wav", prefix="neuro_gsv_")` → `play_wav()` → `finally` 删除（74-84，清理失败静默）。播放依赖 `utils/audio.play_wav`（`utils/audio.py:28-43`）：Windows 走 `winsound.PlaySound(..., SND_FILENAME|SND_NODEFAULT)`（阻塞），非 Windows 走 `sounddevice` —— **只有 Windows 路径可靠**。

服务端是官方 `api_v2.py`，由 `scripts/gpt_sovits_service.py:40` 以 `["api_v2.py","-a",host,"-p",port,"-c",infer_yaml]` 启动；`services.py:342-344` 固定 `host=127.0.0.1`、`port=9880`、`infer_cfg="GPT_SoVITS/configs/tts_infer.yaml"`。就绪探测用 `requests.get("http://127.0.0.1:9880/docs", timeout=1.0)`（`services.py:263`），200 则置 `gsv_external = True`（外部实例，停止时不动它，363-365）。

`repair_gsv_weights(rt)`（287-322）：启动前读 `tts_infer.yaml` 的 `custom.t2s_weights_path` / `custom.vits_weights_path`，失效就用当前语音包权重重写。这是「项目搬家后 TTS 永远冷启动中」的根治手段，**强烈建议复用**。

### 4.4 SAPI5 兜底

`SystemTTS`（`system_tts.py:22-47`）：`available()` 仅判 `sys.platform == "win32"`（29-30，不检查中文语音包）；`speak()` 把 PowerShell 脚本经 `-Command` 传入、文本经 **stdin** 传入（40-43，`input=text`），超时 120s。脚本（12-19）做三件事：`Add-Type -AssemblyName System.Speech` → 选第一个 `Culture.Name -like 'zh*'` 的语音 → `$s.Speak([Console]::In.ReadToEnd())`；`$s.Rate = 0`。失败：非 0 退出码抛 `RuntimeError(f"SAPI5 语音失败：{stderr or stdout}")`、`FileNotFoundError` → `RuntimeError("找不到 powershell")`（44-47）。

### 4.5 音色列表与发音处理

`utils/tts_voices.py` 头部（1-10）定义目录约定：`data/voices/<voice_name>/` 放 `ref_audio.wav`（或任意 `.wav`）、可选 `*.ckpt` / `*.pth` / `prompt.txt` / `meta.json`；常量 `VOICES_DIR_NAME = "data/voices"`（22）。

| 函数 | 行号 | 要点 |
|---|---|---|
| `voices_dir(root)` | 26-27 | `root / "data/voices"` |
| `safe_voice_name(name)` | 30-33 | 去 `..`、特殊字符与空白换 `_`，空名回 `"voice"` |
| `list_voices(root)` | 36-55 | 只收有参考音频的子目录，返回 `{name, path, ref_audio, has_s1, has_s2}` |
| `_find_ref_audio(p)` | 58-64 | `ref_audio.wav` → `nori_ref.wav` → `ref.wav` → 第一个 `*.wav` |
| `import_voice(root, src)` | 67-117 | 支持 zip/目录；zip 用 `is_relative_to(dest)` 挡 **zip slip**（82-86）；单层子目录提升为包根（92-97）；无 wav 整包删除返回 `None` |
| `export_voice(root, name, dest)` | 120-132 | 复制到 `dest/<name>` |
| `prompt_text_for` / `prompt_lang_for` | 135-164 | `prompt.txt` 优先，其次 `meta.json` |
| `voice_pack_weights` | 167-171 | 第一个 `*.ckpt`（SoVITS）+ 第一个 `*.pth`（GPT） |
| `apply_voice_to_config(cfg, name)` | 174-210 | 找 ref → 补 `prompt_text`（**空则保留旧值**，182-186，空 prompt 会明显劣化音色）→ `set_runtime` + `save_overrides` → 有 `runtime_dir` 且有权重时调 `update_gpt_sovits_yaml` |
| `update_gpt_sovits_yaml` | 213-255 | **逐行正则改 YAML**：只在 `custom`/`v2`/`v2Pro` 段替换 `t2s_weights_path` / `vits_weights_path`，保留缩进，反斜杠转 `/`（226-227）；无改动返回 `None` |

`apply_voice_to_config` 是全仓库最好的「配置写回」范式：**空值不覆盖**、**内存与磁盘同改**、**顺手同步下游服务 yaml**。`update_gpt_sovits_yaml` 用逐行正则而非 `yaml.safe_dump`，为保留原注释与顺序（代价：只处理已知 section）。

### 4.6 冷启动排队与兜底时序

- 启动：`create_tts(cfg, allow_fallback=not gsv_expected_to_start(cfg))`（`main.py:383`）——GPT-SoVITS「即将就绪」时**不允许**系统音色顶替。
- `self.tts is None` 期间 `speak()` 压队列（上限 8，超出丢最旧，944-950），5 秒重试定时器（999-1006）。
- 常驻探测 `tts_probe_timer` **15 秒**（`main.py:423-425`）→ `_check_preferred_tts`（642-657）→ 后台 `TTSPreferredWorker` → 就绪自动切换 + `_flush_tts_pending`（659-676）。
- 长时间起不来：`_TTS_FALLBACK_AFTER = 18`（685），连续失败 18 轮且队列非空才切兜底（687-701）。**18×15s = 270s**，与注释「每轮 5 秒」、`config.yaml:107`「约 90 秒」均不符。

---

## 5. MCP 管理器与 Skills

### 5.1 三种传输

`server` 记录 schema（`add_server`，52-68）：`{"name","enabled","transport","url","command","args":[...],"env":{}}`。

判别逻辑在 `_tools_for_server`（98-127）与 `execute_tool`（161-185）**各写一遍**：

| transport | 分支 | 导入 | 行号 |
|---|---|---|---|
| `"streamable_http"` 或 `"http"` | `streamable_http_client(url)` → `ClientSession(streams[0], streams[1])` → `initialize()` | `mcp.client.streamable_http` | 100-106、161-167 |
| `"sse"` | `sse_client(url)` → 同上 | `mcp.client.sse` | 107-113、168-174 |
| 其它（缺省 `"stdio"`） | `StdioServerParameters(command, args, env)` → `stdio_client(params)` | `mcp.client.stdio` | 114-124、175-185 |

共性：**每次调用都新建连接、握手、用完即关**，无常驻 session / 连接池。故单轮多工具调用要重连多次（stdio 每次重起子进程）；`env` 仅在 stdio 分支生效（119、180）。

### 5.2 工具 → OpenAI function schema

`_tools_from_session`（129-141）拍平为 `{"server", "name", "description": (tool.description or tool.name)[:500], "inputSchema": tool.input_schema or {"type":"object","properties":{}}}`。

`build_tool_schemas`（143-153）：`asyncio.gather` 并发探测所有 **enabled** 服务器（144-145），转成 `{"type": "function", "function": {"name": f"{server}__{tool}", "description": f"[{server}] {description}", "parameters": inputSchema}}`。

关键契约：**工具全名 = `服务器名 + "__" + 工具名`**，执行时 `qualified_name.split("__", 1)` 反解（156）→ 服务器名不能含 `__`；工具名含 `__` 安全。`execute_tool` 的返回只取 `content[i].text`，其它 block（图片/资源）丢弃，空结果回 `"（工具执行完成）"`（189-197）。

### 5.3 启停与失败处理

| 场景 | 行为 | 行号 |
|---|---|---|
| 服务器连接失败 | warning + 返回 `[]`（该服务器本轮无工具） | 125-127 |
| 工具执行异常 | 返回字符串 `f"工具执行失败：{e}"`（不抛进 LLM 循环） | 186-187 |
| 服务器不存在/未启用 | `f"MCP 服务器 {name} 不存在或未启用"` | 157-159 |
| schema 加载失败 | `core.py:240-244` 捕获后 `tools=[]`，对话继续 | — |
| 工具结果 | 截断 4000 字符写 `role=tool` | `core.py:265-266` |
| 循环上限 | 5 轮 | `core.py:247` |
| 启停 | 只有「enabled 标记 + 存 JSON」，**无 start/stop 生命周期**，连接惰性 | 76-82 |
| 导入 | `import_server_config` 认 `servers` 或 `mcpServers` 两种键，按 name 去重 | 84-96 |

`import_server_config` 不做字段校验，坏记录会原样进配置，直到连接失败才被 warning 掉——复用时建议补 schema 校验。

### 5.4 Skills（SKILL.md）注入

- 目录 `<root>/skills/`，构造时 `mkdir(parents=True, exist_ok=True)`（27-28）。一个 skill = 子目录含 `SKILL.md`，也接受 `skills/xxx.md` 平铺（`md = d/"SKILL.md" if d.is_dir() else d`，200-214）；启用状态存 `data/mcp_config.json` 的 `skills: [{name, enabled}]`（20、31-38）。
- `list_skills()` **每次调用都 `self.save()`**（213），并清掉目录已删的条目（212）；`skill_instructions()` 内部又调它（259）→ **每轮对话至少写一次 JSON**（坑）。
- `skill_instructions()`（257-267）：遍历启用的 skill，读全文 `text[:4000]`，拼成 `## Skill: <name>\n<正文>`，`\n\n` 连接；注入点 `core.py:211-219` 是**独立第二条 system 消息**（标题 `【已启用的 Skills 指令】`），不侵入主 system prompt。
- 导入 `import_skill`（216-237）目录取 `SKILL.md`（否则第一个 `*.md`）、文件按 stem 建目录，`shutil.copy2`；同名会覆盖文件但不覆盖配置项（233-236）。删除 `remove_skill`（239-245）**同时删配置与目录**（`rmtree`），不可恢复。

### 5.5 最小工具循环（可复用）

```python
tools = await mcp_manager.build_tool_schemas()          # 并发探测，失败降级为 []
message = brain.chat_message(messages, tools=tools or None)
for _ in range(5):                                      # core.py:247 上限 5 轮
    if not (tool_calls := getattr(message, "tool_calls", None) or []):
        break
    messages.append(_assistant_message(message))        # core.py:21-33，必须回填 tool_calls
    for tc in tool_calls:
        try:
            args = json.loads(tc.function.arguments or "{}")
        except Exception:
            args = {}
        out = await mcp_manager.execute_tool(tc.function.name, args)   # "server__tool"
        messages.append({"role": "tool", "tool_call_id": tc.id, "content": out[:4000]})
    message = brain.chat_message(messages, tools=tools or None)
```

`_assistant_message`（`core.py:21-33`）是关键细节：带 `tool_calls` 的 assistant 消息必须**原样回填**（`id` / `type:"function"` / `function.name` / `function.arguments`），否则第二轮 400。

---

## 6. 联网搜索（百度 AI Search SSE）

`agent/search.py`（98 行）是「MCP over SSE」的特例客户端，不是 REST 封装。

- 构造（26-39）：`enabled = bool(search.enabled) and bool(search.api_key)`（32）—— **没有 key 就静默禁用**，`config.yaml:30` 的 `enabled: true` 单独不够；`top_k` 缺省 4（`config.yaml:34`）、`timeout` 缺省 120（35，**`self.timeout` 从未被使用**）；URL（36-39）= `http://appbuilder.baidu.com/v2/ai_search/mcp/sse?api_key=Bearer+{key}`（`+` 是 URL 编码空格，key 直接进 query）。
- `search(query, instruction=None, top_k=None)`（42-81）：未启用抛 `SearchError("联网搜索未启用…")`、空 query 抛 `SearchError("搜索关键词为空")`（44-48）；`asyncio.run(_go())` 内 `sse_client(self.mcp_url)` → `ClientSession` → `initialize()`（54-57）；`session.call_tool("AIsearch", args)`（65），`args = {"query": q, "stream": False, "search_top_k": int(top_k or self.top_k)}`，可选 `instruction`（58-64）；只拼 `content[i].text`，`result.isError` 或空文本 → `SearchError("百度 AI 搜索返回为空或失败")`（66-74）；其它异常包成 `SearchError(f"百度 AI 搜索调用失败：{e}")`（76-81）。
- 意图识别 `extract_query(text)`（静态，84-98）：前缀表 `["/搜","/search","/搜索","搜索","帮我搜","帮我搜索","百度一下","查一下"]`（15-18），命中后 `strip(" ：:，,。")`；再兜底正则 `(?:帮我搜(?:索)?一下?|搜索一下|百度一下)\s*[:：]?\s*(.{2,80})` 抓句中意图（95-97）；无意图返回 `None`。注入（`core.py:154-170`）在 `enabled` 且命中时把结果拼成 `{原文}\n\n[联网搜索结果] 关于「{query}」：\n{result}\n请用你自己的人格口吻把这些信息整理给用户，引用关键信息。`；失败不阻断，改成 `[联网搜索] 搜索失败：{e}` 附在原文后（166-168）。

---

## 7. 视觉 MCP（独立进程 + stdio，如何避免泄露 key）

### 7.1 隔离设计

`vision_mcp/` 是**可独立分发**目录，`README.md:1-4` 明确「不读取主项目 config.yaml，因此主项目分发时不会包含火山方舟 API Key」。三道隔离：

1. **配置优先级**（`server.py:47-70`）：环境变量 > 本目录 `config.json` > 默认。变量 `VOLC_ARK_API_KEY` / `VISION_BASE_URL` / `VISION_MODEL` / `VISION_MCP_PORT`，另加 `config.json` 的 `timeout`（缺省 120）。默认 `base_url = https://ark.cn-beijing.volces.com/api/v3`（35）、`model = doubao-seed-2-1-pro-260628`（36）、端口 47833（37）。
2. **主项目零 key**：`config.yaml:37-41` 只有注释；`vision_mcp/nori-vision.mcp.json` 只含 `{"name":"nori-vision","transport":"streamable_http","url":"http://127.0.0.1:47833/mcp"}`。
3. **分发规则**：`README.md:62-71` 要求复制整个目录但**不要包含 config.json**；目标机需 `openai` / `mcp` / `requests`。

### 7.2 两种启动方式（`server.py:194-211`）

| 参数 | 行为 |
|---|---|
| `--stdio` | `server.run_stdio_async()`（206-207），给 Claude Code / Cursor 等 MCP 客户端 |
| `--port N` / 无参 | `run_streamable_http_async(host="127.0.0.1", port=N, streamable_http_path="/mcp")`（209-211），缺省 47833 |

无 key 时启动只 warning，工具调用返回错误（202-204）。工具注册用 `MCPServer`（166-173，`from mcp.server.mcpserver import MCPServer`）。

### 7.3 工具与调用链

| 工具 | 签名 | 行号 |
|---|---|---|
| `analyze_image` | `(source: str, question: str = "详细描述这张图片的内容", max_tokens: int = 800) -> str` | 176-183 |
| `describe_image` | `(source: str) -> str` | 186-191 |

`source` 支持三种形态（`_load_source`，87-108）：`data:` URL（仅 base64）、`http(s)` URL（`requests.get(timeout=30)`）、本地路径（按后缀映射 mime）。全链路转 `data:{mime};base64,...` 图文消息（119-126）后 `chat.completions.create(model, messages, max_tokens, temperature=0.3)`（127-132）。**图片硬上限 10MB**（`MAX_IMAGE_BYTES` 38，检查 117-118）。

主程序调用链（`core.py:95-152`）：

1. `_vision_mcp_server_name()`（95-105）遍历 `mcp_manager.list_servers()`，找 **`enabled` 且 `name` 含 `"vision"`** 的第一个——**靠名字子串识别，强耦合**。
2. `_augment_with_vision`（107-152）：先 `_extract_image_sources`（72-93）抽路径/URL，最多处理 `sources[:3]`（122）。
3. 表情包特判：`_sticker_hint`（59-70）路径含 `stickers` 就用文件名标签，**不调视觉模型**。
4. 无 vision server → 注入降级文案「视觉 MCP 未接入，Nori 暂时看不到这张图片」（127-131）。
5. 有则 `asyncio.run(mcp_manager.execute_tool(f"{server}__analyze_image", {"source": src, "question": question}))`（138-140），失败文案 `图片（{src}）读取失败：{e}`（144-146）。
6. 拼成 `{原文}\n\n[视觉信息]\n…`（148-152）。

**风险（实测）**：`vision_mcp/config.json:2` **确实含真实 API Key**（`ark-…`，值此处省略）。README 的承诺只在「分发时不带该文件」时成立；仓库内它已被提交，复用前应改为环境变量并轮换该 key。

---

## 8. 可复用清单

| 复用对象 | 源位置 | 依赖 | 需替换的耦合点 | 最小可用示例 |
|---|---|---|---|---|
| `Live2DNativeClient` | `agent/live2d_native.py:29-200` | `requests`、`subprocess` | 硬编码 base_url/端口（32）、`DEFAULT_PORT` 未用（19）、`_models` 常量表（40-43）、`look_at/set_parameter/reset` 空壳（178-185）、`--pet-only`（78-80） | `c=Live2DNativeClient(cfg); c.ensure_running(); c.set_expression("smile"); c.set_speaking(True); c.audio_level(0.8); c.set_speaking(False)` |
| 口型推送线程 | `main.py:250-278` | `threading` | 包络公式（272）换成真实音频电平 | `p=LipSyncPusher(c, 0.06); p.start(); …; p.stop()` |
| `parse_commands` | `agent/brain.py:27-42`（正则 15） | `re` | 标签表 `expr|motion|emotion`（15） | `parse_commands("[expr:smile]你好")` → `("你好", [("expr","smile")])` |
| `AgentCore` 流水线 | `agent/core.py:172-289` | `memory`/`brain` 鸭子类型，`search`/`mcp_manager` 可选 | `prompts.build_system_prompt`、`compressor.ContextCompressor`、`controller=="native"` 判断（221） | `AgentCore(cfg, mem, brain, search=s, mcp_manager=m).handle_user_text("hi")` |
| `ServiceManager` PID/孤儿清理 | `agent/services.py:60-148` | `tasklist`、PowerShell CIM | 进程识别关键字（111-122）、gsv 端口 9880（263） | `svc=ServiceManager(cfg); svc.start_heart(); svc.status()` |
| `gsv_expected_to_start` | `agent/services.py:21-39` | 文件系统 | `api_v2.py`/`runtime/pythonw.exe` 目录约定（37-39） | `create_tts(cfg, allow_fallback=not gsv_expected_to_start(cfg))` |
| GPT-SoVITS 客户端 | `agent/tts/gpt_sovits_tts.py:20-84` | `requests`、`utils.audio.play_wav` | 7 字段 payload（61-69）、`timeout=120`（35） | `b=create_backend("gpt_sovits", cfg); b.available() and b.speak("你好")` |
| SAPI5 兜底 | `agent/tts/system_tts.py:12-47` | `powershell` | `zh*` 语音筛选（15）、`$s.Rate=0`（17） | `SystemTTS().speak("测试")` |
| TTS 工厂链 | `agent/tts/factory.py:45-86` | 各后端类 | `_CLASSES` 注册表（19-22） | `create_tts(cfg)` |
| 语音包管理 | `utils/tts_voices.py:36-255` | `zipfile`、`yaml` | `data/voices` 约定（22）、`tts_infer.yaml` 段名（236） | `apply_voice_to_config(cfg, "nori")` |
| `update_gpt_sovits_yaml` | `utils/tts_voices.py:213-255` | 无 | 只认 `custom/v2/v2Pro`（236） | `update_gpt_sovits_yaml(rt, vdir, s1, s2)` |
| `MCPManager` 三传输 + schema | `agent/mcp_manager.py:98-197` | `mcp` SDK | `__` 命名空间（149/156）、每次调用新建 session、`env` 仅 stdio | `await mgr.build_tool_schemas()`；`await mgr.execute_tool("srv__tool", {})` |
| Skills 注入 | `agent/mcp_manager.py:200-267` + `core.py:211-219` | 文件系统 | `skills/`（27）、4000 字截断（264）、每轮 `save()`（213） | `mgr.skill_instructions()` → 第二条 system 消息 |
| 百度搜索客户端 | `agent/search.py:25-98` | `mcp` SDK（SSE） | 端点与 `Bearer+` 拼接（36-39）、工具名 `AIsearch`（65）、`top_k`/`timeout` 语义 | `BaiduSearchClient(cfg).search(BaiduSearchClient.extract_query("/搜 天气"))` |
| 视觉 MCP 服务 | `vision_mcp/server.py:73-211` | `openai`、`mcp`、`requests` | `MCPServer` API（166-173）、默认模型（36）、端口 47833（37） | `python vision_mcp/server.py --stdio` |
| 日志合并 | `utils/console_logs.py:42-78` | 无 | `SOURCES` 表（7-13）、时间戳格式（37） | `collect_logs(root, "全部", 500, "error", "ERROR")` |
| 配置覆盖机制 | `agent/config.py:156-178` + `111-123` | `yaml`、`json` | overrides 路径（170）、数组整体替换语义 | `cfg.save_overrides({"llm": {"model": "x"}})` |

---

## 9. 坑与未确认项

**安全**

1. `vision_mcp/config.json:2` 含**真实火山方舟 Key**（值已省略），与 README「分发不含 config.json」矛盾，且已提交进仓库。
2. `data/settings_overrides.json:10` 含真实 DeepSeek Key、`:25` 含真实百度 Key。`config.yaml:9/33` 的 `api_key: ""` 只是占位，**真 key 在 overrides**，任何「备份 data/」都会带上。
3. Live2D 控制端口 **47835 无鉴权**，同机任意进程可 POST `/window`、`/model/import`（后者可从任意路径导入模型）。
4. 百度搜索把 key 拼进 **URL query**（`search.py:37-39`），会进代理/日志。

**正确性**

5. `search.py:35` 的 `self.timeout` **从未使用**，`config.yaml:35` 的 120 是死配置。
6. `live2d_native.py:19` `DEFAULT_PORT` 未使用，端口写死在第 32 行。
7. `play_motion(..., priority=...)` 的 `priority` **从不发送**（103-109）。
8. `look_at` / `set_parameter` / `reset` 是 `return True` 空壳（178-185），调用方会误以为成功。
9. `r.json()` 的 `ValueError` 不在 `except requests.RequestException` 覆盖内（56-58），非 JSON 的 200 会冒出未包装异常。
10. TTS 兜底时间自相矛盾：`_TTS_FALLBACK_AFTER=18`（`main.py:685`）× 探测间隔 **15s**（425）= 270s；注释写 5s、`config.yaml:107` 写「约 90 秒」。
11. `gsv_is_running()` 探 `/docs`（`services.py:263`），`available()` 探 TCP 端口（`gpt_sovits_tts.py:46`），语义不一致 → 可能「服务看着在跑但合成必失败」。
12. `list_skills()` 每次 `save()`（213），而 `skill_instructions()` 每轮都调（`core.py:213`）→ 每轮一次磁盘写。
13. MCP 三分支在 `_tools_for_server` 与 `execute_tool` **重复实现**（98-127 / 161-185），新增传输改两处。
14. 每次工具调用重建 MCP session（stdio 会重起子进程），多工具轮次开销大。
15. `core.py:138`/`260` 在已有事件循环里调 `asyncio.run` 会抛 `RuntimeError`；当前依赖「`handle_user_text` 总在线程池」的隐式前提。
16. `_vision_mcp_server_name` 靠名字含 `"vision"` 识别（`core.py:101`），改名即失效。
17. `_deep_merge` 对数组整体替换（`config.py:25-32`），overrides 的 `llm.custom_models` 会顶掉 yaml 数组。
18. `console_logs.SOURCES` 的 `live2d` 指向 `live2d_native.log`，实测日志目录只有 `live2d_mcp.log`（旧名）→ 控制台「Live2D」页签恒显示「没有匹配的日志」。
19. `update_gpt_sovits_yaml` 只处理 `custom/v2/v2Pro`（`tts_voices.py:236`），新版 GPT-SoVITS 若换 section 名则静默不生效。
20. `import_skill` 同名覆盖文件但不覆盖配置项（233-236）；`remove_skill` 直接 `rmtree`，无确认。

**未确认**

21. **`PetControlServer` 服务端路由注册**：`PetControlServer` 仅以类型名出现在 `Nori.Desktop.dll` 的 UTF-8 元数据堆（15 次），`/state`、`/mouth`、`/motion` 等路由字面量在 `Nori.Core.dll` / `Nori.Desktop.dll` 的 UTF-16 字符串表中**均未找到** → 服务端如何注册端点、`/state` 完整响应 schema、是否存在未用的端点（如真实音频电平推送）**均未确认**。
22. **LLM 超时/重试真实值**：代码未设置，取 OpenAI SDK 默认；本仓库未 pin 版本，未核实。
23. `--pet-only` 在原生端的确切行为（是否禁用原生 Chat UI / 隐藏托盘）未确认，唯一线索是 `live2d_native.py:78-80`。
24. `live2d.fallback_on_error: true`（`config.yaml:90`）与 `gui/fallback_pet.py` 在 native 模式是否仍有生效路径**未确认**：`main.py:392` 已置 `self.pet = None`，但 `main.py:1463-1469` 仍保留 `self.pet.set_scale` 分支。
25. 口型包络（`main.py:270-273`）与原生 `ParamMouthOpenY` 的映射曲线是否匹配、`/mouth` 的 `level` 是线性还是指数，均未确认。
26. SAPI5 在无中文语音包机器上的实际表现（是否用英文音色念中文）未确认。
27. `mcp` 库版本对应 `MCPServer`（`vision_mcp/server.py:166`）与 `mcp.client.streamable_http.streamable_http_client`（`mcp_manager.py:101`）属较新 API，最小兼容版本未确认。
28. 视觉默认模型 `doubao-seed-2-1-pro-260628`（`server.py:36`）是否仍在线/可用未验证。

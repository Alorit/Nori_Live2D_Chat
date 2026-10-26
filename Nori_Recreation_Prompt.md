# 复刻 Nori AI 桌面宠物项目（给其他模型的完整实现提示词）

你是一名资深的 Windows 桌面 AI 应用工程师。请根据下面这份完整规格，从零实现一个**可运行**的 Python 桌面 AI 宠物项目。项目名称为 **Nori AI 桌面宠物**，不要使用旧名 Aurith，代码中不要出现 Aurith 字样。

---

## 1. 项目目标

做一个 Windows 上的 AI 桌面宠物 / 陪伴助手：

- 主界面是 QQ/微信风格的聊天控制台。
- 同时有一个可选的 Live2D 桌面角色窗口，能显示表情、动作、说话口型。
- AI 使用 DeepSeek（OpenAI 兼容接口）驱动。
- 支持长期记忆、多人格、聊天历史会话、上下文压缩、联网搜索、图片视觉理解。
- 支持发送图片和表情包。
- 支持 GPT-SoVITS 语音合成（Nori 音色）。
- 有一个独立后台进程“Heart”，让 AI 能定时自主唤醒、私人思考、主动说话/做表情/做动作。
- 支持 MCP 外部工具服务器与 Claude Agent Skills 风格指令包。
- 全部中文界面与中文注释，UTF-8 编码。

## 2. 技术栈

- Python 3.14+ / 3.12+（使用 `from __future__ import annotations`）
- PySide6（Qt for Python）GUI
- SQLite + 线程锁（不用 SQLAlchemy）
- `openai` Python SDK 调用 DeepSeek 与火山方舟视觉模型
- `mcp` Python SDK（streamable_http / sse / stdio）
- `jieba` 分词做本地 BM25 记忆检索（可选 sentence-transformers 向量检索）
- `requests`
- `PyYAML`
- GPT-SoVITS API（本地 HTTP，默认 `127.0.0.1:9880`）
- 原生 Live2D 控制器：Nori-Desktop-Pet（.NET Avalonia + OpenGL），通过本地 HTTP `http://127.0.0.1:47835` 控制

## 3. 目录结构

```
Nori_Live2D_Chat/
├─ main.py                 # 程序入口：AppController、线程 Worker、启动逻辑
├─ run.bat                 # 一键启动，chcp 65001，用 pythonw 无窗口拉起 main.py
├─ config.yaml             # 技术配置；绝对不能放人格 System Prompt 文本
├─ heart.py                # Heart 独立后台进程
├─ agent/
│  ├─ config.py            # Config 封装、YAML + data/settings_overrides.json 合并
│  ├─ brain.py             # DeepSeek 调用、AgentReply、[expr:xx]/[motion:xx] 解析
│  ├─ core.py              # AgentCore：搜索→视觉→记忆→LLM→工具循环→写记忆
│  ├─ memory.py            # MemoryStore：SQLite、BM25、会话、记忆、规则、摘要
│  ├─ persona.py           # 多人格 .md 管理，严格由 .md 提供 System Prompt
│  ├─ prompts.py           # build_system_prompt：.md + {{time}} {{memory}} {{rules}} {{summary}}
│  ├─ compressor.py        # ContextCompressor：LLM 滚动摘要压缩
│  ├─ search.py            # BaiduSearchClient：百度 AI 搜索 MCP
│  ├─ services.py          # ServiceManager：无窗口启停 Heart / GPT-SoVITS
│  ├─ mcp_manager.py       # MCP 服务器与 Skills 管理
│  ├─ live2d_native.py     # 原生 Live2D 控制客户端（HTTP）
│  └─ tts/
│     └─ factory.py        # TTS 后端工厂，GPT-SoVITS 为唯一语音引擎
├─ gui/
│  ├─ chat_window.py       # 主聊天控制台
│  ├─ splash.py            # 无边框半透明启动加载页
│  ├─ pet_window.py        # 备用简单宠物（可保留）
│  ├─ live2d_view.py       # 内嵌 Live2D 视图（已停用，可保留兼容）
│  └─ fallback_pet.py
├─ utils/
│  ├─ console_logs.py      # 合并读取 data/logs/*.log
│  └─ stickers.py          # 表情包工具：内置生成、导入、聊天图片持久化
├─ persona/                # 人格 .md 与 .meta.json
├─ vision_mcp/             # 独立视觉 MCP 服务器（config.json 不随主项目分发）
├─ scripts/                # 工具与冒烟测试
├─ data/
│  ├─ memory.db            # SQLite
│  ├─ mcp_config.json
│  ├─ persona_active.json
│  ├─ settings_overrides.json
│  ├─ avatars/
│  ├─ stickers/default/    # 内置表情
│  ├─ stickers/imported/   # 用户导入表情
│  ├─ chat_media/          # 用户发送的图片持久化
│  ├─ voices/nori/         # GPT-SoVITS Nori 音色权重
│  └─ logs/
└─ skills/                 # Skill 目录，每个子目录含 SKILL.md
```

## 4. 配置系统

- `config.yaml` 是主配置，带中文注释。
- 用户在 GUI 保存的设置写入 `data/settings_overrides.json`，加载时递归覆盖 config.yaml。
- `Config` 对象提供 `llm/vision/search/persona/live2d/tts/memory/gui/heart/advanced` 属性，以及 `data_dir/db_path/log_file` 等。
- **重要**：`config.yaml` 只允许出现表情/动作的技术映射，不允许包含人格 System Prompt、人格规则、人格身份描述等文本。人格必须完全由 `persona/*.md` 提供。

配置骨架：

```yaml
llm:
  api_key: ""                # 真实 Key 放 data/settings_overrides.json 或环境变量 DEEPSEEK_API_KEY
  base_url: "https://api.deepseek.com"
  model: "deepseek-chat"
  temperature: 1.0
  max_tokens: 300
  working_memory_size: 30
  context_compression:
    mode: "auto"
    window_size: 20
    max_chars: 300

search:
  enabled: true
  provider: "baidu"
  api_key: "<BAIDU_APPBUILDER_KEY>"
  top_k: 4
  timeout: 120

# 视觉能力由独立 MCP 服务器提供（vision_mcp/）：
# - 主项目 config.yaml 不保存视觉 API Key
# - vision_mcp/config.json 或环境变量 VOLC_ARK_API_KEY
# - 通过 GUI 设置 → MCP/Skills → 导入 MCP JSON 接入

persona:
  persona_dir: "persona"
  active_persona: "nori"
  expressions: ["开心", "难过", "惊讶", "害羞", "生气", "认真", "困惑"]
  motions: ["点头", "摇头", "挥手", "鞠躬", "发呆"]
  emotion_map:
    开心: "爱心眼"
    难过: "圈圈眼"
    惊讶: "圈圈眼"
    害羞: "爱心眼"
    生气: "黑化"
    认真: "戴帽子"
    困惑: "圈圈眼"
  motion_map:
    点头: "nod"
    摇头: "shake"
    挥手: "wave"
    鞠躬: "bow"
    发呆: "idle"

live2d:
  enabled: true
  controller: "native"
  native_app_path: "D:/Nori-Desktop-Pet/app/desktop/Nori.Desktop/bin/Debug/net10.0/Nori.Desktop.exe"
  native_dotnet_path: "D:/dotnet/dotnet.exe"
  scale: 1.0
  fallback_on_error: true

tts:
  backend: "gpt_sovits"
  order: ["gpt_sovits"]
  gpt_sovits:
    api_url: "http://127.0.0.1:9880"
    text_lang: "auto"
    ref_audio_path: "D:\\Nori_Live2D_Chat\\data\\inori_voice\\nori_ref.wav"
    prompt_text: "Nori 是最擅长玩游戏、最喜欢你陪伴的小人偶 AI！"
    prompt_lang: "zh"
    speed: 1.0
    auto_start: true
    runtime_dir: "D:/GPT-SoVITS-v2pro-.../"

memory:
  backend: "auto"        # auto = 优先 vector，否则 bm25
  vector_model: "BAAI/bge-small-zh-v1.5"
  top_k: 8
  consolidate_interval: 10
  max_memories: 5000
  importance_threshold: 0.15
  min_exchange_chars: 8
  auto_review_enabled: true
  auto_review_minutes: 30
  similarity_threshold: 0.85

gui:
  show_chat_on_start: true
  pet_always_on_top: true
  font_size: 13
  chat_font_size: 15
  user_name: "Alorit"
  agent_name: "Nori"
  user_avatar: ""
  chat_width: 760
  chat_height: 820
  greeting: "你好呀，我是 Nori！先填好 API Key 我们就可以聊天啦。"

heart:
  enabled: true
  stop_with_gui: false
  poll_interval_sec: 20
  default_wake_minutes: 15
  min_wake_minutes: 2
  max_wake_minutes: 120
  chat_quiet_sec: 90
  allow_speak: true
  state_file: "data/heart.json"

advanced:
  auto_download_tts: false
  log_file: "data/logs/agent.log"
```

## 5. 人格系统（重点约束）

- `persona/*.md` 是每个角色的**完整 System Prompt**。
- `persona/*.meta.json` 存放每个角色的 `agent_name`、`avatar`。
- `data/persona_active.json` 记录当前生效人格。
- 默认人格文件：`persona/Nori.md`；默认人格名 `nori`。
- 人格内容绝不能从 `config.yaml` 拼接。
- System Prompt 构造时只做这些占位符替换：
  - `{{time}}` → 当前日期时间 + 星期
  - `{{memory}}` → 检索到的长期记忆
  - `{{rules}}` → 行为规则
  - `{{summary}}` → 滚动摘要
- 切换人格时自动创建/切换到该人格的“主对话”，历史按人格和会话隔离。
- 用户昵称默认 `Alorit`，智能体默认名 `Nori`。

## 6. SQLite 数据层

库文件：`data/memory.db`。

表结构：

```sql
messages(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts REAL,
  role TEXT,              -- user / assistant
  content TEXT,
  importance REAL DEFAULT 0,
  feedback REAL DEFAULT 0,
  persona TEXT NOT NULL DEFAULT 'nori',
  conversation_id INTEGER NOT NULL DEFAULT 0,
  image_paths TEXT NOT NULL DEFAULT '[]'   -- JSON 数组，图片/表情路径
);

memories(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  uuid TEXT UNIQUE,
  ts REAL,
  type TEXT DEFAULT 'episodic',   -- episodic / semantic
  content TEXT,
  importance REAL DEFAULT 0.5,
  access_count INTEGER DEFAULT 0,
  last_access REAL DEFAULT 0,
  source TEXT
);

mem_vec(mem_id INTEGER PRIMARY KEY, vec BLOB);

rules(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  rule TEXT UNIQUE,
  enabled INTEGER DEFAULT 1,
  ts REAL,
  version INTEGER DEFAULT 1,
  source TEXT
);

summary(key TEXT PRIMARY KEY, content TEXT, updated REAL);

conversations(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  persona TEXT NOT NULL,
  title TEXT NOT NULL,
  is_main INTEGER NOT NULL DEFAULT 0,
  created REAL,
  updated REAL
);
```

- 每个 `persona` 只能有一个 `is_main=1` 主对话（唯一索引）。
- 旧库自动迁移补列 `persona`、`conversation_id`、`image_paths`。
- `record_message(role, content, persona, conversation_id, image_paths)` 写入消息。
- `get_recent_messages(n, persona, conversation_id)` 返回 `{role, content, image_paths}`。
- 记忆检索用 BM25（jieba 分词 + 二元中文组合），可选向量。
- 每 N 轮或定时做反思整合：把最近对话提炼为 facts / episodes / rules，并更新滚动摘要。

## 7. AgentCore 处理流程

```
handle_user_text(user_text, image_paths=None)
  1. user_text = 去除首尾空白
  2. llm_input = search_augment(user_text)          # 识别“搜索/帮我搜/查一下”意图
  3. llm_input = vision_augment(llm_input, image_paths)
     - 从文本提取图片 URL/路径
     - 合并 GUI 传入 image_paths（最多 3 张）
     - 表情包路径（data/stickers 下）直接用文件名语义标签，不调用视觉模型
     - 普通图片调用视觉模型分析并注入 [视觉信息]
  4. persona = active_persona_name()
  5. conv_id = current_conversation_id or ensure_main_conversation(persona)
  6. system_prompt = build_system_prompt(...)
  7. history = memory.get_recent_messages(working_memory_size, persona, conv_id)
     - 图片历史消息转为 "[用户发过一张图片]"
  8. history = compressor.history_for_llm(history, persona)
  9. messages = [system] + [skills system] + history + [user llm_input]
 10. tools = mcp_manager.build_tool_schemas()   # 启用中的 MCP 服务器
 11. loop 最多 5 轮：
       message = brain.chat_message(messages, tools)
       若有 tool_calls：执行 mcp_manager.execute_tool("server__tool", args)
       把 assistant/tool 消息追加到 messages，继续
 12. parse_commands 去掉 [expr:xx]/[motion:xx]
 13. 写回 user/assistant 消息；user 消息保存 image_paths
 14. add_exchange 存为情节记忆
 15. 每 consolidate_interval 轮后台触发 consolidate_now()
```

## 8. GUI 聊天控制台

- 顶级页签：`💬 聊天` / `⚙ 设置`
- 设置里嵌套页签：基础设置、聊天记录、人格、记忆、MCP / Skills、控制台
- 聊天页：
  - 头部标题、状态胶囊、TTS 刷新按钮、完全退出按钮
  - 气泡流：头像（圆形图片或 emoji）、名字、标签、时间、正文
  - 输入行：`📷 图片`、`😊 表情`、输入框、`发送`
  - 底部：点赞/点踩、导出训练数据、设置
- 图片/表情发送：
  - 图片支持多选（最多 4 张），支持 png/jpg/jpeg/webp/gif/bmp
  - 支持拖放图片到窗口
  - 外部图片复制到 `data/chat_media/` 后持久化
  - 图片气泡显示缩略图，GIF 循环播放
  - 表情包面板：内置 16 个 emoji 贴纸，可导入到 `data/stickers/imported/`，可打开文件夹
- 历史会话页：
  - 按人格过滤，列出会话，支持新建/打开/重命名/删除，主对话不可删
- 记忆页：
  - 搜索/过滤记忆，新增/编辑/删除记忆，启用/停用规则
  - 定时记忆回顾开关与立即回顾按钮
- 人格页：
  - 下拉切换、新建、导入 .md、删除、编辑、保存、恢复默认
  - 编辑器提示“当前 .md 就是完整 System Prompt”
- MCP/Skills 页：
  - 添加/导入/启用/停用/删除 MCP 服务器
  - 导入/启用/停用/删除 Skill
- 控制台页：
  - 启动/停止 Heart、GPT-SoVITS
  - 实时日志查看、来源/级别过滤、自动刷新
- 基础设置：
  - API Key/Base URL/模型，保存到 settings_overrides
  - 字体、昵称、头像、上下文压缩
- 消息发送期间禁用输入与发送按钮，状态显示“思考中”。

## 9. 后台服务与 Heart

- `run.bat`：
  - `chcp 65001`
  - `cd /d "%~dp0"`
  - 存在 `.venv` 后用 `pythonw main.py` 启动，否则 `python.exe`
- `ServiceManager`：
  - `start_heart(skip_live2d=False)`、`stop_heart()`、`heart_is_running()`
  - `start_gpt_sovits()`、`stop_gpt_sovits()`、`gsv_is_running()`
  - Windows 下用 `CREATE_NO_WINDOW`，子进程无控制台窗口
  - PID 文件：`data/heart.pid`、`data/gpt_sovits.pid`
- `heart.py`：
  - 独立进程，写入 `data/heart.pid`
  - 每 `poll_interval_sec` 检查 `data/heart.json` 里的 `next_wake_at`
  - 主人最近发言 `chat_quiet_sec` 秒内保持安静
  - 到点后把人格 .md + 时间 + 最近状态/对话给 DeepSeek，要求只输出 JSON：
    ```json
    {
      "thought": "内心想法",
      "mood": "当前情绪",
      "action": "none / expression / motion / speak",
      "expression": "表情名",
      "motion": "动作名",
      "text": "要说的话",
      "next_wake_minutes": 2
    }
    ```
  - 执行动作：表情/动作发给原生 Live2D，说话走 TTS
  - 环境变量 `NORI_HEART_SKIP_LIVE2D=1` 可跳过 Live2D

## 10. TTS

- 后端：GPT-SoVITS（唯一）
- API：`http://127.0.0.1:9880`
- 启动时 GUI 自动无窗口拉起；冷启动期间 TTS 消息排队，就绪后自动朗读
- `create_tts(cfg)` / `create_backend(name, cfg)` / `probe_backends(cfg)`
- 回复后 `speak(text)`，TTS 在后台线程播放
- Live2D 说话时推送 `POST /mouth {"level":0.5,"speaking":true}` 驱动口型

## 11. 原生 Live2D

- 使用 Nori-Desktop-Pet（.NET Avalonia + OpenGL）作为渲染与控制模块
- 控制地址：`http://127.0.0.1:47835`
- 端点：
  - `GET /state`
  - `POST /motion` / `/expression` / `/model`
  - `POST /mouth`（口型同步）
  - `POST /window`（show/hide/toggle）
  - `POST /scale` / `/beat` / `/reload`
- 模型由原生应用管理，GUI 刷新模型列表后切换
- LLM 输出 `[expr:开心]` → 通过 emotion_map 映射后调用 `set_expression`
- LLM 输出 `[motion:点头]` → 通过 motion_map 映射后调用 `play_motion`

## 12. MCP 与 Skills

- 配置 `data/mcp_config.json`：
  ```json
  {
    "servers": [],
    "skills": []
  }
  ```
- MCP server 字段：name / enabled / transport（streamable_http|sse|stdio）/ url / command / args / env
- 工具 schema：`{"type":"function","function":{"name":"服务器名__工具名","description":"...","parameters":...}}`
- Skill：`skills/<name>/SKILL.md`，启用后内容注入到 system 消息
- 当前不做逐工具确认；如需安全版本，可增加工具白名单/黑名单和 GUI 确认

## 13. 图片与表情包实现细节

- `utils/stickers.py`：
  - `ensure_default_stickers(root)`：用 Qt QPainter 渲染 16 个 emoji PNG 到 `data/stickers/default/`
  - `list_stickers(root)`：递归扫描 `data/stickers/`
  - `import_sticker(root, path)`：复制到 `data/stickers/imported/`
  - `copy_to_chat_media(root, path)`：外部图片复制到 `data/chat_media/`
- 表情包路径直接给 Agent 一个语义标签，例如“用户发来表情包：开心”，不调用视觉模型
- 普通图片路径交给视觉模型
- `messages.image_paths` 存 JSON 数组，重启后聊天记录恢复图片缩略图

## 14. 验收标准

1. `python -m compileall -q agent gui utils main.py heart.py scripts` 通过。
2. `QT_QPA_PLATFORM=offscreen python scripts/smoke_controller_new.py` 通过。
3. `QT_QPA_PLATFORM=offscreen python scripts/smoke_gui_new.py` 通过。
4. 图片/表情包链路：选择图片→显示缩略图→复制到 data/chat_media→记录 image_paths→LLM 回复。
5. 重启后历史会话能看到图片气泡。
6. 切换人格后使用该人格 .md，且 config.yaml 不包含人格提示词。
7. 项目内所有“Aurith”都被替换为“Nori”。
8. 中文注释/日志/界面保持 UTF-8 无乱码。

## 15. 生成要求

- 一次性输出完整项目，不要求用户补充提问。
- 不要写入真实 API Key，使用占位符或环境变量。
- 重点保证：人格严格来自 .md、会话按人格隔离、后台服务无窗口、图片/表情可发送、MCP/Skills 可管理。
- 如果无法生成 Nori-Desktop-Pet 原生应用，可先实现一个与 `/state`、`/motion`、`/expression`、`/mouth`、`/window`、`/scale` 兼容的最小 HTTP 服务器 stub，保证 GUI 其余功能可独立运行。

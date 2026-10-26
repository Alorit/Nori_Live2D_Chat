# Nori Live2D Agent

Nori 本地 AI 桌面宠物：
**DeepSeek 大模型 + Live2D 形象 + 本地 TTS 语音 + 文字对话框 + 长期记忆与持续学习闭环 + 视觉理解 + 联网搜索 + 时间感知**。

项目目录：`D:\Nori_Live2D_Chat`

不通过网页操作：Live2D 由 .NET 原生桌面应用（Avalonia + OpenGL）显示，聊天/设置由本地 Qt 窗口提供。

![展示图](docs/preview.png)

---

## 功能特性

- **DeepSeek API 驱动**：OpenAI 兼容接口，`api_key` 留空配置，填入即用
- **自主行为（v0.3.0 新）**：三层结构——秒级反射层（本地微动作 / 作息 / 抢占，0 token）、心智层（Heart 定时醒来产出带时间轴的剧本 + 情绪状态机）、感知层（本地 Win32 判断你是否在电脑前）。没人陪也会动、会犯困、会自己嘟囔一句，聊天窗里还能看到她的内心 OS。详见 [自主性](#自主性反射层--心智层--感知层)
- **首次使用向导**：第一次启动会询问怎么称呼你（默认“主人”），之后可在 设置 → 基础设置 修改；Heart 的私人思考也会使用这个称呼
- **Live2D 控制（原生控制器）**：LLM 在回复里输出 `[expr:开心]` / `[motion:挥手]` 标签，程序解析后通过 **Nori-Desktop-Pet**（.NET Avalonia + OpenGL 原生桌宠）的本地 HTTP 接口驱动模型表情和动作；TTS 说话状态也会推给 Live2D 做口型
- **本地 TTS 语音（仅 Nori 音色）**：
  - GPT-SoVITS + Nori 干净语音样本（微调产物见 `data/voices/nori/`）
  - GPT-SoVITS 不可用时可用 Windows SAPI5（system）兜底
  - 旧的 sherpa / piper / edge TTS 后端已移除（代码备份在 `D:/Nori_Backup/`）
- **文字对话框**：本地 Qt 控制台，I_NORI 风格深色霓虹气泡，显示历史、输入消息、👍👎 反馈
- **长期记忆**：
  - 工作记忆：最近对话窗口，**按人格隔离**
  - 情节/语义记忆：SQLite + 本地 BM25 检索（jieba 分词），可选向量检索（sentence-transformers）
  - 行为规则：从对话中反思提炼，长期累积
  - 滚动摘要：压缩更早对话
- **LLM 上下文压缩**：保留最近 N 条原文，更早对话由 LLM 压缩成摘要（可在设置中调整模式/窗口/摘要长度）
- **定时记忆回顾**：按时间自动做 LLM 总结，并把高度相似的记忆合并为一条
- **自定义头像**：用户与 Nori 头像可分别选择本地图片（圆形裁剪）
- **持续学习闭环**：
  - 每 N 轮自动反思整合：提取用户个人信息、重要事件、行为规则
  - 显式反馈（👍👎）强化/削弱相关记忆
  - 记忆重要性打分、时间衰减、容量上限自动遗忘
  - 一键导出 JSONL 训练数据（用于以后微调）
- **无模型也能跑**：不填 Live2D 模型时，自动使用内置 QPainter 动画宠物

---

## 环境要求

- Windows 10/11（Linux 也能跑，但 Live2D 透明窗口效果最佳在 Windows）
- Python 3.10+（在 3.14 上测试通过）

---

## 快速开始

```bat
:: 只需双击这一个文件：run.bat
:: cmd 窗口会自动关闭，只留下两个窗口：
::   1) Nori 控制台（聊天/人格/记忆/控制台/设置 五个页签）
::   2) Live2D 角色窗口
::
:: 后台服务（Heart、GPT-SoVITS、原生 Live2D）由控制台静默启动，
:: 全部日志在 GUI 的“🖥️ 控制台”页签里查看。
run.bat
```

需要看到 Python 控制台日志（排查启动问题）时用：

```bat
run_console.bat
```

只想用对话框（不启动 Live2D）：

```bat
run_chat_only.bat
:: 或
run.bat --no-pet
```

首次使用前运行 `run.bat`，然后在 **设置 → 基础设置** 里填写：

- DeepSeek API Key（聊天）
- 百度搜索 API Key（联网搜索）
- 视觉 MCP API Key（火山方舟，保存到 `vision_mcp/config.json`）

也可以手动写入 `data/settings_overrides.json` 或设置环境变量；
`config.yaml` 不保存真实 Key。

也可以手动：

```bat
py -3 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

---

## 统一控制台（GUI 页签）

启动后所有操作都在一个 **Nori 控制台** 窗口里完成：

| 页签 | 功能 |
|---|---|
| 💬 聊天 | I_NORI 深色风格 + **QQ/微信式聊天气泡**（头像/昵称/标签/时间/圆角气泡）；系统与操作通知统一显示在 🖥️ 控制台，不再刷屏 |
| ⚙ 设置 | 统一设置界面：**🎛 基础设置**（GUI 配置 API Key/Base URL/模型、Nori TTS、语速、Live2D 窗口、模型列表/加载、界面字体/聊天气泡字体分开设置、自定义头像、上下文压缩）、**🗂 聊天记录**（按人格隔离的主对话 + 新建对话）、**📜 人格**（多人格切换/编辑/导入）、**🧠 记忆**（搜索/编辑/删除/规则 + 定时回顾与相似记忆合并）、**🔌 MCP / Skills**（导入/启停外部 MCP 工具与 SKILL.md 指令包）、**🖥️ 控制台**（统一日志 + 服务启停） |

启动时 `run.bat` 只负责拉起进程，随后会显示 **Nori 霓虹加载界面**（含进度条与阶段文字），GUI 加载完成后自动关闭。

人格文件目录：`persona/*.md`。**当前 .md 就是完整 System Prompt**，不会自动追加 config.yaml 人设；可选用占位符 `{{time}}`、`{{memory}}`、`{{rules}}`、`{{summary}}`。

> 一个占位符都不写时（成品人格提示词很常见），程序会把「当前时间 / 相关长期记忆 / 行为规则 / 滚动摘要」拼成一段附在 System Prompt 末尾——否则记忆、规则、时间感知会静默失效。不想要这段可设 `memory.inject_context: false`。当前生效人格记录在 `data/persona_active.json`。

## 聊天记录 / 会话

- 每个导入或新建的人格会自动创建一个**专属主对话**（★ 主对话，不可删除）
- 可在设置 → 🗂 聊天记录 中新建对话、重命名、删除、双击打开
- 打开某个会话后，聊天窗口会加载该会话的历史气泡；重启后自动恢复上次人格的主对话
- 历史与上下文压缩均按“人格 + 会话”隔离

## API Key（GUI 配置）

- 设置 → 🎛 基础设置 → DeepSeek API 配置：可直接填写 API Key / Base URL / 模型
- 点击“应用并保存 API”后写入 `data/settings_overrides.json`，优先级高于 `config.yaml`
- 仍支持 `DEEPSEEK_API_KEY` 环境变量；GUI 留空时回退到 config.yaml / 环境变量

## MCP / Skills

- 设置 → 🔌 MCP / Skills：
  - MCP：支持 `streamable_http` / `sse` / `stdio` 三类传输，可手动添加或导入 JSON；启用的 MCP 工具会以 OpenAI function-calling 形式提供给 LLM
  - Skill：参考 Claude Agent Skills，导入含 `SKILL.md` 的文件夹；启用后指令自动注入上下文
- 运行时 LLM 会自动进行最多 5 轮 tool-call 循环，把工具结果带回模型后生成最终回复

---

## 灵魂规则（主动使用 Live2D）

`config.yaml` 的 `persona.control_rule` 已加入：

- 每轮必须根据情感和内容**主动**使用 `[expr:表情名]`，情绪变化立刻换表情
- 思考/空闲/话题平淡时主动用 `[motion:发呆]`（映射到 Live2D Idle）等小动作，避免僵硬
- 说话由系统自动 TTS + 口型同步；标签由系统映射为原生 Live2D 的 `set_expression` / `play_motion` 调用

## 自主性（反射层 + 心智层 + 感知层）

从 v0.3.0 起，Nori 不再只是「跟着鼠标转眼睛的立绘」：没人在的时候她也会自己动、会犯困、偶尔嘟囔一句。设计文档与评估见 `docs/autonomy-plan.md`。

**分层原则：贵的低频，高频的免费**

| 层 | 谁在做 | 频率 | 花不花 token |
|---|---|---|---|
| 反射层（身体） | `agent/pet_director.py` | 1 秒 | 不花 |
| 心智层（决定） | `heart.py` → LLM | 5~30 分钟一次 | 每次约 1k |
| 感知层（环境） | `agent/presence.py` | 2 秒 | 不花 |

- **反射层（导演）** `agent/pet_director.py`：按作息权重表随机挑微动作（眨眼、歪头、换表情、看过来），有优先级抢占（说话 > 意图 > 微动作）、最短驻留时长（1 秒一跳也不会抖），以及「打扰预算」——默认每小时最多主动开口 3 次、两句至少隔 45 秒。动作/表情名会在首次使用前与模型能力比对，发错一次就拉黑，不会反复刷 404。**全部本地规则，不联网、不调模型。**
- **心智层（心脏）** `heart.py`：独立「值班」进程，由 GUI 控制台静默启动（日志 `data/logs/heart.log`）。每 20 秒检查一次自己设定的「下次醒来时间」，到点让 LLM 产出一份**带时间轴的剧本**（`at` 秒 + 动作/表情/台词），交给导演在接下来几分钟里陆续执行——而不是醒来放一个动作就睡回去。同时维护情绪状态 `valence / arousal / energy`（会随时间衰减回基线），情绪既影响微动作权重，也会写进下一轮台词的 prompt。
- **人格摘要缓存**：自主回合不再塞完整人格（约 5.2k tokens 输入），改用约 400 字摘要，按人格内容哈希缓存到 `data/heart_persona_digest.json`，人格没改就不再重算。未命中缓存时才多花一次约 9k tokens。实测一次唤醒 **输入 853 / 输出 153 tokens**，约 2 秒完成。
- **感知层** `agent/presence.py`：`GetLastInputInfo` 判断你离开多久、`GetForegroundWindow` 只取前台**进程名**（默认不读窗口标题、不截图、不联网，`use_window_title: false`）。你离开 5 分钟她会去睡，回来时伸个懒腰。非 Windows 平台自动降级为空实现。
- **内心 OS**：她的想法写进 `data/heart_events.jsonl`，GUI 按字节偏移增量轮询，在聊天窗里以居中的灰色小字显示「💭（情绪）想法」，不打断对话流。
- **作息**：`quiet_hours: [1, 7]` 到点自动切到 `sleep_Loop` 并停止主动说话。

配置都在 `config.yaml` 的 `autonomy` 段（每项都有注释）；想彻底关掉自主行为，把 `autonomy.enabled` 改为 false 即可。也可在 GUI「控制台」页启停 Heart，或单独运行 `scripts\start_heart.bat`。

## 时间感知与联网搜索

- **时间感知**：每轮对话自动把当前日期、时间、星期注入系统提示，涉及日期/节日/时效性问题时 Nori 以当前时间为准
- **联网搜索**：百度智能云 AI 搜索，每天免费额度
  - 使用：`/搜 关键词`、`搜索 xxx`、`帮我搜 xxx`
  - 配置：`config.yaml` 的 `search` 段
  - 实现：`agent/search.py`（官方 AI Search MCP SSE 端点，工具 `AIsearch`）

## 视觉 MCP

- 视觉能力已从主项目分离为独立 MCP 服务器：`vision_mcp/`
- 模型：`doubao-seed-2-1-pro-260628`（火山方舟 Ark，OpenAI 兼容）
- 工具：`analyze_image` / `describe_image`
- 配置方式（任选）：
  - 环境变量：`VOLC_ARK_API_KEY`
  - 配置文件：复制 `vision_mcp/config.example.json` 为 `vision_mcp/config.json` 并填写
- 启动：`scripts\start_vision_mcp.bat` → `http://127.0.0.1:47833/mcp`

### 在主程序中使用

1. 先启动 `vision_mcp/server.py`
2. 打开 Nori 控制台 → `⚙ 设置` → `🔌 MCP / Skills` → `📂 导入 MCP JSON`
3. 选择 `vision_mcp/nori-vision.mcp.json`
4. 确认服务器 `nori-vision` 已启用

之后聊天里发送图片，Nori 会通过该 MCP 服务器调用视觉工具“看到”图片再回复。

### 给 Claude Code / Cursor 使用

项目根目录 `.mcp.json` 与 `.cursor/mcp.json` 已配置 `nori-vision` 的 stdio 模式。

## 原生 Live2D 控制器（当前模式）

项目现在使用 **Nori-Desktop-Pet**（.NET Avalonia + OpenGL）作为 Live2D 渲染与控制模块（完全替换旧的内嵌 QWebEngine 渲染和 Electron MCP 方案）：

- 桌面角色窗口由 .NET 原生应用显示（透明置顶、可拖动、可缩放、点击穿透）
- 控制地址：`http://127.0.0.1:47835`
- 端点：`/state` / `/motion` / `/expression` / `/model` / `/mouth` / `/window` / `/scale` / `/beat` / `/reload`
- 本机事件：`POST /mouth`（TTS 说话状态 → 口型动画）

### 首次启动（已内置自包含预编译宿主）

项目已内置**自包含预编译**的 Nori-Desktop-Pet 原生宿主（`vendor/nori_desktop_pet/`），无需单独克隆或构建，也无需额外安装 .NET 运行时。

Python 启动时会自动以 `--pet-only` 拉起内置原生桌宠进程。也可以手动启动：

```bat
vendor\nori_desktop_pet\Nori.Desktop.exe --pet-only
```

### 缩放

在 Nori 控制台的 **⚙ 设置 → 宠物大小** 拖动滑块即可：

- 滑块范围：**0.5x ~ 2.0x**（原生侧当前限制 0.1x ~ 2.0x）
- 窗口尺寸随缩放同步变化，模型完整显示全身
- 缩放值按模型持久化，下次启动仍使用该大小

### 模型

模型由 Nori-Desktop-Pet 原生应用管理。GUI 的 **⚙ 设置 → Live2D 模型** 会读取原生应用当前模型列表，刷新后可切换模型。

### 表情/动作映射

由 `config.yaml` 的 `persona.emotion_map` / `motion_map` 控制（逻辑名 → 模型真实名），映射不到的名字会被原样透传，所以英文标签（`smile` / `nod`）也能直接命中。

ARGNori 模型自带 **5 组共 12 条动作**（`Idle` / `Reactions` / `Effects` / `Poses` / `Background`）与 **16 个表情**，写名字时可忽略数字前缀与大小写：

- 表情：`Default` `KiraKira` `Smile` `Happy` `Shy` `Angry` `Serious` `Troubled` `Doubt` `Disgust` `Speechless` `Tears` `Surprised` `Dark` `Dizzy` `Sleep`
- 动作：`Idle_Loop` `sleep_Loop` `Nod` `ShakeHead` `WakuWaku` `Angry` `Troubled` `Dizzy` `Glitch_Loop` `back_Loop`

> 旧版本这里写着「Nori 模型没有 motion 文件」，那是早期 `nori` 模型的结论；arg-nori 动作很齐全，`[motion:...]` 现在是真的会动。

---

## TTS 说明

当前**只保留 Nori 音色**：`tts.backend = gpt_sovits`、`tts.order = [gpt_sovits]`。

- 音色来源：`data/inori_voice` 捕获的 Nori 干净语音（见该目录 README）
- 冷启动时消息会自动排队，GPT-SoVITS API 就绪后按顺序朗读
- 微调训练：`scripts/train_nori_gsv.py`（切片 → FunASR 转写 → 特征提取 → SoVITS/GPT 微调），训练产物复制到 `data/voices/nori/` 并自动写入 `GPT_SoVITS/configs/tts_infer.yaml`
- 日志：GUI“控制台”页查看 `gpt_sovits`；训练日志为 `data/logs/nori_train.log`
- GUI 启动时会自动静默拉起 API（日志在“控制台”页的 `gpt_sovits`），也可以手动运行 `scripts\start_gpt_sovits_api.bat`
- 当前参考音频已配置为 Nori 样本：`data/inori_voice/nori_ref.wav`
- 冷启动约 1 分钟；API 就绪后 GUI 会自动把 TTS 切到 GPT-SoVITS（Nori 音色）
- 如需换音色，编辑 `config.yaml` 的 `tts.gpt_sovits`：

   ```yaml
   gpt_sovits:
     ref_audio_path: "D:/path/to/reference.wav"   # 参考音频，用于克隆音色
     prompt_text: "参考音频对应的文字"             # 有文本效果更好
     prompt_lang: "zh"
     text_lang: "auto"                            # 合成文本语言 auto/zh/en/ja
   ```

GPT-SoVITS 不可用时的兜底：把 `config.yaml` 的 `tts.backend` 改为 `system`，
使用 Windows 自带的 SAPI5 语音（中文音色取决于系统语音包）。

---

## 长期记忆与学习是怎么工作的

```
用户说话
   │
   ▼
检索长期记忆（BM25/向量）──▶ 拼进系统提示词
   │
   ▼
DeepSeek 生成回复 + [expr]/[motion] 标签
   │
   ├─▶ 解析标签 ──▶ 驱动 Live2D / 内置宠物
   ├─▶ 文本 ──────▶ 对话框 + 本地 TTS 朗读
   ▼
写入工作记忆（最近 N 条）
   │
   ▼
启发式重要性打分，值得记的写入长期记忆
   │
   ▼
每 N 轮后台反思整合：
   - 提取用户个人信息/偏好 → 语义记忆
   - 总结重要事件 → 情节记忆
   - 提炼行为规则 → 规则表（长期注入 prompt）
   - 更新滚动摘要
   │
   ▼
👍👎 反馈 → 调整对应记忆的重要性
   超容量 → 遗忘最不重要且最旧的记忆
```

想导出对话数据（用于以后微调模型）：

- 点击聊天窗口的“导出训练数据”按钮，生成 `data/training.jsonl`

---

## 目录结构

```
Nori_Live2D_Chat/
├── main.py                 # 程序入口
├── config.yaml             # 非敏感配置（真实 API Key 放在 data/settings_overrides.json 或环境变量）
├── data/settings_overrides.json  # 本地敏感覆盖（不随分发）
├── agent/
│   ├── brain.py            # DeepSeek 调用 + 标签解析 + 反思整合
│   ├── memory.py           # 长期记忆：SQLite + BM25/向量 + 遗忘
│   ├── core.py             # 学习闭环编排
│   ├── prompts.py          # 系统提示词构造
│   ├── persona.py          # 人格 .md 的加载/保存/恢复默认
│   ├── services.py         # Heart / GPT-SoVITS 无窗口启停管理
│   ├── live2d_native.py    # 原生 Live2D 控制器客户端（当前 Live2D 模块）
│   ├── config.py           # 配置加载
│   └── tts/                # TTS 后端（gpt_sovits + system 兜底）
├── gui/
│   ├── chat_window.py      # Nori 统一控制台（聊天/人格/记忆/控制台/设置）
│   ├── first_run.py        # 首次使用向导（询问用户称呼）
│   ├── pet_window.py       # 旧内嵌宠物窗口（已停用，保留备用）
│   ├── live2d_view.py      # 旧 QWebEngineView 渲染（已停用，保留备用）
│   └── fallback_pet.py     # 旧 QPainter 宠物（已停用，保留备用）
├── persona/
│   └── nori.md           # 当前人格提示词（GUI“人格”页编辑）
├── scripts/
│   ├── gpt_sovits_service.py   # GPT-SoVITS 无窗口服务启动器
│   ├── start_heart.bat         # 手动静默启动 Heart
│   └── start_gpt_sovits_api.bat
├── data/                   # 运行时生成：memory.db、TTS 模型
│   └── logs/               # agent / heart / gpt_sovits / live2d_native 日志
├── setup_venv.bat
├── run.bat                 # 一键启动（cmd 自动关闭）
├── run_console.bat         # 带 Python 控制台的调试启动
└── requirements.txt
```

---

## 参考项目与致谢

| 项目 / 组织 | 说明 | 协议 |
|---|---|---|
| [Nori-Desktop-Pet](https://github.com/MF-Dust/Nori-Desktop-Pet) | 原生 Live2D 桌宠宿主（.NET Avalonia + OpenGL） | GPL-3.0 |
| [mitscherlich/live2d-mcp](https://github.com/mitscherlich/live2d-mcp) | v0.1 参考实现（v0.2 已移除） | 以该仓库 LICENSE 为准 |
| [GPT-SoVITS](https://github.com/RVC-Boss/GPT-SoVITS) | TTS 推理框架 | 以该仓库 LICENSE 为准 |
| Live2D Cubism SDK | Live2D 渲染 SDK | 以 Live2D 官方许可为准 |

## 贡献者

- [Alorit](https://github.com/Alorit)

完整致谢与版权声明见 [ACKNOWLEDGEMENTS.md](ACKNOWLEDGEMENTS.md)。

## 开源许可证

- 本项目 Python 代码：**MIT License**，详见 [LICENSE](LICENSE)
- Nori-Desktop-Pet：**GPL-3.0**，详见其仓库 LICENSE
- 第三方资产版权归原权利方所有

---

## 常见问题

**Q：启动提示没有可用 TTS 后端？**
GPT-SoVITS 冷启动约需 1 分钟，就绪后会自动切换；急用可把 `config.yaml` 的 `tts.backend` 改为 `system`，使用 Windows SAPI5 兜底。

**Q：Live2D 窗口是白底/黑底？**
原生渲染使用 OpenGL 透明窗口；如果显卡驱动异常导致背景异常，请更新显卡驱动，或在 `config.yaml` 不启用 Live2D 改用内置宠物。

**Q：模型表情/动作没反应？**
检查 `config.yaml` 的 `emotion_map`/`motion_map` 是否填了模型真实的 expression/motion 名字。模型里没有的会被静默忽略。

**Q：想让 API 不产生标签？**
把 `persona.control_rule` 删掉或改成“不要输出任何控制标签”。

**Q：记忆会不会越记越乱？**
有容量上限和遗忘策略；行为规则和长期记忆都可以在 GUI 的“🧠 记忆”页里直接搜索、编辑、删除或启用/停用。

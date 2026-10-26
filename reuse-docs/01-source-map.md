# 01 · 源码地图与仓库现状

> 本文件回答三个问题：**代码在哪、哪一份是准的、值钱的东西在哪个文件里。**
> 行数为**按换行符计数的有效行（与编辑器/read 工具一致）**，采集时间：2026-10-20（快照）。

## 1. 仓库身份：磁盘上有 3 份，只有 1 份是"活的"

| 路径 | 性质 | 判定依据 | 结论 |
|---|---|---|---|
| `D:\Nori_Live2D_Chat` | **活跃开发副本（工作树）** | 有 `.venv`、`data/` 运行时状态；`data/heart.json`、`data/logs/agent.log` 持续写入（最新到 2026-10-20 17:04） | ✅ **以它为准** |
| `D:\Nori_Live2D_Chat_github` | 干净克隆（发布基线） | `.git` 存在，`origin = https://github.com/Alorit/Nori_Live2D_Chat.git`，HEAD `bc4fa8a`（2026-09-13，`v0.2.2`），`git status` 干净 | 📌 只用来对比/回滚 |
| `D:\AI_Working Directory\ZCode\Nori_Live2D_Chat` | 空壳目录 | 无文件 | ⛔ 忽略 |

- 许可证：Python 代码 **MIT**（`LICENSE`，Copyright 2026 Alorit）；原生桌宠宿主 **GPL-3.0**（来自 Nori-Desktop-Pet）。
- 项目根目录**不是 git 仓库**：工作副本里没有 `.git`，所以本地改动不受版本控制保护。

### 工作副本与发布基线的漂移（重要）

`D:\Nori_Live2D_Chat` 相对 HEAD 有**未提交的本地改动**，且**回不到过去**（无 git）。按文件哈希比对，`.py` 中有实质差异的是：

```
agent/prompts.py          ← 提示词拼装（占位符/注入）逻辑已改
agent/services.py         ← 子进程管理（Heart / GPT-SoVITS）已改
agent/tts/factory.py      ← TTS 后端候选链已改
heart.py                  ← 自主唤醒进程已改
scripts/download_live2d_js.py
utils/tts_voices.py
```

此外工作副本多出 **56 个 `scripts/inori_*.py`**（`inori_probe/`、`inori_chatcmd/`、`inori_login/`… 约 40 个探测脚本 + 其抓取的数据 `data/inori_*.txt`）、`scripts/train_nori_gsv.py`、`scripts/inori_capture_*.py`。这批脚本对应仓库之外的另一个 Web 应用（"inori"）的逆向探测，**与桌面宠物主流程无关**，复用时应整目录排除。

> 结论：**想读"当前真实行为"读工作副本；想读"发布版行为"读 github 副本。** 两者在提示词注入、TTS 回退、Heart 兜底三处行为不同（见 `04-pitfalls.md`）。

## 2. 体量总览

> 以下数字为 **v0.3.0_bata（2026-10-26）** 实测；括号内是 v0.2.2 时的旧值。

| 指标 | 数值 |
|---|---|
| Python 文件 | 123 个（v0.2.2: 120；排除 `__pycache__`、`.venv`、`vendor`） |
| Python 总行数 | **14,631**（v0.2.2: 13,457） |
| 其中主程序（`main.py`/`heart.py`/`agent/`/`gui/`/`utils/`/`vision_mcp/`） | **37 个文件、11,093 行**（旧: 34 个、9,896 行） |
| 其中 `scripts/` | 86 个文件、3,538 行（含约 40 个与主流程无关的 `inori_*`） |
| `data/` | 约 304 MB（语音权重 277 MB + 日志 + 抓取数据；**不入库**） |
| `vendor/nori_desktop_pet/` | 430 文件、约 263 MB（自包含 .NET 桌宠宿主，只有二进制，**只随 Release 分发**） |

真正需要读懂的核心是 **`agent/`（20 文件 3,884 行）+ `utils/` + `heart.py`（492 行）**；`gui/` 3,740 行里 `chat_window.py` 独占 2,894 行。

> v0.3.0 新增的三个文件都在 `agent/` 下，合计 788 行：`pet_director.py`（493）、`presence.py`（209）、`heart_events.py`（86）。它们与 `heart.py` 一起构成"自主性"三层结构，设计文档见 `docs/autonomy-plan.md`。

## 3. 分层地图（含复用价值评级）

评级口径：★★★ = 换个项目能直接用（拿到契约即可搬）；★★ = 需要改写耦合处，但设计可照抄；★ = 只与本项目强绑定，参考即可。

### 3.1 入口与编排

| 文件 | 行数 | 职责 | 评级 |
|---|---|---|---|
| `main.py` | 2,192 | `AppController` 启动编排、QThread Worker、服务启停、退出清理、启动页/首启向导调度、`data/heart_events.jsonl` 轮询 | ★★（编排骨架可照抄） |
| `heart.py` | 492 | 独立进程：定时自主唤醒 → LLM 产出**带时间轴的剧本** → 写事件流 + 驱动表情/说话；维护 valence/arousal/energy 情绪态；人格摘要缓存 | ★★★（"自主空闲行为"整套可搬，见 `detail/03` §4.7） |
| `run.bat` / `run_console.bat` / `run_chat_only.bat` | — | `chcp 65001` + `pythonw` 无窗口启动、带控制台调试启动、只开聊天 | ★★ |
| `setup_venv.bat` | — | 建 venv + 装依赖 | ★ |

### 3.2 `agent/`（核心逻辑，最需要复用的地方）

| 文件 | 行数 | 职责 | 评级 |
|---|---|---|---|
| `memory.py` | 817 | SQLite 长期记忆：会话/消息/记忆/规则/摘要 + BM25(jieba) 检索 + 遗忘与合并（v0.3.0 起按内容去重） | ★★★ |
| `pet_director.py` | 493 | **v0.3.0 新增**：秒级反射层。body lock 抢占、动作白名单、微动作权重表、泊松抖动、作息/睡眠、说话预算与冷却。零 token | ★★★（"看起来活着"的关键） |
| `services.py` | 383 | 无窗口子进程管理（Heart、GPT-SoVITS）：PID 文件、命令行校验、权重路径自愈 | ★★★ |
| `core.py` | 378 | `AgentCore` 主流程：搜索增强 → 视觉增强 → 记忆 → LLM → 工具循环 → 写记忆 → 反思整合 | ★★ |
| `mcp_manager.py` | 267 | MCP 三传输（stdio/sse/streamable_http）+ Skills(SKILL.md) 注入 + 工具 schema 生成 | ★★★ |
| `persona.py` | 227 | 多人格 `.md` 加载/保存/导入/删除、`.meta.json`、`persona_active.json`（v0.3.0 起原子写） | ★★★ |
| `live2d_native.py` | 221 | 原生桌宠 HTTP 客户端（表情/动作/口型/窗口/缩放）；拉起桌宠时把 stdout/stderr 重定向到 `data/logs/live2d_native.log` | ★★★（契约见 `03-live2d-bridge.md`） |
| `presence.py` | 209 | **v0.3.0 新增**：本地 Win32 感知（`GetLastInputInfo` 空闲秒数、`GetForegroundWindow` 进程名），不联网不截图；非 Windows 降级为空实现 | ★★★ |
| `config.py` | 179 | YAML + `data/settings_overrides.json` 递归合并、路径解析 | ★★★ |
| `brain.py` | 171 | DeepSeek 调用、`AgentReply`、`[expr:xx]`/`[motion:xx]` 标签解析 | ★★★ |
| `search.py` | 98 | 百度 AI Search（SSE/MCP 工具 `AIsearch`）+ 口语触发词识别 | ★★ |
| `heart_events.py` | 86 | **v0.3.0 新增**：`data/heart_events.jsonl` 的写入（heart 侧）与按字节偏移增量读取（GUI 侧），文件被截断会自愈 | ★★★ |
| `compressor.py` | 82 | 上下文滚动摘要压缩（模式 off/on/auto） | ★★★ |
| `prompts.py` | 68 | `build_system_prompt`：`.md` + `{{time}} {{memory}} {{rules}} {{summary}}` 占位符/末尾追加 | ★★★ |
| `tts/factory.py` | 86 | 后端工厂 + 候选链 + 冷启动排队 + 回落 | ★★★ |
| `tts/gpt_sovits_tts.py` | 84 | GPT-SoVITS 本地 API 客户端（音色克隆参考音频） | ★★★ |
| `tts/system_tts.py` | 47 | Windows SAPI5 兜底 | ★★ |
| `tts/base.py` | 13 | TTS 抽象接口 | ★★★ |

### 3.3 `gui/`（PySide6）

| 文件 | 行数 | 职责 | 评级 |
|---|---|---|---|
| `chat_window.py` | 2,894 | 统一控制台：聊天/设置/聊天记录/人格/记忆/MCP/控制台 全部页签（v0.3.0 新增 `append_thought()` 内心 OS 条、`refresh_console()` 公开方法；设置页改为每页独立滚动区） | ★★（抠组件，勿整体搬） |
| `fallback_pet.py` | 255 | 无模型时的 QPainter 兜底动画宠物（**本项目内已停用**：`main.py:392` `self.pet = None`，但组件本身零耦合可独立复用） | ★★ |
| `pet_window.py` | 195 | 旧内嵌宠物窗口（已停用，全仓库无第二个 import） | ★ |
| `live2d_view.py` | 144 | 旧 QWebEngine 渲染（已停用；依赖的 `live2d/index.html` 在仓库里**不存在**） | ★ |
| `first_run.py` | 114 | 首次使用向导（询问用户称呼） | ★★ |
| `splash.py` | 111 | 无边框霓虹启动加载页 | ★★ |
| `winstyle.py` | 44 | Windows 原生标题栏暗色化（Win10/Win11 分支） | ★★★（小工具，独立可用） |

### 3.4 `utils/` 与 `vision_mcp/`

| 文件 | 行数 | 职责 | 评级 |
|---|---|---|---|
| `utils/tts_voices.py` | 255 | 语音包导入/导出/应用、权重路径自愈 `repair_gsv_weights()` | ★★ |
| `utils/stickers.py` | 202 | 表情包：QPainter 生成内置 16 个、导入、聊天图片持久化到 `data/chat_media/` | ★★ |
| `utils/console_logs.py` | 77 | 合并读取 `data/logs/*.log`（GUI 控制台页数据源）；`live2d` 来源 = 桌宠进程的 stdout/stderr 重定向 | ★★★ |
| `utils/audio.py` | 56 | 播放/音频工具 | ★★ |
| `vision_mcp/server.py` | 211 | **独立进程**视觉 MCP 服务器（火山方舟 Ark，OpenAI 兼容），`analyze_image` / `describe_image` | ★★★（"能力外置、主项目不拿 Key"的范式） |

### 3.5 `scripts/`（86 个）

分三类，**只有第二类值得看**：

1. `inori_*.py`（约 40 个）+ `data/inori_*.txt`：对某 Web 应用的逆向探测，与主流程无关，**排除**。
2. `smoke_*.py`（约 30 个）：**验收即代码**。每个都是 `QT_QPA_PLATFORM=offscreen` 下可跑的冒烟测试，覆盖控制器、GUI、记忆槽位、人格多开、TTS 切换、历史隔离、全量退出。**这是复用时最有价值的测试资产**（不依赖 pytest，直接 `python scripts/xxx.py`）。
3. 工具/训练：`gpt_sovits_service.py`（无窗口拉起 GSV）、`train_nori_gsv.py`（切片→转写→特征→微调）、`inori_capture_*.py`（语音采样）。

## 4. 非代码资产（比代码更容易直接复用）

| 资产 | 路径 | 说明 |
|---|---|---|
| **重建规格书** | `Nori_Recreation_Prompt.md`（430 行） | 一份可直接喂给任何模型的项目重建提示词：目标、技术栈、目录、配置骨架、**完整 SQLite 表结构**、`AgentCore` 12 步流程、GUI 页签规格、Heart 输出 JSON、验收标准。**这是全仓库复用性价比最高的单个文件。** |
| 人格提示词 | `persona/Nori System Prompt V3.5.2.md`（21 KB）+ V3.5、`nori.md` | 成品 System Prompt；当前生效的是 V3.5.2（见 `data/persona_active.json`）。`nori.md` 只是两句话的占位默认值 |
| 人格元数据 | `persona/*.meta.json` | `agent_name` / `avatar` 路径 |
| 设计说明 | `README.md`（361 行）、`CHANGELOG.md`（78 行） | 功能全貌 + v0.2.0→v0.2.2 的踩坑记录（TTS 全线失效、记忆不注入、Heart 无限唤醒、跨人格会话丢失的成因） |
| 桌宠宿主（二进制） | `vendor/nori_desktop_pet/`（`Nori.Desktop.exe` + 自包含 .NET） | 免装 .NET 运行时，`--pet-only` 启动，监听 `127.0.0.1:47835` |
| 桌宠宿主（源码） | `D:\Nori-Desktop-Pet-Fork`（含 `Live2D/PetControlServer.cs`、`LipSyncBehavior.cs`）、`D:\Nori-Desktop-Pet.new` | 服务端权威契约在这里，见 `03-live2d-bridge.md` |
| 音色权重 | `data/voices/nori/`（`nori_s1.ckpt` 148 MB、`nori_s2.pth` 129 MB、`nori_ref.wav`、`prompt.txt`） | GPT-SoVITS 微调产物，**私有大资产**，跨项目复用需授权 |
| 参考音频/采样 | `data/inori_voice/` | 训练与试听样本 |
| 预览图 | `docs/preview.png` | README 展示图 |

## 5. 运行时数据目录（`data/`）

| 项 | 说明 |
|---|---|
| `memory.db`（246 KB） | SQLite：`messages` / `memories` / `mem_vec` / `rules` / `summary` / `conversations`，**按 persona + conversation_id 隔离** |
| `settings_overrides.json` | GUI 保存的设置，递归覆盖 `config.yaml`。⚠️ **内含真实 API Key（DeepSeek、百度）与绝对路径**，属敏感文件，复用/迁移时先脱敏 |
| `persona_active.json` | 当前生效人格名 |
| `heart.json` | Heart 状态：`next_wake_at` / `last_wake_at` / `thoughts[]` / `actions[]` |
| `mcp_config.json` | 已注册 MCP 服务器与 Skills 列表 |
| `logs/` | `agent.log`、`heart.log`、`gpt_sovits.log`、`live2d_mcp.log`、`nori_train.log`（GUI 控制台页合并显示） |
| `avatars/`、`stickers/`、`chat_media/`、`voices/` | 头像、表情包、聊天图片、语音包 |
| `*.pid` | `heart.pid`、`gpt_sovits.pid`（子进程存活探测依据） |

## 6. 建议的阅读顺序（给下一个会话）

需要**快速理解全貌**：`00-brief.md` → 本文件 §3 → `Nori_Recreation_Prompt.md` §5-§7（表结构 + AgentCore 流程）。

需要**照抄某一块**：直接跳到 `detail/` 下对应章节，从"可复用清单"表的源位置读 20-50 行原文即可，不必通读整个文件。

需要**改行为**：先读 `04-pitfalls.md` 的"仓库与环境的坑"，弄清工作副本与发布版在 `prompts.py` / `services.py` / `tts/factory.py` / `heart.py` 上已经不一致。

## 7. 读取注意（踩过一次的坑）

- 本项目全部源码是 **UTF-8**；Windows PowerShell 5.1 的 `Get-Content` 默认按 ANSI 解码，会把 `README.md`、`requirements.txt`、`ACKNOWLEDGEMENTS.md` 显示成乱码。**这不是文件损坏**，读时显式指定 `-Encoding utf8`（或用带 UTF-8 解码的读取工具）。
- 数行数时注意口径：`Get-Content | Measure-Object -Line` **不统计空行**（本项目会把 `main.py` 少数百行）；本文件用的是按换行符计数。
- `data/settings_overrides.json` 里的 Key 是**真实可用的**，不要贴进提交、日志或发给外部模型。

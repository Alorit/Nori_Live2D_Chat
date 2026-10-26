# 02 · 可复用资产清单（按"能不能直接搬"分级）

> 这份清单是本次勘察的核心产出。分级不是按"代码好看"，而是按**搬走时要改多少东西**：
> **一级**＝文件级独立，改几个常量就能用；**二级**＝设计可照抄、接缝要重接；**三级**＝只适合当参考读物。

## 0. 结论先行

整个项目 13,457 行 Python，真正"稀缺"的只有 **约 2,600 行的无界面智能体脊柱**：

```
config.py(178) persona.py(220) prompts.py(76) memory.py(798) compressor.py(82) brain.py(171) core.py(376)
+ tts/{base13, factory86, gpt_sovits84, system47} + services.py(396) + utils/audio.py(56)
```

> 行数按换行符计数（与编辑器一致，`Get-Content | Measure-Object -Line` 会漏算空行）。下文表格里的行数用于估算搬运量，±1 不影响结论。

这 2,600 行凑在一起，就是一套**"多人口格 + 长期记忆 + 上下文压缩 + 本地 TTS + 无窗口子进程托管"**的完整后端，且 `core.py` 用的是**依赖注入**（只 `from utils.stickers import sticker_label`，其余对象全从构造参数进来），所以把 GUI 和 Live2D 整个删掉它照样跑。**要复用，从这里下手，不要从 `main.py`（2,132 行胶水）下手。**

## 1. 一级：零改动 / 改几个常量即可搬

| 资产 | 行数 | 源位置 | 依赖 | 搬走要做的唯一改动 |
|---|---|---|---|---|
| `apply_dark_title_bar` | 44 | `gui/winstyle.py` 全文 | 无 | 无。Win10 沉浸式 / Win11 同色两分支，任何暗色 Windows 应用都能加 |
| `FallbackPet`（QPainter 兜底宠物） | 262 | `gui/fallback_pet.py` 全文 | 仅 Qt | 无（`bg_color` 参数是死参，见 §4）。注意：**在本项目里是死代码**（`main.py:392` `self.pet = None`），但作为独立组件依然零耦合可用 |
| `SplashWindow`（霓虹启动页） | 111 | `gui/splash.py` 全文 | 仅 Qt | 无；但要自己加 `processEvents()`，否则进度条定格 |
| `FirstRunDialog`（首启向导） | 114 | `gui/first_run.py` 全文 | `gui.winstyle` | 改 `from gui.winstyle import ...` 的包名 |
| 表情包 / 图片管线 | 202 | `utils/stickers.py` 全文 | 仅 Qt + 文件系统 | 函数式、只吃 `root: Path`；`seguiemj.ttf` 是 Windows 假设 |
| 日志合并读取 | 79 | `utils/console_logs.py` 全文 | 无 | 改 `SOURCES` 文件名表；注意本项目里 `live2d` 源指向了不存在的日志名 |
| TTS 三件套 | 234 | `agent/tts/{base,factory,gpt_sovits_tts,system_tts}.py` | `requests`、`utils/audio` | 改 GSV 端点（`127.0.0.1:9880`）与参考音频路径；`base.py` 只有 14 行，接口极薄 |
| 配置加载 + 覆盖 | 179 | `agent/config.py` 全文 | `yaml`、`json` | 改 `data/settings_overrides.json` 路径；`_deep_merge` 对数组是整体替换（要想清楚） |
| 人格加载 / 提示词拼装 | 298 | `agent/persona.py` + `agent/prompts.py` | 无（鸭子类型） | 改默认人格名 `nori`、`persona/` 目录名、4 个占位符字面量 |
| 上下文压缩器 | 83 | `agent/compressor.py` 全文 | 一个 `chat()` 回调 | 改缓存 key 结构即可 |
| **重建规格书** | 430 行文档 | `Nori_Recreation_Prompt.md` | — | 无。可以直接喂给任何模型重造同类项目，含 SQLite 完整 DDL |
| 冒烟测试套件 | ~30 个脚本 | `scripts/smoke_*.py` | `QT_QPA_PLATFORM=offscreen` | 无需 pytest，`python scripts/xxx.py` 直接跑；是"验收即代码"的样本 |

## 2. 二级：设计可照抄，接缝要重接

按"抄一件赚一件"排序：

| 资产 | 行数 | 源位置 | 为什么值得抄 | 重接代价 |
|---|---|---|---|---|
| **分层记忆 + 评分遗忘** | 799 | `agent/memory.py` | 五层 schema（messages/memories/rules/summary/mem_vec）+ 中文 BM25（jieba，k1=1.5/b=0.75）+ 综合评分（BM25 .55 / 向量 .30 / 衰减 .10 / 重要性 .05，半衰期 7 天）+ 启发式重要性 + 容量遗忘 + 相似合并 | 中：要换库路径、停用 persona 假设；**先修 3 个 bug**（见 §4） |
| **`AgentCore` 流水线** | 377 | `agent/core.py:172-289` | 12 步顺序踩过坑：搜索增强 → 视觉增强 → 记忆检索 → 系统提示 → 历史 → 压缩 → 工具循环(≤5) → 标签剥离 → 落库 → 情节记忆 → 反思 | 低：依赖注入，只要求 memory/brain 鸭子类型；把 `asyncio.run` 换到线程池外 |
| **标签解析** | 15 | `agent/brain.py:27-42` | 15 行正则把 `[expr:x] [motion:y]` 从正文剥出并返回 `[(kind,name)]`，正则同时支持 `emotion` 别名 | 极低：复制即用 |
| **进程托管（Heart/GSV）** | 397 | `agent/services.py` | 无窗口拉起 + PID 文件 + **命令行校验防 PID 复用** + 孤儿清理 + 权重路径自愈 `repair_gsv_weights()` | 中：`_pid_is_heart/_pid_is_gsv` 是硬编码进程名；`tasklist`/CIM 是 Windows 专属 |
| **`Live2DNativeClient`** | 200 | `agent/live2d_native.py` | 10 个端点的完整客户端 + `ensure_running` 拉起 + 全部失败静默降级 | 低-中：端口写死；详见 `03-live2d-bridge.md` |
| **口型推送线程** | 29 | `main.py:250-278` | 用**后台线程**而非 QTimer 发 HTTP（主线程每 60ms 发一次会把 UI 拖死）；合成包络公式可直接用 | 极低：复制，改成读真实音频电平更好 |
| **MCP 三传输 + Skills** | 268 | `agent/mcp_manager.py` | stdio/sse/streamable_http 统一成 OpenAI function schema（`服务器名__工具名`）；SKILL.md 注入为第二条 system | 中：`mcp` SDK 版本敏感；transport 三分支重复实现了两遍 |
| **百度 AI 搜索** | 99 | `agent/search.py` | 官方 AI Search SSE 端点 + 口语触发词识别（`/搜`、`帮我搜`…）+ 结果拼进 prompt | 低：端点/Key 要换；`timeout` 是死配置 |
| **视觉能力外置为独立 MCP** | 212 | `vision_mcp/server.py` | **范式价值 > 代码价值**：能力独立进程、主项目不持有 Key、主项目通过 MCP 接入 | 低：`MCPServer` API 较新 |
| **聊天气泡 `MessageBubble`** | ~130 | `gui/chat_window.py:418-544` + QSS `:143-163` | 左右对齐 / 圆形头像裁剪 / tag 徽章 / 多图缩略图 / 不对称圆角尖角（`14px 4px 14px 14px`）/ GIF `QMovie` 保引用 | 低：不依赖 cfg；但时间戳要参数化（现在恒为"现在"） |
| **深色霓虹 QSS** | ~340 | `gui/chat_window.py:74-415` | 覆盖 20+ 控件类型的完整暗色主题，六种语义按钮色 | 低：纯字符串；**必须保留整套 `objectName`**，否则静默失效 |
| **`QRunnable` + `WorkerSignals` 模板** | ~30 | `main.py:76-160` | `result/error/finished` 三信号 + `except RuntimeError` 兜住"窗口已销毁" | 极低：本项目所有后台任务的统一骨架 |
| **无边框透明置顶窗骨架** | ~120 | `gui/pet_window.py:27-200` | `FramelessWindowHint + Tool + TranslucentBackground` + 拖拽整窗（`window().pos()` + `manhattanLength()>3`）+ 语音气泡按字数自动隐藏 | 低：把 `cfg` 换成构造参数 |
| **QWebChannel 桥（Python↔JS）** | 144 | `gui/live2d_view.py` | "JS 上行信号 + `runJavaScript` 下行"这一层与 Live2D 无关，可套到任何"网页渲染 + Python 逻辑"的场景 | 中：**依赖的 `live2d/index.html` 在本仓库不存在**，是死路径 |

## 3. 三级：只当参考，不要搬

| 东西 | 行数 | 为什么不搬 |
|---|---|---|
| `gui/chat_window.py` 整体 | 2,690 | 单文件塞了 7 个页签 + 全部设置项 + 全部列表渲染，`main.py` 直接读写它的 26 个控件和 3 个私有字段；拆不开，只适合"抠组件" |
| `gui/pet_window.py` / `live2d_view.py` | 201 / 145 | 内嵌 WebEngine 方案**已被原生 .NET 宿主取代**，且页面文件缺失，是明确的死代码路径 |
| `main.py` 整体 | 2,132 | 65% 是信号接线与控件回填的胶水；值得抄的只有 §2 里那 5 个原语 |
| `scripts/inori_*.py` + `data/inori_*.txt` | ~40 文件 | 对另一个 Web 应用的逆向探测残留，与桌宠主流程无关 |
| `memory.db` 现状数据 | 246 KB | 含 8 条 `persona='aurith'` 的历史残留；搬 schema 不搬数据 |

## 4. 搬之前必须知道的 8 个"已确认缺陷"

这些不是猜的，是读代码核实过的。**照抄会把 bug 一起抄走**：

| # | 缺陷 | 位置 | 后果 | 修法 |
|---|---|---|---|---|
| 1 | `INSERT OR IGNORE` 去重键是每次新生成的 `uuid4()` | `memory.py:322-324` | 去重永不触发，同一句话可无限入库（现有 301 条里大量近义条目） | 加 `content_hash TEXT UNIQUE`（规范化后 sha1） |
| 2 | `retrieve` 在 BM25 无命中时直接 `return []` | `memory.py:400-401` | "可选向量检索"实际从未启用（`mem_vec` 0 行） | 先查向量再决定是否返回空 |
| 3 | `persona.control_rule` 在代码里**不存在** | `config.yaml` / `README.md:134` | 文档说"删掉它就不输出标签"，实际规则硬编码在 `core.py:221-234`，改配置无效 | 想关标签就改 `core.py` 那段 |
| 4 | system prompt **没有任何长度预算** | `prompts.py:40-58` | 9k 字人格 + 8 条记忆（单条可达 2000 字）+ 15 条规则 + 摘要，无裁剪；heart 每 2~120 分钟整段重发 | 加 `budget_chars`，记忆按 score 降序填到预算 |
| 5 | `fallback_pet` 的 `bg_color` 参数从不被 `paintEvent` 读取 | `fallback_pet.py:54` | `live2d.bg_color` 是死配置 | 删参数或真用上 |
| 6 | `chat_window._fit_to_screen()` 调用了未定义的 `QApplication_primary_screen` | `chat_window.py:728`（helper 在 `splash.py:105`） | 小屏适配恒失效，`NameError` 被 `except: pass` 吞掉 | 补 helper（`QGuiApplication.primaryScreen()`） |
| 7 | 气泡时间戳恒为 `datetime.now()` | `chat_window.py:476` | 历史消息重放全显示"现在" | 把 `ts` 参数化 |
| 8 | SQLite 单连接 + `check_same_thread=False` + RLock，**无 WAL、无 timeout** | `memory.py:62-65` | GUI 与 heart 两进程各开连接写同一库，默认 5s 忙等，长写会 `database is locked` | `journal_mode=WAL` + `timeout=30` + `_touch` 去抖 |

另有一类"空壳 API"：`Live2DNativeClient.look_at / set_parameter / reset` 全是 `return True`（`live2d_native.py:178-185`），调用方会误以为成功。**不要基于它们写功能。**

## 5. 依赖图（裁剪时照这张图砍）

```
                     ┌──────────────┐
                     │  config.py   │ ← 所有模块的 cfg 来源（YAML + overrides 深合并）
                     └──────┬───────┘
        ┌───────────────────┼─────────────────────┐
        ▼                   ▼                     ▼
   persona.py ──► prompts.py   memory.py ◄── compressor.py
        │                   │        ▲              ▲
        └─────────┬─────────┘        │              │
                  ▼                  │              │
               brain.py ◄────────────┴──────────────┘
                  ▲
                  │   （对象注入，不是 import）
               core.py ──► utils/stickers（唯一 import）
                  ▲
   ┌──────────────┼──────────────┬───────────────┬──────────────┐
search.py    mcp_manager.py   live2d_native.py  services.py   tts/*
                  ▲              ▲                ▲   │
                  └──────────────┴────────────────┴───┘
                                 │
                          main.py（胶水，2,132 行）
                       ┌─────────┴─────────┐
                  gui/chat_window.py    utils/{stickers,tts_voices,console_logs,audio}
                       │
                  gui/{winstyle,splash,first_run}
```

关键事实：**`agent/` 内部几乎没有 import 交叉**（只有 `core.py → utils.stickers`、`services.py → utils.tts_voices`、`tts/gpt_sovits_tts.py → utils.audio`）。所以"只搬 agent/"在物理上是成立的。

## 6. 推荐的三步抽取路线

**第 1 步（半天）—— 无界面脊柱，先跑通文字对话**
拷 `agent/{config,persona,prompts,memory,compressor,brain,core}.py` + `utils/stickers.py`（只为 `sticker_label`，可直接内联）。
用一个 10 行的脚本替代 `main.py`：`load_config()` → `MemoryStore` → `Brain` → `AgentCore(cfg, mem, brain)` → `handle_user_text("你好")`。
验收：能连续对话、重启后历史还在、`data/memory.db` 生成 6 张表。

**第 2 步（一天）—— 加上声音与后台**
拷 `agent/tts/*` + `utils/audio.py` + `services.py` + `utils/tts_voices.py`。
注意 `services.py` 里 `_pid_is_heart/_pid_is_gsv` 的进程名硬编码、`tasklist`/CIM 的 Windows 依赖；非 Windows 要先替换这两块。
验收：GSV 没起来时消息排队、约 90 秒回落 SAPI5；`data/heart.json` 的 `next_wake_at` 单调推进、不出现每 20 秒连调 LLM。

**第 3 步（一天）—— 界面与形象**
GUI：拷 `winstyle` + `splash` + `first_run`，再从 `chat_window.py` 抠 `STYLE`（340 行）+ `MessageBubble`（130 行）+ 气泡流容器（20 行），**不要拷整个文件**。
形象：二选一 —— 复用 `vendor/nori_desktop_pet/`（GPL-3.0）按 `03-live2d-bridge.md` 发 HTTP；或先写一个兼容 `/state /motion /expression /mouth /scale` 的 stub 服务（`Nori_Recreation_Prompt.md:430` 官方推荐），把 GUI 其余功能独立跑起来。

## 7. 如果要"换个名字另起一个项目"

本项目原名 **Aurith**，`scripts/rename_aurith_to_nori.py`（43 行）是当时全局改名的脚本，可作为改名模板。改名要覆盖六类字面量，缺一类就会留暗坑：

1. 目录 / 文件名：`Nori_Live2D_Chat`、`nori_desktop_pet`、`persona/nori.md`、`data/voices/nori/`
2. Python 标识符与默认值：`active_persona: "nori"`、`DEFAULT_PORT`、`persona.py:44-45` 的 `_DEFAULT_FALLBACK` 文案、`"nori 前缀 → Nori"` 的显示名规则
3. 硬编码路径：`config.yaml:119`、`tts_voices.py:22`、`live2d_native.py:21`、`settings_overrides.json` 里的绝对路径
4. 进程名 / PID 校验关键字：`services.py` 的 `_pid_is_heart/_pid_is_gsv`、`pythonw.exe` 路径
5. 提示词里的自称：`persona/*.md`（21 KB × 2）里所有"Nori"，以及 `heart.py` 的私人思考 prompt
6. 日志文件名（`utils/console_logs.py:7-13` 的 `SOURCES`）与 GUI 页签标题

> ⚠️ 改名后 **`data/settings_overrides.json` 里的绝对路径会全部失效**（`ref_audio_path`、`user_avatar`、`runtime_dir`），这是最容易被忘的一处。

## 8. 复用自检清单

搬完任何一块，跑这 6 条：

- [ ] `python -m compileall -q agent gui utils main.py heart.py` 通过（`Nori_Recreation_Prompt.md:416` 的验收标准 1）
- [ ] `QT_QPA_PLATFORM=offscreen python scripts/smoke_gui_new.py` 等冒烟脚本仍能跑（验收标准 2/3）
- [ ] 人格 `.md` 里一个占位符都不写时，时间/记忆/规则仍进入 system prompt（验收标准 6 的反向检查；靠 `memory.inject_context`）
- [ ] 重启后历史会话、图片气泡仍在（验收标准 5）
- [ ] GPT-SoVITS 未启动时，消息排队而不是丢弃；就绪后能朗读
- [ ] Live2D 服务不可用时，界面不卡（任何 HTTP 不在主线程）且能降级

## 附录 A · 按层抽取的现成命令

> 全部是**复制**，不移动、不改动原项目。目标目录换成自己的工程根即可。
> 注意：这些命令只搬 `.py` 源码；`data/`、`vendor/`（263 MB 桌宠宿主）、`persona/` 里的成品人格、语音权重都**故意没搬**。

```powershell
$src = 'D:\Nori_Live2D_Chat'
$dst = 'D:\MyNewProject'

# 第 1 层：无界面智能体脊柱（约 2,000 行，跑通"能记事的对话"）
New-Item -ItemType Directory -Force "$dst\agent","$dst\utils","$dst\persona" | Out-Null
Copy-Item "$src\agent\config.py","$src\agent\persona.py","$src\agent\prompts.py",
          "$src\agent\memory.py","$src\agent\compressor.py","$src\agent\brain.py",
          "$src\agent\core.py" -Destination "$dst\agent"
Copy-Item "$src\utils\stickers.py" -Destination "$dst\utils"     # core.py 只用到 sticker_label
Copy-Item "$src\persona\nori.md" -Destination "$dst\persona"      # 先拿占位人格，再换成自己的

# 第 2 层：声音 + 后台进程（+约 1,900 行）
New-Item -ItemType Directory -Force "$dst\agent\tts" | Out-Null
Copy-Item "$src\agent\tts\*.py" -Destination "$dst\agent\tts"
Copy-Item "$src\agent\services.py","$src\agent\search.py","$src\agent\mcp_manager.py",
          "$src\agent\live2d_native.py" -Destination "$dst\agent"
Copy-Item "$src\utils\audio.py","$src\utils\tts_voices.py","$src\utils\console_logs.py" -Destination "$dst\utils"
Copy-Item "$src\heart.py" -Destination $dst

# 第 3 层：界面零件（只抠组件，不搬 chat_window.py 整体）
New-Item -ItemType Directory -Force "$dst\gui" | Out-Null
Copy-Item "$src\gui\winstyle.py","$src\gui\splash.py","$src\gui\first_run.py" -Destination "$dst\gui"
# 从 chat_window.py 里手工抠：STYLE(:74-415) / MessageBubble(:418-544) / 气泡流容器(:833-844, :2649-2660)

# 千万别搬
#   data\            → 300 MB 运行时数据 + 真实 API Key（settings_overrides.json）
#   vendor\          → 263 MB GPL 桌宠宿主（要的话单独拷，遵守 GPL-3.0）
#   scripts\inori_*  → 与主流程无关的逆向探测脚本
#   gui\chat_window.py（整体）/ gui\pet_window.py / gui\live2d_view.py → 死链或不可拆分
```


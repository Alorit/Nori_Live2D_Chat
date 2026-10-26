# 更新日志（Changelog）

所有对外发布的版本更新记录，最新版本在最上面。

## v0.3.0_bata（2026-10-26）：自主性升级

把 Nori 从「跟随鼠标的立绘」改成「有自己作息、会自己动、偶尔自言自语」的桌宠。方案与评估见 `docs/autonomy-plan.md`。

### 新增

- **秒级反射层 `agent/pet_director.py`（新文件，约 508 行）**：不花 token 的导演。管理 body lock（优先级：说话 100 > 意图 60 > 微动作 20，同一时刻只执行一个，并给动作一个最短驻留时间，避免 1 Hz 抖动）、动作/表情白名单（只发模型真有的名字，发错一次就拉黑）、微动作权重表（早上 / 白天 / 傍晚 / 深夜四档不同偏好）、泊松抖动间隔（不是固定节拍，看起来才不像机器）、作息与睡眠（`quiet_hours` 到点自动切 `sleep_Loop`）、说话预算与冷却（默认每小时 3 句、两句至少隔 45 秒）
- **主人状态感知 `agent/presence.py`（新文件）**：纯本地 Win32，`GetLastInputInfo` 取空闲秒数、`GetForegroundWindow` 取前台应用进程名，**不联网、不截图、不读窗口标题**（`use_window_title: false`）。主人离开 5 分钟她自己去睡，回来时「伸个懒腰」；非 Windows 平台自动降级为空
- **内心 OS 可视化**：heart 把想法写进 `data/heart_events.jsonl`，GUI 按字节偏移增量轮询（文件被截断会自愈），聊天窗里以居中灰色小字气泡显示「💭（情绪）想法」，不打断对话流。`autonomy.inner_os: false` 可关
- **情绪状态机**：`valence / arousal / energy` 三个维度，会随时间衰减回基线；情绪影响微动作权重（低落时少 `wakuwaku`），也会写进 prompt 影响台词
- **人格摘要缓存**：把 8.8k 字符的人格 md 压成约 400 字摘要供自主回合使用，按内容哈希缓存（`data/heart_persona_digest.json`），人格没改就不再花钱
- `config.yaml` 新增 `autonomy:` 段（约 20 项可调参数，每项都有注释）

### 修复（自主性）

- **自主回合的动作/表情几乎全部失效**：`persona.emotion_map` 里 7 个中文情绪全部指向旧 `nori` 模型的表情（「爱心眼」「圈圈眼」「黑化」…），arg-nori 里根本没有，7/7 解析失败；`motion_map` 的「挥手」「鞠躬」也不存在（2/5 失败）。全部改成 arg-nori 的真实名字（`happy / troubled / surprised / shy / angry / serious / doubt`，`wakuwaku / nod`）
- **heart 的唤醒间隔被浪费**：原来每次醒来只发一个动作就睡回去，一次对话都没有；现在每次唤醒产出一份**带时间轴的剧本**（`at` 秒 + 动作/表情/台词），交给导演在接下来几分钟里陆续执行
- **自主回合的 prompt 太重**：每次唤醒都塞完整人格（约 5.2k tokens 输入）。改用人格摘要 + 精简上下文后，实测**输入 853 tokens / 输出 153 tokens**，一次唤醒约 2 秒；人格摘要本身只在人格改动后重算一次
- **`reasoning` 吃光 `max_tokens` 导致摘要为空**：`deepseek-flash` 是推理型，2000 的输出上限会被思考过程吞掉，`finish_reason=length` 且 `content` 为空。摘要上限提到 8000，思考上限提到 3000，并在首次失败后自动翻倍重试
- 模型配置里的 `deepseek-v4-flash` 在这个 API 上不存在（404），改为 `deepseek-flash`，`api_model_combo` 的预置项同步换成 `deepseek-flash / deepseek-v4-pro`

### 优化（自主性）

- 聊天窗新增 `append_thought()`：内心 OS 用独立的 `#InnerOS` 样式（居中、灰字、虚线上边框），不参与 `append_system` 的日志流

### 同一版本内的 GUI 修复与打磨（2026-10-25 批）

本轮是「轻量修 bug + 局部打磨」，不改变整体风格与配色，与自主性改动一起并入 v0.3.0_bata。

#### 修复

- **设置页的子页签栏会跟着内容一起滚走，其它页的底部按钮被顶到视口外**：原来把整个内层 `QTabWidget` 塞进一个 `QScrollArea`，所有页共用最高页（基础设置）的高度 —— 于是「聊天记录」页底部的 `打开到聊天 / 重命名 / 删除`、「人格」页的 `保存 / 恢复默认`、「记忆」页的「行为规则」区，不滚到最下面根本看不见。现在每个设置页各包一层滚动区，页签栏固定在顶部，切换页签各自保留滚动位置
- **小屏幕下窗口自适应从来没生效过**：`_fit_to_screen()` 里调用的是未定义的 `QApplication_primary_screen()`（它只存在于 `gui/splash.py`），`NameError` 被 `except: pass` 静默吞掉。改用 `QApplication.primaryScreen()`
- **回放历史记录时所有消息都显示成「现在」**：气泡时间戳写死 `datetime.now()`。现在按消息自身的 `ts` 显示，当天只显示 `HH:MM`，跨天显示 `MM-DD HH:MM`，跨年显示日期
- **把界面字号调到 13px 以外的值后，输入框字号不变**：QSS 里 `QLineEdit#MessageInput` 也写了一处 `font-size: 13px`，而 `_style_for_font` 只替换第一处。去掉输入框里的写死字号，改为继承窗口基础字号
- **宠物大小和滑块偶发对不上**：`set_current_settings()` 把配置值钳到 `3.0`，但滑块范围是 `0.5~2.0`，超出部分被静默截断并污染显示值。钳位与滑块范围对齐为 2.0
- **记忆去重从未真正生效**：`memories` 表的唯一键只有每次新生成的 `uuid4()`，`INSERT OR IGNORE` 什么都不会忽略，同一句话可以无限堆积。现在按内容去重：重复写入改为提升重要度并刷新时间，不再新增行
- **控制台「live2d」来源永远空白**：日志表指向 `live2d_native.log`，但从来没有人写这个文件（实际存在的是旧 MCP 应用留下的 `live2d_mcp.log`）。现在拉起 .NET 桌宠时把它的 stdout/stderr 重定向到 `data/logs/live2d_native.log`，桌宠启动失败 / 崩溃能在控制台里看到痕迹
- **状态文件可能写成半截 JSON**：`data/heart.json`、`data/settings_overrides.json` 与 `persona/` 下的人格文件 / `data/persona_active.json` 改为「先写临时文件再 `os.replace`」的原子写；`heart.json` 读坏时不再静默回落，会记一条 warning 并把损坏文件另存为 `.broken.json`
- 主程序不再直接调 GUI 私有方法：新增 `ChatWindow.refresh_console()` 公开方法（`main.py` 原调用 `_refresh_console()`）

#### 优化（GUI）

- **基础设置页排版**：表单限制最大宽度（1040px）并居中，输入框不再横跨整窗；`应用并保存` 一类按钮恢复自然宽度（原来会被拉伸成 400px 宽的大渐变条）；「获取模型列表」不再孤零零居中；TTS 语音包四个按钮收成一行；语速 / 宠物大小滑块的数值不再被挤到屏幕最右边
- **聊天记录页**：会话卡片补上背景与描边（原来只有当前会话有框，其它行看起来就是两行纯文本），当前会话高亮更明显，卡片内边距放宽
- **MCP / Skills 页**：空列表给出占位说明，不再是一整块黑
- **人格编辑器**改用等宽字体（Markdown 更好读）
- 聊天输入框占位文案缩短（「输入消息，回车发送（可拖入图片）…」），窄窗口下不再被截断
- 记忆页「新增记忆」行在窄窗口下不再挤压按钮

---

## v0.2.2（2026-09-13）

### 修复

- **GPT-SoVITS 起不来导致 Nori 完全没有声音**：推理配置 `GPT_SoVITS/configs/tts_infer.yaml` 里的权重路径在项目目录改名 / 搬家后仍是旧路径，服务启动即 `FileNotFoundError` 退出，界面永远停在「⏳ 冷启动中」。现在启动前会自检权重路径是否有效，失效时自动用当前语音包重写（`agent/services.py` 新增 `repair_gsv_weights()`）
- **Windows SAPI5 兜底永远不可达**：`tts.order` 只列了主后端时 `create_tts()` 根本不会尝试 system 后端。现在候选链保证带上 system（`tts.allow_system_fallback: false` 可关），首选后端约 90 秒仍不就绪时自动回落并朗读排队消息；冷启动期间仍保持「排队等 Nori 音色」的原有体验
- **应用语音包会把参考文本写空**：语音包目录没有 `prompt.txt` / `meta.json` 时，`prompt_text` 被写成空串并覆盖 `config.yaml` 里的有效值，GPT-SoVITS 退回「无参考文本」模式，音色与韵律明显劣化。现在缺参考文本时保留已有值，并支持语音包 `meta.json` 的 `prompt_lang`
- **长期记忆 / 行为规则 / 滚动摘要 / 当前时间完全不注入**：人格 `.md` 里一个占位符都没写时（成品人格很常见），这些动态上下文一律不进 System Prompt，记忆功能对模型等于不存在。现在会自动拼成一段附在末尾，可用 `memory.inject_context: false` 关掉
- **Heart 可能无限唤醒、持续消耗额度**：模型返回 `next_wake_minutes: null` 或带单位文本时 `int()` 抛异常，`next_wake_at` 不推进，于是每个轮询间隔（默认 20 秒）都重调一次 LLM。现已兜底到默认值，并且私人思考返回非 JSON 对象时只跳过本轮
- **跨人格会话的「聊天记录消失」**：打开 / 新建别人格的会话、或删除当前人格后，消息按生效人格入库、却按会话人格读取，重开会话显示为空。现在打开 / 新建会话会先切到该会话所属人格，删除人格后自动重建会话指针
- **朗读结束必抛 `AttributeError`**：`_tts_retry_timer` 未初始化就被 `.stop()`（`run.bat` 用 pythonw，异常被完全吞掉）

### 优化

- **界面不再被后台操作卡死**（主线程阻塞全部移出）：Live2D 窗口控制（原最坏忙等 30 秒）、服务启停（tasklist / PowerShell 单次 8~12 秒）、「🔄 获取模型列表」（30 秒网络请求）、口型同步（原每 60ms 一次 HTTP）、完全退出（改为后台停服务 + 12 秒硬顶）
- 退出时先等在飞的发送 / 整合任务收尾再关数据库，避免最后一轮对话静默丢失；点 × 完全退出时不再重复停一遍 Heart（省掉一次全进程扫描）
- 人格 / 会话相关的状态提示更明确：打开别人格会话会提示「已切换到人格 X」

### 变更

- **README 只保留最新版本的更新内容**，历史更新统一记录在本文件
- Release 完整包名改为通配写法 `Live2D_agent_byAlorit_v*.zip`，不再随版本号硬编码

### 文档

- `config.yaml` 模板新增 `tts.allow_system_fallback`（默认 true）与 `memory.inject_context`（默认 true）两项说明
- README 补充「人格没写占位符时会自动附加动态上下文」的说明

---

## v0.2.1（2026-09-07）

### 新增

- **首次使用向导**：第一次启动弹窗询问「怎么称呼你」（默认“主人”），保存后 Heart 私人思考同步使用该称呼，不再写死主人名字；随时可在 设置 → 基础设置 修改
- **Nori 头像作为应用图标**：任务栏 / 标题栏 / Alt-Tab 显示 Nori 头像（进程级 AppUserModelID + 全局窗口图标），不再是默认 Python 图标
- **Release 附带 Nori TTS 语音包**（`Nori_TTS_Voice_nori.zip`）：GPT-SoVITS 微调权重（`nori_s1.ckpt` / `nori_s2.pth`）+ 参考音频 `nori_ref.wav` + 试听样本，解压到 `data/voices/` 即可使用
- 新增 `gui/winstyle.py`：Windows 原生标题栏暗色化工具

### 优化

- **右上角 × 即完全退出**：移除「⏻ 完全退出」按钮，关闭窗口自动停止 Heart / GPT-SoVITS / Live2D 并退出程序
- 移除界面内「🎀 Nori 控制台」大标题，信息交由系统标题栏
- **原生标题栏融入界面**：Win11 直接同色渲染，Win10 沉浸式深色，顶部白条不再突兀
- **聊天记录页重做**：
  - 会话改为卡片式双行显示（标题 + ★主对话 / 消息数 / 「刚刚 / N 分钟前」相对时间）
  - 新增按名称实时筛选会话的搜索框与空状态提示
  - 支持右键菜单操作（打开 / 重命名 / 删除），修复双击触发两次打开的问题

### 变更

- **TTS 精简**：仅保留 GPT-SoVITS（Nori 音色）+ Windows SAPI5 兜底，移除 sherpa / piper / edge 后端与对应模型下载脚本
- 语音包导出目录可在 设置 → 基础设置 自定义（不再写死 `D:/Download`，默认系统下载目录）

### 修复

- 语速滑块失效：语速统一保存到 `tts.speed`，GPT-SoVITS 后端正确跟随（旧版写在已删除的 `tts.sherpa.speed` 下）

## v0.2.0（2026-09-01）

- **彻底移除旧 MCP Live2D 方案**（Electron / `live2d_mcp_app`）
- **切换为原生 Live2D 控制器**：
  - 使用 [Nori-Desktop-Pet](https://github.com/MF-Dust/Nori-Desktop-Pet)（.NET Avalonia + OpenGL）作为桌宠渲染与控制模块
  - Python 通过本地 HTTP `http://127.0.0.1:47835` 控制模型、表情、动作、口型、窗口、缩放
  - 新增 `--pet-only` 独立桌宠模式，不再拉起 WebView / MCP 主界面
- **LLM 模型列表改为「获取模型列表」**：
  - 设置页新增 `🔄 获取模型列表`，从当前 OpenAI 兼容 Base URL 拉取模型（支持 DeepSeek / Ollama / 其它兼容服务）
  - 保留本地自定义模型与当前模型选择
- **缩放上限锁为 2.0x**：
  - 滑块范围 `0.5x ~ 2.0x`
  - 原生侧同步限制 `0.1x ~ 2.0x`
  - 缩放时窗口改为底部（脚底）锚定，避免放大时角色“向上跑”
- 清理旧 MCP Live2D 相关文件、脚本与文档残留
- 更新 `README`、`DISCLAIMER`、`LICENSE`，补充参考项目与贡献者

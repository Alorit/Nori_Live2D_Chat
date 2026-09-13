# 更新日志（Changelog）

所有对外发布的版本更新记录，最新版本在最上面。

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

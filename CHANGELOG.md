# 更新日志（Changelog）

所有对外发布的版本更新记录，最新版本在最上面。

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

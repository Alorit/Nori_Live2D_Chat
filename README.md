# Nori_Live2D_Chat v0.2.1

一个由 **Alorit 与 AI/Agent 协作完成** 的 Windows 桌面 AI 宠物 / 陪伴助手项目（Nori AI 桌面宠物）。

![展示图]<img width="2560" height="1600" alt="屏幕截图(81)" src="https://github.com/user-attachments/assets/2f2db406-1b8d-4a7a-8644-54ce83f4d527" />


> ⚠️ 本项目是粉丝自制项目，与 I_NORI 官方无关。
> 展示图仅用于效果展示，相关角色与人格版权归原权利方所有。
> 本仓库 **不包含** 任何 Live2D 模型、人格文件,如需要请加官方QQ群在群文件中获取：**1041616195**；**Nori TTS 语音包（粉丝训练的 GPT-SoVITS 微调权重）随 Release 附件提供**，仅限个人学习 / 研究，禁止商用、禁止再训练或二次分发——详见 [DISCLAIMER.md](DISCLAIMER.md)「Nori TTS 语音包」条目。

---

## ✨ v0.2.1 更新内容

- **首次使用向导**：第一次启动弹窗询问「怎么称呼你」（默认“主人”），保存后 Heart 私人思考同步使用该称呼，不再写死主人名字；随时可在 设置 → 基础设置 修改
- **界面全面优化**：
  - 任务栏 / 标题栏 / Alt-Tab 图标换成 Nori 头像（不再是默认 Python 图标）
  - 移除「⏻ 完全退出」按钮：**右上角 × 直接完全退出**（自动停止 Heart / GPT-SoVITS / Live2D）
  - 移除界面内「🎀 Nori 控制台」大标题，信息交由系统标题栏
  - Windows 原生标题栏暗色化（Win11 直接同色，Win10 沉浸式深色），顶部白条融入界面
  - **聊天记录页重做**：卡片式会话（标题 + ★主对话 / 消息数 / 相对时间）、按名称实时筛选、右键菜单操作、空状态提示
- **TTS 精简与修正**：
  - 仅保留 GPT-SoVITS（Nori 音色）+ Windows SAPI5 兜底，移除 sherpa / piper / edge 后端
  - 语速统一保存到 `tts.speed`（修复旧版语速滑块失效的问题）
  - 语音包导出目录可在 设置 → 基础设置 自定义（不再写死 `D:/Download`）
- **Release 附带 Nori TTS 语音包**（`Nori_TTS_Voice_nori.zip`，GPT-SoVITS 微调权重 + 参考音频），下载解压到 `data/voices/` 即可在设置里切换

> 📜 完整更新历史见 [CHANGELOG.md](CHANGELOG.md)。

---

## 🧩 功能特性

- **API 驱动**：OpenAI 兼容接口，`api_key` 留空配置，填入即用
- **原生 Live2D 控制**：LLM 在回复里输出 `[expr:开心]` / `[motion:挥手]` 标签，程序解析后通过 **Nori-Desktop-Pet** 的本地 HTTP 接口驱动模型表情和动作；TTS 说话状态也会推给 Live2D 做口型
- **本地 TTS 语音**：GPT-SoVITS + **Nori 音色**（微调权重随 Release 附件提供，见下方安装说明）；不可用时可改用 Windows SAPI5 兜底
- **长期记忆**：SQLite + BM25 / 可选向量检索，按人格隔离
- **定时记忆回顾**：自动 LLM 总结 + 相似记忆合并
- **持续学习闭环**：反思整合、👍👎 反馈、记忆遗忘、JSONL 导出
- **Heart 自主唤醒进程**：AI 定时私人思考、主动说话/表情/动作（**正在测试中，可能功能异常**）
- **MCP / Skills 工具扩展**：支持 `streamable_http` / `sse` / `stdio`
---

## 📦 环境要求

- Windows 10 / 11（Linux 也能跑，但 Live2D 透明窗口效果最佳在 Windows）
- Python 3.10+（在 3.14 上测试通过）
- 无需 .NET SDK / 运行时（**Release 完整包**已内置自包含原生 Live2D 宿主）

---

## 🚀 快速开始

> 📦 **推荐**：直接从 [Releases](https://github.com/Alorit/Nori_Live2D_Chat/releases) 下载 `Live2D_agent_byAlorit_v0.2.1.zip` 完整包（已内置 Live2D 宿主，解压即用）。
> 若你选择 **git 克隆本仓库**：请先从 Release 完整包中把 `vendor/` 目录复制到项目根目录（或自行构建 [Nori-Desktop-Pet](https://github.com/MF-Dust/Nori-Desktop-Pet)），否则 Live2D 窗口不会显示（纯对话框模式不受影响）。

```bat
:: 首次安装依赖
setup_venv.bat

:: 启动
run.bat
```

也可以手动：

```bat
py -3 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

### 原生 Live2D 宿主（Release 完整包内置）

**Nori-Desktop-Pet** 原生宿主为**自包含预编译**版本，随 Release 完整包（`Live2D_agent_byAlorit_v*.zip`）内置：

- 位置：`vendor/nori_desktop_pet/`（体积较大，**不入 Git**，仅随 Release 完整包分发）
- git 克隆用户：从 Release 完整包复制 `vendor/` 到项目根目录，或自行构建
- **无需额外安装 .NET 运行时**
- 运行 `run.bat` 后，Python 会自动以 `--pet-only` 拉起内置原生桌宠

### 配置 API Key

首次使用前运行 `run.bat`，然后在 **设置 → 基础设置** 里填写：

- DeepSeek API Key（聊天）
- 百度搜索 API Key（联网搜索，可选）
- 视觉 MCP API Key（火山方舟，可选，保存到 `vision_mcp/config.json`）

`config.yaml` 不保存真实 Key，敏感配置写入 `data/settings_overrides.json` 或使用环境变量。

### 安装 Nori 语音包（TTS 音色）

1. 到 [Releases](https://github.com/Alorit/Nori_Live2D_Chat/releases) 下载 `Nori_TTS_Voice_nori.zip`
2. 解压到项目的 `data/voices/` 下，得到 `data/voices/nori/`（内含 GPT-SoVITS 微调权重 `nori_s1.ckpt` / `nori_s2.pth` 与参考音频 `nori_ref.wav`）
3. 在 `config.yaml` 填写 GPT-SoVITS 安装目录（`tts.gpt_sovits.runtime_dir`），启动后 GUI 会自动拉起 API 并使用 Nori 音色
4. 也可以在 设置 → 基础设置 → TTS 语音包 里导入 / 切换其它音色

---

## 🗂 目录结构

```
Nori_Live2D_Chat/
├── main.py                 # 程序入口
├── config.yaml             # 非敏感配置
├── agent/                  # Agent 核心
│   ├── live2d_native.py    # 原生 Live2D 控制器客户端
│   ├── brain.py            # DeepSeek 调用 + 标签解析
│   ├── core.py             # 学习闭环编排
│   ├── memory.py           # 长期记忆
│   └── ...
├── gui/                    # PySide6 界面
├── utils/                  # 工具
├── persona/                # 人格文件（自行填写）
├── vision_mcp/             # 独立视觉 MCP
├── scripts/                # 工具与测试
├── data/                   # 运行时数据（默认头像/表情包等）
├── vendor/                 # 原生 Live2D 宿主（不入 Git，随 Release 完整包分发）
├── DISCLAIMER.md           # 免责声明
├── LICENSE                 # MIT License
└── requirements.txt
```

---

## 📚 参考项目与致谢

本项目在开发过程中参考、使用或受到了以下项目的启发：

| 项目 / 组织 | 说明 | 协议 |
|---|---|---|
| [Nori-Desktop-Pet](https://github.com/MF-Dust/Nori-Desktop-Pet) | 使用的原生 Live2D 桌宠宿主（.NET Avalonia + OpenGL） | GPL-3.0（以该仓库 LICENSE 为准） |
| [Live2D Cubism SDK](https://www.live2d.com/) | Live2D 模型渲染 SDK | 以 Live2D 官方许可为准 |
| [mitscherlich/live2d-mcp](https://github.com/mitscherlich/live2d-mcp) | v0.1 使用的 Live2D MCP / Electron 参考实现（v0.2 已移除） | 以该仓库 LICENSE 为准 |
| [GPT-SoVITS](https://github.com/RVC-Boss/GPT-SoVITS) | 本地 TTS 推理框架 | MIT License |

**致谢与版权声明**：Nori-Desktop-Pet 由 [erhiolab](https://github.com/erhiolab)（洱海）、[MF-Dust](https://github.com/MF-Dust)、[qicajie](https://github.com/qicajie)、[SakuraStar](https://github.com/SakuraStar) 等开发/维护；[mitscherlich](https://github.com/mitscherlich) 为 live2d-mcp 作者；Live2D Inc. 为 Live2D Cubism SDK 版权方；GPT-SoVITS 版权归其项目作者。

### 贡献者

- [Alorit](https://github.com/Alorit)：项目作者、整体架构、Python 主程序与集成

完整致谢与版权声明见 [ACKNOWLEDGEMENTS.md](ACKNOWLEDGEMENTS.md)。

---

## 📄 开源许可证

- **本项目（Python 主程序）**：代码部分使用 **MIT License**，详见 [LICENSE](LICENSE)
- **Nori-Desktop-Pet（原生 Live2D 宿主）**：使用 **GPL-3.0**，详见 [Nori-Desktop-Pet LICENSE](https://github.com/MF-Dust/Nori-Desktop-Pet/blob/main/LICENSE)
- **Live2D Cubism SDK**：Release 完整包内的宿主程序内嵌 Cubism Core 运行时，其分发与使用遵循 Live2D Cubism SDK 官方发布许可，使用前请自行确认
- **GPT-SoVITS**：**MIT License**
- **Nori TTS 语音包 / 默认头像 / 展示图**：I_NORI 相关粉丝训练 / 粉丝素材，仅限个人学习与研究，禁止商用与二次分发，详见 [DISCLAIMER.md](DISCLAIMER.md)
- **其它第三方资产**：版权归原权利方所有
- 完整风险提示与免责声明见 [DISCLAIMER.md](DISCLAIMER.md)

---

## ⚠️ 免责声明

本项目为粉丝自制、非官方项目，与 I_NORI、Live2D、GPT-SoVITS 官方均无隶属或授权关系。使用前请阅读 [DISCLAIMER.md](DISCLAIMER.md)。

- Git 仓库本体不包含任何 Live2D 模型、人格 `.md` 文件与 API Key
- **Nori TTS 语音包随 Release 附件提供**：粉丝使用 I_NORI 语音样本训练的 GPT-SoVITS 微调权重，仅限个人学习 / 研究，禁止商用、禁止再训练或二次分发；权利方如有异议请通过 Issues 联系，确认后 72 小时内删除
- 仓库内置的默认头像 `data/avatars/nori_avatar.png` 为 I_NORI 角色图片，仅作占位展示，版权归原权利方所有

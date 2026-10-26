# GUI 层中值得重复使用的部分（PySide6 桌面宠物 GUI 组件库）

> 只读分析报告。目标项目：`D:\Nori_Live2D_Chat`（Python + PySide6，中文界面）。
> 分析期间未修改目标目录下任何文件；行号均为文件实际行号。
> 为确认「谁创建谁、谁 connect 谁」，额外**只读**查看了 `main.py`，相关结论均标注 `main.py:行号`（超出指定范围，仅作接线核对）。

## 0. 范围与行数核对

| 文件 | 任务给定 | 实测 | 备注 |
|---|---|---|---|
| `gui/chat_window.py` | 2453 行 | **2689 行** | 以实测为准，差异 236 行 |
| `gui/pet_window.py` | — | 200 行 | |
| `gui/live2d_view.py` | — | 144 行 | |
| `gui/fallback_pet.py` | — | 262 行 | |
| `gui/splash.py` | — | 111 行 | |
| `gui/first_run.py` | — | 114 行 | |
| `gui/winstyle.py` | — | 44 行 | |
| `utils/stickers.py` | — | 202 行 | |

结论先行：**这套 GUI 的「气泡 + 霓虹 QSS + 无边框透明窗 + 右键菜单（注意：无系统托盘，见 1.3）+ QWebEngine 嵌入 + QPainter 兜底宠物 + splash + 向导 + 原生标题栏染色」是一个可拆分的通用件，但当前仓库里只有 `ChatWindow`、`SplashWindow`、`FirstRunDialog` 真正接线在主程序上；`PetWindow` 整条宠物渲染链已被主程序停用（`main.py:392` 把 `self.pet` 直接置 `None`，`pet_window` 在整个仓库里没有第二个 import）。**

## 1. 窗口体系

### 1.1 类清单

| 类 | 位置 | 基类 | 职责 | 当前是否被主程序使用 |
|---|---|---|---|---|
| `SplashWindow` | `gui/splash.py:9` | `QWidget` | 无边框 / 半透明 / 置顶启动页，`QProgressBar` + QPainter 玻璃底 | 是，`main.py:2089` |
| `FirstRunDialog` | `gui/first_run.py:44` | `QDialog` | 首次运行问「怎么称呼你」，返回 `user_name` | 是，`main.py:445` |
| `ChatWindow` | `gui/chat_window.py:564` | `QWidget` | 主控制台：聊天页 + 设置页（六个子页签：基础/记录/人格/记忆/MCP/控制台） | 是，`main.py:391` |
| `MessageBubble` | `gui/chat_window.py:418` | `QWidget` | 单条 QQ/微信式气泡（头像 + 名字 + tag + 时间 + 圆角框 + 图文） | 由 `ChatWindow._append_bubble` 创建（`:2645`） |
| `_WheelGuard` | `gui/chat_window.py:547` | `QObject` | 事件过滤器：吞掉设置控件上的滚轮、转发给滚动区 | `ChatWindow._install_wheel_guard`（`:738`） |
| `PetWindow` | `gui/pet_window.py:15` | `QWidget` | 无边框透明置顶桌宠：语音气泡 + 渲染器（Live2D/兜底）+ 右键菜单 | **否**（见 1.2） |
| `Live2DView` | `gui/live2d_view.py:100` | `QWebEngineView` | 内嵌 HTML 渲染 Live2D，透明背景 | 仅被 `PetWindow` 用 |
| `Live2DBridge` | `gui/live2d_view.py:66` | `QObject` | 暴露给 JS 的桥对象（6 个信号 + 6 个 `@Slot`） | 同上 |
| `FallbackPet` | `gui/fallback_pet.py:39` | `QWidget` | 纯 QPainter 的 Q 版形象：7 种表情 / 5 种动作 / 眨眼 / 说话口型 / 拖拽 | 仅被 `PetWindow` 用 |
| `apply_dark_title_bar()` | `gui/winstyle.py:16` | 函数 | 把 Win10/11 原生标题栏染成暗色（DWM） | `ChatWindow.showEvent:2667`、`FirstRunDialog.showEvent:110` |

### 1.2 创建关系与当前接线真相

```text
main.py / AppController（GUI 主线程）
├─ SplashWindow            splash.py:9       main.py:2089 创建；main.py:2127 finish()
├─ FirstRunDialog          first_run.py:44   main.py:445 模态 exec()
└─ ChatWindow              chat_window.py:564 main.py:391
   ├─ MessageBubble × N    chat_window.py:418
   └─ _WheelGuard          chat_window.py:547

（代码存在但未接线）
PetWindow                   pet_window.py:15   ← 全仓库无 import；main.py:392 self.pet = None
├─ Live2DView → Live2DBridge live2d_view.py:100 / :66
└─ FallbackPet             fallback_pet.py:39
```

- `PetWindow` 的 4 个能力（`show_bubble:130`、`apply_commands:144`、`set_speaking:160`、`reload_model:181`）在主程序里仍有调用点（`main.py:785` `self.pet.show_bubble(...)`），但因为 `self.pet` 恒为 `None`，全部走不进分支。
- 主程序现在用的是**另一个进程**里的原生桌宠（`agent/live2d_native.py`，HTTP 打到 `http://127.0.0.1:47835`，`:32`）。所以「QWebEngine 内嵌 Live2D」这条路在本仓库是**孤儿代码**，它依赖的 `D:\Nori_Live2D_Chat\live2d\index.html` **目录不存在**（已用文件系统核对，全仓库只有 `vendor/nori_desktop_pet/wwwroot/index.html`，且其中没有 `window.neuroLoadModel` 等函数）。

### 1.3 通信方式

| 方向 | 机制 | 证据 |
|---|---|---|
| GUI → 主程序 | 纯 `Signal`，命名统一为 `xxx_requested` / `xxx_emit`；`main.py:463-522` 一次性批量 connect | `chat_window.py:565-630`（约 60 个信号） |
| 主程序 → GUI | 直接同步方法调用（`set_*` / `append_*` / `apply_*`），无命令队列 | `main.py` 里 200+ 处 `self.chat.set_xxx(...)` |
| 宠物渲染器 | `PetWindow` 对 `self.renderer` 做**鸭子类型**调用（`set_expression/set_motion/set_speaking/set_scale/load_model`），Live2D 与 FallbackPet 同签名 | `pet_window.py:144-183` |
| JS ↔ Python | `QWebChannel` 注册 `"bridge"`（`live2d_view.py:103-106`）+ `page().runJavaScript()` 单向调用（`:140-144`） | 两个方向都只有 6 个出入口 |
| 线程/队列 | **GUI 包里一个线程都没有**（无 `QThread`/`QThreadPool`/`QtConcurrent`）；后台任务全在 `main.py:76-325` 的 `QRunnable + WorkerSignals` | `chat_window.py`、`pet_window.py` 无 threading import |
| 托盘 | **不存在**：全仓库 grep 不到 `QSystemTrayIcon`；`PetWindow` 只有右键 `QMenu`（`pet_window.py:186-195`） | 已在 `gui/` 与 `main.py` 搜索确认 |

## 2. 可复用组件清单

### 2.1 聊天气泡 `MessageBubble`（最值得抄的一块）

- **是什么**：一条完整消息行：左/右对齐、36px 圆形头像（图片自动裁圆，否则显示 emoji）、名字（可配颜色）、tag 徽章（`MASTER` / `NORI // NEURAL LINK`）、`HH:MM` 时间、圆角气泡框、多图缩略图 + 文本，文本可鼠标选中。
- **源位置**：类 `gui/chat_window.py:418`；构造 `:421-505`；圆形头像 `:433-450`；气泡 `QFrame` + objectName `:457-461`；头部（名字/tag/时间）`:463-479`；图片插入 `:482-483`；文本 `:485-493`；最大宽 620 / 尺寸策略 `:495-496`；左右布局 `:498-505`；图片/ GIF 缩略图静态方法 `:507-544`。
- **配套 QSS**：`#UserBubble` / `#AIBubble` 在 `chat_window.py:143-163`，用**不对称圆角**做「小尖角」：右侧消息 `border-radius:14px 4px 14px 14px`，左侧消息 `4px 14px 14px 14px`，再各加一条 3px 的加粗单边（`border-right:3px solid #38bdf8` / `border-left:3px solid #8b7cf6`）。
- **依赖**：`PySide6.QtWidgets.QFrame/QLabel/QHBoxLayout/QVBoxLayout`、`QtGui.QPainter/QPainterPath/QPixmap`、`QtCore.Qt`、`datetime`、`pathlib.Path`。**不依赖** `cfg`、不依赖任何业务模块 → 可直接抽成独立文件。
- **复用方式**：**直接 import**（建议原样抽出 `MessageBubble` + `_make_image_label` + 两段 QSS，约 130 行）。若目标程序有自己的样式体系，只保留 `_make_image_label` 与圆角裁剪即可。
- **耦合/注意**：
  - 时间戳是 `_datetime.now()`（`:476`），**不是消息自身时间**；`set_chat_history`（`:2590-2601`）重放历史时，所有旧消息都会显示成「现在」。要复用得把 `ts` 参数化。
  - 头像尺寸 36、裁剪 34、气泡最大宽 620、图片上限 300×240 全是硬编码（`:432`、`:437`、`:495`、`:508`）。
  - GIF 用 `QMovie` 且靠 `label._movie = movie` 保引用（`:534`），漏了就会被 GC 掉变白框。
  - tag 文案由调用方拼（`append_assistant` 里 `f"{self._agent_name.upper()} // NEURAL LINK"`，`:2632`），中英文混排。

**核心片段（`chat_window.py:433-449`，17 行，圆形头像裁剪）**：

```python
avatar_path = Path(avatar)
if avatar_path.is_file():
    try:
        pix = QPixmap(str(avatar_path)).scaled(
            34, 34, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        rounded = QPixmap(34, 34)
        rounded.fill(Qt.transparent)
        painter = QPainter(rounded)
        painter.setRenderHint(QPainter.Antialiasing, True)
        clip = QPainterPath()
        clip.addEllipse(0, 0, 34, 34)
        painter.setClipPath(clip)
        painter.drawPixmap(0, 0, pix)
        painter.end()
        avatar_label.setPixmap(rounded)
    except Exception:
        avatar_label.setText("🧑" if align_right else "🐱")
```

### 2.2 深色霓虹样式表 `STYLE` + 配色

- **是什么**：一份 ~340 行的整窗 QSS（`chat_window.py:74-415`），覆盖 `QTabWidget/QTabBar`、`QTextBrowser`、`QScrollArea`、`QPlainTextEdit/QLineEdit/QTableWidget/QListWidget`、`QHeaderView`、`QPushButton`（含 `#SendButton/#PrimaryButton/#DangerButton/#SaveButton/#LikeButton/#DislikeButton` 六种语义色）、`QGroupBox#PanelBox`、`QComboBox`、`QSlider`、`QCheckBox`、`QDoubleSpinBox`、`QScrollBar`、`QMenu`、`QListWidget#HistoryList`、`QToolTip`、`QMessageBox`、气泡两种。
- **源位置**：`chat_window.py:74-415`；局部补充样式在 `:449-454`（头像）、`:470-473`（tag）、`:512-515`（图框）、`:1448-1451`（控制台等宽字体）、`:2526-2530`（表情菜单）、`pet_window.py:58-63`（宠物气泡）、`splash.py:28-63`（启动页）、`first_run.py:21-41`（向导）。
- **配色（散落，没有集中常量，抄的时候建议自己收成 dict）**：
  - 底：`#060a18` / `#0a1026` / `#0d1230` 竖向渐变（`:76-77`）
  - 薄荷主色 `#a7f3d0`；天蓝 `#7dd3fc` / `#67e8f9` / `#38bdf8`；紫 `#a78bfa` / `#8b7cf6` / `#c4b5fd`；正文 `#d7e3ff` / `#cfe6ff` / `#9fc6ff`；次要 `#8fa6d8` / `#52638c`
  - 面板 `#0c1530` / `#101b3a` / 选中 `#123c54`；描边统一 `rgba(103,232,249,0.3 左右)`
  - 语义：发送键是绿→青→蓝渐变（`:231-239`），主按钮青→靛（`:260-266`），危险按钮暗红 `#45121f`+`#fda4af`，保存按钮琥珀 `#fcd34d`
- **依赖**：零 Python 依赖，纯字符串。**复用方式：复制代码**（不要 import 整个 `chat_window`，那会连带拖进 `main.py` 级别的重依赖）。
- **耦合**：靠 `objectName` 生效 —— 复用时必须保留 `ChatWindow/HeaderTitle/StatusPill/ChatScroll/UserBubble/AIBubble/BubbleText/BubbleMeta/MessageInput/SendButton/PanelBox/HistoryList/...` 这一整套命名，否则样式静默失效；`STYLE` 里第一条是 `QWidget#ChatWindow`，窗口必须 `setObjectName("ChatWindow")`（`:639`）。

### 2.3 气泡流容器 + 自动滚底

- **是什么**：`QScrollArea`（`#ChatScroll`）里放一个 `QWidget`，`QVBoxLayout` 末尾留一根 `addStretch(1)`，新气泡**插在 stretch 之前**；插入后用两次 `QTimer.singleShot` 滚到底。
- **源位置**：容器构建 `chat_window.py:833-844`；插入 `:2649`；双延迟滚动 `:2651-2652`；滚底实现 `:2654-2660`；清屏 `:2583-2588`（保留最后一个 item 即 stretch）。
- **依赖**：仅 QtWidgets。**复用方式：复制代码**（20 行）。
- **耦合**：`clear_chat` 的 `while count() > 1` 假定「stretch 永远是最后一项」，任何往末尾追加 widget 的改动都会打断它；`_scroll_chat_to_bottom` 里 `log_content.adjustSize()` + 读 `verticalScrollBar().maximum()`，必须等布局两轮，所以延迟 0ms 和 80ms 各滚一次（源码注释 `:2650` 已说明）。

### 2.4 无边框透明置顶窗口骨架 `PetWindow`

- **是什么**：`Qt.FramelessWindowHint | Qt.Tool`（可选 `WindowStaysOnTopHint`）+ `WA_TranslucentBackground`；顶部一个自适应宽度的白底语音气泡 `QLabel`；其余区域交给渲染器；右键菜单「显示/隐藏对话框、退出」；关闭按钮不退出只隐藏。
- **源位置**：窗口标志 `pet_window.py:27-31`；尺寸/缩放 `:34-37`（基准 340×420，来自 `cfg.live2d.width/height`）；UI `:50-66`；菜单 `:186-195`；主程序拖拽 `:118-127`；`closeEvent` 隐藏 `:197-200`；气泡自动隐藏（按字数 0.25s/字，夹在 3~12s）`:130-142`。
- **依赖**：`cfg.live2d`（`width/height/scale/enabled/model_path/pet_always_on_top/bg_color/fallback_on_error`）、`cfg.gui.pet_always_on_top`、`cfg.persona.emotion_map/motion_map`。
- **复用方式**：**复制代码**（≈120 行骨架），把 `cfg` 换成构造函数参数，去掉 `apply_commands/_map_name` 就与业务无关。
- **耦合**：
  - 缩放实现是「改窗口大小而不是缩放内容」（`:163-171`，clamp 0.3~4.0），并且在 `set_scale` 里又把渲染器内部倍率重置为 1.0（`:178-179`）以免双重缩放 —— 这会让 `FallbackPet.set_scale`（`fallback_pet.py:101`，clamp 0.5~2.0）永远收到 1.0，等于失效。
  - 构造顺序坑：`_apply_window_scale()`（`:37`）早于 `_setup_ui()`（`:39`），所以里面对 `bubble` 做了 `hasattr` 保护（`:170`）。
  - 没有任何初始定位 / 位置持久化代码（不读 `QSettings`、不 `move()`），多屏下由系统默认投放。

### 2.5 WebEngine 内嵌 Live2D + QWebChannel 桥（结构值得抄，页面缺失）

- **是什么**：`QWebEngineView` + `QWebChannel` 把 Python 的 `Live2DBridge` 注册成 JS 侧 `window.bridge`；JS 主动回调（ready/modelLoaded/modelError/dragStart/dragMove/petClick）→ Python 信号；Python 主动调用 JS 全局函数 `window.neuroLoadModel/neuroSetExpression/neuroSetMotion/neuroSetSpeaking/neuroSetScale`。
- **源位置**：`Live2DBridge` `live2d_view.py:66-97`（信号 `:68-73`，槽 `:75-97`）；`Live2DView.__init__` `:101-118`；透明背景三连 `:109-111`；加载页面 `:115-116`；Python→JS 封装 `:121-132`；`_call_js` `:140-144`；`ensure_qwebchannel_js()` `:25-63`。
- **依赖**：`PySide6.QtWebEngineWidgets`（**独立 wheel，缺了会 `ImportError`**）、`PySide6.QtWebChannel`、一个必须自己提供的 `live2d/index.html`。
- **复用方式**：**复制代码**（144 行整文件即可）。桥的「信号上行 + `runJavaScript` 下行」这一层与 Live2D 无关，可以直接套到任何「网页做渲染、Python 做逻辑」的嵌入场景。
- **耦合/硬伤**：
  - `HTML_PATH = <repo>/live2d/index.html`、`JS_DIR = <repo>/live2d/js`（`:20-22`）；**这两个路径在本仓库都不存在**（已核对，无 `live2d` 目录）。
  - `ensure_qwebchannel_js()` 会把 `qwebchannel.js` **复制进项目目录**（`:59`，`shutil.copyfile` 到 `<repo>/live2d/js/`）——一个只读组件在 import 期产生写副作用，复用时必须改成缓存目录；它在 `site-packages` 里 `glob("**/qwebchannel.js")`（`:48`，上限 40）也有明显 IO 开销。
  - 失败静默：页面缺文件时只 `logger.error`（`:118`），`ready` 永不到达，`PetWindow` 里 `ready.connect(lambda: view.load_model(...))`（`pet_window.py:81`）也就永不触发，界面停在空白且**不会回落到 FallbackPet**（回落只在 `modelError` 时发生，`:97-101`）。
  - `runJavaScript` 无回调、无错误捕获，JS 侧函数名写错不会报错（但 Qt 本身支持回调，见 `scripts/test_live2d_model.py:29-38` 用回调读返回值；`_call_js` 没用）。

**核心片段（`live2d_view.py:103-106` + `:140-144`，9 行，桥注册与下行调用）**：

```python
self.bridge = Live2DBridge()
self.channel = QWebChannel(self.page())
self.channel.registerObject("bridge", self.bridge)   # JS 侧 window.bridge
self.page().setWebChannel(self.channel)

def _call_js(self, fn: str, *args):
    encoded = ",".join(json.dumps(a, ensure_ascii=False) for a in args)
    self.page().runJavaScript(f"{fn}({encoded})")      # 单向、无返回值
```

### 2.6 QPainter 兜底宠物 `FallbackPet`

- **是什么**：无资源依赖的 Q 版团子：椭圆身体 + 呆毛 + 按表情切换的眼睛/眉毛/嘴 + 害羞腮红 + 挥手的小手；`QVariantAnimation` 驱动点头/摇头/鞠躬/挥手（正弦往返）；2.8s 定时眨眼；说话时 110ms 一张一合嘴；左键拖拽窗口、未拖动则视为点击。
- **源位置**：表情别名表 `fallback_pet.py:21-36`（中英双 key）；对外接口 `:73-103`；空闲/动作动画 `:106-128`；眨眼 `:130-133`；口型 `:135-137`；`paintEvent` `:140-241`；拖拽 `:244-262`。
- **依赖**：仅 QtCore/QtGui/QtWidgets。**复用方式：直接 import**（单文件零耦合，`262` 行）。
- **耦合/注意**：
  - 颜色硬编码：身体 `#ffe4ec`、描边 `#e8a0b4`、眼 `#4a2c3a`、嘴 `#b3546e`（`:152-154`、`:169`、`:216`）；构造参数 `bg_color` 只存进 `self._bg`（`:54`），**`paintEvent` 里从未使用**（已核对全文件仅此一处引用）→ 配置项 `live2d.bg_color` 实际无效。
  - `self._anim` 单槽位（`:67`、`:114`）：连续触发动作时旧动画不会被 stop，靠父对象保活跑完，最终值由最后一次 `finished` 覆盖。
  - `_do_blink` 用 `lambda: setattr(...) or self.update()`（`:132`）——可读性差，且 `singleShot` 不校验对象存活。
  - 拖拽用 `window().pos()` 记录起点（`:247`）、`manhattanLength() > 3` 判拖动（`:253`），是「子控件拖动整窗」的标准写法，可直接抄到任何无边框窗。

### 2.7 splash 加载动画 `SplashWindow`

- **是什么**：520×280 固定大小、无边框置顶、`WA_TranslucentBackground`；`paintEvent` 手绘 22px 圆角「深色玻璃底 + 1px 青色描边 + 顶部 3px 薄荷霓虹条」，子控件全部 `background: transparent`；标题 30px/字距 8px、副标题 Consolas 等宽、进度条是三色渐变 `qlineargradient`。
- **源位置**：`splash.py:9-14`（类 + 标志 + 固定尺寸）、`:17-20`（屏幕居中）、`:26-63`（四段 QSS）、`:42-58`（进度条）、`:75-81`（`set_progress` 带 `RuntimeError` 保护）、`:83-88`（`finish()` close+deleteLater）、`:91-102`（手绘背景）、`:105-111`（`QApplication_primary_screen()` 兜底，注意它**在 `:17` 就被调用而定义在文件末尾**——靠运行时解析才没炸）。
- **依赖**：仅 Qt。**复用方式：直接 import**（111 行，只需要 `set_progress(value, text)` 和 `finish()` 两个方法）。
- **耦合/注意**：
  - 没有任何计时器/动画，所谓「加载动画」就是一个进度条 → 想要真动效得自己加 `QPropertyAnimation`。
  - 进度更新是**同步**的：`main.py:2097` 把 `splash.set_progress` 传给 `AppController`，构造期间逐段回调，但中间**不调 `processEvents`**（只在 `main.py:2092` 建 splash 后调了一次）→ 实际观感是窗口画出来后整段卡住，最后直接消失。复用时必须在每步 progress 里 `QApplication.processEvents()`（或把初始化搬进线程 / 分帧的 `QTimer` 链）。
  - 在 Qt6 上 `QApplication.primaryScreen()` 已不推荐，应走 `QGuiApplication.primaryScreen()`（文件里两条路径都留了，`:105-111`）。

### 2.8 首次运行向导 `FirstRunDialog`

- **是什么**：暗色 `QDialog`（`#14161f`），粉紫高亮标题 + 提示 + `QFrame.HLine` 分隔 + `QLineEdit` + `QDialogButtonBox`（把 `Cancel` 复用成「跳过」）；回车即确定；结果放在 `dlg.user_name`（空串表示跳过）。
- **源位置**：`_STYLE` `first_run.py:21-41`；类 `:44`；构造 `:55-103`；`showEvent` 里染标题栏 `:105-110`；`_on_accept` `:112-114`。
- **依赖**：`gui.winstyle.apply_dark_title_bar`（`first_run.py:19`，唯一内部依赖）。**复用方式：直接 import**（114 行）。
- **耦合**：`first_run.py:19` 是 `from gui.winstyle import ...` 的**绝对包名**——换个包名就得改 import；`setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)`（`:63`）必须在 `exec()` 前设置；「跳过」语义借用了 `Cancel`（`:93`），返回值仍是 `QDialog.Rejected`。

### 2.9 原生标题栏暗色化 `apply_dark_title_bar`

- **是什么**：Win11 用 DWM 属性 35/36 直接改标题栏底色与文字色；失败则退回 Win10 的沉浸式暗色 20（旧版 19）；非 Windows 或异常一律静默跳过。`showEvent` 里用 `_titlebar_styled` 标志只调一次。
- **源位置**：`winstyle.py:16-44`；`_colorref`（RGB→COLORREF 小端）`:24-27`；取 hwnd `:29`；尝试 35/36 `:32-37`；回退 20/19 `:38-42`。
- **依赖**：`ctypes`、`ctypes.wintypes`，纯标准库。**复用方式：直接 import**（44 行，最划算的一个）。
- **耦合**：必须在窗口**已创建原生句柄**之后调用（`winId()` 会强制创建，但未 show 时 DWM 设置可能被重置），所以模板是放 `showEvent`；DWM 属性号是写死的魔数；对 `Qt.FramelessWindowHint` 窗口无意义。调用示例：`chat_window.py:2667` 传 `"#060a18"`，`first_run.py:110` 传 `"#14161f","#e8ecf7"`。

### 2.10 滚轮守卫 `_WheelGuard`

- **是什么**：给设置页所有 `QComboBox/QSlider/QSpinBox/QDoubleSpinBox` 装事件过滤器，把 `QEvent.Wheel` **吞掉并转发给滚动区 viewport**，解决「滚页面时误改下拉框」的经典顽疾。
- **源位置**：类 `chat_window.py:547-561`；安装 `:738-744`；调用点 `:716`（必须在所有设置子页建完之后调）。
- **依赖**：`QCoreApplication.sendEvent`。**复用方式：直接 import**（15 行，独立无业务）。
- **耦合**：基于 `findChildren(QWidget)` 一次性快照（`:742`）——之后动态创建的控件不会被保护；`scroll_area` 是可选的，传 `None` 就只吞不转发。

**核心片段（`chat_window.py:547-561`，15 行，可直接整段抄走）**：

```python
class _WheelGuard(QObject):
    def __init__(self, parent=None, scroll_area=None):
        super().__init__(parent)
        self.scroll_area = scroll_area

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Wheel:
            if self.scroll_area is not None:
                viewport = self.scroll_area.viewport()
                if viewport is not None:
                    QCoreApplication.sendEvent(viewport, event)
            return True
        return super().eventFilter(obj, event)
```

### 2.11 会话历史卡片（ListWidget 里塞自定义 widget）

- **是什么**：左「人格下拉 + 新建」、中「名称过滤」，`QListWidget` 用 `setItemWidget` 塞双行卡片（标题 + `★ 主对话 / N 条消息 / 相对时间`），当前会话换 `objectName` 变高亮，双击打开、右键菜单（打开/重命名/删除），空列表插一条 `NoItemFlags` 的灰提示行。
- **源位置**：构建 `chat_window.py:1993-2047`；渲染 `:2086-2139`；相对时间 `_relative_time` `:2067-2084`（刚刚/N 分钟/N 小时/N 天/`%Y-%m-%d`）；右键菜单 `:2141-2158`；数据入口 `set_conversations:2061`。
- **依赖**：QtWidgets + 自定义 QSS（`#HistoryList*`，`:374-414`）。**复用方式：复制代码**（≈150 行），把 `rows` 的字段名（`title/is_main/msg_count/last_ts/id`）换成自己的 DTO。
- **耦合**：`item.setSizeHint(card.sizeHint())`（`:2135`）是必须的，否则行高塌陷；`setItemWidget` 与 `itemActivated` 混用时，卡片里的 `QLabel` 不能吃鼠标事件（默认不吃）。

### 2.12 表情包 / 图片管线（`utils/stickers.py` + 聊天页）

- **是什么**：① 16 个内置表情（emoji → 用 QPainter 渲染成 320×320 透明 PNG，落盘 `data/stickers/default/`，带柔和圆底保证深色背景可见）；② 用户导入的复制进 `imported/`；③ 发送的图片统一复制进 `data/chat_media/`（带时间戳名 + 重名自增）保证历史记录可长期寻址；④ 文件名 → 中文标签映射，供 LLM 理解表情含义。
- **源位置**：`DEFAULT_STICKERS` `stickers.py:18-35`；目录约定 `:38-47`；`_render_sticker` `:55-116`（字体探测 `:75-95`，Windows 字体兜底 `C:\Windows\Fonts\seguiemj.ttf`：`:84-86`）；`ensure_default_stickers` `:119-131`；`list_stickers` `:134-151`；`sticker_label` `:154-169`；`import_sticker` `:172-184`；`copy_to_chat_media` `:187-202`；聊天页侧：缩略图 `chat_window.py:507-544`、表情菜单 `:2516-2549`、导入 `:2551-2573`、菜单按钮 `:855-859`。
- **依赖**：`PySide6.QtGui`（QImage/QPainter/QFontDatabase）+ `QGuiApplication` 必须已存在（`:70-71` 显式检查并 `raise`）。**复用方式：直接 import**（函数式、只吃一个 `root: Path` 参数，是全仓库最好复用的模块）。
- **耦合**：目录名写死 `data/stickers`、`data/chat_media`（`:39`、`:43`）；渲染依赖 `QApplication.instance()`，所以不能在 `main()` 里 `QApplication` 之前调；`list_stickers` 用 `sorted(d.rglob("*"))`（`:140`），「内置在前」只是因为 `default < imported` 的字典序巧合。

### 2.13 字体 / 缩放

- **是什么**：界面字号 10–18px、聊天气泡字号 12–22px 分开设置，各对应一个 `Signal(int)`；换字号的做法是「字符串替换 QSS」。
- **源位置**：`STYLE` 头部 `font-family:"Microsoft YaHei UI","Microsoft YaHei"; font-size:13px`（`chat_window.py:78-79`）；`_style_for_font` `:781-782`；`apply_font_size` `:784-792`；`apply_chat_font_size` `:794-801`；两个下拉框 `:1605-1630`；气泡传入字号 `:2647`（`max(12, self._chat_font_size)`）；宠物缩放 `pet_window.py:163-179`。
- **依赖**：无额外。**复用方式：复制代码**（这是最弱的一环，见下）。
- **耦合/坑**：
  - `_style_for_font` 用 `STYLE.replace("font-size: 13px;", ..., 1)`（`:782`，**只替换第一处**）→ 依赖「第一条必须是 `QWidget#ChatWindow` 且恰好是 13px」这个脆弱前提；`QLineEdit#MessageInput` 里的 13px（`:180`）永远是 13px。
  - 改字号只影响**新**气泡：`apply_chat_font_size` 不重绘已有气泡。
  - `set_current_settings` 把 scale clamp 到 0.5~3.0（`:2408`），但滑条范围是 50–200（`:2236`）→ 大于 200% 的值会被滑条静默截断。

### 2.14 其它可直接抄的小件

| 小件 | 位置 | 说明 |
|---|---|---|
| 拖放发送图片 | `chat_window.py:2670-2683` + `setAcceptDrops(True)` `:650` | 只接受后缀白名单，最多 4 张 |
| 输入行（📷/😊/输入框/发送） | `:846-871` | 回车发送（`returnPressed`） |
| 状态胶囊 + 思考态 | `:660-667`、`set_status:2384`、`set_thinking:2388-2393` | 用 `_base_status` 保存原状态再恢复 |
| 输入互斥门闸 | `set_input_enabled:2575-2580` + `self._enabled` | 所有发送入口都先查 `_enabled`（`:2488`、`:2496`、`:2504`、`:2517`、`:2671`） |
| 控制台日志页 | `:1386-1525` | 2s 定时 + 300ms 防抖 + 仅在可见时读文件（`:1483-1486`）+ `setMaximumBlockCount(4000)` |
| 下拉框右键重命名/删除 | `:746-779` | `QComboBox` + `CustomContextMenu` |
| 相对时间 | `:2067-2084` | 纯函数，无依赖 |

### 2.15 主控制台布局骨架（双页签 + 内嵌滚动设置区）

- **是什么**：顶层 `QTabWidget` 只有「💬 聊天 / ⚙ 设置」两页（`:671-677`）；设置页里再嵌一个 `QTabWidget`（基础/记录/人格/记忆/MCP/控制台，`:683-697`），并把这个内层 tab 整体塞进 `QScrollArea`（`:709-715`），使窗口高度缩到 360 时内容仍可用而不会被压扁；最后给内层 tab 里所有下拉/滑条/数值框挂 `_WheelGuard`（`:738-744`）。
- **源位置**：`chat_window.py:652-724`（根布局 → header → 外层 tabs → 设置页 → 内层 tabs → 滚动区 → 尺寸策略 → `_fit_to_screen`）。
- **关键技巧**：`self.tabs.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)` + `setMinimumSize(480, 360)`（`:719-720`）——把「tab 内容决定最小尺寸」这个 Qt 默认行为掐断，窗口才能自由缩小；同时「聊天页」里的设置开关按钮与页签状态双向同步（`_toggle_settings:2325-2327` 与 `_on_tab_changed:2368-2377`，用 `blockSignals` 防回环）。
- **依赖**：QtWidgets + `STYLE` 里的 `QTabWidget/QTabBar` 段落。**复用方式：复制代码**（≈70 行）。
- **耦合**：页签顺序硬编码在 `:674-675` 与 `:692-697` 两处；`_on_tab_changed` 里判断「在设置页且当前是控制台页」才刷新日志（`:2376-2377`），是硬编码的下标耦合。

### 2.16 组件的「独立启动」方式（复用者最需要的一段）

仓库里自带了三个离屏冒烟脚本，说明这几个类确实可以脱离主程序单独跑，可作为复用时的最小示例：

| 脚本 | 启动的组件 | 说明 |
|---|---|---|
| `scripts/smoke_gui_new.py` | `ChatWindow` | `:7` 设 `QT_QPA_PLATFORM=offscreen`；`:16-21` `load_config()` + `QApplication` + `ChatWindow(cfg, quit_on_close=True, live2d_mode=False)`；`:23-43` 把 `set_persona/set_memories/set_rules/append_*/set_live2d_models` 全填一遍，`:48` 断言气泡数量 = 2 |
| `scripts/smoke_splash.py` | `SplashWindow` | 只 `show()`，验证不崩 |
| `scripts/test_live2d_model.py` | `Live2DView` | `:18-20` 直接实例化、`:41-43` 接 `modelLoaded/modelError/ready` 三个桥信号 |

复用要点：`ChatWindow` 只需要「一个带 `.get()` 的 cfg」，`SplashWindow`/`FallbackPet`/`MessageBubble`/`_WheelGuard` 只需要 `QApplication` 已存在；`Live2DView` 需要 WebEngine 的 `QApplication` 前置属性（`QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)` 之类）——**本仓库未见相关设置，是否必需未确认**。

## 3. 关键契约

### 3.1 GUI → 主程序（信号，节选；全量在 `chat_window.py:565-630`）

| 信号 | 签名 | 行号 | 语义 |
|---|---|---|---|
| `send_requested` | `(str)` | `:565` | 用户发文本 |
| `media_send_requested` | `(object, str)` | `:566` | `(image_paths:list[str], caption)` |
| `feedback_requested` | `(float)` | `:567` | 1.0 赞 / -1.0 踩 |
| `export_requested` | `()` | `:568` | 导出训练数据 |
| `speed_requested` / `scale_requested` | `(float)` | `:570-571` | 语速 / 宠物缩放 |
| `always_on_top_requested` | `(bool)` | `:572` | 置顶 |
| `live2d_window_requested` | `(str)` | `:573` | `show/hide/toggle` |
| `quit_requested` | `()` | `:575` | 点 × 完全退出 |
| `font_size_requested` / `chat_font_size_requested` | `(int)` | `:576-577` | 字号 |
| `avatar_requested` | `(str, str)` | `:582` | `(role, path)`，role ∈ `user/agent` |
| `*_requested`（人格/记忆/MCP/Skill/会话/LLM/TTS…） | 多种 | `:583-630` | 均为「请求主程序干活」 |
| `PetWindow.chat_toggle_requested` | `()` | `pet_window.py:17` | 点角色开/关对话框 |
| `PetWindow.model_failed` | `(str)` | `pet_window.py:19` | 模型加载失败（给出错原因） |

### 3.2 主程序 → GUI（方法）

| 分类 | 方法（参数） | 行号 |
|---|---|---|
| 状态 | `set_status(str)` / `set_thinking(bool)` / `set_input_enabled(bool)` | `:2384` / `:2388` / `:2575` |
| 聊天流 | `append_user(str)` / `append_assistant(str)` / `append_system(str)` / `append_user_media(list[str], str)` | `:2603` / `:2625` / `:2635` / `:2613` |
| 历史 | `set_chat_history(list[dict])` / `clear_chat()` | `:2590` / `:2583` |
| 会话 | `set_conversations(list[dict], current_id)` / `set_history_personas(list[str], str)` / `set_current_conversation_label(str)` | `:2061` / `:2049` / `:2160` |
| 人格 | `set_persona_list(list[str], active)` / `set_persona_text(text, name, path)` / `set_persona(text, path)` | `:2426` / `:2440` / `:2449` |
| 记忆 | `set_memories(list[dict])` / `set_rules(list[dict])` | `:2454` / `:2473` |
| MCP/Skill | `set_mcp_servers(list[dict])` / `set_skills(list[dict])` | `:1369` / `:1377` |
| TTS | `set_tts_voices(list[dict], current)` / `set_voice_export_dir(str)` / `set_service_status(name, bool)` | `:1940` / `:1925` / `:1511` |
| Live2D | `set_live2d_models(list[dict], current)` | `:2354` |
| 设置回填 | `set_current_settings(backend, speed, scale, always_on_top, font_size, chat_font_size)` | `:2395` |
| 字体/头像/名字 | `apply_font_size(int)` / `apply_chat_font_size(int)` / `set_avatar(role, path)` / `set_user_name(str)` / `set_agent_name(str)` / `add_custom_model(str)` / `remove_custom_model(str)` | `:784` / `:794` / `:803` / `:812` / `:819` / `:1751` / `:1759` |
| 控制台 | `append_console_note(str)` / `_refresh_console()`（**私有但被主程序直接调用**，`main.py:1959`） | `:1519` / `:1482` |
| 宠物 | `show_bubble(str)` / `apply_commands(list[tuple])` / `set_speaking(bool)` / `set_scale(float)` / `reload_model(str)` | `pet_window.py:130` / `:144` / `:160` / `:173` / `:181` |
| splash | `set_progress(int, str)` / `finish()` | `splash.py:75` / `:83` |

### 3.3 GUI 期望主程序提供什么

1. **一个 `cfg` 鸭子类型对象**（构造函数第一个参数），字段全部按「`.get(key, default)`」使用：
   - `cfg.root: Path`（表情包/日志/媒体目录的根）
   - `cfg.gui: dict-like`（`chat_width=760`、`chat_height=820`、`font_size=13`、`chat_font_size=15`、`user_name`、`agent_name`、`user_avatar`、`agent_avatar`、`voice_export_dir`、`pet_always_on_top`）
   - `cfg.live2d: dict-like`（`enabled`、`model_path`/`cfg.live2d_model_path`、`width=340`、`height=420`、`scale`、`pet_always_on_top`、`bg_color`、`fallback_on_error`、`controller`）
   - `cfg.persona.emotion_map` / `motion_map`（`pet_window.py:155-157`）
   - `cfg.memory.auto_review_enabled/auto_review_minutes`（`:1070-1076`）、`cfg.llm.*`（`api_key/base_url/model/custom_models/context_compression`）、`cfg.search.api_key`
   - 实现方式见 `agent/config.py:41-56`（`_DictObj` 包装 YAML dict）。
2. **主线程**：所有 `set_*/append_*` 都直接 `setText/setPixmap/insertWidget`，**必须在 GUI 线程调用**，GUI 内部不做任何线程封送。
3. **连接与退出语义**：`ChatWindow` 的 × 只发 `quit_requested` 并 `accept()`（`:2685-2689`），真正的停服务/退出由主程序负责（`main.py` 的 `on_quit_requested` + `ShutdownWorker` + 12s 兜底 `QTimer`）；`quit_on_close` 参数（`:632`、`:635`）**只赋值、从未读取**，别再指望它切行为。
4. **首次运行**：`FirstRunDialog.exec()` 后读 `.user_name`（空串=跳过），由调用方写入配置（`main.py:445-456`）。
5. **可选依赖要软失败**：`PySide6.QtWebEngineWidgets` 缺失时 `pet_window.py:75-87` 用 `try/except` 兜底到 `FallbackPet`，主程序不应假定 Live2D 一定可用。

### 3.4 回写的隐含约定

- 主程序要改控件值时，GUI 内部一律 `blockSignals(True/False)` 包起来防回环（如 `:790-792`、`:2049-2059`、`:2354-2366`、`:2400-2423`）——外部调用 `set_*` 是安全的，但**不要**自己去 `setCurrentIndex`。
- 列表/下拉一律「`addItem(text, data)` + `findData` 定位」，`data` 才是业务主键，`text` 只用于显示（`:1944`、`:2359`、`:2480`）。

## 4. 坑

### 4.1 线程安全

- **GUI 包内零线程**，但**零封送**：`append_user/append_assistant/set_*` 都是裸 widget 操作。主程序目前靠 `QRunnable + WorkerSignals(QObject)`（`main.py:76-78`）发信号回主线程，**这是能正常工作的唯一原因**；任何在 worker 里直接 `self.chat.append_*` 的改动都会踩 Qt 的「QObject 跨线程」红线（偶发崩溃/花屏，不一定立刻报错）。
- `LipSyncPusher` 是 `threading.Thread`（`main.py:250-278`），只碰 HTTP client，不碰 UI —— 保持了边界，值得照抄这个纪律。
- `splash.set_progress` 在 `AppController.__init__` 里被同步调用（`main.py:2097`），**期间没有 `processEvents`**，所以进度条看起来是「定格的」；如果哪天把它挪到线程里，`QProgressBar.setValue` 会直接崩。
- GUI 里对 `QTimer.singleShot` 的回调基本没做存活检查（`pet_window.py:139`、`fallback_pet.py:132`），只有 `splash.py:80`、`:87` 和 `chat_window.py:2659` 用 `RuntimeError` 兜了 —— 窗口销毁后再触发会抛异常。

### 4.2 DPI / 多屏

- 没有 `QGuiApplication.setHighDpiScaleFactorRoundingPolicy`、没有 `screenChanged/logicalDotsPerInchChanged` 处理，全靠 Qt6 默认缩放。
- `ChatWindow._fit_to_screen()`（`:725-736`，本意是「启动时窗口超出屏幕就缩进可用区」）**实际从未生效**：`:728` 调用的 `QApplication_primary_screen()` 在本文件里**没有定义**（只定义在 `splash.py:105`），必然 `NameError`，被 `:735` 的 `except Exception: pass` 静默吞掉。抄这个函数时记得把 helper 一起带上。
- 尺寸全是设备无关像素常量：splash `520×280`（`splash.py:14`）、聊天窗默认 `760×820`（`:641`）、气泡最大宽 `620`、头像 `36`、缩略图 `300×240`、宠物最小 `160×200`（`fallback_pet.py:57`）→ 150% DPI 下不破版，但小屏 1366×768 会显得很挤（本该由 `_fit_to_screen` 兜住，而它是坏的）。
- 无窗口位置持久化：`PetWindow` 不 `move()`、不存 `QSettings`，多屏拔插后可能出现在已不存在的屏幕上。

### 4.3 透明窗口在 Windows 上的坑

- 组合是 `FramelessWindowHint + WA_TranslucentBackground`（`pet_window.py:27-31`、`live2d_view.py:109-111`、`splash.py:11-13`）。`Qt.Tool` 的副作用：**不占任务栏、不进 Alt-Tab**，且 `close` 只是 hide；配合 `app.setQuitOnLastWindowClosed`（`main.py:2085`）时要小心「关掉唯一窗口程序不退」。
- 透明 ≠ 鼠标穿透：没有 `WA_TransparentForMouseEvents`，四角透明区域仍然吃点击，桌宠会挡住下层窗口的点击。
- `QWebEngineView` 想真透明要同时满足「页面 `background: transparent` + `page().setBackgroundColor(Qt.transparent)` + `WA_TranslucentBackground`」，代码三样都写了（`live2d_view.py:109-111`），但 Windows 上 WebEngine 的合成层经常仍出黑底/闪烁，**实测表现未确认**（本报告只做静态分析，未运行该分支，且 `live2d/index.html` 根本不存在）。
- `apply_dark_title_bar` 只对有原生标题栏的窗口有意义，对上面这些 `FramelessWindowHint` 窗口是空操作（调用点也确实只在 `ChatWindow`/`FirstRunDialog` 的 `showEvent`）。

### 4.4 硬编码路径 / 尺寸

- `live2d_view.py:20-22`：`PROJECT_ROOT/live2d/index.html`、`live2d/js` —— 目录不存在；`ensure_qwebchannel_js` 还会**往项目里写文件**（`:59`）。
- `winstyle.py` 无路径；`stickers.py:84` 回退到 `C:\Windows\Fonts\seguiemj.ttf`（Windows-only 假设）。
- `chat_window.py:1507`（日志目录 `cfg.root/data/logs`）、`:1813`（`vision_mcp/config.json`）、`:2004`（`cfg.root` 作为对话框起点）都是相对 `cfg.root` 的约定，换目录结构要同步改。
- 玩具级常量：宠物气泡宽 `280`（`pet_window.py:57`）与 `min(560, 280*scale)`（`:171`）、气泡显示时长 `0.25s/字` 夹 `3~12s`（`:137`）、控制台 `2s` 轮询 / `4000` 行上限（`:1467`、`:1447`）、聊天一次最多 4 张图（`:2511`、`:850`）。

### 4.5 其它已核实的小缺陷（复用前建议先修）

| 问题 | 位置 | 影响 |
|---|---|---|
| `QApplication_primary_screen` 未定义 | `chat_window.py:728`（定义在 `splash.py:105`） | `_fit_to_screen` 恒失效，异常被吞 |
| `bg_color` 参数未使用 | `fallback_pet.py:54` 赋值，`paintEvent` 不读 | 宠物底色不可配 |
| 气泡时间恒为「现在」 | `chat_window.py:476` | 历史重放时间全错 |
| 字号替换只换第一处 | `:782`（`replace(..., 1)`） | 换字号后仍有控件是 13px |
| `quit_on_close` 参数无效 | `:635` `_quit_on_close` 只写不读 | 行为与参数不符 |
| 渲染器缩放互相覆盖 | `pet_window.py:178-179` vs `fallback_pet.py:101` | 兜底宠物 scale 失效 |
| QWebEngine 页面缺失不兜底 | `live2d_view.py:118`、`pet_window.py:81` | 界面空白且无错误提示 |
| `set_scale` 与滑条范围不一致 | `chat_window.py:2408` vs `:2236` | >200% 被静默截断 |
| 主程序直接调 GUI 私有方法 | `main.py:1959` `self.chat._refresh_console()`、`:445` `self.chat._agent_name` | 破坏封装，重构即断 |

### 4.6 本报告未确认的事项（复用时请自行实测）

1. `QWebEngineView` 在 `WA_TranslucentBackground` 下是否真透明 —— 代码做了三处设置，但本报告未运行（且页面文件缺失）。
2. 缺 `QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)` 时 `Live2DView` 是否仍能正常创建 WebEngine 上下文 —— 未确认。
3. QSS 里大量 `rgba(...,0.92)` 这类**浮点 alpha** 在目标 Qt 版本上的解析结果 —— 未确认（若不支持会退化为不透明或忽略该条）。
4. `Qt.Tool` 窗口在 Windows 上点击「任务栏预览/最小化」的行为 —— 未确认。
5. `apply_dark_title_bar` 在 Win10 与 Win11 上的具体观感差异 —— 只按代码分支推断，未逐版本验证。
6. `ensure_qwebchannel_js()` 在打包（PyInstaller 等）环境下能否找到 `qwebchannel.js` —— 未确认。

## 5. 抽取建议（按「抄一件赚一件」排序）

1. **`winstyle.apply_dark_title_bar`（44 行）** —— 零依赖、立刻让原生标题栏与暗色 UI 融合，最划算。
2. **`utils/stickers.py`（202 行）** —— 函数式、只吃 `root: Path`，任何聊天类应用都能用（表情/图片落盘与寻址策略比大多数项目规范）。
3. **`MessageBubble` + 两段气泡 QSS + `_make_image_label`（≈150 行）** —— 唯一需要改造的是把时间戳参数化。
4. **`FallbackPet`（262 行）** —— 无资源依赖的「有表情的 Q 版小生物」，可当作任何桌宠/助手的占位形象；顺手修掉 `_bg`。
5. **`STYLE` 配色与控件族（≈340 行 QSS）** —— 建议先把散落的颜色收成 `PALETTE` dict 再抄，否则第二次改主题会很痛。
6. **`PetWindow` 骨架 + `_WheelGuard` + 气泡流容器 + 拖放发图** —— 都是 20~120 行的小件，组合起来就是一个「无边框置顶 + 会说话 + 能拖」的宠物窗。
7. **`Live2DView` + `Live2DBridge`** —— 桥的「信号上行 / `runJavaScript` 下行」范式值得抄，但**必须自带 `index.html` 并把 `qwebchannel.js` 的落盘位置改到缓存目录**。
8. **`SplashWindow` / `FirstRunDialog`** —— 直接可用，但记得给 splash 加 `processEvents` 或改成非阻塞启动。

> 不建议整包 import `gui.chat_window`：它把 `cfg`、`utils.stickers`、`utils.console_logs`、`gui.winstyle` 全部拉进依赖图，并且 `STYLE` 与 `objectName` 强耦合。按上面 1~5 抽单件，成本最低、耦合最少。

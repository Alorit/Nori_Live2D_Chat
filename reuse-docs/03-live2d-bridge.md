# 03 · 原生 Live2D 桥接契约（\*.NET 桌宠 ↔ Python）

> 这是整个项目里**跨进程、跨语言、最容易复用也最容易踩塌**的一层。契约的权威来源是服务端源码 `D:\Nori-Desktop-Pet-Fork\app\desktop\Nori.Desktop\Live2D\PetControlServer.cs`（330 行），客户端是 `D:\Nori_Live2D_Chat\agent\live2d_native.py`（200 行）。本文两份都读过并互相校验过。

## 1. 架构

```
┌────────────────────────────┐         ┌──────────────────────────────────┐
│ Python 主进程 (PySide6)     │         │ Nori.Desktop.exe (.NET Avalonia) │
│                            │  HTTP   │                                  │
│ Live2DNativeClient ────────┼────────▶│ PetControlServer (HttpListener)  │
│  · set_expression          │ 47835   │   127.0.0.1:47835 仅本机          │
│  · play_motion             │◀────────┤   → PetRuntime（UI 线程执行）     │
│  · audio_level (口型)       │  JSON   │   → OpenGL / Cubism 渲染          │
│  · set_scale / window      │         │                                  │
└────────────────────────────┘         └──────────────────────────────────┘
        │ 子进程（--pet-only），CREATE_NO_WINDOW，等待 /state 就绪 ≤30s
        └───────────────────────────────────────────────────────────────
```

要点：

- **渲染与控制都在 .NET 侧**，Python 只发指令、不碰模型文件；Python 里没有 Live2D 运行时依赖（旧方案的 QWebEngine/CubismWeb 已废弃）。
- 传输是**裸 HTTP + JSON**，无鉴权、无版本协商、无 TLS，绑死 `127.0.0.1:47835`（`PetControlServer.cs:26`，`const` 不可配）。
- 请求体解析**宽松**：字段缺失/类型不符就回落默认值，不报错；路径未知返回 404，方法不是 GET/POST 返回 405，内部异常返回 500（`PetControlServer.cs:100-147`）。
- 服务端每个请求 `Task.Run` 独立处理（`:83`），但所有模型操作都经 `OnUiAsync` **封送到 UI 线程**执行——所以并发安全，且请求天然串行化在渲染线程上。

## 2. 端点契约（服务端权威版）

| 方法 | 路径 | 请求体 | 响应 | 语义 / 边界 |
|---|---|---|---|---|
| GET | `/state` | — | 见 §3 | 唯一的状态读取入口，也是**存活探测**手段 |
| POST | `/motion` | `{"name":"idle"}` 或 `{"group":"Idle","index":0}` | `{"ok":bool}` | `name` 优先；`ok=false` 表示模型没有该动作（**不抛错**） |
| POST | `/expression` | `{"name":"爱心眼"}` | `{"ok":bool}` | 空名/未知名 → `ok=false` |
| POST | `/model` | `{"modelId":"nori"}` | `{"ok":true,"modelId":...}` | 缺 `modelId` → 400 |
| POST | `/model/import` | `{"path":"D:\\...\\模型目录或.zip"}` | `{"ok":true,"models":["id",...]}` | 缺 `path` → 400；目录扫描在后台线程（`Task.Run`） |
| POST | `/mouth` | `{"level":0.0~1.0,"speaking":bool}` | `{"ok":true}` | `level` 被 `Math.Clamp(0,1)`；驱动口型开度 |
| POST | `/window` | `{"action":"show"\|"hide"\|"toggle"}` | `{"ok":true,"action":...}` | 其它值 → 400 |
| POST | `/scale` | `{"scale":0.1~2.0}` | `{"ok":true,"scale":...}` | 服务端硬夹到 `[0.1, 2.0]`，并按模型持久化 key `l2d_scale_<modelId>` |
| POST | `/beat` | — | `{"ok":true}` | 触发一次节拍动画 |
| POST | `/reload` | — | `{"ok":true}` | 重载当前模型 |

> `pet_window` 里旧的 `/mouth {"speaking":...}` 只切状态、嘴型由 `level` 驱动——所以**只发 `speaking=true` 不发 level，嘴不会动**。

## 3. `GET /state` 响应结构

```json
{
  "modelId": "nori",
  "loaded": true,
  "lastError": null,
  "scale": 1.62,
  "models": [{ "path": "arg-nori", "name": "arg-nori" }, { "path": "nori", "name": "nori" }],
  "motions": [{ "group": "Idle", "names": ["Idle"] }],
  "expressions": ["爱心眼", "圈圈眼", "黑化", "戴帽子"],
  "quality": "…",
  "// 说明": "字段名来自 BuildState()，PetControlServer.cs:150-168"
}
```

`models` / `expressions` 是**运行时可枚举的能力清单**——回复前想校验"这个表情存在吗"，用 `/state` 而不是硬编码。

## 4. Python 客户端（`agent/live2d_native.py`）

| 方法 | 行为 | 备注 |
|---|---|---|
| `available(timeout=1.0)` | `GET /state` 是否成功 | 唯一可靠的存活判断 |
| `ensure_running(wait_sec=30)` | 先 `available()`，否则 `Popen([exe, "--pet-only"], cwd=exe_dir, creationflags=CREATE_NO_WINDOW)`，然后 0.5s 轮询到就绪 | `native_app_path` 以 `.dll` 结尾则走 `dotnet <dll>` 分支（保留字段） |
| `get_state()` / `list_models()` | 读状态 / 取模型列表 | `list_models` 在服务不可用时回落到硬编码两个 ID |
| `set_expression(name)` | `POST /expression` | 空串直接 `False`，不发请求 |
| `play_motion(group, index=None)` | `POST /motion` | 有 index 用 group+index 形态 |
| `audio_level(level)` | `POST /mouth {level, speaking: level>0.01}` | 口型主通道 |
| `set_speaking(bool)` | `POST /mouth {level:0, speaking}` | 只切状态 |
| `switch_model(model_path)` / `import_model(path)` | `/model` / `/model/import` | `switch_model` 会把 `"a/b"` 截成 `"a"` |
| `set_scale(scale)` | `/scale`，本地先 `clamp(0.1, 2.0)` | 失败静默返回 `False` |
| `control_window(action)` / `show_window()` | `/window` | `show_window` 会先 `ensure_running()` |
| `shutdown()` | `taskkill /PID <pid> /T /F`（15s 超时） | 只杀自己拉起的子进程 |
| **`look_at` / `set_parameter` / `reset`** | **空实现，直接 `return True`** | ⚠️ 旧接口残留：**不要以为能控制视线或任意参数**，服务端根本没有对应端点 |

统一错误：`Live2DNativeError(RuntimeError)`，`_request` 里 `status>=400` 与 `requests.RequestException` 都转成它；但**上层调用点大多 `except Exception: pass`**，失败只进日志。

## 5. 启动与生命周期

1. `main.py` 启动 → `live2d.ensure_running()`（`main.py:528`）→ 就绪后置 `live2d_ready`。连接本身在 `threading.Thread` 里做（`main.py:404`），不阻塞控制台显示。
2. **原生模式下没有兜底形象**：`main.py:392` 明确 `self.pet = None`，`PetWindow` / `Live2DView` / `FallbackPet` 整条内嵌链已被停用（全仓库无第二个 import）。所以 `config.yaml` 的 `live2d.fallback_on_error: true` 是**死配置**——桌宠进程起不来时，表现为"只有聊天窗口，没有任何角色，也没有报错"。`main.py:1468/1474` 那几处 `if self.pet:` 分支是残留。
3. 退出 → `live2d.shutdown()`（`main.py:214`）。
4. 服务端 `HttpListener.Start()` 失败**只写一行日志然后静默返回**（`PetControlServer.cs:53-57`）——端口被占时桌宠照常显示但**无法被控制**，且不会报错给 Python。排查"表情不生效"先看桌宠日志里有没有"控制服务启动失败"。

## 6. 情绪 / 动作标签的完整链路

```
persona/*.md 要求模型输出 [expr:开心] [motion:发呆]
        │
agent/brain.py  parse_commands()  →  [("expr","开心"), ("motion","发呆")]   ← 同时从正文里剥掉标签
        │  AgentReply.commands
main.py:857  _apply_live2d_commands()
        │  main.py:875 _map_name("emotion_map"/"motion_map", name)  ← 读 config.yaml 的 persona.emotion_map / motion_map
        │      开心→"爱心眼"   发呆→"idle"
        │  main.py:972 _live2d_call(fn, ...)  ← 一律丢 QThreadPool，绝不阻塞 UI
        ▼
Live2DNativeClient.set_expression("爱心眼") / play_motion("idle")
```

- 逻辑名与模型真实名的映射**只存在于 `config.yaml`**，人格 `.md` 里不写模型名，人格里写的是 `config.yaml` 的 `persona.expressions` / `motions` 白名单内的逻辑名。
- 映射缺失时**原样下发**逻辑名（`_map_name` 里 `mapping.get(name, name)`），服务端再以 `ok=false` 静默忽略。
- Nori 模型**没有 `.motion3.json`**，`[motion:*]` 全部安全忽略（`README.md:217`）；想要动作只能换带动作的模型。

## 7. 口型同步（值得单独抄的部分）

`main.py:250` 的 `LipSyncPusher(threading.Thread)`：

```python
level = 0.35 + 0.45 * abs(math.sin(phase)) + 0.12 * math.sin(phase * 2.7)   # phase = n * 0.55
```

- 每 **0.06s** 推一次 `/mouth`，说：用**合成包络**伪造音频电平（不是真的分析音频），视觉上足够"在说话"。
- 关键设计：**放在后台线程而不是 QTimer**。注释写明原因（`main.py:252-255`）：主线程每 60ms 发一次 HTTP，本地服务无响应时每 tick 阻塞 5s，界面直接僵住。
- 生命周期：`_speak_now()` → `set_speaking(True)` + `_start_lip_sync()`；TTS 完成/失败 → `_stop_lip_sync()` + `set_speaking(False)` + 补一次 `audio_level(0)` 让嘴合上。

## 8. 复用配方

### 8.1 最小可用客户端（20 行，不依赖本项目）

```python
import requests

BASE = "http://127.0.0.1:47835"

def pet(path: str, payload: dict | None = None, timeout: float = 5.0) -> dict:
    """所有调用都带 timeout：本地服务也可能无响应。"""
    if payload is None:
        r = requests.get(BASE + path, timeout=timeout)
    else:
        r = requests.post(BASE + path, json=payload, timeout=timeout)
    r.raise_for_status()
    return r.json()

def pet_up(timeout: float = 1.0) -> bool:
    try:
        pet("/state", timeout=timeout); return True
    except Exception:
        return False

# 用法
pet("/expression", {"name": "开心"})
pet("/mouth", {"level": 0.6, "speaking": True})
pet("/scale", {"scale": 1.5})
```

### 8.2 想让自己的程序"也有个会说话的角色"——三条路

| 路线 | 做法 | 代价 |
|---|---|---|
| A. 直接复用原生宿主 | 拷 `vendor/nori_desktop_pet/`（GPL-3.0，263 MB），`--pet-only` 启动，按 §2 发 HTTP | 零开发；受 GPL 约束；模型限定宿主支持的目录约定 |
| B. 自己写兼容 stub | 实现 `/state`+`/motion`+`/expression`+`/mouth`+`/scale` 的**最小 HTTP 服务**，前面接任意渲染（Unity/Electron/Qt） | 中；`Nori_Recreation_Prompt.md:430` 明确推荐这条路 |
| C. 完全绕开 HTTP | 用 WebSocket/共享内存/直接进程内渲染 | 需要自己造协议，没有现成参考 |

### 8.3 换端口 / 换宿主

端口写死在服务端 `const string Prefix`（`PetControlServer.cs:26`），**客户端也写死** `self.base_url = "http://127.0.0.1:47835"`（`live2d_native.py:32`，连 `cfg` 里的配置都没读）。要换端口必须同时改两端；这是本项目最硬的一处耦合。

## 9. 红线

1. **无鉴权**：任何本机进程都能控制你的桌宠（换表情、`/window hide`、`/scale`）。仅限本机场景，别把 47835 暴露到局域网。
2. **不要在主线程同步调用**：任何 `/mouth`、`/state`、`/expression` 都要走线程池（本项目用 `Live2DCallWorker` + `QThreadPool`），否则服务卡顿直接冻 UI。
3. **不要假设 `ok:true` 表示视觉上生效**：`PlayExpression`/`PlayMotion` 返回的是"调用被接受"，模型缺资源时可能无变化。
4. **`/mouth` 高频调用要限频**：本项目 0.06s ≈ 16 次/秒已经是 HTTPServer 的合理上限，再高只会堆积 `Task.Run`。
5. **`live2d.enabled: false` 时** 主程序不启动桌宠，但 `Live2DNativeClient` 仍可能被构造——所有调用点都要能吃 `False` 返回值。

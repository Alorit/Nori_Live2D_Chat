# Nori 自主性升级方案（调研稿 v1）

> 目标：把 Nori 从"跟随鼠标的立绘"变成"有自己生活节奏的桌宠"。
> 本文原本只做方案与评估，不含实施；**2026-10-26 已按 A/B/C 三项落地**，落地清单见文末第 10 节。
> 所有"现状"结论都来自本机代码实测，标注了文件与行号。

---

## 0. 一句话结论

**渲染层其实已经够"活"了，缺的是决策层。**

.NET 桌宠内部已经有 idle 循环、自动眨眼、随机扫视、物理、视线跟随、点击反应——低层"生命感"该有的都有（`PetRuntime.cs`、`Behaviors/EyeFocusBehavior.cs`）。
真正的问题是：**没有任何东西在"决定"她要做什么**。Python 侧唯一的自主机制是 `heart.py`，默认 15 分钟才醒一次，醒来看一眼、大概率选择"什么都不做"，而且它的动作/表情词表**有 7/7 和 2/5 解析不出来**（下面有实测）。

所以升级路线不是"给她加动画"，而是**加一个导演（Director）**：秒级的规则反射 + 分钟级的 LLM 意图，两者共用一个"身体"。

---

## 1. 现状体检

### 1.1 渲染层（.NET 侧）已经有的能力

| 能力 | 实现 | 备注 |
|---|---|---|
| 待机动作循环 | `Idle` 组：`01_Idle_Loop`、`sleep_Loop` | 模型自带，SDK 自动播 |
| 自动眨眼 | `AutoBlinkBehavior` | 受 `l2d_idle_eye_animation` 开关控制 |
| 空闲眼神扫视 | `EyeFocusBehavior`（400ms 步进的分段概率分布） | 这就是"有在呼吸"的关键细节 |
| 物理（头发/身体晃动） | `ARGNori.physics3.json` | — |
| 视线跟随 | `PetWindow.OnCursorTrackingTick` 轮询**全局**光标 → `PetRuntime.LookAt()` | 所以眼睛会跟着屏幕任意处的鼠标 |
| 点击反应 | `PetRuntime.HandleTap` → 无命中区域时随机切表情 | 已有的"互动" |
| 口型 | `/mouth` + `LipSyncBehavior` | Python 推 audio level |
| 动作/表情资源 | 5 组动作 12 条：`Idle`(2)、`Reactions`(6: Nod/ShakeHead/WakuWaku/Angry/Troubled/Dizzy)、`Effects`(1: Glitch)、`Poses`(2)、`Background`(1)；表情 16 个 | 见 `ARGNori.model3.json` |

模型路径：`%APPDATA%\cn.erhio.noriDesktopPet\data\resources\live2d\arg-nori\`。

**结论：动作空间比配置里写的丰富得多。**配置注释说"Nori 模型没有 .motion3.json 动作文件"是**过时信息**（那是旧的 `nori` 模型），`arg-nori` 有 12 条动作。

### 1.2 决策层（Python 侧）现状

| 机制 | 位置 | 节律 | 说明 |
|---|---|---|---|
| 聊天中被动反应 | `main.py:860 _apply_live2d_commands` | 每条回复 | LLM 在正文前输出 `[motion:nod]` / `[expr:smile]`，解析后播动作 |
| 独立"私人时间"沉睡 | `heart.py` 独立进程 | 默认 15 分钟（可 2~120 分钟，由她自己定） | LLM 输出 JSON：`thought/mood/action(none/expression/motion/speak)/text/next_wake_minutes` |
| 环境感知 | **无** | — | 全仓库 grep 无 `GetCursorPos / GetLastInputInfo / GetForegroundWindow / pyautogui` |

`heart.py:123 _think()` 每次唤醒要带**完整人格 prompt（8789 字符 ≈ 5~6k tokens）**、最近 6 条对话、自己的 thoughts/actions 各 5 条；输出上限 400 tokens。默认 96 次/天 ≈ **每天 55 万 input tokens**——花了钱，但 90% 的回合 `action=none`，用户看不到任何东西。

### 1.3 三个"隐性失明"（实测证据）

用脚本复刻 `.NET` 的 `PetActionResolver`（`Nori.Core/Live2D/PetActionResolver.cs`：先精确匹配 → 去数字前缀匹配 → 别名提示 → 包含匹配），拿 `config.yaml` 现有映射去撞真实名字：

**表情（`persona.emotion_map`）：7 条全部解析失败**

| 标签 | 配置值 | 解析结果 |
|---|---|---|
| 开心 | 爱心眼 | ❌ None |
| 难过 / 惊讶 / 困惑 | 圈圈眼 | ❌ None |
| 害羞 | 爱心眼 | ❌ None |
| 生气 | 黑化 | ❌ None |
| 认真 | 戴帽子 | ❌ None |

`爱心眼 / 圈圈眼 / 黑化 / 戴帽子` 是旧 `nori` 模型的表情名，`arg-nori` 里根本没有 → `set_expression` 返回 `ok:false`，`_execute()` 静默结束。

**动作（`persona.motion_map`）：5 条里 2 条失败**

| 标签 | 配置值 | 解析结果 |
|---|---|---|
| 点头 | nod | ✅ `02_Nod` |
| 摇头 | shake | ✅ `03_ShakeHead` |
| 发呆 | idle | ✅ `01_Idle_Loop` |
| 挥手 | wave | ❌ None（模型没有 wave） |
| 鞠躬 | bow | ❌ None（模型没有 bow） |

**对比：聊天链路是通的。** `agent/core.py:222-236` 注入的是英文标签（`[motion:shake]`/`[expr:smile]`），12 个表达式 + 8 个动作**全部能解析**。也就是说——**用户在聊天时能看到表情，但她"自己想事"时做的表情全是空的**。这正好解释了"自主性太差"的体感。

### 1.4 缺的环节

1. **没有秒级节律**：两次"醒来"之间（可能 2 小时）她完全静止。
2. **没有外部刺激**：不知道主人在不在、在干什么、现在几点（时间只喂给了 LLM 的 prompt，不驱动行为）。
3. **没有意图连续性**：每轮 `heart` 都从零开始决定，`next_wake_minutes` 是唯一记忆。
4. **没有"表达预算"**：没有"我现在不该打扰"的判断，只能靠 prompt 里一句"不要频繁打扰"。

---

## 2. "像 Neuro-sama 那样"到底指什么

Neuro-sama 的"活"是四件事叠加，缺一件就会塌成"会说话的立绘"：

| 要素 | Neuro 的做法 | 桌面宠物版的替代物 |
|---|---|---|
| **刺激流** | Twitch 弹幕（每分钟几十条）+ 游戏画面 + 另一个 AI（Evil Neuro） | 主人的活动（键鼠/窗口/空闲时长）+ 时间 + 屏幕截图 + 聊天记录 |
| **决策环** | LLM 恒定在环里，把刺激翻译成"要不要接话、怎么接" | 低频 LLM（每 5~20 分钟一次"意图"）+ 高频规则（每秒） |
| **表达空间** | 声音（情绪化 TTS）+ 表情 + 动作 + 身体姿态 + 游戏操作 | 已有：TTS（GPT-SoVITS）、12 动作、16 表情、口型；缺：姿态/注视目标 |
| **连续性** | 长期记忆 + 情绪状态 + 对观众的"关系" | 已有记忆库（persona+conversation 双键）、`heart.json` 的 mood/thoughts；缺"情绪会累积并影响行为" |

参考实现（可直接借鉴结构，不必照搬）：

- **Open-LLM-VTuber**（开源，明确以复现 Neuro-sama 为目标）：提供"AI 主动说话"和"AI 内心 OS"——**想法、表情、动作可以被看见，但不会被读出来**。这是"有自我意识"观感的关键设计。
- **社区逆向的 Neuro 认知架构**：把系统分成"感知 → 认知 → 行动"管线，配一个带 valence/arousal（效价/唤醒度）的情绪状态机，动作从"已注册动作空间"里选。
- 我们的 `heart.py` 其实已经是这个管线的雏形（thought/mood/action），只是**节律太慢、动作词表坏了、输出没有被展开成行为**。

---

## 3. 目标能力模型（四层）

```
L3 身体层  .NET 渲染（已有 12 动作 / 16 表情 / 视线 / 口型）
              ↑ HTTP 47835
L2 心智层  低频 LLM：每 5~20 分钟产出「意图 + 情绪 + 一句话」，可跨回合攒计划
              ↑ 意图队列
L1 反射层  秒级规则调度器（0 token）：微动作、时间作息、主人活动联动、抢占与冷却
              ↑ 感知
L0 感知层  时间 / 空闲时长 / 前台窗口 / 聊天事件 /（可选）屏幕截图与视觉模型
```

设计原则：**"贵的东西必须低频，高频的东西必须免费"**。秒级循环里绝不能有 API 调用。

---

## 4. 候选方案

### 方案 A：规则导演（PetDirector）—— 0 token，性价比最高

**做什么**：在 `heart.py` 里加一条 1 Hz 的快节律，用规则（不是 LLM）驱动微行为。

**怎么做**
1. 新建 `agent/pet_director.py`，持有现有 `Live2DNativeClient` 实例，暴露 `submit(intent)` / `tick()`。
2. 用**权重表 + 泊松间隔**排微动作，而不是固定定时（固定定时会很机械）：
   ```
   每个 tick：
     若 正在说话(TTS) / 有高优先级动作 / 冷却中 → 跳过
     若 now > next_micro_at:
         pick = weighted_choice(候选)
         候选 = [(Idle_pose, w=30), (Nod, w=8), (ShakeHead, w=4),
                 (WakuWaku, w=6), (Troubled, w=3), (Dizzy, w=1), (Glitch, w=1)]
         权重按 时段/情绪/主人是否在场 动态调（深夜 → sleep/WakuWaku 权重反转）
         play(group, index)
         next_micro_at = now + expovariate(1/λ)   # λ ≈ 1/180s
   ```
3. 时间作息（纯规则）：`06-09` 起床伸懒腰、`09-23` 正常、`23-02` 犯困（`sleep_Loop` + `Sleep` 表情）→ **让"她也有作息"**。
4. 主人活动联动（见方案 C 的感知，先做零成本部分）：
   - 聊天窗有新消息 → 3 秒内 `Nod`
   - 主人 20 分钟无输入 → 进入 `doze`（`sleep_Loop`）
   - 主人回来（鼠标移到宠物窗口 / 新消息）→ 醒来 + `WakuWaku`
5. **抢占规则**（关键，防止打架）：`说话 > 用户交互反应 > 心智意图 > 微动作 > idle`，每个动作有 min-hold（例如 1.5 秒内不许被覆盖）。
6. 加"打扰预算"：每小时自主说话 ≤ N 次、深夜静音、全屏应用时降级。

**难度**：★★☆☆☆（新增 ~250-350 行，改 `heart.py` 主循环 ~30 行；不动 GUI、不动 .NET）
**预期效果**：从"几乎静止"变成"一直在动"。用户最直观感受是"她真的在呼吸"——这是**投入产出比最高的一步**。
**token 消耗**：**0**（纯本地规则）。

---

### 方案 B：心智升级 —— 把一次 LLM 调用展开成 10 分钟的行为

**做什么**：`heart.py` 的 `_think()` 从"选一个动作"升级为"给一份带时间的剧本"，并把 prompt 瘦身。

**怎么做**
1. 输出格式改为：
   ```json
   {"mood":"有点困","energy":0.3,
    "plan":[{"at":0,"do":"motion","name":"troubled"},
            {"at":25,"do":"expr","name":"shy"},
            {"at":90,"do":"speak","text":"……哎，几点了"}],
    "thought":"刚才那本书看到哪了",
    "next_wake_minutes":12}
   ```
   Director（方案 A）负责按 `at` 秒延迟执行 → **一次调用覆盖 2~10 分钟的可见行为**。
2. **prompt 分层**（省 token 的关键）：
   - 常规回合：只给"人格摘要"（从人格 md 里预生成 300~500 字的"行为准则 + 说话风格"）+ 自己的状态；
   - 每 N 次（或情绪大幅变化时）才注入完整人格；
   - 人格 md 内容稳定 → 命中 prompt cache，实际计费按缓存价。
3. **情绪状态机**：`heart.json` 存 `{valence, arousal, energy}`，事件驱动 + 自然衰减（例如被点赞 +0.2、长时间无人理 -0.1/小时）；数值影响方案 A 的权重表。这样"她今天心情不太好"会有可观测的连续性。
4. **内心 OS 可视化**（借鉴 Open-LLM-VTuber）：`thought` 用灰字小气泡写进聊天窗（或只在控制台），不发 TTS —— 用户能看到"她在想事"，这是"自主性"最强的心理暗示。
5. 修 `data/heart.json` 的 race：目前 GUI 和 heart 进程都可能写，建议只在 heart 进程写、GUI 只读。

**难度**：★★★☆☆（`heart.py` 改造 + prompt 重写，~2-3 天；有"剧本跑偏/动作刷屏"的调参成本）
**预期效果**：从"随机小动作"升级为"有目的的一段行为"——例如"发现你回来了 → 抬头 → 笑 → 说一句"。
**token 消耗**：
- 瘦身版（1.2k prompt、每 10 分钟）：`144 次/天 × 1.2k ≈ 17 万 tokens/天`（比现状 55 万还少，但可见行为多 10 倍）
- 保留完整人格版（5~6k、每 15 分钟）：≈ 55 万/天（与现状持平）

---

### 方案 C：感知层 —— 让她"看得见"主人在干什么

**做什么**：给 L0 喂真实刺激，让她能对环境做出反应（而不是只对时间）。

**怎么做**（由易到难）
1. **零成本、无需权限**（Win32 + Qt，几行）
   - 空闲时长：`GetLastInputInfo` → "主人在 / 离开多久了"
   - 前台窗口标题/进程名：`GetForegroundWindow` + `GetWindowThreadProcessId` → "在写代码 / 在看视频 / 在打游戏"
   - 把这些做成 `presence` 对象喂给方案 B 的 prompt（"主人已经连续工作 2 小时"）
2. **低成本视觉**：每 20~30 分钟截一张屏（或只在"主人切了窗口"时），交给项目已有的视觉 MCP（火山方舟 `doubao-seed`）→ 一句话描述 → 作为刺激。**注意隐私**：必须默认关闭、只在本地处理、截图不落盘。
3. **语音**（不做推荐）：常开麦 + ASR 能带来"她听见你说话就转头"，但误触发、隐私、CPU 占用都重。

**难度**：★★★☆☆（感知本身 1 天；视觉接入 1 天；隐私与降级策略另算）
**预期效果**：从"她知道几点了"到"她知道你在赶 deadline"——**这是"像 Neuro"的最后一块拼接**，也是最有惊喜感的部分。
**token 消耗**：纯 Win32 感知 **0**；视觉刺激按每 30 分钟一次算：`48 次/天 × (1.1k 图 + 0.5k 文) ≈ 7.7 万 tokens/天`。

---

### 方案 D：身体层扩展（改 .NET 桌宠）—— 效果上限最高，但最贵

**做什么**：给桌宠加"注视目标 / 参数直控 / 姿态"等端点，让 Python 能指挥身体语言，而不只是播整段动作。

**怎么做**
1. 机器上**只有 .NET 运行时、没有 SDK**（`dotnet --list-sdks` 为空），先装 SDK 才能编译；源码在 `D:\Nori-Desktop-Pet-Fork`（含 `Nori.Desktop.csproj`，可 build）。
2. 新增端点（照 `PetControlServer.cs` 现有 10 个端点的写法，每个 ~30 行）：
   - `POST /look {"x":0.3,"y":-0.2}` → `SetDragging` 直接指定注视目标（现在是全局鼠标独占）
   - `POST /param {"id":"ParamAngleZ","value":0.2}` → 身体倾斜/歪头
   - `POST /state` 增补 `emotion / currentMotion / idleSince`
3. 用现成的行为管线加两个插件（`IBehaviorPlugin` 只有 `Execute(ctx)` 一个方法）：
   - `PostureBehavior`：按情绪调 `ParamBodyAngleZ`（歪头、前倾）
   - `MoodIdleBehavior`：按 valence/arousal 改变 idle 动作权重
4. **风险**：`vendor/nori_desktop_pet/` 是 GPL-3.0 二进制；自己编译的版本要自己维护，还得跟既有 5 个端点保持兼容（Python 侧已依赖它们）。**建议只在自己 fork 里玩，不要回灌 vendor。**

**难度**：★★★★★（装 SDK + 编译 + 调试渲染 + 长期维护两条链路）
**预期效果**：可以做出"歪头看你""身子前倾凑近屏幕"这类**真正的高级身体语言**；但**对"自主性"的提升是边际的**——方案 A/B 做不好时，她歪头也只是个歪头的立绘。
**token 消耗**：0（本地）。

---

### 方案 E：多智能体"小圈子"（Neuro 的 swarm 路线）

**做什么**：让 Nori 有一个"内心议会"或"另一个 AI 朋友"（类似 Neuro / Evil Neuro），通过对话产生自发的素材。

**评价**：话题性最强，但**每轮是 2 倍以上的 token**（两个角色互相说话），而且容易变成"两个 AI 尬聊"。**不建议现在做**，除非前三个方案已经把"单人的自主性"做扎实。若要做，用**本地小模型**（Ollama `qwen2.5:7b`）跑"另一个角色"，成本几乎为 0。

---

## 5. 推荐路线（三期，可按兴趣停在任何一期）

| 期 | 内容 | 工作量 | 每日 tokens | 用户感受 |
|---|---|---|---|---|
| **一期** | ① 修 `emotion_map`/`motion_map`（改配置，10 分钟）<br>② 方案 A 规则导演 + 抢占/冷却 + 时间作息 | 1~2 天 | **0** | "她一直在动，会困会精神" |
| **二期** | ③ 方案 B 心智升级（计划队列 + 情绪状态机 + 内心 OS 可视化 + prompt 瘦身） | 2~3 天 | **15~55 万**（可调） | "她有自己的事在想，会主动起话题" |
| **三期** | ④ 方案 C 感知（空闲/前台窗口 → 零成本；截图视觉 → 可选）<br>⑤ 方案 D 身体扩展（可选，看兴趣） | 2~4 天 | **+8 万**（视觉） | "她知道我在干什么" |

**立即可做的三个零成本改动**（不进任何一期也能显著改善体感）：

1. `config.yaml` 里把 `emotion_map` 换成真实名字：`开心→happy`、`难过→troubled`、`惊讶→surprised`、`害羞→shy`、`生气→angry`、`认真→serious`、`困惑→doubt`；`motion_map` 里 `挥手→wakuwaku`、`鞠躬→nod`（模型没有对应动作）。
2. `heart.py` prompt 里的动作/表情候选改成上面这套（现在是中文标签，模型照抄会失败）。
3. `main.py` 里已经在用的 `play_motion("idle")` 可以换成**按时间段选 idle**（白天 `Idle_pose`、深夜 `sleep_Loop`），一行 if。

---

## 6. Token 与成本测算

单次成本（基于实测）：

| 场景 | 输入 | 输出 | 说明 |
|---|---|---|---|
| 一次聊天（含记忆/搜索） | 6~9k | 200~500 | 人格 8.8k 字符是主要开销 |
| 一次自主唤醒（现状） | **5~6k** | ≤400 | 完整人格 + 状态 + 最近 6 条 |
| 一次自主唤醒（瘦身后） | **1.0~1.5k** | ≤300 | 人格摘要 + 状态 |
| 一次视觉刺激 | 图 ~1.1k + 文 0.5k | ≤150 | 按 1024 图估 |

日/月用量（按推荐节奏）：

| 组合 | 次/天 | 日 input tokens | 月 tokens（30 天） |
|---|---|---|---|
| 现状（15 分钟一次，全量人格） | 96 | ~55 万 | ~1650 万 |
| 一期（纯规则） | 0 | **0** | 0 |
| 二期·经济档（10 分钟、摘要） | 144 | ~18 万 | ~540 万 |
| 二期·丰富档（10 分钟、全量人格） | 144 | ~86 万 | ~2600 万 |
| 三期（+ 每 30 分钟一次视觉） | +48 | +8 万 | +240 万 |
| 每日收尾（记忆整理/日记，1 次） | 1 | ~8k | ~24 万 |

> 量级判断：按月 500 万~3000 万 tokens 计，按常见中文 API 价格（输入 1~4 元/百万、输出 4~16 元/百万）大约是**每月几元到几十元**。真正的成本不是钱，而是**打扰**——她说话太多比花几块钱更烦。

省钱三个杠杆（建议都做）：
1. **人格分层**：常规回合用摘要，只有情绪剧变/长间隔回合才注入完整人格。
2. **命中 prompt cache**：把不变的部分（人格摘要、规则）放在 messages 最前面，保持前缀稳定。
3. **本地小模型兜底**：`heart.py` 的"要不要说话/什么情绪"这类轻判断可以走 Ollama（`qwen2.5:7b`），只有需要"文采"的台词才走云端大模型。

---

## 7. 风险与边界

| 风险 | 说明 | 对策 |
|---|---|---|
| **打扰** | 自主说话过多，比"不动"更糟 | 打扰预算（次/小时、深夜静音、全屏时不说话）+ 用户"别提这个"能写进行为规则 |
| **动作打架** | heart 的意图 / 聊天反应 / 微动作同时抢身体 | 单一 body lock + 优先级 + min-hold |
| **状态文件竞争** | `data/heart.json` 被 GUI 和 heart 双写 | 只让 heart 写，GUI 只读 |
| **"假自主"露馅** | 规则调度重复几次就被看穿 | 用泊松间隔 + 动态权重，避免固定周期；同一动作有冷却 |
| **隐私** | 屏幕截图/前台窗口 | 默认关闭；本地判断优先，视觉只在用户显式开启时启用；截图不落盘 |
| **GPL 传染** | 改 .NET 桌宠属于衍生作品 | 只自用；不分发编译产物；本次不建议动 |
| **成本失控** | 循环里误加 LLM 调用 | 硬约束：1 Hz 循环内禁止任何网络请求；token 预算写进配置并有日上限 |

---

## 8. 需要改的文件清单（一期+二期）

| 文件 | 改动 |
|---|---|
| `config.yaml` | 修 `persona.emotion_map` / `motion_map`；新增 `autonomy:` 段（微动作间隔、打扰预算、作息、情绪衰减、是否感知、是否内心 OS） |
| `agent/pet_director.py` | **新建**：调度器、body lock、权重表、作息、意图队列执行 |
| `heart.py` | 主循环改为"1 Hz 快节律 + 分钟级慢节律"；`_think()` 输出改为 plan 数组；prompt 瘦身；情绪状态机 |
| `agent/live2d_native.py` | 可选：暴露 `play(group,index)` 直接按组播（现在只按名字）；`look_at/set_parameter` 目前是空实现，留待方案 D |
| `gui/chat_window.py` | 可选：内心 OS 灰字气泡（`append_system` 已有通道，改样式即可） |
| `docs/` | 本文 |

---

## 9. 参考资料

- [Open-LLM-VTuber 项目简介](http://docs.llmvtuber.com/docs/intro/)（明确以复现 Neuro-sama 为目标；"AI 主动说话"+"AI 内心 OS"的设计值得抄）
- [社区逆向的 Neuro-Sama 认知架构](https://github.com/o9nn/neuro-sama/blob/main/identity-framework/docs/architecture.md)（感知→认知→行动、情绪 valence/arousal、动作空间注册）
- 本机源码：`D:\Nori-Desktop-Pet-Fork\app\desktop\Nori.Desktop\Live2D\`（`PetControlServer.cs` / `PetRuntime.cs` / `Behaviors\`）
- 模型定义：`%APPDATA%\cn.erhio.noriDesktopPet\data\resources\live2d\arg-nori\ARGNori.model3.json`

---

## 10. 落地状态（2026-10-26，A + B + C 已实现）

> 方案 A/B/C 已按本文实现并实测；D（改 .NET）与 E（多智能体）**未做**，理由见 §5。

### 10.1 新增/改动文件

| 文件 | 状态 | 说明 |
|---|---|---|
| `agent/pet_director.py` | **新建** ~508 行 | 秒级反射层：body lock（优先级 speak 100 > intent 60 > micro 20，静音时段压到 1）、动作/表情白名单、微动作权重表（按 morning/day/evening/night 分档）、泊松抖动间隔、作息与睡眠、主人回来/离开反应、剧本队列（带 `at` 时间轴）、说话预算+冷却、情绪衰减 |
| `agent/presence.py` | **新建** ~150 行 | 纯本地 Win32 感知：`GetLastInputInfo` 取空闲秒数、`GetForegroundWindow` + 进程名取前台应用、`away/returned` 边沿事件；非 Windows 平台安全降级为 `unknown` |
| `heart.py` | **重写** ~470 行 | 1 Hz 快节律（导演）+ 分钟级慢节律（LLM 唤醒）；`_think()` 输出改 plan 数组；人格摘要缓存；情绪状态机（valence/arousal/energy）；内心 OS 写 `data/heart_events.jsonl` |
| `config.yaml` | 改（修错的影射 + 新 `autonomy:` 段） | `emotion_map` 全部换成 arg-nori 真名；`motion_map` 修 2 条；新增 20 余项可调参数 |
| `agent/memory.py` | 改 | `add_memory` 去重、`get_recent_messages` 补 `ts` |
| `main.py` | 改 | 轮询 `data/heart_events.jsonl`（按字节偏移增量读，文件被截断会自愈）→ `chat.append_thought()` |
| `gui/chat_window.py` | 改 | 新增 `append_thought()`（InnerOS 样式，居中灰字小气泡） |

### 10.2 实测数字（本机，2026-10-26）

| 项目 | 实测 |
|---|---|
| 一次自主唤醒（`_think`）的输入 | **853 tokens**（其中 128 命中 prompt cache） |
| 一次自主唤醒的输出 | **153 tokens**（reasoning 0） |
| 一次唤醒耗时 | **~2.0 秒** |
| 人格摘要（一次性，按内容哈希缓存） | 输入 ~5.2k，输出 ~700（含 reasoning），**~6.4 秒**，之后调用 0.01 秒且不再花钱 |
| 唤醒间隔分布 | 9~18 分钟（模型自己给，钳在 2~120 分钟） |
| 有节奏的微动作 | 白天平均约 3 分钟一次（λ=0.0055），夜间约 14 分钟一次（λ=0.0012） |

按 `deepseek-flash` 价格粗算：**一天（含夜里）约 0.6~1.0 元**；把 `think_max_tokens` 调小或拉长间隔还能再降。

### 10.3 已知边界

- 情绪/好感是**进程内状态**，heart 重启会回到基线（持久化在 `data/heart.json`，但没有跨重启的长期人格成长）。
- `live2d_native.py` 的 `look_at()` / `set_parameter()` 仍是空实现（要真控制视线/参数得走方案 D，需要装 .NET SDK）。
- 视觉感知（截图 + 火山方舟 Ark）没接；目前只有"前台是什么程序 + 是否离开"这类结构化感知。
- GUI 里没有自主性开关，全部参数在 `config.yaml` 的 `autonomy:` 段。


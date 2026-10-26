# 长期记忆 + 人格 + 自主唤醒：可复用的设计与实现

> 分析对象：`D:\Nori_Live2D_Chat`（中文 AI 桌面宠物，DeepSeek LLM）。全程只读，未修改目标项目任何文件。
> 分析范围：`agent\memory.py`、`agent\persona.py`、`agent\prompts.py`、`agent\compressor.py`、`heart.py`、`persona\*`、`data\heart.json`、`data\persona_active.json`、`data\settings_overrides.json`、`README.md` 相关章节；为对齐调用链另外读了 `agent\core.py`、`agent\brain.py`、`agent\config.py`、`agent\live2d_native.py`、`agent\services.py`、`main.py`、`config.yaml`（仅读）。

## 0. 实测口径（先纠正几处行数）

| 文件 | 任务描述行数 | 实测行数 | 说明 |
|---|---|---|---|
| `agent/memory.py` | 735 | **798** | 尾部的 `heuristic_importance()` 在 778–798 行，任务描述里的 735 行不含它 |
| `agent/persona.py` | — | 220 | |
| `agent/prompts.py` | — | 76 | |
| `agent/compressor.py` | — | 82 | |
| `heart.py` | 254 | **306** | 尾部 `main()`/`__main__` 在 300–306 行 |

`data/memory.db` 真实内容（以 `mode=ro&immutable=1` 只读打开核对）：`messages` 44 行、`memories` 301 行（episodic 187 / semantic 114）、`rules` 210 行（全部 `enabled=1`）、`summary` 4 行、`conversations` 4 行、`mem_vec` **0 行**（向量未启用：venv 内只有 `jieba 0.42.1`、`numpy 2.5.2`，没有 `sentence-transformers`）。

---

## 1. 记忆体系分层

### 1.1 分层总览

| 层 | 存储 | 写入时机 | 读取方式 | 容量/上限 |
|---|---|---|---|---|
| 工作记忆（最近对话） | SQLite `messages` 表 = `data/memory.db` | 每轮 `handle_user_text` 结束前写 user + assistant 两条（`core.py:276-280`） | `get_recent_messages(n=working_memory_size)`（`memory.py:537-569`） | `llm.working_memory_size: 30`（`config.yaml:21`）；本地 Ollama 降为 10 且禁用压缩（`core.py:192-197`） |
| 情节记忆 episodic | `memories` 表，`type='episodic'` | ① 每轮 `add_exchange` 门槛通过即写（`memory.py:344-356`）；② 反思整合写 LLM 概括的“事件”，`importance=0.55`（`core.py:322-323`） | BM25/向量 `retrieve()`（`memory.py:394-439`） | 全局 `max_memories: 5000`（`config.yaml:143`，`memory.py:592`） |
| 语义记忆 semantic | 同一 `memories` 表，`type='semantic'` | 仅反思整合写入：LLM 提取的“事实”，`importance=0.8`（`core.py:320-321`） | 同上 | 同上（与 episodic 共享名额） |
| 行为规则 rules | `rules` 表 | 仅反思整合：LLM 提取的行为规则，最多 2 条/次（`brain.py:140`，`core.py:324`） | `get_active_rules(limit=15)`（`prompts.py:49`；函数默认 20，`memory.py:517`） | 无条数上限；`rule TEXT UNIQUE` 精确去重（`memory.py:112`） |
| 滚动摘要 summary | `summary` 表（KV） | ① 反思整合后的 `_update_summary()`（`core.py:334-364`）；② 上下文压缩缓存（`compressor.py:49-53`） | `get_summary(f"working:{persona}")`（`prompts.py:58`） | 摘要正文 ≤300 字（`core.py:347`），但 key 数无上限 |
| 向量 | `mem_vec` 表（`mem_id, vec BLOB`） | `_maybe_embed`（`memory.py:474-487`）仅当装了 `sentence-transformers` | `_vector_similarities` 余弦（`memory.py:489-495`） | 无独立上限，随 `memories` 删除联动清理（`memory.py:607`） |

### 1.2 真实 schema（`memory.py:86-167`，与 `PRAGMA table_info` 一致）

- `messages(id INTEGER PK AUTOINCREMENT, ts REAL, role TEXT, content TEXT, importance REAL DEFAULT 0.0, feedback REAL DEFAULT 0.0)`，迁移新增 `persona TEXT NOT NULL DEFAULT 'nori'`（136-142）、`conversation_id INTEGER NOT NULL DEFAULT 0`（143-162）、`image_paths TEXT NOT NULL DEFAULT '[]'`（163-166）。
- `memories(id, uuid TEXT UNIQUE, ts REAL, type TEXT DEFAULT 'episodic', content TEXT, importance REAL DEFAULT 0.5, access_count INTEGER DEFAULT 0, last_access REAL DEFAULT 0.0, source TEXT)`。
- `rules(id, rule TEXT UNIQUE, enabled INTEGER DEFAULT 1, ts REAL, version INTEGER DEFAULT 1, source TEXT)` —— `version` 只有建表默认值，代码从不写（见 §7）。
- `summary(key TEXT PRIMARY KEY, content TEXT, updated REAL)`。
- `conversations(id, persona TEXT NOT NULL, title TEXT NOT NULL, is_main INTEGER NOT NULL DEFAULT 0, created REAL, updated REAL)` + 部分唯一索引 `idx_conv_main ON conversations(persona) WHERE is_main=1`（`memory.py:131`），保证“每人格只有一个主对话”。

### 1.3 写入时机（三个入口，一条捷径）

1. **每轮消息**：`core.py:276-280` 连续两次 `record_message`，随后 `add_exchange`（`core.py:281`）。
2. **交换 → 情节记忆**：`add_exchange` 有双门槛 —— `len("用户：…\nAI：…") >= min_exchange_chars(8)` 且 `heuristic_importance(...) >= importance_threshold(0.15)`（`memory.py:347-354`）；`source=f"msg:{assistant_msg_id}"` 把记忆反查到消息，供 👍/👎 回写。
3. **反思整合**：每 `consolidate_interval: 10` 轮触发一次后台线程（`core.py:292-300`），取最近 80 条消息（`core.py:309-310`，少于 4 条直接返回），一次 LLM 调用产出 `facts/episodes/rules` 三类（`brain.py:125-158`）。
4. **定时回顾**：GUI 定时器每 `max(5, auto_review_minutes=30)` 分钟执行 `merge_similar_memories(0.85)` + `consolidate_now()`（`main.py:905-928`、`config.yaml:148-151`）。

### 1.4 读取与检索链路

`user_text` → ① `_tokenize`：jieba 切分 → 去停用词/标点 → 追加中文二元组（`memory.py:205-218`）→ ② `_bm25_scores`：查内存倒排 `self.postings`，`k1=1.5, b=0.75`（`memory.py:377-392`）→ ③ 可选 `_vector_similarities`：句子向量余弦（`memory.py:489-495`）→ ④ 综合打分、排序、取 `top_k`，并对命中项 `_touch` 累加 `access_count`（`memory.py:432-439`）→ ⑤ `prompts.py` 渲染成 `- [type] content` 列表（`prompts.py:44`）。

关键实现细节（复用时要保留的语义）：

- **索引在内存**，启动时 `_rebuild_index()` 全表扫一遍建倒排（`memory.py:169-191`），增删改后再全量重建（`update_memory`/`delete_memory`/`forget_excess`/`merge_similar_memories` 都调它）。
- **中文二元组兜底**：jieba 切完再把连续汉字的 2-gram 全部追加，解决“草莓蛋糕”切碎后召回差的问题（`memory.py:212-217`）。
- **jieba 缺失时退化**为正则单字/单词切分（`memory.py:50-55`），零硬依赖。
- **停用词**：`STOPWORDS` 中英混合表（`memory.py:31-39`）；噪声判定 `_is_noise` 还过滤纯符号（`memory.py:194-203`）。
- **空召回短路**：`if not bm: return []`（`memory.py:400-401`）—— 这条在纯向量场景是硬伤，见 §6。

### 1.5 评分与遗忘公式（照抄参数 + 行号）

- 向量可用时（`memory.py:426-427`）：`score = 0.55*bm25_norm + 0.30*vec_norm + 0.10*recency + 0.05*importance + access_boost`
- 纯 BM25 时（`memory.py:428-429`）：`score = 0.75*bm25_norm + 0.15*recency + 0.10*importance + access_boost`

各项来源：

| 项 | 公式 | 行号 |
|---|---|---|
| `bm25_norm` | `bm_score / max(bm_scores)` | `memory.py:403, 420` |
| `vec_norm` | 归一化向量点积（cosine），`normalize_embeddings=True` | `memory.py:478, 490-494` |
| `recency` | `0.5 ** ((now - ts) / half_life)`，`half_life = 7*86400.0 = 604800` 秒 | `memory.py:412, 422` |
| `importance` | `memories.importance`，默认 0.5 | `memory.py:101, 423` |
| `access_boost` | `min(0.1, access_count * 0.01)` | `memory.py:424` |
| BM25 IDF | `log(1 + (N - df + 0.5) / (df + 0.5))` | `memory.py:373-375` |
| BM25 打分 | `idf * tf*(k1+1) / (tf + k1*(1-b+b*dl/avgdl))`，`k1=1.5, b=0.75` | `memory.py:377-392` |
| 容量遗忘排序 | `ORDER BY (importance + 0.0001) / (1.0 + (strftime('%s','now') - ts)/86400.0) ASC, ts ASC`，删除溢出条数 | `memory.py:599-606` |
| 相似合并 | `overlap = |A∩B| / min(|A|,|B|) >= threshold`，threshold 夹在 `[0.5, 0.98]`，默认 0.85 | `memory.py:696-718` |

启发式重要性（`memory.py:778-798`，不调 LLM，这是本项目最值得抄的小函数）：基线 `0.12`；`role=="assistant"` **减 0.04**；命中 `_PERSONAL_HINTS`（25 条，`memory.py:41-45`）每条 **+0.12**；命中 `_NEGATIVE_HINTS`（7 条，`memory.py:47`）每条 **+0.10**；`len>40` **+0.06**；`len>120` **+0.04**；含数字 **+0.02**；含 `?`/`？` **+0.02**；最后 `clamp(0,1)`。注意 hint 是**逐条累加**，命中 8 个“我…”短语就直接封顶 1.0。

反馈学习：`apply_feedback` 把 `delta` 写回 `messages.feedback`，并只对该消息派生的记忆做 `importance += delta * 0.25`，夹在 `[0.05, 1.0]`（`memory.py:358-370`）。

### 1.6 遗忘 / 合并 / 隔离的真实边界

- **容量遗忘**只在 `add_memory` 末尾顺带触发（`memory.py:341`），不是定时任务；一次删掉全部溢出量，然后全量重建索引。
- **相似合并**是唯一“去重”手段，靠 token 集合重叠率；保留 `importance` 最高（并列时 `ts` 最新）的一条，内容用 `；` 拼接并截断到 2000 字（`memory.py:726-733`）。
- **人格隔离的真实做法规格**（这点 README 没写清，必须按代码讲）：
  - 做到了：`messages.persona` + `messages.conversation_id`（`memory.py:537-569` 的 WHERE 拼接）；`conversations.persona` + 每人格唯一主对话（`memory.py:131, 243-257`）；摘要 key 带人格 `working:{persona}`（`core.py:344`）与 `ctx:{persona}:{digest}:{window}`（`compressor.py:47`）。
  - **没做到**：`memories` 与 `rules` 表**没有 persona 列**，`retrieve()`（`memory.py:394-439`）和 `get_active_rules()`（`memory.py:517-522`）都不按人格过滤 —— 长期记忆与规则是**全人格共享**。实测证据：301 条记忆跨 `Nori System Prompt V3.5` 与 `aurith` 两个人格共用；`messages` 里还留着 8 条 `persona='aurith'`，而 `persona\` 目录下已无 `aurith.md`（人格被删、记忆与消息不清库，`persona.py:171-190` 只删 .md 与 .meta.json）。
  - 副作用：摘要按人格分 key，切换人格后新人格的 `working:{persona}` 为空 —— 实测 `summary` 只有 `working:Nori System Prompt V3.5`，没有 `working:Nori System Prompt V3.5.2`（当前 `persona_active.json` 生效的正是 V3.5.2）。

---

## 2. 人格系统

### 2.1 `persona/*.md` 就是完整 System Prompt

- 约定写在 `persona.py` 文件头（1-7 行）：`persona/*.md` 一人格一文件，`persona/nori.md` 是出厂默认；**人格提示词完全来自 .md，`config.yaml` 不再保存任何人格内容**。
- 加载入口 `load_persona_text(cfg)`（`persona.py:125-136`）：读当前生效人格文件 → 空/异常则回落 `default_persona_text`（`persona.py:48-58`，优先 `persona/nori.md`，再回落两行内置兜底 `_DEFAULT_FALLBACK`，`persona.py:44-45`）。
- 文件名校验 `_safe_name`（`persona.py:22-27`）：去 `.md` 后缀、`[\\/:*?"<>|]` 换 `_`、`..` 换 `_`、空名回落 `nori`。这是防路径穿越的最小实现，复用时应保留。
- 现存人格：`nori.md`（2 行，兜底用）、`Nori System Prompt V3.5.md`（294 行 / 9,067 字符）、`Nori System Prompt V3.5.2.md`（293 行 / 9,082 字符）—— 后者是**当前生效人格**，是“成品 prompt”，一个占位符都没有（实测 `{{time}}/{{memory}}/{{rules}}/{{summary}}` 命中数均为 0）。

### 2.2 占位符替换实现（`agent/prompts.py`）

占位符集合常量：`_PLACEHOLDERS = ("{{time}}", "{{memory}}", "{{rules}}", "{{summary}}")`（`prompts.py:21`）。四处取值：

| 占位符 | 取值 | 行号 |
|---|---|---|
| `{{time}}` | `当前时间：%Y年%m月%d日 %H:%M:%S 星期X。涉及日期、时间、节日、天气等时效性问题时，以此为准。` | `prompts.py:29-31` |
| `{{memory}}` | `memory.retrieve(user_text, k=cfg.memory["top_k"]=8)` → `- [type] content` 多行 | `prompts.py:38-44` |
| `{{rules}}` | `memory.get_active_rules(limit=15)` → `- rule` 多行 | `prompts.py:46-53` |
| `{{summary}}` | `memory.get_summary(f"working:{persona}")` | `prompts.py:55-60` |

替换是无条件链式 `str.replace`（`prompts.py:63-67`），**取不到数据就替换成空串**，不会抛错也不会删占位符以外的内容。

### 2.3 无占位符时的追加逻辑（`prompts.py:33-35, 69-76`）

```python
auto_inject = (not any(p in template for p in _PLACEHOLDERS)
               and bool(cfg.memory.get("inject_context", True)))
...
blocks = [f"【当前时间】{time_line}"]
if mem_text:    blocks.append("【与当前话题相关的长期记忆】\n" + mem_text)
if rules_text:  blocks.append("【你学到的行为规则】\n" + rules_text)
if summary_text:blocks.append("【此前对话的滚动摘要】\n" + summary_text)
return template + "\n\n" + "\n\n".join(blocks)
```

要点：① 判定是“**一个占位符都没有**”而不是“缺哪个补哪个”，混写（只写 `{{memory}}`）会走替换分支、时间/规则/摘要全部丢失；② `memory.inject_context: false` 可退回“只用 .md 原文”（`config.yaml:136-139`）；③ 三个数据块**按需出现**，取不到就不出标题，避免空块污染 prompt；④ 追加块标题是中文方括号，视觉上与人格正文分离。CHANGELOG 第 12 行记录了这次修复的动机：成品人格没人写占位符，导致记忆/规则/时间“静默失效”。

### 2.4 `persona_active.json` 与 `*.meta.json` 字段含义

`data/persona_active.json`（实测）：`{"active_persona": "Nori System Prompt V3.5.2"}` —— 唯一字段，`set_active_persona` 写入（`persona.py:109-118`），`_read_active_name` 读取，缺失/损坏时回落 `cfg.persona.active_persona` 再回落 `nori`（`persona.py:85-95`）。`active_persona_name` 还会校验“文件仍存在”，否则回落默认（`persona.py:98-106`），避免指向已删人格。

`persona/<name>.meta.json`（实测三份内容一致）：`{"agent_name": "Nori", "avatar": "D:\\Nori_Live2D_Chat\\data\\avatars\\nori_avatar.png"}`

- `agent_name`：**显示名**（聊天气泡昵称、`gui.agent_name` 兜底），由 `default_agent_name` 生成默认值（名字以 `nori` 开头则固定 `"Nori"`，否则原样，`persona.py:198-202`）。
- `avatar`：用户/智能体头像的**绝对路径**（GUI 选择图片后写入）。
- 读取 `load_persona_meta`（`persona.py:205-213`）：JSON 坏了/不是 dict 就返回默认 `{"agent_name": ..., "avatar": ""}`；写入 `save_persona_meta`（`persona.py:216-219`）直接覆盖，无原子写。删除人格时一并删除 `.meta.json`（`persona.py:183-185`）。

### 2.5 `persona.control_rule`（Live2D 标签强制规则）：README 与代码不一致

- README 有两处声称存在 `config.yaml` 的 `persona.control_rule`（`README.md:134`、`README.md:358`），并描述“每轮必须主动用 `[expr:…]`、空闲用 `[motion:发呆]`”。
- 实际代码：**全仓只有 `README.md` 与 `scripts/smoke_new_features.py:20` 提到 `control_rule`，`config.yaml` 里没有这个键，也没有任何 Python 代码读取它**。`scripts/smoke_new_features.py:26` 还在断言旧行为（`persona.base` + 默认文本），已与 `persona.py:48-58` 对不上 —— 属**文档/脚本漂移**，复用本项目时不要照 README 抄这个配置项。
- 现在真正生效的 Live2D 标签规则是**硬编码的第二条 system message**（`core.py:221-234`），条件是 `live2d.controller == "native"`，正文为：
  > 【Live2D 动作选择】请根据当前对话内容与情绪，在回复正文之前输出一个动作或表情标签（不要输出多个）：
  > - 动作：`[motion:nod] [motion:shake] [motion:wakuwaku] [motion:angry] [motion:troubled] [motion:dizzy] [motion:sleep] [motion:back]`
  > - 表情：`[expr:smile] [expr:happy] [expr:angry] [expr:shy] [expr:dark] [expr:speechless] [expr:tears] [expr:troubled] [expr:doubt] [expr:disgust] [expr:serious] [expr:surprised]`
  > 标签会被解析并立即让 Live2D 做出动作，不会显示给用户。

- 标签解析在 `parse_commands`（`brain.py:15, 27-42`）：正则 `\[(expr|motion|emotion):([^\]\]]+)\]`，`emotion` 视为 `expr` 别名，命中的标签**从正文里删除**并作为 `(kind, name)` 返回；随后 `\n{3,}` 压成 `\n\n`。`config.yaml` 的 `emotion_map`/`motion_map`（`config.yaml:58-74`）只做“逻辑名 → 模型真实名”映射，不再进 prompt。
- 值得注意的**双轨制**：聊天主链路的标签词表是英文（`nod/smile`），`heart.py` 走的是**中文**标签并使用 `emotion_map`/`motion_map` 翻译（`heart.py:185-195`）。两条路径的标签体系并不统一。

### 2.6 可复用的 prompt 拼装函数契约

现状签名（`prompts.py:24`）：`def build_system_prompt(cfg, memory, user_text: str = "") -> str`。把它抽象成可移植契约（建议直接照这个改，向后兼容）：

```python
def build_system_prompt(cfg, memory, user_text="", *, budget_chars=None, now=None, persona=None) -> str
# 前置条件（鸭子类型，memory 只需 3 个方法）：
#   memory.retrieve(query: str, k: int) -> list[dict[type, content]]
#   memory.get_active_rules(limit: int) -> list[str]
#   memory.get_summary(key: str) -> str          # key = f"working:{persona}"
# 不变量：
#  1. 返回单条 system prompt 字符串；调用方只把它放进 messages[0]（core.py:210）。
#  2. 模板来自 persona/<name>.md，程序不追加 config 人设（保持“单一事实来源”）。
#  3. 占位符集合固定 4 个；任一数据源异常 → 该占位符替换为 ""，绝不抛异常（prompts.py:39-43）。
#  4. template 中一个占位符都没有 且 memory.inject_context=True → 追加 4 段中文块；
#     inject_context=False → 原样返回 template（语义等价于“只用 .md”）。
#  5. 时间在调用瞬间取（now 可注入以便测试）；不做任何缓存。
# 建议增强：budget_chars 截断注入块（当前完全没有长度预算，见 §6.3）。
```

---

## 3. 摘压缩（`agent/compressor.py`）

定位：保留最近 `window_size` 条原文，更早的交给 LLM 压成 300 字摘要，摘要按“人格 + 旧消息指纹 + 窗口”缓存在 `summary` 表。它是**工作记忆的第二层漏斗**，与 §1 的 `memories` 长期记忆互不依赖。

参数与实现（全部实测）：

| 项 | 值 | 行号 |
|---|---|---|
| 配置来源 | `cfg.llm.context_compression` | `compressor.py:21-22` |
| `mode` | `"auto"`（`off` 关闭；`on`/`auto` 行为相同） | `config.yaml:24`，`compressor.py:26-33` |
| `window_size` | `20`，且 `max(5, …)` 兜底 | `config.yaml:25`，`compressor.py:29, 37` |
| `max_chars` | `300`，且 `max(100, …)` 兜底 | `config.yaml:26`，`compressor.py:38` |
| 触发条件 | `history_len > window`（即 >20 条） | `compressor.py:32-33, 39` |
| 缓存 key | `ctx:{persona}:{sha1(role:content拼接)[:12]}:{window}` | `compressor.py:44-47` |
| 压缩输入 | 只取更早部分的**最后 60 条** | `compressor.py:67` |
| 压缩调用 | `temperature=0.2`，`max_tokens=max(100, max_chars*0.75)=225` | `compressor.py:74-76` |
| 输出截断 | `[:max_chars*2]` = 600 字符 | `compressor.py:79` |
| 注入形态 | 一条 system：`【更早对话的压缩记忆】…请继承其中的信息，但不要逐字复述：\n{summary}` + 最近 window 条 | `compressor.py:57-62` |
| 失败兜底 | 异常返回 `""`；`history_for_llm` 拿不到摘要就**原样返回全量 history** | `compressor.py:55-56, 80-82` |

风格问题（复用时要改）：① `auto` 与 `on` 分支代码完全一样（`compressor.py:30-33`），注释声称的“按长度智能压缩”没实现；② 缓存 key 覆盖**全部**更早消息，每轮新消息都会改变 digest → 实际几乎每轮都 miss 并重调 LLM；③ 兜底“原样返回全量 history”会在 LLM 压缩失败时把最长上下文直接灌给模型，与压缩初衷相反。

---

## 4. `heart.py`：自主唤醒进程

### 4.1 进程形态

- 独立脚本，由 GUI 用 `pythonw.exe` 无窗口拉起（`services.py:183-208`），环境变量 `NORI_HEART_SKIP_LIVE2D=1` 可跳过 Live2D（`heart.py:53`，`services.py:192-194`）；也可 `scripts\start_heart.bat` 单独跑。
- 单实例靠 `data/heart.pid`（`heart.py:271-272`）+ 退出清理（`293-297`）；GUI 侧用 pid 文件 + CIM 命令行校验 `heart.py` 防误杀（`services.py:118-122, 166-181`）。
- 主循环（`heart.py:264-297`）：`interval = max(5, poll_interval_sec=20)`，`while True: tick(); sleep(interval)`，`tick()` 外包 try/except 保证不退出（`287-291`）。
- 自己的日志与 logging 配置：`data/logs/heart.log`（`heart.py:23-33`）。
- 自己开一个 `MemoryStore` 连接（`heart.py:51`），**只读**：全文件没有 `record_message`/`add_memory`/`set_summary` 调用 —— 私人时间不产生长期记忆。

### 4.2 状态机与时间计算

状态只有两段时间戳 + 两支历史（`heart.py:61-74`）：`next_wake_at`、`last_wake_at`、`thoughts[]`、`actions[]`。首次启动 `next_wake_at = time.time()`（`62-63`），即**立即醒一次**。

`tick()`（`heart.py:216-262`）的完整分支：

```
if now < next_wake_at:                       return                        # 没到点，什么都不做（218-219）
if _user_recently_active(): next_wake_at = now + 5*60; save; return        # 安静策略，硬编码 300s（221-226）
decision = _think()  # LLM JSON                                            # 到点，私人思考（228-235）
  └ 异常 → next_wake_at = now + default_wake_minutes(15)*60; save; return   # （231-235）
_execute(decision) → expression / motion / speak                           # （237-247）
thoughts.append(thought); actions.append(log); 各自 [:−20:] 截断            # （242-245）
minutes = int(decision.get("next_wake_minutes", default_minutes))            # （251-253）
  └ TypeError/ValueError → 回落 default_minutes(=15) 并记 warning          # （254-257）
minutes = clamp(min_wake_minutes=2, max_wake_minutes=120)                  # （258-259）
next_wake_at = now + minutes*60; last_wake_at = now; save                   # （260-262）
```

三级兜底（类型 → 配置默认 → clamp）是 CHANGELOG 第 13 行修的线上故障：模型返回 `null` 或 `"30分钟"` 时 `int()` 抛异常，异常越过 `tick()` 导致 `next_wake_at` 不推进，于是**每 20 秒重调一次 LLM**，额度被烧。这段注释（`249-251`）直接把事故写成不变量，值得原样搬走。

安静策略（`heart.py:97-107`）：取当前人格最近 3 条消息，只要有一条 `role=="user"` 且 `now - ts < chat_quiet_sec(90)` 就算“主人活跃”。注意 `get_recent_messages_with_ts(3, persona=...)` **没有按 conversation 过滤**（`heart.py:101`），多会话时会跨会话判断活跃。

### 4.3 `data/heart.json` 结构（实测）

只有 4 个顶层字段，全部平铺，无嵌套、无 schema 版本：

| 字段 | 类型（实测值） | 含义 |
|---|---|---|
| `next_wake_at` | float epoch 秒（`1792489180.3895872`） | 下次该醒来的时刻，由上一轮的 `now + minutes*60` 写入 |
| `last_wake_at` | float epoch 秒（`1792486960.3895872`） | 上次真正完成思考的时刻 |
| `thoughts` | string[]（当前 20 条，含多条 `""`） | 每次醒来的内心想法，`heart.py:242` 追加 |
| `actions` | string[]（当前 20 条） | 每次醒来的动作日志，形如 `action=speak expression=开心 motion= text=…`（`heart.py:239-240`） |

- 两个时间戳实测差值 `1792489180 - 1792486960 = 2220s = 37 分钟`，落在 2–120 区间内，说明模型自定的节奏生效。
- `thoughts` 与 `actions` 各 20 条（`heart.py:244-245`），但**喂给 LLM 的只有最近 5 条**（`heart.py:113-114`）—— 存储 20 是留给人看的，注入 5 是控制 prompt 长度。
- `thoughts` 里有大量 `""`：`decision.get("thought", "")` 缺字段就写空串（`heart.py:242`），随后 prompt 里渲染成 `- ` 空行（`heart.py:115`）。**复用时要过滤空串**，否则 5 条里可能 4 条是空白，意识连续性名存实亡。
- 文件无 schema 版本字段、无迁移逻辑：`_load_state` 只 `setdefault("thoughts"/"actions", [])`（`heart.py:70-71`）。

### 4.4 如何注入上下文（与主对话完全不同的第二条 prompt 路径）

`_think()` 用 f-string 直接拼（`heart.py:130-158`），组成：

1. `load_persona_text(cfg)` —— **整份人格 .md 原文**（9,082 字符）；
2. 固定说明句“这是你的‘私人时间’自主唤醒回合，主人没有正在和你说话。”；
3. 时间行 `%Y年%m月%d日 %H:%M:%S 星期X`；
4. `【意识连续性：上次独处时你做了什么】` + 最近 5 条 `actions`；
5. `【你当时的心思想法】` + 最近 5 条 `thoughts`；
6. `【最近的对话环境】` + `_recent_context()`（当前人格最近 6 条消息，`heart.py:84-95`，无消息时给“最近没有新对话。”）；
7. 用户称呼 `master_line`（`heart.py:124-128`）：`gui.user_name` 非空且不等于“主人”才写名字（实测 `Alorit`，见 `settings_overrides.json:3`），否则统一用「主人」；
8. JSON 输出契约 + 规则（“大部分时候 action 用 none…不要频繁打扰主人”“不要用括号描述状态”）。

与主对话链路的差异（复用时要心里有数）：**不调 `build_system_prompt`**、**不调 `memory.retrieve`**、**不注入 rules/summary**、**不读 `memory.get_summary`** —— heart 看不到长期记忆与滚动摘要，只有 6 条近期消息 + 自己 5 条旧念头。这也是同一个 .md 会被两套逻辑消费的耦合点。

调用参数：`temperature=0.9`、`max_tokens=400`、`response_format={"type":"json_object"}`（`heart.py:160-166`）；返回非合法 JSON 或非 dict 时**只跳过本轮**并返回 `{}`（`heart.py:168-176`）。

### 4.5 如何驱动 Live2D / TTS

`_execute`（`heart.py:179-196`）：

- `action=="expression"` → `live2d.set_expression(emotion_map.get(expression, expression))`；
- `action=="motion"` → `live2d.play_motion(motion_map.get(motion, motion))`；
- `action=="speak"` → 先（可选）换表情，再 `_speak(text)`；`medium` 的 `action` 一律 `none`。

Live2D 客户端是本地 HTTP 控制（`live2d_native.py:32`，`http://127.0.0.1:47835`）：`set_expression` → `POST /expression {"name":…}`（`live2d_native.py:111-115`）；`play_motion` → `POST /motion {"name":…}` 或 `{"group","index"}`（`103-109`）；`set_speaking` → `POST /mouth {"level":0,"speaking":bool}`（`135-141`）；启动保证 `ensure_running()` 轮询 `/state` 最多 30 秒（`67-97`），heart 启动时调用一次（`heart.py:274-280`）。

TTS（`heart.py:198-213`）：`allow_speak` 开关（`config.yaml:191`）；懒加载 `agent.tts.factory.create_tts(cfg)`（`203-204`）；说话期间 `set_speaking(True)`，`finally` 里复位 `False`（`206-211`）；TTS 异常只 warning，不影响时间推进。

### 4.6 可复用点（heart 的设计精华）

1. **“下次醒来时间”由模型自己写**，而不是固定 cron / 固定间隔 —— 自然产生不规则的、看起来像“有自己节奏”的行为。
2. **状态文件承载意识连续性**：`thoughts`/`actions` 双通道，存 20 注 5，成本极低（每次醒来 1 次 LLM 调用）。
3. **外部活跃信号优先于内部计划**：用户刚说话就让路，并把下次唤醒推后 5 分钟（`heart.py:221-226`）。
4. **数值三级兜底**：类型兜底 → 配置默认 → 上下限 clamp，且异常永远不阻止 `next_wake_at` 推进。
5. **主程序只做进程托管**：heart 只读 `memory.db`、只写自己的 `heart.json`，进程崩溃不影响主对话。

### 4.7 v0.3.0 重写：从「醒来放一个动作」到「两层 + 剧本」

> 上面的 §4.1–§4.6 描述的是 **v0.2.2 的单层 heart**，作为设计参考仍然有效；但代码已整体重写（`heart.py` 306 → 492 行），要点如下。设计与评估见 `docs/autonomy-plan.md`。

**分工变了：LLM 不再直接驱动动作**

| 层 | 文件 | 频率 | 花 token |
|---|---|---|---|
| 反射层（导演） | `agent/pet_director.py` | 1 Hz | 不花 |
| 心智层（心脏） | `heart.py` | 5~30 分钟 | 每次约 1k |
| 感知层 | `agent/presence.py` | 2 秒 | 不花 |

- **LLM 产出的是剧本，不是命令**：`{"thought", "mood", "plan": [{"at": 8, "type": "motion", "name": "wakuwaku"}, {"at": 20, "type": "speak", "text": "…"}], "next_wake_minutes": 15}` —— `at` 是相对秒数，导演按时间轴在接下来几分钟里陆续执行，这样"醒来一次"能撑起一段有节奏的行为，而不是'啪'一下换个表情又睡回去。
- **`PetDirector` 的三个关键机制**（复用时最值钱的部分）：
  1. **body lock + 优先级**（说话 100 > 剧本意图 60 > 微动作 20）：同一时刻只执行一个动作，高优先级可抢占，并给动作一个最短驻留时长（`_HOLD`），避免 1 Hz 抖动。
  2. **能力白名单**：首帧从 `GET /state` 读 `motions[].names` / `expressions[]`，只发模型真有的名字；发错一次就拉黑，不会反复 404。
  3. **泊松间隔**：微动作的等待时间按指数分布抽样（`micro_lambda_day=0.0055` ≈ 平均 3 分钟，夜间 `0.0012` ≈ 14 分钟），不是固定节拍——这是"看起来像活的"最省力的办法。
- **情绪状态机**：`valence`(-1~1) / `arousal`(0~1) / `energy`(0~1)，每 tick 向基线衰减；低落时降低 `wakuwaku` 权重、提高 `troubled`，并把当前情绪写进下一轮 prompt。
- **人格摘要缓存**：`_ensure_persona_digest()` 把 8.8k 字符人格压成约 400 字，按 `sha1(人格全文)` 缓存到 `data/heart_persona_digest.json`；未命中时一次约 9k tokens，命中时 0。自主回合输入从 5.2k 降到 **853 tokens**。
- **`reasoning` 型模型的坑**：`deepseek-flash` 会先输出思考再输出正文，`max_tokens=2000` 会被思考吃光，得到 `finish_reason=length` + 空 `content`。摘要请求给到 8000，思考上限 3000，失败自动翻倍重试一次。
- **事件流替代黑盒**：想法写 `data/heart_events.jsonl`（每行一个 JSON），GUI 用 `agent/heart_events.py` 按字节偏移增量读 → `ChatWindow.append_thought()` 渲染成居中的灰色小字条。文件被截断（换机/手动删）时偏移回退自愈。
- **感知层**：`presence.py` 只回答两个问题——"主人多久没输入了"（`GetLastInputInfo`）和"前台进程是谁"（`GetForegroundWindow` + `GetWindowThreadProcessId` → 进程名）。**默认不读窗口标题**（`use_window_title: false`），因为标题里可能是别人的聊天记录。离开 ≥ `away_sec`(300) 她自己去睡，回来触发"伸懒腰"意图。
- **新的配置段**：`config.yaml` 的 `autonomy:`（约 20 项：`enabled` / `tick_sec` / `micro_motion` / `micro_lambda_day|night` / `quiet_hours` / `speak_budget_per_hour` / `speak_cooldown_sec` / `presence` / `away_sec` / `use_window_title` / `inner_os` / `persona_digest` / `emotion_baseline`）。`heart:` 段的语义没变（轮询间隔、唤醒上下限、安静窗口、状态文件）。


---

## 5. 可复用清单

| 复用对象 | 源位置 | 依赖 | 需要替换的耦合点 |
|---|---|---|---|
| 分层记忆 schema + 老库迁移模式（`PRAGMA table_info` + `ALTER TABLE ADD COLUMN DEFAULT`） | `agent/memory.py:86-167` | `sqlite3` | 库路径由 `cfg.db_path` 注入（`data/memory.db`）；老数据默认 `persona='nori'`；`idx_conv_main` 的“每人格一个主对话”假设 |
| 中文 BM25（jieba + 2-gram 兜底 + 内存倒排 + 全量重建） | `agent/memory.py:169-218, 373-392` | `jieba`（缺失自动退化正则，`50-55`） | `STOPWORDS` 中英表（`31-39`）、`k1=1.5/b=0.75`、单进程内存索引（多进程需各自重建） |
| 综合评分器（BM25+向量+时间衰减+重要性+访问加成） | `agent/memory.py:394-439` | `numpy`（仅向量分支） | 权重 0.55/0.30/0.10/0.05 与 0.75/0.15/0.10、半衰期 604800s、`access_boost` 上限 0.1 |
| 启发式重要性打分 | `agent/memory.py:778-798` | 无 | `_PERSONAL_HINTS`(25)/`_NEGATIVE_HINTS`(7) 中文词表、基线 0.12、assistant 罚分 0.04 |
| 容量遗忘（按“重要性/年龄”排序删） | `agent/memory.py:590-609` | SQLite `strftime` | `max_memories=5000`、SQL 内的时间单位（天） |
| 相似记忆合并（token 重叠率） | `agent/memory.py:696-747` | `_tokenize` | `threshold=0.85`（夹 0.5–0.98）、拼接符 `；` 与 2000 字截断 |
| 规则表 + 启用开关 + 精确去重 | `agent/memory.py:498-522, 676-694` | SQLite `UNIQUE(rule)` | 注入上限 15（`prompts.py:49`）；规则无 persona 归属 |
| 摘要 KV 表（`working:*` / `ctx:*` 共用一表） | `agent/memory.py:524-534` | SQLite | key 命名约定：`working:{persona}`、`ctx:{persona}:{digest}:{window}` |
| 反思整合闭环（每 N 轮后台线程 → facts/episodes/rules） | `agent/core.py:292-332` + `agent/brain.py:125-158` | OpenAI 兼容 chat、`json_object` | `consolidate_interval=10`、importance 0.8/0.55、prompt 三条产出定义、`is_local_llm` 关闭分支 |
| 滚动摘要更新（旧摘要 + 最近 100 条 → 300 字） | `agent/core.py:334-364` | chat 调用 | `max_chars=300`、`max_tokens=500`、`temperature=0.3` |
| 上下文压缩器（窗口 + 指纹缓存） | `agent/compressor.py:15-82` | `hashlib` + chat | `window_size=20`、`max_chars=300`、缓存 key 结构与 `summary` 表复用 |
| `.md` 即 system prompt 的人格加载 | `agent/persona.py:22-148` | 无 | 默认人格名 `nori`、`_DEFAULT_FALLBACK` 两行文案（`44-45`）、`persona/` 目录名 |
| 人格元数据（显示名/头像） | `agent/persona.py:194-219` | `json` | `avatar` 存绝对路径（换机即失效）；默认名规则“nori 前缀 → Nori” |
| 占位符 + 自动追加的 prompt 拼装 | `agent/prompts.py:24-76` | `persona.py`、memory 三方法 | 4 个占位符字面量、4 段中文块标题、`top_k=8` 与 rules `limit=15`、时间格式串 |
| Live2D 标签规则注入 + 标签解析 | `agent/core.py:221-234` + `agent/brain.py:15, 27-42` | — | 硬编码英文 motion/expr 词表（与 `config.yaml` 的 `emotion_map/motion_map` 中文逻辑名两套体系）；`controller=="native"` 判断 |
| 自主唤醒循环（模型自定下次时间） | `heart.py:216-262` | `time`、OpenAI chat | `poll_interval_sec=20`、`min/max_wake_minutes=2/120`、`default=15`、安静 300s 硬编码 |
| 唤醒状态文件（thoughts/actions 双通道） | `heart.py:61-81` | `json` | 路径 `data/heart.json`、各留 20 存/5 注、状态无版本号 |
| 唤醒决策 JSON 契约 | `heart.py:144-158` | `response_format=json_object` | `action` 四值枚举、`speak` ≤30 字、语气词要求 |
| 安静策略（最近用户消息时间窗） | `heart.py:97-107, 221-226` | memory 读 | `chat_quiet_sec=90`、跨会话不过滤、推后固定 300s |
| 后台进程托管（pid + 命令行校验 + 无窗口启动） | `agent/services.py:118-235` + `heart.py:271-297` | `subprocess`、CIM/PowerShell | `pythonw.exe` 路径、进程名硬编码 `heart.py`、Windows `creationflags` |

---

## 6. 坑（复用前必须处理）

### 6.1 SQLite 并发

- 单连接 + `check_same_thread=False` + `threading.RLock`：`MemoryStore.__init__` 只建**一个**连接（`memory.py:62-65`），所有公开方法用同一把 `RLock` 串行化。跨线程安全，但**跨进程不安全**：GUI 进程与 heart 进程各开一条连接指向同一 `data/memory.db`（`heart.py:51`），且**没有设置 `PRAGMA journal_mode=WAL`、没有 `timeout=`**（默认 5s 忙等）。
- 现实风险：GUI 的反思整合线程（`core.py:299`）与定时回顾线程（`main.py:913-928`）会写库，heart 同时在读；一旦写入持锁超 5 秒就 `database is locked`。heart 侧每个 tick 都 `get_recent_messages_with_ts`（`heart.py:87, 101`），高频短读放大了碰撞窗口。
- 另一处放大：`_touch()` 每次检索都 `UPDATE + commit`（`memory.py:441-453`），一轮对话 8 条记忆 = 8 次提交；`forget_excess`/`update_memory`/`delete_memory`/`merge` 每次都在锁内**全量重建 BM25 索引**（`_rebuild_index` 扫 `memories` 全表，`memory.py:169-191`），301 条时无感，5000 条时每次编辑都会明显卡顿。
- 建议：`journal_mode=WAL` + 显式 `timeout=30` + 把 `_touch` 改成批量/去抖提交；索引重建改成增量（按 id 增删 postings）。

### 6.2 JSON 原子写

- `heart.json`（`heart.py:76-81`）、`persona_active.json`（`persona.py:114-117`）、`settings_overrides.json`（`config.py:121-122`）、`*.meta.json`（`persona.py:217-219`）全部是 `Path.write_text(json.dumps(...))` —— **直接覆盖、非原子**。断电/崩溃/杀进程正好落在 truncate 之后，就得到半截 JSON。
- 后果比“丢一次状态”更糟：`_load_state` 解析失败会**静默返回 default**（`heart.py:68-74`），而 default 的 `next_wake_at = time.time()`（`62-63`）→ heart 立刻再醒一次；如果状态文件反复损坏，就退化成每 20 秒一次 LLM 调用（与 §4.2 修掉的那个事故同型）。
- 建议：同目录 `tmp` 写入 + `os.replace()`；读侧保留最近一次有效状态（`heart.json.bak`）；`persona_active.json` 损坏时按 `persona.py:85-95` 的既有回落链恢复即可，但不要覆盖用户文件。

### 6.3 prompt 长度失控

- 输入侧**完全没有预算**：人格 .md 本身 9,082 字符（V3.5.2）/ 9,067 字符（V3.5）≈ 3k+ tokens；再加 8 条注入记忆、15 条规则、300 字摘要（`prompts.py:40, 49, 58`）。而单条记忆经合并后**最长可到 2000 字**（`memory.py:732`）→ 最坏 8×2000 = 16k 字符，叠在人格上就是数量级膨胀。
- 输出侧有 `llm.max_tokens: 300`（`config.yaml:19`）限制回复，但**没有任何代码限制 `system prompt` 的总字符数**，也没有按 token 估算做裁剪。
- heart 更激进：每 2–120 分钟把 9k 字人格 + 上下文**整段重发**一次（`heart.py:130-158`），且 `max_tokens=400`、`temperature=0.9`。
- 规则表也有“越长越不痛”的问题：`rules` 已积 210 条全部 `enabled=1`，但每轮只注入最新 15 条（`prompts.py:49`）→ 195 条永久沉底，既不参与推理也不被清理。
- 建议：为 `build_system_prompt` 加 `budget_chars`（先裁记忆、再裁规则、最后截摘要）；记忆注入按 score 降序填充到预算为止；heart 侧可缓存人格前缀（同一 `persona` 的静态部分不必每次重算，但注意 provider 侧 prompt cache 需要完全相同的前缀）。

### 6.4 记忆重复

- 最直接的 bug：`add_memory` 用 `INSERT OR IGNORE` 去重，但唯一键是**每次新生成的 `uuid.uuid4()`**（`memory.py:322-324`）→ `OR IGNORE` 永不触发，**同一句话可以无限重复写入**。这是 301 条记忆里出现大量近义条目的结构性原因。
- `rules` 的 `UNIQUE(rule)`（`memory.py:112`）只做**逐字**去重，LLM 换个说法就是新规则 → 210 条里语义重复不少。
- 唯一的语义去重是 `merge_similar_memories`（token 重叠 ≥0.85），它只在 GUI 定时器每 30 分钟跑一次（`main.py:905-928`），且是 O(n²) 双循环逐对算重叠（`memory.py:705-722`），301 条尚可、5000 条不可行；`add_memory` 尾部只调 `forget_excess`（`memory.py:341`），**不查重**。
- 建议：`memories` 增加 `content_hash TEXT UNIQUE`（对规范化后的 content 取 sha1）+ 入库前用 BM25 top-1 做近邻判重（score 高且重叠率高则合并 importance）；把相似合并从“定时全量”改为“按新条目做局部候选”。

### 6.5 其他（容易踩但不在任务清单里）

- **向量分支形同虚设**：`retrieve` 在 BM25 无命中时直接 `return []`（`memory.py:400-401`），向量相似度根本没机会出场；且 `_vector_similarities` 只在 `self.vector is not None` 时调用。本机没装 `sentence-transformers`，`mem_vec` 0 行 —— “可选向量”实际从未启用。
- **`summary` 表只增不删**：`ctx:*` 每个不同窗口/指纹都留一行，没有任何 TTL 或清理；旧版本遗留的单人格 `working` key（实测 203 字）现在没人读（`prompts.py:58` 只读 `working:{persona}`）。
- **人格切换丢摘要**：摘要按 `working:{persona}` 隔离，切到 V3.5.2 后旧人格的摘要不再注入，新人格从空白开始（实测两个 key 的存在/缺失正好对应这一点）。
- **文档漂移**：`persona.control_rule`（`README.md:134, 358`）在代码里不存在，实际规则硬编码在 `core.py:221-234`；`scripts/smoke_new_features.py:20, 26` 仍在用 `persona.base` + `control_rule`，与 `persona.py:48-58` 不一致。
- **heart 不产生记忆**：私人思考只写 `heart.json`，不进 `memories`/`messages`；如果想“自主时间里想到的事能被白天聊到”，需要额外把 `thought` 写成 `type='episodic'` 的记忆（当前完全没有）。
- **`heart.py` 的跨会话活跃判断**：`_user_recently_active` 只看当前人格最近 3 条，不按 `conversation_id` 过滤（`heart.py:101`），会在另一个会话刚聊完时误判“主人在活跃”而静默。

---

## 7. 未确认项

- `control_rule` 具体在哪个版本被移除：只确认当前 `config.yaml` 无此键、无代码读取（`smoke_new_features.py:20` 属遗留），未查 git 历史。
- `rules.version` 字段的用途：建表有 `version INTEGER DEFAULT 1`（`memory.py:112-117`），全文件无任何写入/读取，**未确认**是预留还是废弃。
- 跨进程 SQLite 锁冲突的实际发生频率：未压测，结论来自代码路径（无 WAL、无 timeout、两条连接）。
- `memory.db` 中 8 条 `persona='aurith'` 的来源：`persona/` 目录无对应 `.md`，推测为已删除人格的残留数据，**未确认**删除时序。
- 向量后端是否在别的机器上真正启用过、召回质量如何：本机未安装依赖，**未确认**。
- `heart.json` 中 `thoughts` 的空串是否来自某次模型漏字段还是解析问题：只能确认写入点不做空值过滤（`heart.py:242`），**未确认**模型侧原因。

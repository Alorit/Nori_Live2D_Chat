# 这份文档是什么（副本说明）

本目录 `D:\Nori_Live2D_Chat\reuse-docs\` 是 **Nori 项目的可复用资产勘察报告**，
内容与工作区里的一份**完全相同**（详见下方校验）：

| 项 | 值 |
|---|---|
| 编辑源头（以它为准） | `D:\AI_Working Directory\Deepseek Harness\Aurith\nori-reuse\` |
| 本目录（副本） | `D:\Nori_Live2D_Chat\reuse-docs\` |
| 内容快照 | 2026-10-20（针对 `D:\Nori_Live2D_Chat` 当时的源码） |
| 复制时间 | 2026-10-21 |
| 文件数 | 10 个 `.md`（6 篇正文 + 4 篇 detail） |

## 先读哪一篇

1. `README.md` — 总索引，按"你要干什么"给阅读路径
2. `00-brief.md` — 单页速览：项目形态、五件最值得拿走的资产、三条硬约束、关键数字
3. `02-reusable-assets.md` — **核心**：三级可复用清单 + 依赖图 + 三步抽取路线 + 现成复制命令
4. `03-live2d-bridge.md` — 原生桌宠 HTTP 契约（10 端点 / JSON / 口型同步 / 红线）
5. `04-pitfalls.md` — 28 条已核实问题
6. `detail/` — 四份模块深读（编排层 / GUI / 记忆+人格+Heart / 服务与集成）

## 重要提醒

- **本目录只有文档，没有源码副本**。代码永远以项目里的实际文件为准。
- 文档里的 `文件:行号` 是 2026-10-20 的快照。项目不是 git 仓库且仍在改动，**引用行号前先复核**：
  `Select-String -Path agent\memory.py -Pattern 'def add_memory'`
- 文档里多处提到真实 API Key 的位置（如 `data/settings_overrides.json`、`vision_mcp/config.json`）。**只记录了行号，没有复制任何 Key 的值**；也不要把那些文件的内容贴进本目录。

## 两份如何保持一致

改文档只在**源头**（工作区）改，然后单向同步到本目录：

```powershell
$src = 'D:\AI_Working Directory\Deepseek Harness\Aurith\nori-reuse'
$dst = 'D:\Nori_Live2D_Chat\reuse-docs'
robocopy $src $dst /E /XO /XF _copy-info.md | Out-Null

# 校验：逐文件比对哈希，应无输出
Get-ChildItem -LiteralPath $src -Recurse -File -Filter *.md | Where-Object Name -ne '_copy-info.md' |
  ForEach-Object {
    $rel = $_.FullName.Substring($src.Length + 1)
    $h1 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
    $h2 = (Get-FileHash -LiteralPath (Join-Path $dst $rel) -Algorithm SHA256).Hash
    if ($h1 -ne $h2) { "DRIFT: $rel" }
  }
```

> 若哪天发现两份内容不一致，**以工作区那份为准**，并重新执行上面的同步。
> 若源码已大改（新增模块 / 重构），应重新勘察而不是只同步文档——行号和"死代码"结论都会过期。

"""构造系统提示词。

重要：当前人格 .md 就是完整 System Prompt 的唯一来源。
- 不再向 .md 之外自动追加 config.yaml 里的人设/规则/主人设定；
- .md 里可以使用以下占位符，程序只替换这些占位符：
    {{time}}     当前日期时间
    {{memory}}   检索到的相关长期记忆
    {{rules}}    学到的行为规则
    {{summary}}  滚动摘要
- 人格里一个占位符都没写时（成品人格提示词很常见），默认把「时间 / 相关记忆 /
  行为规则 / 摘要」拼成一段附在末尾：否则记忆、规则、时间感知会静默失效。
  可用 config.yaml 的 memory.inject_context: false 关掉，退回“只用 .md 原文”。
"""
from __future__ import annotations

from datetime import datetime

from .persona import active_persona_name, load_persona_text

_WEEKDAYS = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
_PLACEHOLDERS = ("{{time}}", "{{memory}}", "{{rules}}", "{{summary}}")


def build_system_prompt(cfg, memory, user_text: str = "") -> str:
    """人格 .md 模板 + 动态上下文（占位符替换，或人格没写占位符时自动附加）。"""
    template = load_persona_text(cfg)
    persona = active_persona_name(cfg)

    now = datetime.now()
    time_line = (f"当前时间：{now.strftime('%Y年%m月%d日 %H:%M:%S')} "
                 f"{_WEEKDAYS[now.weekday()]}。涉及日期、时间、节日、天气等时效性问题时，以此为准。")

    # 人格里一个占位符都没有 -> 自动在末尾补上动态上下文（可在设置里关掉）
    auto_inject = (not any(p in template for p in _PLACEHOLDERS)
                   and bool(cfg.memory.get("inject_context", True)))

    mem_text = ""
    if ("{{memory}}" in template or auto_inject) and user_text:
        try:
            mems = memory.retrieve(user_text, k=int(cfg.memory.get("top_k", 8)))
        except Exception:
            mems = []
        if mems:
            mem_text = "\n".join(f"- [{m['type']}] {m['content']}" for m in mems)

    rules_text = ""
    if "{{rules}}" in template or auto_inject:
        try:
            rules = memory.get_active_rules(limit=15)
        except Exception:
            rules = []
        if rules:
            rules_text = "\n".join(f"- {r}" for r in rules)

    summary_text = ""
    if "{{summary}}" in template or auto_inject:
        try:
            summary_text = memory.get_summary(f"working:{persona}") or ""
        except Exception:
            summary_text = ""

    if not auto_inject:
        return (template
                .replace("{{time}}", time_line)
                .replace("{{memory}}", mem_text)
                .replace("{{rules}}", rules_text)
                .replace("{{summary}}", summary_text))

    blocks = [f"【当前时间】{time_line}"]
    if mem_text:
        blocks.append("【与当前话题相关的长期记忆】\n" + mem_text)
    if rules_text:
        blocks.append("【你学到的行为规则】\n" + rules_text)
    if summary_text:
        blocks.append("【此前对话的滚动摘要】\n" + summary_text)
    return template + "\n\n" + "\n\n".join(blocks)

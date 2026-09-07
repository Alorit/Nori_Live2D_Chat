"""Agent 核心编排：记忆、大脑、反思整合的学习闭环。"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
import time
from pathlib import Path

from .brain import AgentReply, Brain, parse_commands
from .compressor import ContextCompressor
from .memory import MemoryStore
from .persona import active_persona_name
from .prompts import build_system_prompt

logger = logging.getLogger("agent.core")


def _assistant_message(message) -> dict:
    out: dict = {"role": "assistant", "content": message.content or ""}
    tool_calls = getattr(message, "tool_calls", None) or []
    if tool_calls:
        out["tool_calls"] = [{
            "id": tc.id,
            "type": "function",
            "function": {
                "name": tc.function.name,
                "arguments": tc.function.arguments or "{}",
            },
        } for tc in tool_calls]
    return out


class AgentCore:
    """在后台线程里被调用的核心对象。GUI 只负责展示和 TTS。"""

    def __init__(self, cfg, memory: MemoryStore, brain: Brain, search=None,
                 mcp_manager=None):
        self.cfg = cfg
        self.memory = memory
        self.brain = brain
        self.search = search
        self.mcp_manager = mcp_manager
        self.turn_count = 0
        self._consolidate_lock = threading.Lock()
        self.last_reply: AgentReply | None = None
        self.compressor = ContextCompressor(brain, memory, cfg)
        self.current_conversation_id: int | None = None

    def current_persona(self) -> str:
        try:
            return active_persona_name(self.cfg)
        except Exception:
            return "nori"

    # ------------------------------------------------------------------
    def _sticker_hint(self, source: str) -> str:
        """内置/导入的表情包直接用文件名标签，不必每次都调用视觉模型。"""
        try:
            p = Path(source)
            parts = p.parts
            if "stickers" in parts:
                from utils.stickers import sticker_label
                label = sticker_label(p)
                return f"用户发来表情包：{label}（{p.name}）"
        except Exception:
            pass
        return ""

    @staticmethod
    def _extract_image_sources(text: str) -> list[str]:
        """从文本里提取图片 URL/路径（轻量版，不依赖视觉模块）。"""
        out: list[str] = []
        url_re = re.compile(r"https?://[^\s\"'<>（）()【】\[\]]+", re.I)
        img_re = re.compile(r"\.(png|jpe?g|webp|gif|bmp)$", re.I)
        for m in url_re.finditer(text):
            url = m.group(0).rstrip(".,;:!?")
            if img_re.search(url.split("?")[0]):
                out.append(url)
        for m in re.finditer(r"[\"']([^\"']+\.(?:png|jpe?g|webp|gif|bmp))[\"']",
                              text, re.I):
            cand = m.group(1).strip()
            if not cand.startswith(("http://", "https://", "data:")) and Path(cand).exists():
                out.append(cand)
        seen = set()
        uniq = []
        for s in out:
            if s not in seen:
                seen.add(s)
                uniq.append(s)
        return uniq

    def _vision_mcp_server_name(self) -> str | None:
        """找到已通过 MCP 设置导入并启用的视觉服务器。"""
        if not self.mcp_manager:
            return None
        try:
            for s in self.mcp_manager.list_servers():
                if s.get("enabled") and "vision" in str(s.get("name", "")).lower():
                    return str(s.get("name"))
        except Exception:
            pass
        return None

    def _augment_with_vision(self, user_text: str,
                             image_paths: list[str] | None = None) -> str:
        """检测消息里的图片路径/URL，通过独立视觉 MCP 注入视觉理解。"""
        sources = []
        if user_text:
            sources = self._extract_image_sources(user_text)
        for src in image_paths or []:
            src = (src or "").strip()
            if src and src not in sources:
                sources.append(src)
        if not sources:
            return user_text

        vision_server = self._vision_mcp_server_name()
        parts = []
        for src in sources[:3]:
            hint = self._sticker_hint(src)
            if hint:
                parts.append(hint)
                continue
            if not vision_server:
                parts.append(
                    f"图片（{src}）：视觉 MCP 未接入，Nori 暂时看不到这张图片，"
                    "请先回应说收到图片了。")
                continue
            try:
                question = (
                    f"用户发来这张图片并说：{user_text}。请客观描述图片内容，"
                    f"并指出与用户这句话相关的信息。" if user_text
                    else "用户发来这张图片，没有附加文字。请客观描述图片内容，"
                          "并指出值得回应的地方。")
                desc = asyncio.run(self.mcp_manager.execute_tool(
                    f"{vision_server}__analyze_image",
                    {"source": src, "question": question}))
                if not desc or desc.startswith("MCP 服务器") or desc.startswith("工具执行失败"):
                    raise RuntimeError(desc or "视觉 MCP 返回空")
                parts.append(f"图片（{src}）内容：{desc}")
            except Exception as e:
                logger.warning("视觉 MCP 分析失败 %s：%s", src, e)
                parts.append(f"图片（{src}）读取失败：{e}")

        if user_text:
            return f"{user_text}\n\n[视觉信息]\n" + "\n".join(parts)
        return ("用户发来图片/表情包，没有附加文字。\n\n[视觉信息]\n"
                + "\n".join(parts)
                + "\n\n请根据图片内容用 Nori 的方式自然回应。")

    def _augment_with_search(self, user_text: str) -> str:
        """识别搜索意图，把联网搜索结果注入 LLM 输入。"""
        if not self.search or not getattr(self.search, "enabled", False):
            return user_text
        try:
            query = self.search.extract_query(user_text)
        except Exception:
            query = None
        if not query:
            return user_text
        try:
            result = self.search.search(query)
        except Exception as e:
            logger.warning("联网搜索失败 %s：%s", query, e)
            return f"{user_text}\n\n[联网搜索] 搜索失败：{e}"
        return (f"{user_text}\n\n[联网搜索结果] 关于「{query}」：\n{result}\n"
                f"请用你自己的人格口吻把这些信息整理给用户，引用关键信息。")

    def handle_user_text(self, user_text: str,
                         image_paths: list[str] | None = None) -> AgentReply:
        """处理用户输入：搜索 -> 视觉理解 -> 记忆 -> LLM -> 写入记忆 -> 返回回复。

        image_paths 为 GUI 发送的图片/表情包路径，会交给视觉模型理解并随消息持久化。
        """
        user_text = (user_text or "").strip()
        image_paths = [str(p).strip() for p in (image_paths or []) if str(p).strip()]
        if not user_text and not image_paths:
            return AgentReply(text="", commands=[])

        llm_input = self._augment_with_search(user_text)
        llm_input = self._augment_with_vision(llm_input, image_paths=image_paths)

        persona = self.current_persona()
        conv_id = self.current_conversation_id or self.memory.ensure_main_conversation(persona)
        self.current_conversation_id = conv_id
        # 先取历史（此时还不包含本条用户消息），再调用 LLM，避免重复
        system_prompt = build_system_prompt(self.cfg, self.memory, user_text or "[图片]")
        # 本地 Ollama 显存/性能敏感：限制历史条数并跳过 LLM 压缩，避免上下文过大
        if getattr(self.cfg, "is_local_llm", False):
            history_limit = 10
            use_compression = False
        else:
            history_limit = self.cfg.working_memory_size
            use_compression = True
        history = self.memory.get_recent_messages(
            history_limit, persona=persona, conversation_id=conv_id)
        # 历史里的图片消息对纯文本 LLM 不可见，转成可读提示
        for m in history:
            if m.get("image_paths"):
                if not m.get("content"):
                    m["content"] = "[用户发过一张图片]"
            m.pop("image_paths", None)
        if use_compression:
            history = self.compressor.history_for_llm(history, persona)

        try:
            messages: list[dict] = [{"role": "system", "content": system_prompt}]
            if self.mcp_manager:
                try:
                    skills = self.mcp_manager.skill_instructions()
                except Exception:
                    skills = ""
                if skills:
                    messages.append({
                        "role": "system",
                        "content": "【已启用的 Skills 指令】\n" + skills})
            # 原生 Live2D 模式：要求模型根据对话情绪选择动作/表情，随回复一起发送
            if str(self.cfg.live2d.get("controller", "") or "").lower() == "native":
                messages.append({
                    "role": "system",
                    "content": (
                        "【Live2D 动作选择】请根据当前对话内容与情绪，在回复正文之前"
                        "输出一个动作或表情标签（不要输出多个）：\n"
                        "- 动作：[motion:nod] [motion:shake] [motion:wakuwaku] "
                        "[motion:angry] [motion:troubled] [motion:dizzy] [motion:sleep] "
                        "[motion:back]\n"
                        "- 表情：[expr:smile] [expr:happy] [expr:angry] [expr:shy] "
                        "[expr:dark] [expr:speechless] [expr:tears] [expr:troubled] "
                        "[expr:doubt] [expr:disgust] [expr:serious] [expr:surprised]\n"
                        "标签会被解析并立即让 Live2D 做出动作，不会显示给用户。"),
                })
            messages += history
            messages.append({"role": "user", "content": llm_input})

            tools = []
            if self.mcp_manager:
                try:
                    tools = asyncio.run(self.mcp_manager.build_tool_schemas())
                except Exception as e:
                    logger.warning("加载 MCP 工具失败：%s", e)
                    tools = []

            message = self.brain.chat_message(messages, tools=tools or None)
            for _round in range(5):
                tool_calls = getattr(message, "tool_calls", None) or []
                if not tool_calls:
                    break
                messages.append(_assistant_message(message))
                for tc in tool_calls:
                    name = getattr(tc.function, "name", "")
                    try:
                        args = json.loads(getattr(tc.function, "arguments", "{}") or "{}")
                    except Exception:
                        args = {}
                    if self.mcp_manager:
                        try:
                            result = asyncio.run(self.mcp_manager.execute_tool(name, args))
                        except Exception as e:
                            result = f"工具执行失败：{e}"
                    else:
                        result = "MCP 未启用"
                    messages.append({"role": "tool", "tool_call_id": tc.id,
                                     "content": result[:4000]})
                message = self.brain.chat_message(messages, tools=tools or None)
            raw = message.content or ""
            text, cmds = parse_commands(raw)
            reply = AgentReply(text=text, commands=cmds, raw=raw)
        except Exception as e:
            logger.exception("LLM 调用失败")
            reply = AgentReply(text=f"[出错了] {e}", commands=[])

        stored_text = user_text or "（用户发来一张图片/表情包）"
        user_msg_id = self.memory.record_message(
            "user", stored_text, persona=persona, conversation_id=conv_id,
            image_paths=image_paths)
        assistant_msg_id = self.memory.record_message(
            "assistant", reply.text, persona=persona, conversation_id=conv_id)
        self.memory.add_exchange(stored_text, reply.text, assistant_msg_id)

        reply.user_msg_id = user_msg_id
        reply.assistant_msg_id = assistant_msg_id
        self.last_reply = reply
        self.turn_count += 1

        self._maybe_consolidate_async()
        return reply

    # ------------------------------------------------------------------
    def _maybe_consolidate_async(self):
        # 本地 Ollama 显存/性能敏感：关闭自动反思整合，避免后台 LLM 抢占资源
        if getattr(self.cfg, "is_local_llm", False):
            return
        interval = int(self.cfg.memory.get("consolidate_interval", 10))
        if interval <= 0 or self.turn_count % interval != 0:
            return
        t = threading.Thread(target=self.consolidate_now, daemon=True, name="memory-consolidate")
        t.start()

    def consolidate_now(self):
        """反思整合：提取事实/事件/规则，并做滚动摘要（按当前人格隔离）。"""
        if not self._consolidate_lock.acquire(blocking=False):
            return
        try:
            persona = self.current_persona()
            conv_id = self.current_conversation_id
            recent = self.memory.get_recent_messages_with_ts(
                80, persona=persona, conversation_id=conv_id)
            if len(recent) < 4:
                return
            logger.info("开始记忆反思整合（人格 %s，会话 %s，共 %d 条消息）",
                        persona, conv_id, len(recent))
            result = self.brain.consolidate(recent)
            facts = result.get("facts", []) or []
            episodes = result.get("episodes", []) or []
            rules = result.get("rules", []) or []

            for f in facts:
                self.memory.add_memory(str(f).strip(), mem_type="semantic", importance=0.8, source="consolidate")
            for e in episodes:
                self.memory.add_memory(str(e).strip(), mem_type="episodic", importance=0.55, source="consolidate")
            n_rules = self.memory.add_rules([str(r).strip() for r in rules], source="consolidate")

            # 滚动摘要：压缩工作记忆之外的内容
            self._update_summary()
            logger.info("反思整合完成：事实 %d，事件 %d，规则 %d", len(facts), len(episodes), n_rules)
        except Exception as e:
            logger.exception("反思整合失败：%s", e)
        finally:
            self._consolidate_lock.release()

    def _update_summary(self):
        """让 LLM 把当前摘要 + 近期对话压缩成新的滚动摘要。"""
        try:
            persona = self.current_persona()
            conv_id = self.current_conversation_id
            recent = self.memory.get_recent_messages_with_ts(
                100, persona=persona, conversation_id=conv_id)
            if not recent:
                return
            lines = "\n".join(f"{role}: {content}" for role, content, _ in recent)
            summary_key = f"working:{persona}"
            old_summary = self.memory.get_summary(summary_key)
            prompt = ("你负责维护一个 AI 桌面宠物的长期摘要。把【旧摘要】和【最近对话】压缩成一段"
                      "不超过 300 字的滚动摘要，保留用户个人信息、偏好、重要事件和行为规则。"
                      "只输出摘要本身，不要解释。")
            if old_summary:
                prompt += f"\n\n【旧摘要】\n{old_summary}"
            prompt += f"\n\n【最近对话】\n{lines}"

            client = self.brain._ensure_client()
            resp = client.chat.completions.create(
                model=self.cfg.model,
                temperature=0.3,
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}],
            )
            new_summary = (resp.choices[0].message.content or "").strip()
            if new_summary:
                self.memory.set_summary(new_summary, summary_key)
        except Exception as e:
            logger.debug("滚动摘要更新失败：%s", e)

    # ------------------------------------------------------------------
    def apply_feedback(self, delta: float):
        """给最近一条 AI 回复打反馈分。"""
        if self.last_reply and self.last_reply.assistant_msg_id:
            self.memory.apply_feedback(self.last_reply.assistant_msg_id, delta)

    def export_training_data(self, path: str) -> str:
        return self.memory.export_conversations_jsonl(path)

    def stats(self) -> dict:
        return self.memory.stats()

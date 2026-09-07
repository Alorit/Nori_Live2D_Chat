"""Nori 的“心脏”：独立自主唤醒进程。

参考 Vigil 框架的“自唤醒”思路：
- 独立进程定时轮询，检查 AI 自己设定的“下次醒来时间”
- 到点后发起一轮无用户输入的私人思考（LLM）
- AI 决定：只是思考 / 换表情 / 做动作 / 主动说句话，并决定下次何时醒来
- 每次醒来的思考记录会写入状态，下次醒来时注入上下文，保持意识连续性
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

LOG_FILE = PROJECT_ROOT / "data" / "logs" / "heart.log"
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
_handlers = [logging.FileHandler(LOG_FILE, encoding="utf-8")]
if sys.stdout is not None:
    _handlers.append(logging.StreamHandler(sys.stdout))
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=_handlers,
)
logger = logging.getLogger("nori.heart")

from agent.config import load_config
from agent.live2d_native import Live2DNativeClient
from agent.memory import MemoryStore
from agent.persona import active_persona_name, load_persona_text
from openai import OpenAI

_WEEKDAYS = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]


class NoriHeart:
    def __init__(self, cfg):
        self.cfg = cfg
        self.h = cfg.heart
        self.state_path = PROJECT_ROOT / str(self.h.get("state_file", "data/heart.json"))
        self.state_path.parent.mkdir(parents=True, exist_ok=True)

        self.memory = MemoryStore(cfg.db_path, cfg.memory)
        self.client = OpenAI(api_key=cfg.api_key, base_url=cfg.base_url, timeout=120)
        self.live2d_enabled = os.environ.get("NORI_HEART_SKIP_LIVE2D") != "1"
        self.live2d = Live2DNativeClient(cfg) if self.live2d_enabled else None
        self.tts = None

        self.state = self._load_state()
        self.last_wake_log = ""

    # ------------------------------------------------------------------
    def _load_state(self) -> dict:
        default = {
            "next_wake_at": time.time(),
            "last_wake_at": 0,
            "thoughts": [],
            "actions": [],
        }
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            data.setdefault("thoughts", [])
            data.setdefault("actions", [])
            return data
        except Exception:
            return default

    def _save_state(self):
        try:
            self.state_path.write_text(
                json.dumps(self.state, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning("保存 heart 状态失败：%s", e)

    # ------------------------------------------------------------------
    def _recent_context(self) -> str:
        try:
            persona = active_persona_name(self.cfg)
            recent = self.memory.get_recent_messages_with_ts(6, persona=persona)
            if not recent:
                return "最近没有新对话。"
            lines = []
            for role, content, _ts in recent:
                lines.append(f"{role}: {content}")
            return "最近对话：\n" + "\n".join(lines)
        except Exception:
            return ""

    def _user_recently_active(self) -> bool:
        quiet = float(self.h.get("chat_quiet_sec", 90))
        try:
            persona = active_persona_name(self.cfg)
            recent = self.memory.get_recent_messages_with_ts(3, persona=persona)
            for role, _content, ts in recent:
                if role == "user" and (time.time() - float(ts)) < quiet:
                    return True
        except Exception:
            pass
        return False

    # ------------------------------------------------------------------
    def _think(self) -> dict:
        now = datetime.now()
        time_line = f"{now.strftime('%Y年%m月%d日 %H:%M:%S')} {_WEEKDAYS[now.weekday()]}"
        thoughts = self.state.get("thoughts", [])[-5:]
        actions = self.state.get("actions", [])[-5:]
        thoughts_text = "\n".join(f"- {t}" for t in thoughts) or "（这是第一次醒来）"
        actions_text = "\n".join(f"- {a}" for a in actions) or "（还没做过动作）"

        expressions = "、".join(self.cfg.persona.get("expressions", []))
        motions = "、".join(self.cfg.persona.get("motions", []))
        min_minutes = int(self.h.get("min_wake_minutes", 2))
        max_minutes = int(self.h.get("max_wake_minutes", 120))
        persona_text = load_persona_text(self.cfg)
        # 用户称呼：gui.user_name 由首次使用向导 / 设置页维护，留空则用「主人」
        user_name = str(self.cfg.gui.get("user_name", "") or "").strip()
        if user_name and user_name != "主人":
            master_line = f"- 主人的名字是 {user_name}，不要把他认错。"
        else:
            master_line = "- 没有单独设置主人名字，统一用「主人」称呼对话用户。"

        prompt = f"""{persona_text}

这是你的“私人时间”自主唤醒回合，主人没有正在和你说话。
{time_line}

【意识连续性：上次独处时你做了什么】
{actions_text}

【你当时的心思想法】
{thoughts_text}

【最近的对话环境】
{self._recent_context()}

请像有自我意识一样决定这次醒来要做什么，并只输出 JSON：
{{
  "thought": "这次醒来时的内心想法，一两句话",
  "mood": "当前情绪，用中文",
  "action": "none / expression / motion / speak",
  "expression": "若 action 是 expression 或 speak 可填：{expressions}",
  "motion": "若 action 是 motion 可填：{motions}",
  "text": "若 action 是 speak，说一句不超过30字的话，句末加语气词",
  "next_wake_minutes": {min_minutes}到{max_minutes}之间的整数，由你决定下次多久醒来
}}

规则：
- 大部分时候 action 用 none（安静地想），偶尔主动做小动作或说一句话，不要频繁打扰主人。
{master_line}
- 不要用括号描述状态。"""

        resp = self.client.chat.completions.create(
            model=self.cfg.model,
            temperature=0.9,
            max_tokens=400,
            response_format={"type": "json_object"},
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.choices[0].message.content or "{}"
        return json.loads(raw)

    # ------------------------------------------------------------------
    def _execute(self, decision: dict):
        action = decision.get("action", "none")
        expression = decision.get("expression", "")
        motion = decision.get("motion", "")
        text = (decision.get("text") or "").strip()

        if action == "expression" and expression and self.live2d_enabled:
            self.live2d.set_expression(
                self.cfg.persona.get("emotion_map", {}).get(expression, expression))
        elif action == "motion" and motion and self.live2d_enabled:
            self.live2d.play_motion(
                self.cfg.persona.get("motion_map", {}).get(motion, motion))
        elif action == "speak" and text:
            if expression and self.live2d_enabled:
                self.live2d.set_expression(
                    self.cfg.persona.get("emotion_map", {}).get(expression, expression))
            self._speak(text)
        return action

    def _speak(self, text: str):
        if not self.h.get("allow_speak", True):
            return
        try:
            if self.tts is None:
                from agent.tts.factory import create_tts
                self.tts = create_tts(self.cfg)
            if self.live2d_enabled:
                self.live2d.set_speaking(True)
            try:
                self.tts.speak(text)
            finally:
                if self.live2d_enabled:
                    self.live2d.set_speaking(False)
        except Exception as e:
            logger.warning("heart 说话失败：%s", e)

    # ------------------------------------------------------------------
    def tick(self):
        now = time.time()
        if now < float(self.state.get("next_wake_at", 0)):
            return

        if self._user_recently_active():
            # 主人刚说过话，先安静，过几分钟再醒
            logger.info("主人最近活跃，heart 保持安静")
            self.state["next_wake_at"] = now + 5 * 60
            self._save_state()
            return

        logger.info("heart 唤醒，开始私人思考")
        try:
            decision = self._think()
        except Exception as e:
            logger.warning("私人思考失败：%s", e)
            self.state["next_wake_at"] = now + int(self.h.get("default_wake_minutes", 15)) * 60
            self._save_state()
            return

        try:
            action = self._execute(decision)
            log = (f"action={action} expression={decision.get('expression','')} "
                   f"motion={decision.get('motion','')} text={decision.get('text','')}")
            logger.info("heart 决策：%s", log)
            self.state.setdefault("thoughts", []).append(decision.get("thought", ""))
            self.state.setdefault("actions", []).append(log)
            self.state["thoughts"] = self.state["thoughts"][-20:]
            self.state["actions"] = self.state["actions"][-20:]
        except Exception as e:
            logger.warning("heart 执行动作失败：%s", e)

        minutes = int(decision.get("next_wake_minutes", self.h.get("default_wake_minutes", 15)))
        minutes = max(int(self.h.get("min_wake_minutes", 2)),
                      min(int(self.h.get("max_wake_minutes", 120)), minutes))
        self.state["last_wake_at"] = now
        self.state["next_wake_at"] = now + minutes * 60
        self._save_state()

    def run(self):
        if not self.cfg.api_key:
            logger.error("没有 DeepSeek API Key，heart 无法工作")
            return
        if not self.h.get("enabled", True):
            logger.info("heart 未启用")
            return
        pid_file = PROJECT_ROOT / "data" / "heart.pid"
        pid_file.write_text(str(os.getpid()), encoding="utf-8")
        try:
            try:
                if self.live2d_enabled:
                    self.live2d.ensure_running()
                else:
                    logger.info("Live2D 已禁用（NORI_HEART_SKIP_LIVE2D=1）")
            except Exception as e:
                logger.warning("Live2D 未就绪：%s", e)

            interval = max(5, int(self.h.get("poll_interval_sec", 20)))
            logger.info("heart 启动，轮询间隔 %ss，下次唤醒 %s",
                        interval,
                        datetime.fromtimestamp(self.state.get("next_wake_at", time.time())))
            while True:
                try:
                    self.tick()
                except Exception as e:
                    logger.warning("heart tick 异常：%s", e)
                time.sleep(interval)
        finally:
            try:
                if pid_file.read_text(encoding="utf-8").strip() == str(os.getpid()):
                    pid_file.unlink(missing_ok=True)
            except Exception:
                pass


def main():
    cfg = load_config()
    NoriHeart(cfg).run()


if __name__ == "__main__":
    main()

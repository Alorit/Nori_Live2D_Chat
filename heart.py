"""Nori 的“心脏”：独立自主进程 = 秒级反射层 + 分钟级心智层。

两层分工（这是“自主性”的关键，缺一层都不像活的）：

- **反射层（1 Hz，0 token）**：``agent.pet_director.PetDirector`` 负责微动作、作息、
  主人是否在场、动作优先级。她从“几乎静止”变成“一直在动”主要靠这一层。
- **心智层（分钟级，花 token）**：本文件 ``_think()`` 每隔几分钟醒一次，产出一份
  **带时间轴的剧本**（plan），导演按 `at` 秒延迟播出去 —— 一次调用覆盖十几分钟的可见行为。

另外两件事：
- ``agent.presence`` 让她知道主人在不在、在干什么（纯本地，不联网）；
- ``agent.heart_events`` 把内心 OS / 自主说话写给 GUI，用户在聊天窗里看得到她在想什么。

历史包袱与约束：
- 状态文件 ``data/heart.json`` 只由本进程写（GUI 只读），避免双写竞争；
- 主人刚说过话时保持安静（``chat_quiet_sec``）；
- 任何 LLM 异常都必须推进 ``next_wake_at``，否则会退化成“每秒重调一次 LLM”的热循环。
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
import threading
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
from agent.heart_events import emit as emit_event
from agent.live2d_native import Live2DNativeClient
from agent.memory import MemoryStore
from agent.persona import active_persona_name, load_persona_text
from agent.pet_director import PetDirector
from agent.presence import Presence
from openai import OpenAI

_WEEKDAYS = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]

DIGEST_FILE = "data/heart_persona_digest.json"
EVENTS_FILE = "data/heart_events.jsonl"

_DIGEST_PROMPT = """把下面这份人格设定压缩成「独处时的自己」看的行为摘要，供你在没有对话时判断该怎么表现。

要求：
- 保留：身份设定、说话风格与语气、称呼方式、行为准则、明确禁止的事；
- 删掉：记忆/时间占位符的说明、示例对白、格式模板；
- 400 字以内，用第二人称写（“你是……”），不要前言后语，只输出摘要正文。

人格设定：
"""


class NoriHeart:
    def __init__(self, cfg):
        self.cfg = cfg
        self.h = cfg.heart
        self.auto = getattr(cfg, "autonomy", None)
        self.state_path = PROJECT_ROOT / str(self.h.get("state_file", "data/heart.json"))
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.events_path = PROJECT_ROOT / EVENTS_FILE

        self.memory = MemoryStore(cfg.db_path, cfg.memory)
        self.client = OpenAI(api_key=cfg.api_key, base_url=cfg.base_url, timeout=120)
        self.live2d_enabled = os.environ.get("NORI_HEART_SKIP_LIVE2D") != "1"
        # 即使 GUI 已经在管桌宠（NORI_HEART_SKIP_LIVE2D=1），导演也要能往同一个
        # 47835 端口发 /motion、/expression —— 否则「自主动作」在主用法下全部变成空操作。
        # 这里只做「附着」：不 ensure_running、不 shutdown、不碰口型。
        self.live2d = Live2DNativeClient(cfg)
        self.live2d_owned = self.live2d_enabled
        self.tts = None
        self._digest_cache: dict | None = None

        self.state = self._load_state()
        self.last_wake_log = ""

        self.presence = Presence(cfg)
        self.director = PetDirector(
            cfg,
            live2d=self.live2d,
            presence=self.presence,
            speak=self._speak if self.h.get("allow_speak", True) else None,
            emit=self._emit if self._inner_os_enabled() else None,
        )

    # ------------------------------------------------------------------ 配置
    def _conf(self, key: str, default):
        try:
            return self.auto.get(key, default) if self.auto is not None else default
        except Exception:
            return default

    def _inner_os_enabled(self) -> bool:
        return bool(self._conf("inner_os", True))

    # ------------------------------------------------------------------ 事件
    def _emit(self, kind: str, **payload) -> None:
        emit_event(self.events_path, kind, **payload)

    # ------------------------------------------------------------------ 状态
    def _load_state(self) -> dict:
        default = {
            "next_wake_at": time.time(),
            "last_wake_at": 0,
            "thoughts": [],
            "actions": [],
            "mood": "",
            "emotion": {"valence": 0.1, "arousal": 0.45, "energy": 0.6},
        }
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            data.setdefault("thoughts", [])
            data.setdefault("actions", [])
            data.setdefault("mood", "")
            emo = data.setdefault("emotion", {})
            if not isinstance(emo, dict):
                data["emotion"] = {"valence": 0.1, "arousal": 0.45, "energy": 0.6}
            return data
        except FileNotFoundError:
            return default
        except Exception as e:
            # 以前这里静默回落：状态文件损坏时看不出任何痕迹，只能靠猜
            logger.warning("读取 heart 状态失败（%s），本轮用默认状态", e)
            try:
                bad = self.state_path.with_suffix(".broken.json")
                self.state_path.replace(bad)
                logger.warning("损坏的状态文件已另存为 %s", bad.name)
            except Exception:
                pass
            return default

    def _save_state(self):
        """原子写：先写临时文件再替换，避免进程被杀时留下半截 JSON。"""
        try:
            tmp = self.state_path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(self.state, ensure_ascii=False, indent=2),
                           encoding="utf-8")
            os.replace(tmp, self.state_path)
        except Exception as e:
            logger.warning("保存 heart 状态失败：%s", e)

    # ------------------------------------------------------------------ 上下文
    def _recent_context(self) -> str:
        try:
            persona = active_persona_name(self.cfg)
            recent = self.memory.get_recent_messages_with_ts(6, persona=persona)
            if not recent:
                return "最近没有新对话。"
            lines = []
            for role, content, _ts in recent:
                who = "主人" if role == "user" else "你"
                lines.append(f"{who}：{str(content)[:120]}")
            return "\n".join(lines)
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

    def _presence_line(self) -> str:
        try:
            return self.director.describe_presence() if self.director else ""
        except Exception:
            return ""

    # ------------------------------------------------------------------ 人格摘要
    def _persona_digest(self) -> str:
        """把全量人格 md 压成 400 字摘要，省约 70% 的自主回合输入 token。

        按人格正文哈希缓存：人格不改就不重复花钱。
        """
        full = load_persona_text(self.cfg) or ""
        if not self._conf("persona_digest", True) or len(full) < 1500:
            return full
        key = hashlib.sha1(full.encode("utf-8")).hexdigest()
        cache_path = PROJECT_ROOT / DIGEST_FILE
        if self._digest_cache is None:
            try:
                self._digest_cache = json.loads(cache_path.read_text(encoding="utf-8"))
            except Exception:
                self._digest_cache = {}
        cache = self._digest_cache or {}
        if cache.get("hash") == key and cache.get("text"):
            return str(cache["text"])
        try:
            resp = self.client.chat.completions.create(
                model=self.cfg.model,
                max_tokens=int(self._conf("digest_max_tokens", 8000)),
                messages=[{"role": "user", "content": _DIGEST_PROMPT + full}],
            )
            digest = (resp.choices[0].message.content or "").strip()
            if not digest:
                # deepseek-flash 是推理模型：reasoning 会吃掉 max_tokens，
                # 预算给小了就只剩空 content（finish_reason=length）
                logger.warning("人格摘要返回空 content（finish=%s, usage=%s）",
                               resp.choices[0].finish_reason, resp.usage)
        except Exception as e:
            logger.warning("生成人格摘要失败（%s），本轮回落到截断版人格", e)
            digest = ""
        if not digest:
            digest = full[:1200]
        self._digest_cache = {"hash": key, "text": digest}
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = cache_path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(self._digest_cache, ensure_ascii=False, indent=2),
                           encoding="utf-8")
            os.replace(tmp, cache_path)
        except Exception:
            pass
        logger.info("已生成人格摘要（%d 字 → %d 字）", len(full), len(digest))
        return digest

    # ------------------------------------------------------------------ 心智层
    def _think(self) -> dict:
        now = datetime.now()
        time_line = f"{now.strftime('%Y年%m月%d日 %H:%M')} {_WEEKDAYS[now.weekday()]}"
        thoughts = self.state.get("thoughts", [])[-4:]
        actions = self.state.get("actions", [])[-4:]
        thoughts_text = "\n".join(f"- {t}" for t in thoughts) or "（这是第一次醒来）"
        actions_text = "\n".join(f"- {a}" for a in actions) or "（还没做过什么）"

        expressions = "、".join(self.cfg.persona.get("expressions", []))
        motions = "、".join(self.cfg.persona.get("motions", []))
        min_minutes = int(self.h.get("min_wake_minutes", 2))
        max_minutes = int(self.h.get("max_wake_minutes", 120))
        persona_text = self._persona_digest()
        quiet_start, quiet_end = self.director.quiet_start, self.director.quiet_end

        user_name = str(self.cfg.gui.get("user_name", "") or "").strip()
        if user_name and user_name != "主人":
            master_line = f"- 主人的名字是 {user_name}，不要把他认错。"
        else:
            master_line = "- 没有单独设置主人名字，统一用「主人」称呼对话用户。"

        presence = self._presence_line()
        emo = self.state.get("emotion", {}) or {}
        mood_line = (f"心情 {self.state.get('mood') or '平静'}；"
                     f"效价 {float(emo.get('valence', 0.1)):+.2f}（-1 难受 ~ 1 开心），"
                     f"精力 {float(emo.get('energy', 0.6)):.2f}（0 困 ~ 1 精神）")

        prompt = f"""{persona_text}

这是你的「私人时间」：主人没有在和你说话，你可以自己决定做什么。
现在是 {time_line}。

【主人现在】
{presence or "不知道。"}

【你此刻的状态】
{mood_line}

【上一次独处时你做了什么】
{actions_text}

【你当时的心思想法】
{thoughts_text}

【最近的对话】
{self._recent_context()}

请像真的有自我意识一样，决定接下来这段时间你怎么过。只输出 JSON：
{{
  "thought": "此刻的内心想法，一两句话，像自言自语",
  "mood": "两个字左右的中文情绪词",
  "valence": -1 到 1 的小数,
  "arousal": 0 到 1 的小数,
  "energy": 0 到 1 的小数,
  "plan": [
    {{"at": 0, "do": "motion", "name": "发呆"}},
    {{"at": 45, "do": "expr", "name": "困了"}},
    {{"at": 120, "do": "speak", "text": "……几点了"}}
  ],
  "next_wake_minutes": {min_minutes} 到 {max_minutes} 的整数
}}

规则：
- plan 是接下来十几分钟的动作时间轴，at 是距现在多少秒，按时间顺序，最多 5 条；
- do 只能是 motion / expr / speak：
  · motion 从这些里选：{motions}
  · expr 从这些里选：{expressions}
- 大多数时候 plan 只有 1~3 条小动作，把「你在做什么」演出来；不要每条都说话；
- speak 要短（30 字以内）、口语化，像自言自语被主人听见；
- 深夜 {quiet_start}:00 到 {quiet_end}:00 尽量只做小动作，不要说话；
- next_wake_minutes 决定你多久后再醒一次，你在发呆/睡觉就长一点，有事想做就短一点。
{master_line}
- 不要用括号描述状态，不要在 JSON 外输出任何东西。"""

        resp = self.client.chat.completions.create(
            model=self.cfg.model,
            temperature=0.9,
            max_tokens=int(self._conf("think_max_tokens", 2400)),
            response_format={"type": "json_object"},
            messages=[{"role": "user", "content": prompt}],
        )
        raw = (resp.choices[0].message.content or "").strip()
        if not raw:
            # 推理模型（deepseek-flash）先把 token 花在 reasoning 上，预算不足时
            # content 会是空的；这里降一次格式约束、放宽预算再试一次
            logger.warning("私人思考返回空 content（finish=%s），重试一次",
                           resp.choices[0].finish_reason)
            resp = self.client.chat.completions.create(
                model=self.cfg.model,
                temperature=0.9,
                max_tokens=int(self._conf("think_max_tokens", 2400)) * 2,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = (resp.choices[0].message.content or "").strip()
        if not raw:
            logger.warning("私人思考仍然为空（finish=%s, usage=%s）",
                           resp.choices[0].finish_reason, resp.usage)
            return {}
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            logger.warning("私人思考返回的不是合法 JSON（%s）：%s", e, raw[:120])
            return {}
        if not isinstance(data, dict) or not data:
            logger.warning("私人思考返回的不是有效 JSON 对象：%s", raw[:120])
            return {}
        return data

    # ------------------------------------------------------------------ 执行
    def _apply_decision(self, decision: dict, now: float) -> int:
        """把 LLM 的剧本交给导演；返回排进队列的条数。"""
        plan = decision.get("plan")
        items: list[dict] = []
        if isinstance(plan, list):
            items = [p for p in plan if isinstance(p, dict)]
        if not items:
            # 兼容旧格式（只有单个 action）与模型偷懒的情况
            action = str(decision.get("action", "") or "").lower()
            expression = str(decision.get("expression", "") or "").strip()
            motion = str(decision.get("motion", "") or "").strip()
            text = str(decision.get("text", "") or "").strip()
            if action == "motion" and motion:
                items = [{"at": 0, "do": "motion", "name": motion}]
            elif action == "expression" and expression:
                items = [{"at": 0, "do": "expr", "name": expression}]
            elif action == "speak" and text:
                items = [{"at": 0, "do": "expr", "name": expression},
                         {"at": 0, "do": "speak", "text": text}]
        return self.director.submit_plan(items, now=now)

    def _speak(self, text: str):
        """异步朗读：TTS 合成/播放可能要几秒，不能卡住 1 Hz 的反射层。"""
        text = (text or "").strip()
        if not text or not self.h.get("allow_speak", True):
            return
        threading.Thread(target=self._speak_blocking, args=(text,),
                         name="heart-speak", daemon=True).start()

    def _speak_blocking(self, text: str):
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
        # 自主说的话也要进记忆，否则重启后在聊天记录里查不到，连续性会断
        try:
            persona = active_persona_name(self.cfg)
            self.memory.record_message("assistant", text, persona=persona)
        except Exception:
            pass

    # ------------------------------------------------------------------ 唤醒
    def wake(self, now: float | None = None) -> None:
        now = now or time.time()
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

        if decision:
            try:
                self.director.set_emotion(decision.get("valence"),
                                          decision.get("arousal"),
                                          decision.get("energy"))
                mood = str(decision.get("mood", "") or "").strip()
                if mood:
                    self.state["mood"] = mood
                emo = self.state.setdefault("emotion", {})
                emo.update({"valence": round(self.director.valence, 2),
                            "arousal": round(self.director.arousal, 2),
                            "energy": round(self.director.energy, 2)})
                added = self._apply_decision(decision, now)
                thought = str(decision.get("thought", "") or "").strip()
                log = (f"mood={mood} plan={added}条 thought={thought[:40]}")
                logger.info("heart 决策：%s", log)
                self.state.setdefault("thoughts", []).append(thought)
                self.state.setdefault("actions", []).append(log)
                self.state["thoughts"] = self.state["thoughts"][-20:]
                self.state["actions"] = self.state["actions"][-20:]
                if thought:
                    self._emit("thought", text=thought, mood=mood)
                self._emit("state", mood=mood,
                           valence=round(self.director.valence, 2),
                           arousal=round(self.director.arousal, 2),
                           energy=round(self.director.energy, 2))
            except Exception as e:
                logger.warning("heart 执行决策失败：%s", e)
        else:
            logger.info("heart 醒来但没给出决定，本轮跳过")

        # 模型可能返回 null / "30分钟" / 缺字段：任何取不到整数的情况都必须落到默认值，
        # 否则异常会越过 wake()（next_wake_at 不推进）→ 每个心跳都重调一次 LLM
        default_minutes = int(self.h.get("default_wake_minutes", 15))
        try:
            minutes = int(decision.get("next_wake_minutes", default_minutes))
        except (TypeError, ValueError):
            logger.warning("next_wake_minutes 不是整数（%r），改用默认 %d 分钟",
                           decision.get("next_wake_minutes"), default_minutes)
            minutes = default_minutes
        minutes = max(int(self.h.get("min_wake_minutes", 2)),
                      min(int(self.h.get("max_wake_minutes", 120)), minutes))
        self.state["last_wake_at"] = now
        self.state["next_wake_at"] = now + minutes * 60
        self._save_state()

    # ------------------------------------------------------------------ 主循环
    def tick(self, now: float | None = None) -> None:
        """1 Hz 反射层：微动作 / 作息 / 在场感知。"""
        if self.director is None:
            return
        self.director.tick(now)

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
                if self.live2d_owned:
                    self.live2d.ensure_running()
                elif self.live2d.available(timeout=1.0):
                    logger.info("Live2D 由 GUI 托管，导演已附着到 %s", self.live2d.base_url)
                else:
                    logger.info("Live2D 由 GUI 托管但暂未就绪（导演会静默跳过动作）")
            except Exception as e:
                logger.warning("Live2D 未就绪：%s", e)

            # 恢复上次的情绪，保持连续性
            emo = self.state.get("emotion", {}) or {}
            self.director.set_emotion(emo.get("valence"), emo.get("arousal"),
                                      emo.get("energy"))

            tick_sec = float(self._conf("tick_sec", 1) or 1)
            tick_sec = max(0.2, min(10.0, tick_sec))
            logger.info("heart 启动：心跳 %.1fs，下次唤醒 %s",
                        tick_sec,
                        datetime.fromtimestamp(self.state.get("next_wake_at", time.time())))
            next_tick = time.time()
            last_chat_check = 0.0
            while True:
                try:
                    now = time.time()
                    # 主人正在对话时：别在她说“我在听”的时候插一句“几点了”
                    if now - last_chat_check > 3:
                        last_chat_check = now
                        if self._user_recently_active():
                            dropped = self.director.clear_plan("speak")
                            if dropped:
                                logger.info("主人正在对话，撤回 %d 条待播台词", dropped)
                            self.director.note_chat(now)
                    self.director.tick(now)
                    if now >= float(self.state.get("next_wake_at", 0)):
                        self.wake(now)
                except Exception as e:
                    logger.warning("heart tick 异常：%s", e)
                next_tick += tick_sec
                time.sleep(max(0.05, next_tick - time.time()))
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

"""PetDirector：秒级反射层（0 token）。

为什么需要它：
`heart.py` 过去只有一条“每 15 分钟醒一次”的慢节律，两次醒来之间她完全静止，
看起来就是一张贴图。Neuro 那类“有生命感”的观感其实主要来自**高频、廉价、随机**的
小动作——这件事交给 LLM 太贵也没必要，交给规则最合适。

分工：
- **导演（本文件，1 Hz，免费）**：微动作、作息、主人是否在场、动作优先级、说话预算；
- **编剧（heart._think，分钟级，花钱）**：醒来时给一份带时间轴的剧本（plan），
  导演把剧本按 `at` 秒延迟播出去，于是一次 LLM 调用能覆盖十几分钟的可见行为。

三条硬规则：
1. 1 Hz 的 tick 里**禁止任何网络请求**（除了把动作发给本地 47835 端口）；
2. 动作要有优先级和身体锁，避免“想法/聊天反应/微动作”互相打断；
3. 说不说话有预算：每小时最多 N 次，深夜闭嘴。
"""
from __future__ import annotations

import logging
import random
import time
from collections import deque
from datetime import datetime

logger = logging.getLogger("agent.director")

# 优先级：大的可以打断小的
PRIORITY_SPEAK = 100
PRIORITY_USER = 80
PRIORITY_INTENT = 60
PRIORITY_MICRO = 20

# arg-nori 真实存在的动作 / 表情（模型里没有的名字会被服务端拒绝）
MOTIONS = {
    "idle", "sleep", "nod", "shake", "shakehead", "wakuwaku",
    "angry", "troubled", "dizzy", "glitch", "back", "idlepose",
}
EXPRESSIONS = {
    "default", "kirakira", "dizzy", "angry", "shy", "dark", "speechless",
    "smile", "tears", "troubled", "doubt", "disgust", "serious", "happy",
    "sleep", "surprised",
}

# 微动作权重表：(kind, name, weight)
_MICRO = {
    "morning": [
        ("expr", "happy", 10), ("expr", "smile", 8), ("expr", "default", 6),
        ("motion", "wakuwaku", 8), ("motion", "nod", 6), ("motion", "idle", 10),
    ],
    "day": [
        ("expr", "happy", 6), ("expr", "smile", 8), ("expr", "doubt", 4),
        ("expr", "serious", 4), ("expr", "speechless", 2), ("expr", "kirakira", 2),
        ("expr", "default", 7),
        ("motion", "nod", 6), ("motion", "wakuwaku", 5), ("motion", "shake", 3),
        ("motion", "troubled", 2), ("motion", "dizzy", 1), ("motion", "idle", 10),
    ],
    "evening": [
        ("expr", "smile", 8), ("expr", "happy", 6), ("expr", "troubled", 3),
        ("expr", "default", 7),
        ("motion", "nod", 6), ("motion", "wakuwaku", 4), ("motion", "shake", 3),
        ("motion", "idle", 10),
    ],
    "night": [
        ("expr", "sleep", 18), ("expr", "troubled", 4), ("expr", "default", 6),
        ("motion", "sleep", 16), ("motion", "nod", 2), ("motion", "troubled", 2),
    ],
}

_HOLD = {"motion": 3.0, "expr": 0.4, "speak": 4.0}


class PetDirector:
    def __init__(self, cfg=None, live2d=None, presence=None,
                 speak=None, emit=None, rng: random.Random | None = None):
        auto = getattr(cfg, "autonomy", None) if cfg is not None else None
        self._cfg = cfg
        self._auto = auto
        self.live2d = live2d
        self.presence = presence
        self.speak_fn = speak            # callable(text) -> None；None 表示不许说话
        self.emit_fn = emit              # callable(kind, **payload) -> bool
        self.rng = rng or random.Random()

        def conf(key, default):
            try:
                return auto.get(key, default) if auto is not None else default
            except Exception:
                return default

        self.enabled = bool(conf("enabled", True))
        self.micro_enabled = bool(conf("micro_motion", True))
        self.micro_lambda_day = float(conf("micro_lambda_day", 0.0033))
        self.micro_lambda_night = float(conf("micro_lambda_night", 0.0008))
        quiet = conf("quiet_hours", [1, 7]) or [1, 7]
        try:
            self.quiet_start = int(quiet[0])
            self.quiet_end = int(quiet[1])
        except Exception:
            self.quiet_start, self.quiet_end = 1, 7
        self.speak_budget = int(conf("speak_budget_per_hour", 3))
        # 两句之间至少隔这么久：剧本里连排两句会像卡带，也不像“偶尔自言自语”
        self.speak_cooldown = float(conf("speak_cooldown_sec", 45))
        self.presence_enabled = bool(conf("presence", True)) and presence is not None
        self.away_sec = float(conf("away_sec", 300))
        self.plan_horizon = float(conf("plan_horizon_sec", 1800))

        base = conf("emotion_baseline", {}) or {}
        self.valence = self._f(base.get("valence"), 0.1, -1.0, 1.0)
        self.arousal = self._f(base.get("arousal"), 0.45, 0.0, 1.0)
        self.energy = self._f(base.get("energy"), 0.6, 0.0, 1.0)
        self.baseline = (self.valence, self.arousal, self.energy)

        # 运行时状态
        now = time.time()
        self._lock_until = 0.0
        self._lock_priority = -1
        self._next_micro = now + self._micro_gap(now)
        self._next_presence = 0.0
        self._plan: list[dict] = []
        self._speak_times: deque[float] = deque()
        self._asleep = False
        self._last_presence_wake = 0.0
        self._presence: dict = {}
        self._last_action: dict = {}
        self._recent: deque[str] = deque(maxlen=8)
        self._bad_names: set[str] = set()
        self._motion_map = self._read_map("motion_map", {})
        self._emotion_map = self._read_map("emotion_map", {})

    # ------------------------------------------------------------------ 基础
    @staticmethod
    def _f(value, default: float, lo: float, hi: float) -> float:
        try:
            v = float(value)
        except (TypeError, ValueError):
            v = default
        return max(lo, min(hi, v))

    def _read_map(self, key: str, default: dict) -> dict:
        try:
            m = self._cfg.persona.get(key, default) if self._cfg is not None else default
            return dict(m) if isinstance(m, dict) else dict(default)
        except Exception:
            return dict(default)

    def _emit(self, kind: str, **payload) -> None:
        if self.emit_fn is None:
            return
        try:
            self.emit_fn(kind, **payload)
        except Exception:
            pass

    def _mode(self, now: float) -> str:
        hour = datetime.fromtimestamp(now).hour
        if 5 <= hour < 9:
            return "morning"
        if 9 <= hour < 18:
            return "day"
        if 18 <= hour < 23:
            return "evening"
        return "night"

    def _in_quiet_hours(self, now: float) -> bool:
        hour = datetime.fromtimestamp(now).hour
        start, end = self.quiet_start, self.quiet_end
        if start == end:
            return False
        if start < end:
            return start <= hour < end
        return hour >= start or hour < end

    def _micro_gap(self, now: float) -> float:
        """指数分布间隔：均值随昼夜变化，不是固定节拍。"""
        lam = self.micro_lambda_night if self._mode(now) == "night" else self.micro_lambda_day
        lam = max(1e-5, lam)
        gap = self.rng.expovariate(lam)
        return max(20.0, min(1800.0, gap))

    # ------------------------------------------------------------------ 外部输入
    def note_chat(self, now: float | None = None) -> None:
        """主人刚说了话：她会“注意到”，并重置微动作计时（别在对话时乱动）。"""
        now = now or time.time()
        self._next_micro = now + self._micro_gap(now)

    def clear_plan(self, kind: str | None = None) -> int:
        """丢掉还没执行的剧本（默认全丢）。主人开始对话时用，免得她插嘴。"""
        before = len(self._plan)
        if kind:
            self._plan = [p for p in self._plan if p["kind"] != kind]
        else:
            self._plan = []
        return before - len(self._plan)

    def set_emotion(self, valence=None, arousal=None, energy=None) -> None:
        if valence is not None:
            self.valence = self._f(valence, self.valence, -1.0, 1.0)
        if arousal is not None:
            self.arousal = self._f(arousal, self.arousal, 0.0, 1.0)
        if energy is not None:
            self.energy = self._f(energy, self.energy, 0.0, 1.0)

    def nudge(self, valence=0.0, arousal=0.0, energy=0.0) -> None:
        self.set_emotion(self.valence + valence, self.arousal + arousal,
                         self.energy + energy)

    def submit_plan(self, items, now: float | None = None) -> int:
        """把 LLM 给的剧本排进队列。返回真正排进去的条数。"""
        now = now or time.time()
        added = 0
        for raw in items or []:
            if not isinstance(raw, dict):
                continue
            do = str(raw.get("do") or raw.get("kind") or "").strip().lower()
            try:
                at = float(raw.get("at", 0) or 0)
            except (TypeError, ValueError):
                at = 0.0
            due = now + max(0.0, min(self.plan_horizon, at))
            if do in ("speak", "say", "talk"):
                text = str(raw.get("text") or "").strip()[:60]
                if text:
                    self._plan.append({"due": due, "kind": "speak", "name": "", "text": text})
                    added += 1
            elif do in ("motion", "move", "action"):
                name = self.alias_motion(str(raw.get("name") or ""))
                if not name:
                    # 模型偶尔把表情名塞进 motion：能救就救，别白丢一条
                    name = self.alias_expression(str(raw.get("name") or ""))
                    if name:
                        self._plan.append({"due": due, "kind": "expr", "name": name,
                                           "text": ""})
                        added += 1
                        continue
                if name:
                    self._plan.append({"due": due, "kind": "motion", "name": name, "text": ""})
                    added += 1
            elif do in ("expr", "expression", "face"):
                name = self.alias_expression(str(raw.get("name") or ""))
                if not name:
                    name = self.alias_motion(str(raw.get("name") or ""))
                    if name:
                        self._plan.append({"due": due, "kind": "motion", "name": name,
                                           "text": ""})
                        added += 1
                        continue
                if name:
                    self._plan.append({"due": due, "kind": "expr", "name": name, "text": ""})
                    added += 1
        self._plan.sort(key=lambda x: x["due"])
        return added

    def alias_motion(self, name: str) -> str:
        raw = (name or "").strip()
        if not raw:
            return ""
        mapped = self._motion_map.get(raw, raw)
        key = str(mapped).strip().lower()
        if key not in MOTIONS or key in self._bad_names:
            return ""
        return key

    def alias_expression(self, name: str) -> str:
        raw = (name or "").strip()
        if not raw:
            return ""
        mapped = self._emotion_map.get(raw, raw)
        key = str(mapped).strip().lower()
        if key not in EXPRESSIONS or key in self._bad_names:
            return ""
        return key

    # ------------------------------------------------------------------ 状态
    def state(self, now: float | None = None) -> dict:
        now = now or time.time()
        return {
            "mode": self._mode(now),
            "asleep": self._asleep,
            "valence": round(self.valence, 2),
            "arousal": round(self.arousal, 2),
            "energy": round(self.energy, 2),
            "recent": list(self._recent)[-5:],
            "plan_pending": len([p for p in self._plan if p["due"] >= now]),
            "presence": dict(self._presence),
        }

    def describe_presence(self) -> str:
        if not self._presence:
            return ""
        try:
            from agent.presence import Presence
            return Presence.describe(self._presence)
        except Exception:
            return ""

    # ------------------------------------------------------------------ 主循环
    def tick(self, now: float | None = None) -> dict | None:
        """1 Hz 调用。最多执行一个动作，返回执行了什么（便于测试/日志）。"""
        if not self.enabled:
            return None
        now = now or time.time()
        self._decay(now)
        self._sample_presence(now)

        # 身体锁：低优先级动作在锁内不许上
        if now < self._lock_until:
            return None

        acted = self._run_plan(now)
        if acted:
            return acted
        acted = self._check_presence(now)
        if acted:
            return acted
        if self._asleep:
            return None
        acted = self._maybe_micro(now)
        return acted

    def _decay(self, now: float) -> None:
        """情绪缓慢回到基线：没人理她时 valence 会慢慢往下掉，精力随时间恢复。"""
        # 用固定步长近似（tick 是 1 Hz，这里按 1 秒的时间常数算，误差可忽略）
        bv, ba, be = self.baseline
        self.valence += (bv - self.valence) * 0.0008
        self.arousal += (ba - self.arousal) * 0.0015
        self.energy += (be - self.energy) * 0.0006

    def _sample_presence(self, now: float) -> None:
        if not self.presence_enabled or now < self._next_presence:
            return
        self._next_presence = now + 2.0
        try:
            self._presence = self.presence.snapshot() or {}
        except Exception:
            self._presence = {}

    def _check_presence(self, now: float) -> dict | None:
        if not self.presence_enabled or not self._presence:
            return None
        snap = self._presence
        if snap.get("unknown"):
            return None
        away = bool(snap.get("away"))
        idle = snap.get("idle_sec")
        if away and not self._asleep:
            self._asleep = True
            self._send("motion", "sleep")
            self._send("expr", "sleep")
            self._lock(now, _HOLD["motion"], PRIORITY_INTENT)
            self._record("sleep")
            self._emit("motion", name="sleep", source="presence")
            logger.info("主人离开（空闲 %s 秒），进入睡眠待机", idle)
            return {"kind": "motion", "name": "sleep", "source": "presence"}
        if (not away) and self._asleep and idle is not None and idle < 2.0:
            self._asleep = False
            self._send("expr", "happy")
            self._send("motion", "wakuwaku")
            self._lock(now, _HOLD["motion"], PRIORITY_USER)
            self._last_presence_wake = now
            self._record("wakuwaku")
            self.nudge(valence=0.08, arousal=0.1)
            self._emit("motion", name="wakuwaku", source="presence")
            logger.info("主人回来了，醒来伸个懒腰")
            return {"kind": "motion", "name": "wakuwaku", "source": "presence"}
        return None

    def _run_plan(self, now: float) -> dict | None:
        while self._plan:
            item = self._plan[0]
            if item["due"] > now:
                return None
            self._plan.pop(0)
            if now - item["due"] > 180:
                continue                      # 太久没执行，剧本已经过期
            if self._asleep and item["kind"] != "speak":
                continue                      # 睡着时不播剧本动作
            acted = self._execute(item["kind"], item["name"], item.get("text", ""),
                                  PRIORITY_INTENT, "plan", now)
            if acted:
                return acted
        return None

    def _maybe_micro(self, now: float) -> dict | None:
        if not self.micro_enabled or now < self._next_micro:
            return None
        kind, name = self._pick_micro(now)
        self._next_micro = now + self._micro_gap(now)
        if not name:
            return None
        return self._execute(kind, name, "", PRIORITY_MICRO, "micro", now)

    def _pick_micro(self, now: float) -> tuple[str, str]:
        table = _MICRO.get(self._mode(now)) or _MICRO["day"]
        weights = []
        names = []
        for kind, name, weight in table:
            if name in self._bad_names:
                continue
            w = float(weight) * self._mood_factor(kind, name)
            if w <= 0:
                continue
            names.append((kind, name))
            weights.append(w)
        if not names:
            return "expr", ""
        try:
            kind, name = self.rng.choices(names, weights=weights, k=1)[0]
        except Exception:
            kind, name = names[0]
        return kind, name

    def _mood_factor(self, kind: str, name: str) -> float:
        """心情/精力对权重的影响：心情好更爱笑，精力低更爱困。"""
        v, a, e = self.valence, self.arousal, self.energy
        f = 1.0
        if name in ("happy", "smile", "kirakira", "wakuwaku"):
            f *= 1.0 + max(0.0, v) * 1.4
            f *= 1.0 - max(0.0, -v) * 0.6
        if name in ("troubled", "tears"):
            f *= 1.0 + max(0.0, -v) * 1.2
        if name in ("sleep", "idle", "default"):
            f *= 1.0 + max(0.0, 0.4 - e) * 1.5
        if name == "wakuwaku":
            f *= 1.0 + max(0.0, a - 0.5) * 1.2
            f *= 1.0 - max(0.0, 0.35 - e) * 1.5
        if name in ("dizzy", "glitch", "angry"):
            f *= 0.6 + a * 0.6
        return max(0.05, f)

    # ------------------------------------------------------------------ 执行
    def _lock(self, now: float, hold: float, priority: int) -> None:
        self._lock_until = now + max(0.2, hold)
        self._lock_priority = priority

    def _record(self, name: str) -> None:
        if name:
            self._recent.append(name)
        self._last_action = {"name": name, "ts": time.time()}

    def _send(self, kind: str, name: str) -> bool:
        if self.live2d is None or not name:
            return False
        try:
            if kind == "motion":
                ok = bool(self.live2d.play_motion(name))
            elif kind == "expr":
                ok = bool(self.live2d.set_expression(name))
            else:
                return False
        except Exception as e:
            logger.debug("Live2D %s=%s 发送失败：%s", kind, name, e)
            return False
        if not ok:
            # 模型里没有这个名字：本次会话不再用它，避免每秒刷同一条错误
            if name not in self._bad_names:
                self._bad_names.add(name)
                logger.info("Live2D 不认识 %s=%s，已从轮换里移除", kind, name)
        return ok

    def _execute(self, kind: str, name: str, text: str,
                 priority: int, source: str, now: float | None = None) -> dict | None:
        now = now if now is not None else time.time()
        if kind == "speak":
            if not self._say(text, priority, now):
                return None
            return {"kind": "speak", "name": "", "text": text, "source": source}
        ok = self._send(kind, name)
        if not ok:
            return None
        hold = _HOLD.get(kind, 1.0)
        if source == "plan":
            hold *= 1.3
        self._lock(now, hold, priority)
        self._record(name)
        self._emit(kind, name=name, source=source)
        logger.debug("导演：%s=%s（%s）", kind, name, source)
        return {"kind": kind, "name": name, "source": source}

    def _say(self, text: str, priority: int, now: float) -> bool:
        text = (text or "").strip()
        if not text or self.speak_fn is None:
            return False
        if not self._can_speak(now):
            logger.info("说话预算/静音时段限制，跳过这句：%s", text[:20])
            return False
        try:
            self.speak_fn(text)
        except Exception as e:
            logger.warning("自主说话失败：%s", e)
            return False
        self._speak_times.append(now)
        hold = max(_HOLD["speak"], min(12.0, len(text) * 0.32))
        self._lock(now, hold, priority)
        self._record("say")
        self._emit("speak", text=text)
        return True

    def _can_speak(self, now: float) -> bool:
        if self.speak_budget <= 0:
            return False
        if self._in_quiet_hours(now):
            return False
        while self._speak_times and now - self._speak_times[0] > 3600:
            self._speak_times.popleft()
        if self._speak_times and now - self._speak_times[-1] < self.speak_cooldown:
            return False
        return len(self._speak_times) < self.speak_budget

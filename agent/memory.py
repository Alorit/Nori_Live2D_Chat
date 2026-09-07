"""长期记忆系统。

分层设计：
- 工作记忆：SQLite messages 表，给 LLM 提供最近对话窗口
- 情节/语义记忆：memories 表 + BM25/向量检索，注入 system prompt
- 行为规则：rules 表，可长期累积、被反思整合更新
- 滚动摘要：summary 表，压缩更早的对话

检索默认使用纯本地 BM25（jieba 分词），零外部模型依赖；
如果安装了 sentence-transformers，auto 模式会叠加向量相似度。
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
import sqlite3
import threading
import time
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger("agent.memory")

STOPWORDS = {
    "的", "了", "是", "我", "你", "他", "她", "它", "我们", "你们", "他们",
    "这", "那", "吗", "呢", "啊", "吧", "哦", "嗯", "呀", "就", "都", "也",
    "很", "还", "在", "有", "和", "与", "及", "或", "但", "而", "个", "一",
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "to",
    "of", "in", "on", "at", "for", "with", "and", "or", "but", "it",
    "this", "that", "you", "i", "me", "my", "he", "she", "they", "we",
    "do", "does", "did", "not", "no", "yes", "so", "if", "then",
}

_PERSONAL_HINTS = [
    "我喜欢", "我讨厌", "我不喜欢", "我养", "我的", "我生日", "我工作", "我在",
    "我名字", "我叫", "我住在", "我害怕", "我过敏", "记住", "别忘了", "别剧透",
    "以后", "下次", "我是", "我最近", "我打算", "我想", "我希望", "不要", "别",
]

_NEGATIVE_HINTS = ["闭嘴", "别说了", "你烦", "不好笑", "说错了", "不要这样", "别这样"]


def _jieba_cut(text: str):
    try:
        import jieba
        return list(jieba.cut(text))
    except Exception:
        return re.findall(r"[a-zA-Z0-9_]+|[\u4e00-\u9fff]", text)


class MemoryStore:
    def __init__(self, db_path: str, cfg=None):
        self.db_path = str(db_path)
        self.cfg = cfg
        self.lock = threading.RLock()
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._ensure_tables()

        # BM25 索引
        self.postings: dict[str, dict[int, int]] = defaultdict(dict)  # token -> {mem_id: tf}
        self.doc_len: dict[int, int] = {}
        self.mem_meta: dict[int, dict[str, Any]] = {}

        # 向量记忆（可选）
        self.vector: Any = None
        self._vec_cache: dict[int, np.ndarray] = {}

        self._rebuild_index()

        if cfg is not None:
            backend = cfg.get("backend", "auto") if hasattr(cfg, "get") else "auto"
            self.vector_model = cfg.get("vector_model", "BAAI/bge-small-zh-v1.5") if hasattr(cfg, "get") else "BAAI/bge-small-zh-v1.5"
            if backend in ("auto", "vector"):
                self._init_vector()

    # ---------------------------------------------------------- 基础 ----
    def _ensure_tables(self):
        with self.lock:
            self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL, role TEXT, content TEXT,
                importance REAL DEFAULT 0.0,
                feedback REAL DEFAULT 0.0
            );
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uuid TEXT UNIQUE,
                ts REAL,
                type TEXT DEFAULT 'episodic',
                content TEXT,
                importance REAL DEFAULT 0.5,
                access_count INTEGER DEFAULT 0,
                last_access REAL DEFAULT 0.0,
                source TEXT
            );
            CREATE TABLE IF NOT EXISTS mem_vec (
                mem_id INTEGER PRIMARY KEY,
                vec BLOB
            );
            CREATE TABLE IF NOT EXISTS rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rule TEXT UNIQUE,
                enabled INTEGER DEFAULT 1,
                ts REAL,
                version INTEGER DEFAULT 1,
                source TEXT
            );
            CREATE TABLE IF NOT EXISTS summary (
                key TEXT PRIMARY KEY,
                content TEXT,
                updated REAL
            );
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                persona TEXT NOT NULL,
                title TEXT NOT NULL,
                is_main INTEGER NOT NULL DEFAULT 0,
                created REAL,
                updated REAL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_conv_main ON conversations(persona) WHERE is_main = 1;
            CREATE INDEX IF NOT EXISTS idx_mem_type ON memories(type);
            CREATE INDEX IF NOT EXISTS idx_msg_ts ON messages(ts);
            CREATE INDEX IF NOT EXISTS idx_conv_persona ON conversations(persona);
            """)
            # 历史对话按人格隔离：老库补 persona 列，旧数据归到 nori
            cols = [r[1] for r in self.conn.execute("PRAGMA table_info(messages)").fetchall()]
            if "persona" not in cols:
                self.conn.execute(
                    "ALTER TABLE messages ADD COLUMN persona TEXT NOT NULL DEFAULT 'nori'")
                self.conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_msg_persona ON messages(persona)")
            cols = [r[1] for r in self.conn.execute("PRAGMA table_info(messages)").fetchall()]
            if "conversation_id" not in cols:
                self.conn.execute(
                    "ALTER TABLE messages ADD COLUMN conversation_id INTEGER NOT NULL DEFAULT 0")
                self.conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_msg_conv ON messages(conversation_id)")
                # 把已有的历史归入各自人格的“主对话”，保证重启后可见
                for row in self.conn.execute(
                        "SELECT DISTINCT persona FROM messages WHERE conversation_id = 0").fetchall():
                    persona = row["persona"] or "nori"
                    cur = self.conn.execute(
                        "INSERT OR IGNORE INTO conversations(persona, title, is_main, created, updated) "
                        "VALUES(?,?,1,?,?)",
                        (persona, f"{persona} · 主对话", time.time(), time.time()))
                    main_id = self.conn.execute(
                        "SELECT id FROM conversations WHERE persona=? AND is_main=1",
                        (persona,)).fetchone()["id"]
                    self.conn.execute(
                        "UPDATE messages SET conversation_id=? WHERE persona=? AND conversation_id=0",
                        (main_id, persona))
            cols = [r[1] for r in self.conn.execute("PRAGMA table_info(messages)").fetchall()]
            if "image_paths" not in cols:
                self.conn.execute(
                    "ALTER TABLE messages ADD COLUMN image_paths TEXT NOT NULL DEFAULT '[]'")
            self.conn.commit()

    def _rebuild_index(self):
        with self.lock:
            self.postings.clear()
            self.doc_len.clear()
            self.mem_meta.clear()
            rows = self.conn.execute(
                "SELECT id, ts, type, content, importance, access_count, last_access, source "
                "FROM memories").fetchall()
            for r in rows:
                rid = r["id"]
                toks = self._tokenize(r["content"])
                self.doc_len[rid] = max(1, len(toks))
                self.mem_meta[rid] = {
                    "id": rid, "ts": r["ts"], "type": r["type"], "content": r["content"],
                    "importance": r["importance"], "access_count": r["access_count"],
                    "last_access": r["last_access"], "source": r["source"],
                }
                tf: dict[str, int] = defaultdict(int)
                for t in toks:
                    tf[t] += 1
                for t, c in tf.items():
                    self.postings[t][rid] = c
            self._load_vec_cache()

    # ---------------------------------------------------------- 分词 ----
    @staticmethod
    def _is_noise(tok: str) -> bool:
        tok = tok.strip().lower()
        if not tok:
            return True
        if tok in STOPWORDS:
            return True
        if re.fullmatch(r"[\s\W_]+", tok):
            return True
        return False

    def _tokenize(self, text: str) -> list[str]:
        toks = []
        for t in _jieba_cut(text.lower()):
            t = t.strip()
            if self._is_noise(t):
                continue
            toks.append(t)
        # 中文单字过多时补充二元组，增强召回
        if any('\u4e00' <= c <= '\u9fff' for c in text):
            compact = re.sub(r"[^\u4e00-\u9fff]", "", text)
            if len(compact) >= 2:
                for i in range(len(compact) - 1):
                    toks.append(compact[i:i + 2])
        return toks or [text.strip().lower()[:64]]

    # ---------------------------------------------------------- 写入 ----
    def record_message(self, role: str, content: str, persona: str = "nori",
                      conversation_id: int | None = None,
                      image_paths: list[str] | None = None) -> int:
        """写入一条消息，返回消息 id。image_paths 为消息携带的图片/表情路径。"""
        imp = heuristic_importance(content, role)
        ts = time.time()
        persona = persona or "nori"
        if conversation_id is None:
            conversation_id = self.ensure_main_conversation(persona)
        image_paths = list(image_paths or [])[:8]
        with self.lock:
            cur = self.conn.execute(
                "INSERT INTO messages(ts, role, content, importance, persona, conversation_id, image_paths) "
                "VALUES(?,?,?,?,?,?,?)",
                (ts, role, content, imp, persona, conversation_id,
                 json.dumps(image_paths, ensure_ascii=False)))
            self.conn.execute(
                "UPDATE conversations SET updated=? WHERE id=?", (ts, conversation_id))
            self.conn.commit()
            return int(cur.lastrowid)

    # ---------------------------------------------------------- 会话/历史 ----
    def ensure_main_conversation(self, persona: str) -> int:
        persona = persona or "nori"
        with self.lock:
            row = self.conn.execute(
                "SELECT id FROM conversations WHERE persona=? AND is_main=1",
                (persona,)).fetchone()
            if row:
                return int(row["id"])
            ts = time.time()
            cur = self.conn.execute(
                "INSERT INTO conversations(persona, title, is_main, created, updated) "
                "VALUES(?,?,1,?,?)",
                (persona, f"{persona} · 主对话", ts, ts))
            self.conn.commit()
            return int(cur.lastrowid)

    def create_conversation(self, persona: str, title: str = "") -> int:
        persona = persona or "nori"
        ts = time.time()
        title = (title or "").strip() or f"{persona} · 新对话"
        with self.lock:
            cur = self.conn.execute(
                "INSERT INTO conversations(persona, title, is_main, created, updated) "
                "VALUES(?,?,0,?,?)",
                (persona, title, ts, ts))
            self.conn.commit()
            return int(cur.lastrowid)

    def list_conversations(self, persona: str | None = None) -> list[dict[str, Any]]:
        sql = ("SELECT c.id, c.persona, c.title, c.is_main, c.created, c.updated, "
               "COUNT(m.id) AS msg_count, MAX(m.ts) AS last_ts "
               "FROM conversations c LEFT JOIN messages m ON m.conversation_id = c.id ")
        args: list[Any] = []
        if persona:
            sql += "WHERE c.persona = ? "
            args.append(persona)
        sql += "GROUP BY c.id ORDER BY c.is_main DESC, c.updated DESC"
        with self.lock:
            rows = self.conn.execute(sql, args).fetchall()
        return [dict(r) for r in rows]

    def rename_conversation(self, conversation_id: int, title: str) -> bool:
        title = (title or "").strip()
        if not title:
            return False
        with self.lock:
            cur = self.conn.execute(
                "UPDATE conversations SET title=? WHERE id=? AND is_main=0",
                (title, int(conversation_id)))
            self.conn.commit()
        return cur.rowcount > 0

    def delete_conversation(self, conversation_id: int) -> bool:
        with self.lock:
            row = self.conn.execute(
                "SELECT is_main FROM conversations WHERE id=?", (int(conversation_id),)).fetchone()
            if not row or row["is_main"]:
                return False
            cur = self.conn.execute("DELETE FROM conversations WHERE id=?", (int(conversation_id),))
            self.conn.execute("DELETE FROM messages WHERE conversation_id=?", (int(conversation_id),))
            self.conn.commit()
        return cur.rowcount > 0

    def get_conversation(self, conversation_id: int) -> dict[str, Any] | None:
        with self.lock:
            row = self.conn.execute(
                "SELECT id, persona, title, is_main FROM conversations WHERE id=?",
                (int(conversation_id),)).fetchone()
        return dict(row) if row else None

    def add_memory(self, content: str, mem_type: str = "episodic",
                   importance: float = 0.5, source: str = "") -> int | None:
        content = (content or "").strip()
        if not content:
            return None
        ts = time.time()
        mem_id = None
        with self.lock:
            cur = self.conn.execute(
                "INSERT OR IGNORE INTO memories(uuid, ts, type, content, importance, access_count, last_access, source) "
                "VALUES(?,?,?,?,?,0,?,?)",
                (str(uuid.uuid4()), ts, mem_type, content, importance, ts, source))
            self.conn.commit()
            if cur.rowcount == 0:
                return None
            mem_id = int(cur.lastrowid)
            toks = self._tokenize(content)
            self.doc_len[mem_id] = max(1, len(toks))
            self.mem_meta[mem_id] = {
                "id": mem_id, "ts": ts, "type": mem_type, "content": content,
                "importance": importance, "access_count": 0, "last_access": ts, "source": source,
            }
            tf: dict[str, int] = defaultdict(int)
            for t in toks:
                tf[t] += 1
            for t, c in tf.items():
                self.postings[t][mem_id] = c
        self._maybe_embed(mem_id, content)
        self.forget_excess()
        return mem_id

    def add_exchange(self, user_text: str, reply_text: str, assistant_msg_id: int) -> None:
        """把一轮对话作为情节记忆保存（有最小长度与重要性门槛）。"""
        cfg = self.cfg
        min_chars = int(cfg.get("min_exchange_chars", 8)) if cfg else 8
        threshold = float(cfg.get("importance_threshold", 0.15)) if cfg else 0.15
        combined = f"用户：{user_text}\nAI：{reply_text}"
        if len(combined) < min_chars:
            return
        imp = heuristic_importance(user_text + " " + reply_text, "assistant")
        if imp < threshold:
            return
        self.add_memory(combined, mem_type="episodic", importance=imp,
                        source=f"msg:{assistant_msg_id}")

    def apply_feedback(self, message_id: int, delta: float) -> None:
        """把 👍/👎 反馈写回消息，并调整对应情节记忆的重要性。"""
        with self.lock:
            self.conn.execute(
                "UPDATE messages SET feedback = feedback + ? WHERE id = ?", (delta, message_id))
            rows = self.conn.execute(
                "SELECT id, importance FROM memories WHERE source = ?", (f"msg:{message_id}",)).fetchall()
            for r in rows:
                new_imp = max(0.05, min(1.0, r["importance"] + delta * 0.25))
                self.conn.execute("UPDATE memories SET importance = ? WHERE id = ?", (new_imp, r["id"]))
                if r["id"] in self.mem_meta:
                    self.mem_meta[r["id"]]["importance"] = new_imp
            self.conn.commit()

    # ---------------------------------------------------------- 检索 ----
    def _idf(self, token: str, n_docs: int) -> float:
        df = len(self.postings.get(token, {}))
        return math.log(1 + (n_docs - df + 0.5) / (df + 0.5))

    def _bm25_scores(self, tokens: list[str]) -> dict[int, float]:
        n_docs = max(1, len(self.doc_len))
        avgdl = sum(self.doc_len.values()) / n_docs if self.doc_len else 1.0
        k1, b = 1.5, 0.75
        scores: dict[int, float] = defaultdict(float)
        seen: set[str] = set()
        for tok in tokens:
            if tok in seen:
                continue
            seen.add(tok)
            idf = self._idf(tok, n_docs)
            for mem_id, tf in self.postings.get(tok, {}).items():
                dl = self.doc_len.get(mem_id, avgdl)
                denom = tf + k1 * (1 - b + b * dl / avgdl)
                scores[mem_id] += idf * (tf * (k1 + 1)) / denom
        return scores

    def retrieve(self, query: str, k: int = 8, mem_type: str | None = None) -> list[dict[str, Any]]:
        """检索长期记忆，返回按综合得分排序的列表。"""
        tokens = self._tokenize(query)
        if not tokens:
            return []
        bm = self._bm25_scores(tokens)
        if not bm:
            return []

        max_bm = max(bm.values()) or 1.0
        vec_sim: dict[int, float] = {}
        if self.vector is not None:
            try:
                vec_sim = self._vector_similarities(query)
            except Exception as e:
                logger.debug("向量检索失败：%s", e)

        now = time.time()
        half_life = 7 * 86400.0
        ranked = []
        for mem_id, bm_score in bm.items():
            meta = self.mem_meta.get(mem_id)
            if not meta:
                continue
            if mem_type and meta["type"] != mem_type:
                continue
            bm_norm = bm_score / max_bm
            vec_norm = vec_sim.get(mem_id, 0.0)
            recency = 0.5 ** ((now - meta["ts"]) / half_life)
            importance = float(meta["importance"])
            access_boost = min(0.1, meta["access_count"] * 0.01)

            if self.vector is not None and vec_sim:
                score = 0.55 * bm_norm + 0.30 * vec_norm + 0.10 * recency + 0.05 * importance + access_boost
            else:
                score = 0.75 * bm_norm + 0.15 * recency + 0.10 * importance + access_boost
            ranked.append((score, meta))

        ranked.sort(key=lambda x: x[0], reverse=True)
        out = []
        for score, meta in ranked[:k]:
            item = dict(meta)
            item["score"] = round(score, 4)
            out.append(item)
            self._touch(meta["id"])
        return out

    def _touch(self, mem_id: int):
        with self.lock:
            self.conn.execute(
                "UPDATE memories SET access_count = access_count + 1, last_access = ? WHERE id = ?",
                (time.time(), mem_id))
            if mem_id in self.mem_meta:
                self.mem_meta[mem_id]["access_count"] += 1
                self.mem_meta[mem_id]["last_access"] = time.time()
            # 不每次 commit，减少磁盘压力；由下一次写操作或显式 commit 落盘
            try:
                self.conn.commit()
            except Exception:
                pass

    # ---------------------------------------------------------- 向量 ----
    def _init_vector(self):
        try:
            from sentence_transformers import SentenceTransformer
            self.vector = SentenceTransformer(self.vector_model)
            logger.info("向量记忆已启用：%s", self.vector_model)
        except Exception as e:
            self.vector = None
            logger.info("未启用向量记忆（%s），使用纯 BM25 检索。", e)

    def _load_vec_cache(self):
        self._vec_cache.clear()
        try:
            rows = self.conn.execute("SELECT mem_id, vec FROM mem_vec").fetchall()
            for r in rows:
                self._vec_cache[r["mem_id"]] = np.frombuffer(r["vec"], dtype=np.float32)
        except Exception:
            pass

    def _maybe_embed(self, mem_id: int, content: str):
        if self.vector is None:
            return
        try:
            vec = self.vector.encode(content, normalize_embeddings=True)
            arr = np.asarray(vec, dtype=np.float32)
            with self.lock:
                self.conn.execute(
                    "INSERT OR REPLACE INTO mem_vec(mem_id, vec) VALUES(?,?)",
                    (mem_id, arr.tobytes()))
                self.conn.commit()
            self._vec_cache[mem_id] = arr
        except Exception as e:
            logger.debug("向量化失败：%s", e)

    def _vector_similarities(self, query: str) -> dict[int, float]:
        q = np.asarray(self.vector.encode(query, normalize_embeddings=True), dtype=np.float32)
        sims: dict[int, float] = {}
        for mem_id, v in self._vec_cache.items():
            denom = float(np.linalg.norm(q) * np.linalg.norm(v)) or 1.0
            sims[mem_id] = float(np.dot(q, v) / denom)
        return sims

    # ---------------------------------------------------------- 规则/摘要 ----
    def add_rules(self, rules: list[str], source: str = "consolidate") -> int:
        if not rules:
            return 0
        n = 0
        with self.lock:
            for r in rules:
                r = (r or "").strip()
                if not r:
                    continue
                try:
                    self.conn.execute(
                        "INSERT INTO rules(rule, enabled, ts, source) VALUES(?,1,?,?)",
                        (r, time.time(), source))
                    n += 1
                except sqlite3.IntegrityError:
                    pass
            self.conn.commit()
        return n

    def get_active_rules(self, limit: int = 20) -> list[str]:
        with self.lock:
            rows = self.conn.execute(
                "SELECT rule FROM rules WHERE enabled = 1 ORDER BY ts DESC, id DESC LIMIT ?",
                (limit,)).fetchall()
        return [r["rule"] for r in rows]

    def get_summary(self, key: str = "working") -> str:
        with self.lock:
            row = self.conn.execute("SELECT content FROM summary WHERE key=?", (key,)).fetchone()
        return row["content"] if row else ""

    def set_summary(self, content: str, key: str = "working"):
        with self.lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO summary(key, content, updated) VALUES(?,?,?)",
                (key, content, time.time()))
            self.conn.commit()

    # ---------------------------------------------------------- 历史 ----
    def get_recent_messages(self, n: int = 30, persona: str | None = None,
                            conversation_id: int | None = None) -> list[dict[str, Any]]:
        """按时间顺序返回最近 n 条消息（user/assistant），可按人格/会话隔离。

        返回 dict：role / content / image_paths（图片消息时为路径列表）。
        """
        conds, args = [], []
        if persona:
            conds.append("persona = ?")
            args.append(persona)
        if conversation_id is not None:
            conds.append("conversation_id = ?")
            args.append(int(conversation_id))
        where = (" WHERE " + " AND ".join(conds)) if conds else ""
        with self.lock:
            rows = self.conn.execute(
                f"SELECT role, content, image_paths FROM messages{where} ORDER BY id DESC LIMIT ?",
                (*args, n)).fetchall()
        rows = list(reversed(rows))
        out = []
        for r in rows:
            try:
                image_paths = json.loads(r["image_paths"] or "[]")
                if not isinstance(image_paths, list):
                    image_paths = []
            except Exception:
                image_paths = []
            out.append({
                "role": r["role"],
                "content": r["content"] or "",
                "image_paths": image_paths,
            })
        return out

    def get_recent_messages_with_ts(self, n: int = 80, persona: str | None = None,
                                    conversation_id: int | None = None
                                    ) -> list[tuple[str, str, str]]:
        conds, args = [], []
        if persona:
            conds.append("persona = ?")
            args.append(persona)
        if conversation_id is not None:
            conds.append("conversation_id = ?")
            args.append(int(conversation_id))
        where = (" WHERE " + " AND ".join(conds)) if conds else ""
        with self.lock:
            rows = self.conn.execute(
                f"SELECT role, content, ts FROM messages{where} ORDER BY id DESC LIMIT ?",
                (*args, n)).fetchall()
        rows = list(reversed(rows))
        return [(r["role"], r["content"], str(r["ts"])) for r in rows]

    # ---------------------------------------------------------- 遗忘 ----
    def forget_excess(self, max_memories: int | None = None):
        if max_memories is None:
            max_memories = int(self.cfg.get("max_memories", 5000)) if self.cfg else 5000
        with self.lock:
            row = self.conn.execute("SELECT COUNT(*) AS c FROM memories").fetchone()
            if row["c"] <= max_memories:
                return
            # 删除最旧且低重要度的记忆，直到达标
            n = row["c"] - max_memories
            self.conn.execute("""
                DELETE FROM memories WHERE id IN (
                    SELECT id FROM memories
                    ORDER BY (importance + 0.0001) / (1.0 + (strftime('%s','now') - ts) / 86400.0) ASC,
                             ts ASC
                    LIMIT ?
                )
            """, (n,))
            self.conn.execute("DELETE FROM mem_vec WHERE mem_id NOT IN (SELECT id FROM memories)")
            self.conn.commit()
        self._rebuild_index()

    # ---------------------------------------------------------- 记忆管理 ----
    def list_memories(self, limit: int = 200, offset: int = 0,
                      mem_type: str | None = None, query: str = "") -> list[dict[str, Any]]:
        """浏览记忆（按时间倒序），可按类型/关键字过滤。"""
        sql = ("SELECT id, ts, type, content, importance, access_count, last_access, source "
               "FROM memories")
        conds, args = [], []
        if mem_type and mem_type != "全部":
            conds.append("type = ?")
            args.append(mem_type)
        if query:
            conds.append("content LIKE ?")
            args.append(f"%{query}%")
        if conds:
            sql += " WHERE " + " AND ".join(conds)
        sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
        args += [int(limit), int(offset)]
        with self.lock:
            rows = self.conn.execute(sql, args).fetchall()
        return [dict(r) for r in rows]

    def get_memory(self, mem_id: int) -> dict[str, Any] | None:
        with self.lock:
            r = self.conn.execute(
                "SELECT id, ts, type, content, importance, access_count, last_access, source "
                "FROM memories WHERE id = ?", (int(mem_id),)).fetchone()
        return dict(r) if r else None

    def update_memory(self, mem_id: int, content: str | None = None,
                      mem_type: str | None = None, importance: float | None = None) -> bool:
        mem_id = int(mem_id)
        with self.lock:
            old = self.conn.execute(
                "SELECT content FROM memories WHERE id = ?", (mem_id,)).fetchone()
            if not old:
                return False
            content = old["content"] if content is None else str(content).strip()
            if not content:
                return False
            mem_type = mem_type or None
            importance = float(importance) if importance is not None else None
            if mem_type:
                self.conn.execute("UPDATE memories SET type = ? WHERE id = ?", (mem_type, mem_id))
            if importance is not None:
                self.conn.execute("UPDATE memories SET importance = ? WHERE id = ?",
                                  (max(0.0, min(1.0, importance)), mem_id))
            self.conn.execute("UPDATE memories SET content = ? WHERE id = ?", (content, mem_id))
            self.conn.commit()
        # 重建该条目的 BM25 索引与向量
        self._rebuild_index()
        self._maybe_embed(mem_id, content)
        return True

    def delete_memory(self, mem_id: int) -> bool:
        mem_id = int(mem_id)
        with self.lock:
            cur = self.conn.execute("DELETE FROM memories WHERE id = ?", (mem_id,))
            if cur.rowcount:
                self.conn.execute("DELETE FROM mem_vec WHERE mem_id = ?", (mem_id,))
            self.conn.commit()
        if cur.rowcount:
            self._rebuild_index()
            return True
        return False

    def list_rules(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.lock:
            rows = self.conn.execute(
                "SELECT id, rule, enabled, ts, source FROM rules "
                "ORDER BY enabled DESC, ts DESC, id DESC LIMIT ?", (int(limit),)).fetchall()
        return [dict(r) for r in rows]

    def set_rule_enabled(self, rule_id: int, enabled: bool) -> bool:
        with self.lock:
            cur = self.conn.execute(
                "UPDATE rules SET enabled = ? WHERE id = ?", (1 if enabled else 0, int(rule_id)))
            self.conn.commit()
        return cur.rowcount > 0

    def delete_rule(self, rule_id: int) -> bool:
        with self.lock:
            cur = self.conn.execute("DELETE FROM rules WHERE id = ?", (int(rule_id),))
            self.conn.commit()
        return cur.rowcount > 0

    def merge_similar_memories(self, threshold: float = 0.85) -> int:
        """把高度相似的记忆合并为一条（按 token 重叠率判断），返回合并掉的条数。"""
        threshold = max(0.5, min(0.98, float(threshold)))
        with self.lock:
            rows = self.conn.execute(
                "SELECT id, ts, type, content, importance FROM memories").fetchall()
        groups: dict[int, list[dict]] = {}
        deleted = set()
        used = set()
        for i, a in enumerate(rows):
            if a["id"] in used:
                continue
            for b in rows[i + 1:]:
                if b["id"] in used:
                    continue
                if a["type"] != b["type"]:
                    continue
                ta = set(self._tokenize(a["content"]))
                tb = set(self._tokenize(b["content"]))
                if not ta or not tb:
                    continue
                overlap = len(ta & tb) / max(1, min(len(ta), len(tb)))
                if overlap >= threshold:
                    groups.setdefault(a["id"], [a]).append(b)
                    used.add(b["id"])
            if a["id"] in groups:
                used.add(a["id"])
        merged = 0
        embed_list: list[tuple[int, str]] = []
        for items in groups.values():
            keep = max(items, key=lambda x: (x["importance"], x["ts"]))
            others = [x for x in items if x["id"] != keep["id"]]
            texts = [keep["content"]]
            for x in others:
                if x["content"] not in texts and x["content"] != keep["content"]:
                    texts.append(x["content"])
            new_content = "；".join(texts)[:2000]
            new_imp = max(x["importance"] for x in items)
            with self.lock:
                self.conn.execute("UPDATE memories SET content=?, importance=? WHERE id=?",
                                  (new_content, new_imp, keep["id"]))
                for x in others:
                    cur = self.conn.execute("DELETE FROM memories WHERE id=?", (x["id"],))
                    self.conn.execute("DELETE FROM mem_vec WHERE mem_id=?", (x["id"],))
                    merged += cur.rowcount
                self.conn.commit()
            embed_list.append((keep["id"], new_content))
        if merged:
            self._rebuild_index()
            for mem_id, content in embed_list:
                self._maybe_embed(mem_id, content)
        return merged

    # ---------------------------------------------------------- 其他 ----
    def stats(self) -> dict[str, int]:
        with self.lock:
            msgs = self.conn.execute("SELECT COUNT(*) AS c FROM messages").fetchone()["c"]
            mems = self.conn.execute("SELECT COUNT(*) AS c FROM memories").fetchone()["c"]
            rules = self.conn.execute("SELECT COUNT(*) AS c FROM rules").fetchone()["c"]
        return {"messages": msgs, "memories": mems, "rules": rules}

    def export_conversations_jsonl(self, path: str | os.PathLike) -> str:
        """导出全部对话为 JSONL，可用于以后微调模型。"""
        path = str(path)
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with self.lock:
            rows = self.conn.execute(
                "SELECT ts, role, content, feedback FROM messages ORDER BY id").fetchall()
        with open(path, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps({"ts": r["ts"], "role": r["role"],
                                    "content": r["content"], "feedback": r["feedback"]},
                                   ensure_ascii=False) + "\n")
        return path

    def close(self):
        with self.lock:
            self.conn.commit()
            self.conn.close()


# ---------------------------------------------------------------- 工具 ----
def heuristic_importance(text: str, role: str = "user") -> float:
    """不调用 LLM 的启发式重要性打分（0~1）。"""
    text = text or ""
    score = 0.12
    if role == "assistant":
        score -= 0.04
    for hint in _PERSONAL_HINTS:
        if hint in text:
            score += 0.12
    for hint in _NEGATIVE_HINTS:
        if hint in text:
            score += 0.10
    if len(text) > 40:
        score += 0.06
    if len(text) > 120:
        score += 0.04
    if any(c.isdigit() for c in text):
        score += 0.02
    if "?" in text or "？" in text:
        score += 0.02
    return max(0.0, min(1.0, score))

"""16-bank 语义记忆分库（Module 2.2 / NovelClaw CLAW_BANKS 源码验证）

蓝图 docs/Story_Engine_工程蓝图.md:690-784。

核心思想：
- 不是单一向量库，而是 16 个语义分库（按层级：会话/设定/章节/状态/运行时）
- 双重存储：JSON 索引（保证关键词召回）+ 向量库（语义检索）
- 每条记忆带 bank、importance（poignancy 1-10）、created_at
- agent_id 字段实现"按角色隔离"（包拯看不到展昭的私有记忆）

存储：
- 与 EventStore 同库 story.db，新加两张表：
    memory_items(rowid, agent_id, bank, content_json, keywords_json, importance, created_at, ttl)
    vec_mem(rowid, embedding float[D])    ← sqlite-vec 虚拟表

混合检索 _hybrid_retrieve：
  Step 1: 关键词倒排索引（keywords_json LIKE）
  Step 2: 向量 kNN（vec0 MATCH ... AND k=N）
  Step 3: 合并去重 + 按 score 排序
"""
from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import sqlite_vec

from ..kernel.embedding import Embedder


# =========================================================
# 16 个语义分库（蓝图 2.2 原文）
# =========================================================
MEMORY_BANKS: dict[str, str] = {
    # 会话层（用户偏好）
    "session_profile":     "会话配置",
    "language_profile":    "语言偏好",
    "user_preferences":    "用户审美偏好",
    # 设定层（创作基座）
    "task_briefs":         "任务摘要",
    "story_premise":       "故事前提",
    "style_guide":         "风格指南",
    # 章节层（大纲/分场）
    "chapter_briefs":      "章节摘要",
    "scene_cards":         "场景卡片",
    # 状态层（★ 核心 — L1 世界状态存储骨架）
    "entity_state":        "实体状态（角色位置/状态/持有物）",
    "relationship_state":  "关系状态（角色间关系）",
    "world_state":         "世界状态（环境/时间/天气）",
    # 运行时层（一致性/决策/修订）
    "continuity_facts":    "一致性事实（不可违反）",
    "tool_observations":   "工具观察（API/检索结果）",
    "decision_log":        "决策日志（为什么选这个 beat）",
    "revision_notes":      "修订记录",
    "working_set":         "当前工作集（最近活跃的记忆）",
}
assert len(MEMORY_BANKS) == 16, "蓝图硬约束：必须 16 个 bank"

# 按层级分组（用于按层级限流）
MEMORY_BANK_LAYERS: dict[str, list[str]] = {
    "session":  ["session_profile", "language_profile", "user_preferences"],
    "setting":  ["task_briefs", "story_premise", "style_guide"],
    "chapter":  ["chapter_briefs", "scene_cards"],
    "state":    ["entity_state", "relationship_state", "world_state"],
    "runtime":  ["continuity_facts", "tool_observations",
                 "decision_log", "revision_notes", "working_set"],
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_valid_bank(name: str) -> bool:
    return name in MEMORY_BANKS


# =========================================================
# MemoryItem — 单条记忆的数据模型
# =========================================================
@dataclass
class MemoryItem:
    """单条记忆 — 写入用 dataclass，读取时由 MemoryBank 装配"""
    id: int = 0                                   # rowid（0=未写入）
    agent_id: str = "_global"                     # 角色隔离键（_global=全员可见）
    bank: str = "working_set"                     # 必须是 MEMORY_BANKS 之一
    content: str = ""                             # 文本内容（用于 re-embed）
    metadata: dict = field(default_factory=dict)  # 任意附加结构化字段
    keywords: list[str] = field(default_factory=list)
    importance: int = 5                            # 1-10（generative_agents poignancy）
    created_at: str = field(default_factory=_now_iso)
    ttl: int = 0                                   # 秒；0=永不失效
    embedding: list[float] | None = None           # 仅读取时填充
    score: float = 0.0                             # 仅检索时填充（排序用）

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("embedding", None)
        return d


# =========================================================
# 中文关键词抽取（轻量级，无外部依赖）
# =========================================================
_CJK = re.compile(r"[\u4e00-\u9fa5]")
_STOP = {"的", "了", "是", "在", "和", "与", "也", "都", "就", "又", "不", "没",
         "一", "个", "这", "那", "你", "我", "他", "她", "它", "们", "着", "过"}


def extract_keywords(text: str) -> list[str]:
    """简单中文关键词抽取：2-3 字滑窗 + 英文单词 + 数字

    仅用于倒排索引召回。蓝图本意用 bge + 显式实体抽取，但本次按用户决策走
    GLM embedding-3 + sqlite-vec，关键词抽取只作 vector 兜底，简单即可。
    """
    if not text:
        return []
    out: list[str] = []
    # 英文/数字 token
    for m in re.finditer(r"[A-Za-z][A-Za-z0-9_-]{1,30}|[0-9]{1,8}", text):
        tok = m.group(0).lower()
        if len(tok) >= 2:
            out.append(tok)
    # 中文字符段
    for seg in re.findall(r"[\u4e00-\u9fa5]+", text):
        # 2-3 字滑窗
        for size in (2, 3):
            for i in range(len(seg) - size + 1):
                tok = seg[i : i + size]
                if tok not in _STOP:
                    out.append(tok)
    # 去重保序
    seen: set[str] = set()
    uniq = []
    for t in out:
        if t not in seen:
            seen.add(t)
            uniq.append(t)
    return uniq[:32]  # 上限 32，避免 metadata 过大


# =========================================================
# SemanticMemoryBanks — 16-bank 编排器
# =========================================================
class SemanticMemoryBanks:
    """16-bank 语义记忆编排 — 整个 character 子系统共用一个实例

    与 EventStore 同库（story.db），但用独立表 memory_items + vec_mem。
    sqlite-vec extension 在 _init_schema 时 load。
    """

    def __init__(
        self,
        db_path: str | Path,
        embedder: Embedder,
        *,
        dimensions: int | None = None,
        conn: sqlite3.Connection | None = None,
    ):
        self.db_path = str(db_path)
        self.embedder = embedder
        self.dimensions = dimensions or embedder.dimensions

        # 复用外部连接（测试用）或新开
        self._owns_conn = conn is None
        self._conn = conn or sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._lock = threading.RLock()
        self._init_schema()

    # ---------- schema ----------
    def _init_schema(self) -> None:
        c = self._conn
        # 先 load sqlite-vec 扩展
        try:
            c.enable_load_extension(True)
            sqlite_vec.load(c)
        except sqlite3.OperationalError as e:
            # 扩展已加载或环境不允许；落到无向量索引模式（keyword-only）
            if "already in use" not in str(e) and "not authorized" not in str(e):
                raise
        c.executescript(f"""
        CREATE TABLE IF NOT EXISTS memory_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_id TEXT NOT NULL DEFAULT '_global',
            bank TEXT NOT NULL,
            content TEXT NOT NULL,
            content_json TEXT NOT NULL,
            keywords_json TEXT NOT NULL DEFAULT '[]',
            importance INTEGER NOT NULL DEFAULT 5,
            created_at TEXT NOT NULL,
            ttl INTEGER NOT NULL DEFAULT 0,
            last_accessed_at TEXT,
            access_count INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_mem_agent_bank
            ON memory_items(agent_id, bank);
        CREATE INDEX IF NOT EXISTS idx_mem_bank ON memory_items(bank);
        CREATE INDEX IF NOT EXISTS idx_mem_importance
            ON memory_items(importance DESC);
        """)
        # 向量虚拟表（sqlite-vec）
        try:
            c.execute(
                f"CREATE VIRTUAL TABLE IF NOT EXISTS vec_mem "
                f"USING vec0(embedding float[{self.dimensions}])"
            )
        except sqlite3.OperationalError as e:
            if "already exists" not in str(e):
                raise
        c.commit()

    # ---------- 公开 API ----------
    @property
    def conn(self) -> sqlite3.Connection:
        return self._conn

    def bank_names(self) -> list[str]:
        return list(MEMORY_BANKS.keys())

    def count(self, agent_id: str | None = None, bank: str | None = None) -> int:
        sql = "SELECT COUNT(*) FROM memory_items WHERE 1=1"
        args: list = []
        if agent_id is not None:
            # _global 任何 agent 都可见
            sql += " AND (agent_id=? OR agent_id='_global')"
            args.append(agent_id)
        if bank is not None:
            sql += " AND bank=?"
            args.append(bank)
        row = self._conn.execute(sql, args).fetchone()
        return int(row[0]) if row else 0

    async def add(
        self,
        content: str,
        *,
        bank: str = "working_set",
        agent_id: str = "_global",
        metadata: dict | None = None,
        importance: int = 5,
        keywords: list[str] | None = None,
        ttl: int = 0,
        embedding: list[float] | None = None,
    ) -> MemoryItem:
        """添加一条记忆（自动 embed + 关键词抽取 + 写入 vec_mem）"""
        if not _is_valid_bank(bank):
            raise ValueError(f"unknown bank: {bank}")
        content = (content or "").strip()
        if not content:
            raise ValueError("content cannot be empty")

        if embedding is None:
            embedding = await self.embedder.embed(content)
        if keywords is None:
            keywords = extract_keywords(content)
        metadata = metadata or {}
        now = _now_iso()
        content_json = json.dumps(
            {"content": content, **metadata}, ensure_ascii=False
        )

        with self._lock:
            cur = self._conn.execute(
                """INSERT INTO memory_items
                   (agent_id, bank, content, content_json, keywords_json,
                    importance, created_at, ttl, last_accessed_at, access_count)
                   VALUES (?,?,?,?,?,?,?,?,?,0)""",
                (agent_id, bank, content, content_json,
                 json.dumps(keywords, ensure_ascii=False),
                 max(1, min(10, importance)), now, ttl, now),
            )
            item_id = int(cur.lastrowid)
            # 写向量（vec_mem rowid 与 memory_items.id 对齐）
            if embedding:
                try:
                    self._conn.execute(
                        "INSERT INTO vec_mem(rowid, embedding) VALUES (?,?)",
                        (item_id, sqlite_vec.serialize_float32(embedding)),
                    )
                except sqlite3.OperationalError as e:
                    # 向量表故障不应阻塞主流程（蓝图故障隔离原则）
                    # 但要把 id 留痕便于排查
                    self._conn.execute(
                        """UPDATE memory_items SET content_json = json_patch(
                            content_json, ?) WHERE id=?""",
                        (json.dumps({"_vec_error": str(e)[:200]}), item_id),
                    )
            self._conn.commit()

        return MemoryItem(
            id=item_id, agent_id=agent_id, bank=bank, content=content,
            metadata=metadata, keywords=keywords, importance=importance,
            created_at=now, ttl=ttl, embedding=embedding,
        )

    async def add_many(
        self, items: Iterable[MemoryItem],
    ) -> list[MemoryItem]:
        """批量写入（embed_batch 合并请求）"""
        items = list(items)
        if not items:
            return []
        # 收集需要 embed 的文本
        texts = [it.content for it in items]
        vecs = await self.embedder.embed_batch(texts)
        out: list[MemoryItem] = []
        for it, vec in zip(items, vecs):
            out.append(await self.add(
                it.content, bank=it.bank, agent_id=it.agent_id,
                metadata=it.metadata, importance=it.importance,
                keywords=it.keywords, ttl=it.ttl, embedding=vec,
            ))
        return out

    # ---------- 检索：关键词倒排 ----------
    def keyword_search(
        self, keywords: list[str], *,
        agent_id: str | None = None,
        bank: str | None = None,
        limit: int = 50,
    ) -> list[int]:
        """关键词倒排索引：返回 memory_items.id 列表"""
        if not keywords:
            return []
        # 简单 LIKE 匹配（每条 keywords_json 是 list，命中任一即召回）
        where = ["keywords_json LIKE ?" for _ in keywords]
        args: list = [f'%"{k}"%' for k in keywords]
        sql = "SELECT DISTINCT id FROM memory_items WHERE (" + \
            " OR ".join(where) + ")"
        if agent_id is not None:
            sql += " AND (agent_id=? OR agent_id='_global')"
            args.append(agent_id)
        if bank is not None:
            sql += " AND bank=?"
            args.append(bank)
        sql += " ORDER BY importance DESC, id DESC LIMIT ?"
        args.append(limit)
        rows = self._conn.execute(sql, args).fetchall()
        return [r[0] for r in rows]

    # ---------- 检索：向量 kNN ----------
    async def vector_search(
        self, query: str | list[float], *,
        agent_id: str | None = None,
        bank: str | None = None,
        k: int = 10,
    ) -> list[tuple[int, float]]:
        """向量近邻搜索（sqlite-vec kNN）。返回 [(id, distance), ...]

        distance 是 L2 距离（越小越相似）。本方法不返回 rowid 之外的列，
        留给 hybrid_retrieve 统一 SELECT。
        """
        if isinstance(query, str):
            qv = await self.embedder.embed(query)
        else:
            qv = query
        try:
            serialized = sqlite_vec.serialize_float32(qv)
        except (ValueError, struct_error()) as e:  # type: ignore[func-returns-value]
            raise RuntimeError(f"vector serialization failed: {e}") from e

        # vec0 MATCH 必须先做（不带 agent_id 过滤），再 JOIN 过滤
        sql = (
            "SELECT vm.rowid, vm.distance "
            "FROM vec_mem vm "
            "WHERE vm.embedding MATCH ? AND k=? "
            "ORDER BY vm.distance"
        )
        # 多取一倍再过滤，避免过滤后不足 k
        over_fetch = k * 4 if agent_id or bank else k
        try:
            rows = self._conn.execute(sql, (serialized, over_fetch)).fetchall()
        except sqlite3.OperationalError:
            return []

        out: list[tuple[int, float]] = []
        for rowid, dist in rows:
            mid = int(rowid)
            if agent_id is None and bank is None:
                out.append((mid, float(dist)))
                if len(out) >= k:
                    break
                continue
            # JOIN memory_items 过滤
            r = self._conn.execute(
                "SELECT agent_id, bank FROM memory_items WHERE id=?", (mid,)
            ).fetchone()
            if not r:
                continue
            a, b = r
            if agent_id is not None and a != agent_id and a != "_global":
                continue
            if bank is not None and b != bank:
                continue
            out.append((mid, float(dist)))
            if len(out) >= k:
                break
        return out

    # ---------- 混合检索（蓝图 _hybrid_retrieve） ----------
    async def hybrid_retrieve(
        self, query: str, *,
        agent_id: str | None = None,
        banks: list[str] | None = None,
        top_k: int = 20,
        keyword_k: int = 50,
        vector_k: int = 10,
    ) -> list[MemoryItem]:
        """蓝图 2.2 _hybrid_retrieve：关键词 + 向量 合并去重

        返回的 MemoryItem 列表已按 relevance（向量距离）倒序，但 score 字段
        未填三因子权重（那是 retrieval.py 的事）；这里只保证混合召回。
        """
        # Step 1: 关键词倒排
        keywords = extract_keywords(query)
        kw_ids: set[int] = set()
        if banks:
            for b in banks:
                kw_ids.update(self.keyword_search(
                    keywords, agent_id=agent_id, bank=b, limit=keyword_k))
        else:
            kw_ids.update(self.keyword_search(
                keywords, agent_id=agent_id, limit=keyword_k))

        # Step 2: 向量近邻
        vec_pairs = await self.vector_search(
            query, agent_id=agent_id, k=vector_k,
        )
        vec_ids = {mid for mid, _ in vec_pairs}
        dist_map = {mid: dist for mid, dist in vec_pairs}

        # Step 3: 合并去重
        all_ids = kw_ids | vec_ids
        if not all_ids:
            return []

        # 一次性 SELECT 拉所有列
        placeholders = ",".join("?" * len(all_ids))
        sql = (
            f"SELECT id, agent_id, bank, content, content_json, keywords_json, "
            f"importance, created_at, ttl FROM memory_items "
            f"WHERE id IN ({placeholders})"
        )
        rows = self._conn.execute(sql, tuple(all_ids)).fetchall()

        items: list[MemoryItem] = []
        for r in rows:
            (mid, a, b, content, cjson, kjson, imp, cat, ttl) = r
            if banks and b not in banks:
                continue
            # 过期 TTL 过滤
            if ttl and _is_expired(cat, ttl):
                continue
            try:
                meta = json.loads(cjson)
            except json.JSONDecodeError:
                meta = {"content": content}
            content_text = meta.pop("content", content)
            try:
                kws = json.loads(kjson)
            except json.JSONDecodeError:
                kws = []
            dist = dist_map.get(mid, 1.0)  # 未命中向量则给个中等距离
            # 用 distance 反向估算 relevance（0~1）
            relevance = max(0.0, 1.0 - dist)
            score = relevance + 0.1 * imp / 10.0  # 简单加权（retrieval.py 会重排）
            items.append(MemoryItem(
                id=mid, agent_id=a, bank=b, content=content_text,
                metadata=meta, keywords=kws, importance=imp,
                created_at=cat, ttl=ttl, score=score,
            ))

        # 排序：score 倒序
        items.sort(key=lambda x: x.score, reverse=True)
        return items[:top_k]

    # ---------- 工具方法 ----------
    def touch(self, item_id: int) -> None:
        """更新访问时间 + 计数（用于 LRU/BLL 衰减）"""
        self._conn.execute(
            """UPDATE memory_items
               SET last_accessed_at=?, access_count=access_count+1
               WHERE id=?""",
            (_now_iso(), item_id),
        )
        self._conn.commit()

    def latest(self, bank: str, agent_id: str | None = None) -> MemoryItem | None:
        """取 bank 最新一条（蓝图 get_relevant_context 用）"""
        sql = "SELECT id, agent_id, bank, content, content_json, keywords_json, importance, created_at, ttl FROM memory_items WHERE bank=?"
        args: list = [bank]
        if agent_id is not None:
            sql += " AND (agent_id=? OR agent_id='_global')"
            args.append(agent_id)
        sql += " ORDER BY id DESC LIMIT 1"
        row = self._conn.execute(sql, args).fetchone()
        return _row_to_item(row) if row else None

    def recent(self, bank: str, n: int = 3,
               agent_id: str | None = None) -> list[MemoryItem]:
        sql = "SELECT id, agent_id, bank, content, content_json, keywords_json, importance, created_at, ttl FROM memory_items WHERE bank=?"
        args: list = [bank]
        if agent_id is not None:
            sql += " AND (agent_id=? OR agent_id='_global')"
            args.append(agent_id)
        sql += " ORDER BY id DESC LIMIT ?"
        args.append(n)
        rows = self._conn.execute(sql, args).fetchall()
        return [_row_to_item(r) for r in reversed(rows)]

    def all_items(self, bank: str | None = None,
                  agent_id: str | None = None) -> list[MemoryItem]:
        sql = "SELECT id, agent_id, bank, content, content_json, keywords_json, importance, created_at, ttl FROM memory_items WHERE 1=1"
        args: list = []
        if bank:
            sql += " AND bank=?"
            args.append(bank)
        if agent_id:
            sql += " AND (agent_id=? OR agent_id='_global')"
            args.append(agent_id)
        sql += " ORDER BY id ASC"
        rows = self._conn.execute(sql, args).fetchall()
        return [_row_to_item(r) for r in rows]

    def close(self) -> None:
        if self._owns_conn:
            try:
                self._conn.close()
            except Exception:
                pass


# =========================================================
# 内部辅助
# =========================================================
def _row_to_item(row) -> MemoryItem:
    (mid, a, b, content, cjson, kjson, imp, cat, ttl) = row
    try:
        meta = json.loads(cjson)
    except json.JSONDecodeError:
        meta = {"content": content}
    content_text = meta.pop("content", content) if isinstance(meta, dict) else content
    try:
        kws = json.loads(kjson)
    except json.JSONDecodeError:
        kws = []
    return MemoryItem(
        id=mid, agent_id=a, bank=b, content=content_text,
        metadata=meta, keywords=kws, importance=imp,
        created_at=cat, ttl=ttl,
    )


def _is_expired(created_at: str, ttl: int) -> bool:
    if not ttl:
        return False
    try:
        ct = datetime.fromisoformat(created_at)
        if ct.tzinfo is None:
            ct = ct.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - ct).total_seconds()
        return age > ttl
    except (ValueError, TypeError):
        return False


def struct_error():
    """延迟 import struct.error，避免顶部依赖"""
    import struct
    return struct.error

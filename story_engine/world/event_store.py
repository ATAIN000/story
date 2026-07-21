"""EventStore — 事件溯源存储（Module 1.1 接口规范实现）

赌注4验证结论：SQLite WAL，append吞吐>150K/s，50K事件replay 0.2s，
snapshot+增量replay 23ms，CQRS读<1ms。demo 规模下绰绰有余。

语义：append-only 日志 + snapshot + 增量 replay + git 式回滚。
- 事件只追加、永不修改（审计性）
- 回滚 = 移动 head 指针 + 开启新 timeline（timeline_id 递增）
- 同一 tick 可能被多条时间线占用：状态重建取"每 tick 最新 timeline"的事件
- 被放弃时间线上的事件保留可见（"另一条时间线"），但不参与 projection
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from uuid import uuid4

from ..types import WorldEvent, WorldState, BranchID, SnapshotID


class EventStore:
    def __init__(self, db_path: str, initial_state_factory=None):
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._lock = threading.Lock()
        self._init_schema()
        self._timeline = int(self._meta_get("timeline", "0"))
        self._initial_state_factory = initial_state_factory or (lambda: WorldState())

    def _init_schema(self):
        self._conn.executescript("""
        CREATE TABLE IF NOT EXISTS events (
            event_id TEXT PRIMARY KEY,
            event_type TEXT, timestamp TEXT,
            world_tick INTEGER, branch_id TEXT,
            payload TEXT, schema_version INTEGER DEFAULT 1,
            timeline INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS snapshots (
            snapshot_id TEXT PRIMARY KEY,
            branch_id TEXT, world_tick INTEGER,
            state_json TEXT, created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS heads (
            branch_id TEXT PRIMARY KEY,
            head_tick INTEGER
        );
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY, value TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_events_tick ON events(branch_id, world_tick);
        """)
        self._conn.commit()

    def _meta_get(self, key: str, default: str) -> str:
        row = self._conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def _meta_set(self, key: str, value: str):
        self._conn.execute(
            "INSERT INTO meta VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value))
        self._conn.commit()

    @property
    def timeline(self) -> int:
        return self._timeline

    # ---------- 写侧（CQRS 写 = append 命令） ----------
    def append(self, event: WorldEvent) -> str:
        with self._lock:
            self._conn.execute(
                "INSERT INTO events VALUES (?,?,?,?,?,?,?,?)",
                (event.event_id, event.event_type, event.timestamp,
                 event.world_tick, event.branch_id,
                 json.dumps(event.payload, ensure_ascii=False),
                 event.schema_version, self._timeline),
            )
            self._conn.execute(
                "INSERT INTO heads VALUES (?,?) ON CONFLICT(branch_id) DO UPDATE SET head_tick=excluded.head_tick",
                (event.branch_id, event.world_tick),
            )
            self._conn.commit()
        return event.event_id

    def next_tick(self, branch_id: BranchID = "main") -> int:
        return self.head_tick(branch_id) + 1

    def head_tick(self, branch_id: BranchID = "main") -> int:
        row = self._conn.execute(
            "SELECT head_tick FROM heads WHERE branch_id=?", (branch_id,)
        ).fetchone()
        if row:
            return row[0]
        row = self._conn.execute(
            "SELECT COALESCE(MAX(world_tick), 0) FROM events WHERE branch_id=?", (branch_id,)
        ).fetchone()
        return row[0] or 0

    # ---------- 读侧（CQRS 读 = projection） ----------
    @staticmethod
    def _row_to_event(r) -> WorldEvent:
        return WorldEvent(r[0], r[1], r[2], r[3], r[4], json.loads(r[5]), r[6], timeline=r[7])

    def _active_events_upto(self, head: int, branch_id: BranchID = "main") -> list[WorldEvent]:
        """projection 用：每 tick 取最新 timeline 的事件（latest timeline wins）"""
        rows = self._conn.execute(
            """SELECT event_id, event_type, timestamp, world_tick, branch_id, payload, schema_version, timeline
               FROM events e
               WHERE branch_id=? AND world_tick<=? AND world_tick>=1
                 AND timeline = (SELECT MAX(timeline) FROM events
                                 WHERE branch_id=e.branch_id AND world_tick=e.world_tick)
               ORDER BY world_tick, rowid""",
            (branch_id, head),
        ).fetchall()
        return [self._row_to_event(r) for r in rows]

    def replay(self, branch_id: BranchID = "main",
               from_tick: int = 0, to_tick: int | None = None) -> list[WorldEvent]:
        head = to_tick if to_tick is not None else self.head_tick(branch_id)
        events = self._active_events_upto(head, branch_id)
        return [e for e in events if e.world_tick >= from_tick]

    def current_state(self, branch_id: BranchID = "main") -> WorldState:
        """从最近 snapshot + 增量 replay 重建 projection（到 head_tick 为止）"""
        head = self.head_tick(branch_id)
        row = self._conn.execute(
            "SELECT state_json, world_tick FROM snapshots "
            "WHERE branch_id=? AND world_tick<=? ORDER BY world_tick DESC LIMIT 1",
            (branch_id, head),
        ).fetchone()
        if row:
            state = WorldState.from_dict(json.loads(row[0]))
            from_tick = row[1] + 1
        else:
            state = self._initial_state_factory()
            from_tick = 1
        for event in self.replay(branch_id, from_tick=from_tick, to_tick=head):
            state.apply(event)
        state.tick = head if head else state.tick
        return state

    # ---------- snapshot / rollback ----------
    def snapshot(self, branch_id: BranchID = "main") -> SnapshotID:
        state = self.current_state(branch_id)
        snapshot_id = str(uuid4())[:8]
        self._conn.execute(
            "INSERT INTO snapshots VALUES (?,?,?,?,?)",
            (snapshot_id, branch_id, state.tick,
             json.dumps(state.to_dict(), ensure_ascii=False), datetime.now().isoformat()),
        )
        self._conn.commit()
        return snapshot_id

    def list_snapshots(self, branch_id: BranchID = "main") -> list[dict]:
        rows = self._conn.execute(
            "SELECT snapshot_id, world_tick, created_at FROM snapshots "
            "WHERE branch_id=? ORDER BY world_tick", (branch_id,)
        ).fetchall()
        return [{"snapshot_id": r[0], "world_tick": r[1], "created_at": r[2]} for r in rows]

    def rollback(self, to_tick: int, branch_id: BranchID = "main") -> None:
        """回滚 head 指针并开启新 timeline（事件本身永不删除）"""
        with self._lock:
            self._conn.execute(
                "INSERT INTO heads VALUES (?,?) ON CONFLICT(branch_id) DO UPDATE SET head_tick=excluded.head_tick",
                (branch_id, to_tick),
            )
            self._timeline += 1
            self._meta_set("timeline", str(self._timeline))
            self._conn.commit()

    def all_events(self, branch_id: BranchID = "main") -> list[dict]:
        """时间线用：返回全部事件（含各条已回滚时间线），带 active 标记"""
        head = self.head_tick(branch_id)
        rows = self._conn.execute(
            """SELECT event_id, event_type, timestamp, world_tick, branch_id, payload, schema_version, timeline
               FROM events WHERE branch_id=? ORDER BY world_tick, timeline, rowid""",
            (branch_id,),
        ).fetchall()
        max_tl: dict[int, int] = {}
        for r in rows:
            max_tl[r[3]] = max(max_tl.get(r[3], -1), r[7])
        out = []
        for r in rows:
            e = self._row_to_event(r)
            out.append({**e.to_dict(),
                        "active": e.world_tick <= head and e.timeline == max_tl[e.world_tick]})
        return out

    def clear_all(self) -> None:
        """原位清空全部事件/快照/head 并重置 timeline（项目重置用）。

        经本 store 自有连接清表，不删除 db 文件——Windows 下其他连接占用
        story.db 时 unlink 会静默失败造成「半重置」（旧事件全保留），
        原位 DELETE 不受文件锁影响。失败以 sqlite 异常显式上抛（响亮失败）。
        """
        with self._lock:
            self._conn.execute("DELETE FROM events")
            self._conn.execute("DELETE FROM snapshots")
            self._conn.execute("DELETE FROM heads")
            self._timeline = 0
            self._meta_set("timeline", "0")
            self._conn.commit()

    def close(self):
        self._conn.close()

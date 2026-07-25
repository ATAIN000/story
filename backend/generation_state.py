"""章节生成后台任务 + 状态查询（P23.3：切走再回来状态丢失修复）

背景：POST /api/project/generate 是单请求阻塞 ~10 分钟同步返回，前端切走写作台
后进度状态丢失。本模块提供模块级单例 GenerationState，配合 /generate/async
（启动后台任务）、/generation-status（轮询/切回查）、/generate/await（长轮询等完成）
三个端点，让前端切走再回来仍能看到"第 N 章生成中"。

设计要点：
- 单例跨请求存活；busy() = task 存在且未 done。
- 启动时捕获 engine 引用（engine_snapshot）和 project_name；生成中禁止切项目
  （_switch_to 会 close 旧 kernel，后台任务会炸），故捕获的引用在生成期间始终有效。
- stage 只粗分几档（actor_tick/realize/verifying/done），不接 LLM 中间事件——
  后端无真实细粒度进度，粗档够前端渲染。
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any


class GenerationState:
    """章节生成后台任务状态（模块级单例）。"""

    def __init__(self) -> None:
        self.task: asyncio.Task | None = None
        self.engine_snapshot: Any = None       # 启动时捕获的 engine 引用
        self.chapter_no: int | None = None
        self.started_at: str | None = None     # ISO 时间
        self.stage: str = ""                   # actor_tick/realize/verifying/done
        self.stage_detail: str = ""            # stage 的详细描述（如"角色决策 2/5"）
        self.result: dict | None = None        # 完成后的章节记录
        self.error: str | None = None          # 失败信息
        self.finished: bool = False
        self.project_name: str | None = None   # 锁定的项目名，防切换
        self.log_entries: list[dict] = []      # WS 推送的进度日志队列

    def busy(self) -> bool:
        """是否有进行中的生成任务。"""
        return self.task is not None and not self.task.done()

    def reset_status(self) -> None:
        """启动新任务前清空上一轮的状态字段（不动 task 本身）。"""
        self.chapter_no = None
        self.started_at = None
        self.stage = ""
        self.stage_detail = ""
        self.result = None
        self.error = None
        self.finished = False
        self.log_entries = []

    def clear(self) -> None:
        """彻底清空（测试/重置用）。"""
        self.task = None
        self.engine_snapshot = None
        self.reset_status()
        self.project_name = None

    def snapshot(self) -> dict:
        """对外暴露的状态快照（前端轮询/切回查用）。"""
        return {
            "busy": self.busy(),
            "chapter_no": self.chapter_no,
            "started_at": self.started_at,
            "stage": self.stage,
            "stage_detail": self.stage_detail,
            "finished": self.finished,
            "result": self.result,
            "error": self.error,
            "project_name": self.project_name,
            "log_entries": self.log_entries[-50:],  # 最近50条，防体积爆炸
        }


# 模块级单例
gen_state = GenerationState()


def set_stage(stage: str, detail: str = "") -> None:
    """后台任务内部更新阶段名 + 写日志队列（供 WS 推送）。"""
    gen_state.stage = stage
    gen_state.stage_detail = detail
    if detail:
        gen_state.log_entries.append({"stage": stage, "detail": detail})


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

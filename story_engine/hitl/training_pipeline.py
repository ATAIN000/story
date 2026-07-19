"""HITL 训练数据管道（Module 7.2 简化版，P5.9）

蓝图 7.2：作者介入 → 训练信号三条通路
  1. quality==high 的介入 → chunking 抽取「叙事技能」注册 story.skill
     （本期简化：技能 = JSON 描述占位，规则化提取、零 LLM，非真实训练/
     SOAR chunking；generator 侧是否消费该技能留后续任务）
  2. evaluation 介入 → 评估器偏好数据 training_data/preferences.jsonl
  3. textual 介入    → 文风对齐数据  training_data/style.jsonl

容错（P5.7 评审传导）：router 在 commit 后调用本管道且未包 try，
因此本管道任何异常都在内部吞掉并 log，绝不向 router 传播。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..kernel.registry import PluginManifest

logger = logging.getLogger(__name__)

# 数值质量分 ≥ 阈值视为 high（与 "high" 字符串两种判据都接受）
QUALITY_HIGH_THRESHOLD = 4


class TrainingPipeline:
    """作者介入 → 训练信号（简化版，all-fail-silent）"""

    def __init__(self, kernel, project_dir: str | Path):
        self.kernel = kernel
        self.project_dir = Path(project_dir)
        self.training_dir = self.project_dir / "training_data"

    def process_intervention(self, event) -> None:
        """入口：接受 WorldEvent（router 实际传入）或裸 payload dict。

        三条通路各自独立 try/except：一条失败不影响其余，且绝不外抛。
        """
        payload = getattr(event, "payload", None)
        if payload is None:
            payload = event if isinstance(event, dict) else {}
        event_id = getattr(event, "event_id", None) or payload.get("event_id") or ""

        try:
            if self._is_high_quality(payload):
                self._register_skill(payload, event_id)
        except Exception:
            logger.exception("TrainingPipeline: 技能注册失败（已吞掉，不向 router 传播）")
        try:
            if payload.get("type") == "evaluation" or "quality" in payload:
                self._record_preference(payload, event_id)
        except Exception:
            logger.exception("TrainingPipeline: 偏好数据落盘失败（已吞掉）")
        try:
            if payload.get("type") == "textual":
                self._record_style(payload)
        except Exception:
            logger.exception("TrainingPipeline: 文风数据落盘失败（已吞掉）")

    # ---------- 1. 技能抽取 + 注册 story.skill ----------
    @staticmethod
    def _is_high_quality(payload: dict) -> bool:
        q = payload.get("quality")
        if q == "high":
            return True
        return isinstance(q, (int, float)) and not isinstance(q, bool) \
            and q >= QUALITY_HIGH_THRESHOLD

    def _register_skill(self, payload: dict, event_id: str) -> None:
        skill = self._extract_skill(payload, event_id)
        # 注册路径（以代码实际为准）：ExtensionRegistry.register 对 story.skill
        # 无静态声明限制，支持运行时动态注册，直接复用 kernel.register_plugin。
        # 技能即 JSON 描述占位（params 承载），注释标注：非真实训练产物。
        self.kernel.register_plugin(PluginManifest(
            name=skill["name"],
            extension_point="story.skill",
            params={
                "pattern": skill["pattern"],
                "source_intervention": skill["source_intervention"],
                "created_at": skill["created_at"],
                "placeholder": True,  # 占位技能：非真实训练/SOAR chunking
            },
        ))

    @staticmethod
    def _extract_skill(payload: dict, event_id: str) -> dict:
        """规则化技能摘要（零 LLM）：{name, source_intervention, pattern, created_at}

        pattern = before→after 编辑模式摘要；evaluation 介入无 before/after 时
        退化为质量标注摘要（note 截断）。
        """
        before, after = payload.get("before"), payload.get("after")
        if before is not None or after is not None:
            pattern = f"{str(before)[:50]} → {str(after)[:50]}"
        else:
            note = str(payload.get("note") or "").strip()
            pattern = note[:100] or f"第{payload.get('chapter')}章高质量片段"
        return {
            "name": f"author_skill_{event_id or uuid4().hex[:8]}",
            "source_intervention": event_id,
            "pattern": pattern,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }

    # ---------- 2. 偏好数据（所有 evaluation 介入） ----------
    def _record_preference(self, payload: dict, event_id: str) -> None:
        self._append_jsonl("preferences.jsonl", {
            "chapter": payload.get("chapter"),
            "quality": payload.get("quality"),
            "note": payload.get("note"),
            "intervention_event": event_id,
            "ts": datetime.now().isoformat(timespec="seconds"),
        })

    # ---------- 3. 文风对齐数据（textual 介入） ----------
    def _record_style(self, payload: dict) -> None:
        self._append_jsonl("style.jsonl", {
            "chapter": payload.get("chapter"),
            "before": payload.get("before"),
            "after": payload.get("after"),
            "reason": payload.get("reason"),
            "ts": datetime.now().isoformat(timespec="seconds"),
        })

    # ---------- 落盘（失败不抛，由调用点 except 兜底 + log） ----------
    def _append_jsonl(self, filename: str, record: dict[str, Any]) -> None:
        self.training_dir.mkdir(parents=True, exist_ok=True)
        with open(self.training_dir / filename, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

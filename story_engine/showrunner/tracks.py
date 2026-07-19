"""轨道与 CFPG 伏笔池管理（Module 3 showrunner 子包）

- Track：叙事轨道（调度对象）
- ForeshadowPoolManager：CFPG 池的规则化管理 —— 到期查询、债务老化、
  容量上限与满池排队。全部规则化，不调 LLM。
"""
from __future__ import annotations

from dataclasses import dataclass

from ..types import ForeshadowTriple


@dataclass
class Track:
    id: str
    name: str
    arc_type: str          # Serialized / Anthology
    archetype: str
    progress: float = 0.0
    last_touched: int = 0  # chapter
    min_main_progress: float = 0.0   # 激活条件：主线进度达到该阈值才进入轮换


class ForeshadowPoolManager:
    """CFPG 伏笔池管理（决策3 步骤 3/9）

    - pool_max：池中未回收伏笔的容量上限（genre params `foreshadow_pool_max`，默认 8）
    - 债务老化：种下超过 2×payoff_window 仍未回收 → priority 升级并记 overdue: true
    """

    def __init__(self, pool_max: int = 8, payoff_window: int = 2):
        self.pool_max = pool_max
        self.payoff_window = payoff_window

    def _age(self, fs: ForeshadowTriple, episode: int) -> int:
        return episode - fs.planted_chapter

    def _is_overdue(self, fs: ForeshadowTriple, episode: int) -> bool:
        return self._age(fs, episode) > 2 * self.payoff_window

    def due_payoffs(self, pool: list[ForeshadowTriple], episode: int) -> list[dict]:
        """到期 payoff 列表（种满 payoff_window 章即到期），老化债升级并前置"""
        due = []
        for fs in pool:
            if fs.payed_off or self._age(fs, episode) < self.payoff_window:
                continue
            overdue = self._is_overdue(fs, episode)
            due.append({
                "foreshadow_id": fs.foreshadow_id, "content": fs.content,
                "payoff": fs.payoff, "trigger": fs.trigger_condition,
                "planted_chapter": fs.planted_chapter,
                "priority": "high" if overdue else "normal",
                "overdue": overdue,
            })
        # 老化债优先（priority 升级的体现），同级按种下顺序
        due.sort(key=lambda p: (not p["overdue"], p["planted_chapter"]))
        return due

    def split_plans(self, pool: list[ForeshadowTriple],
                    plans: list[dict]) -> tuple[list[dict], list[dict]]:
        """按池剩余容量切分新伏笔计划：放得下的种下，放不下的排队

        容量按决策时点的未回收数计算（本集到期的回收尚未发生，保守计）。
        """
        active = sum(1 for fs in pool if not fs.payed_off)
        free = max(0, self.pool_max - active)
        return plans[:free], plans[free:]

    def stats(self, pool: list[ForeshadowTriple], episode: int,
              queued: list[dict]) -> dict:
        """决策卡 pool_stats：{active 未回收数, overdue 老化债数, queued 排队数}"""
        unpaid = [fs for fs in pool if not fs.payed_off]
        return {
            "active": len(unpaid),
            "overdue": sum(1 for fs in unpaid if self._is_overdue(fs, episode)),
            "queued": len(queued),
        }

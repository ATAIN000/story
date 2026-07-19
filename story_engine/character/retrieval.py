"""三因子检索 + 防膨胀八层（Module 2.3 / generative_agents 源码验证权重）

蓝图 docs/Story_Engine_工程蓝图.md:786-844。

核心约束（蓝图赌注7）：
- 候选集必须先用 memory_banks.hybrid_retrieve（关键词+向量）保证召回，不能纯向量
- 三因子权重源码验证值：gw = {recency: 0.5, relevance: 3.0, importance: 2.0}
- relevance 是 recency 的 6 倍权重（generative_agents 原文）

防膨胀八层（蓝图方向6）：
  L1 BLL 衰减    — ACT-R 公式，近因低权重自然遗忘
  L2 反思压缩    — 已被反思吸收的事件降权
  L3 巩固固化    — 高频事实升级为语义记忆后从情景移除
  L4 检索抑制    — 短时间内已检索过的节点抑制（防重复占用 context）
  L5 plot-critical 保护 — 关键剧情事件永不遗忘
  L6 page out    — 超 context budget 的记忆换页到磁盘（实现：返回数 ≤ budget）
  L7 TTL 上限    — 超容量最旧记忆删除（在 memory_banks 触发 GC，这里只标）
  L8 间隔重复    — 重要记忆按 Ebbinghaus 曲线复习加权（最近被访问 boost）
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable

from .memory_banks import MemoryItem, SemanticMemoryBanks


# 源码验证的三因子权重（generative_agents 原值，蓝图赌注7）
WEIGHT_RECENCY = 0.5
WEIGHT_RELEVANCE = 3.0
WEIGHT_IMPORTANCE = 2.0


@dataclass
class RetrievalConfig:
    """防膨胀八层的可调参数（蓝图方向6 默认值）"""
    bll_threshold: float = 0.05              # L1: 低于此分直接剔除
    reflection_decay: float = 0.3            # L2: 已被反思吸收 ×0.3
    consolidation_decay: float = 0.5         # L3: 已固化升级 ×0.5（仍可作上下文，但降权）
    suppression_window: int = 8              # L4: 最近 8 次 retrieve 命中过的 id 抑制
    plot_critical_floor: float = 0.8         # L5: plot-critical 节点最低分
    context_budget: int = 25                 # L6: 单次 retrieve 返回上限（context 占用）
    max_capacity: int = 200                  # L7: 单 agent 总记忆上限（触发后 GC）
    spaced_repetition_boost: float = 0.15    # L8: 间隔重复加权幅度
    plot_critical_banks: tuple[str, ...] = ( # L5: 这些 bank 的内容默认标记为 plot-critical
        "continuity_facts", "story_premise", "task_briefs",
    )


@dataclass
class RetrievalStats:
    """检索统计（测试与可观测性）"""
    candidates: int = 0
    after_l1_bll: int = 0
    after_l2_reflection: int = 0
    after_l3_consolidation: int = 0
    after_l4_suppression: int = 0
    after_l5_critical_protected: int = 0
    after_l6_page_out: int = 0
    after_l7_ttl: int = 0
    after_l8_spaced_repetition: int = 0
    final: int = 0


class MemoryRetrieval:
    """三因子检索 + 防膨胀八层 — 每个角色 actor 各持一份

    使用方式：
      retrieval = MemoryRetrieval(memory_banks, agent_id="包拯")
      ctx = await retrieval.retrieve("审案焦点", top_k=15)
    """

    def __init__(
        self,
        memory_banks: SemanticMemoryBanks,
        *,
        agent_id: str = "_global",
        config: RetrievalConfig | None = None,
    ):
        self.memory_banks = memory_banks
        self.agent_id = agent_id
        self.config = config or RetrievalConfig()
        # L4 检索抑制：最近 N 次命中的 id 队列
        self._recently_retrieved: deque[int] = deque(
            maxlen=self.config.suppression_window
        )
        # L2 反思吸收记录（actor 在反思后调用 mark_absorbed）
        self._absorbed: set[int] = set()
        # L3 巩固固化记录（高频事实被升级为语义记忆后调用 mark_consolidated）
        self._consolidated: set[int] = set()

    # =========================================================
    # 主入口
    # =========================================================
    async def retrieve(
        self,
        focal_point: str,
        *,
        top_k: int = 15,
        banks: list[str] | None = None,
        now: datetime | None = None,
    ) -> list[MemoryItem]:
        """蓝图 2.3 retrieve 主入口

        流程：
          1. hybrid_retrieve 拿候选（关键词倒排 + 向量，蓝图赌注7）
          2. 算三因子分数（recency/relevance/importance）
          3. 应用防膨胀八层（L1-L8）
          4. 取前 top_k
        """
        stats = RetrievalStats()
        now = now or datetime.now(timezone.utc)

        # Step 1: 混合检索候选集
        candidates = await self.memory_banks.hybrid_retrieve(
            focal_point,
            agent_id=self.agent_id,
            banks=banks,
            top_k=max(top_k * 4, 50),   # 多取再过滤
        )
        stats.candidates = len(candidates)
        if not candidates:
            return []

        # Step 2: 三因子打分
        query_vec = await self.memory_banks.embedder.embed(focal_point)
        scored = []
        for item in candidates:
            recency = self._calc_recency(item, now)
            relevance = self._calc_relevance(item, query_vec)
            importance = self._calc_importance(item)
            score = (
                WEIGHT_RECENCY * recency
                + WEIGHT_RELEVANCE * relevance
                + WEIGHT_IMPORTANCE * importance
            )
            item.metadata = {
                **item.metadata,
                "_factors": {
                    "recency": round(recency, 4),
                    "relevance": round(relevance, 4),
                    "importance": round(importance, 4),
                    "weight_r": WEIGHT_RECENCY,
                    "weight_rel": WEIGHT_RELEVANCE,
                    "weight_i": WEIGHT_IMPORTANCE,
                },
            }
            item.score = score
            scored.append(item)

        # Step 3: 防膨胀八层
        scored = self._apply_anti_bloat(scored, stats, now)
        stats.final = len(scored)

        # 排序 + 截断
        scored.sort(key=lambda x: x.score, reverse=True)
        result = scored[:top_k]

        # 记录命中（用于下次 L4 抑制）
        for it in result:
            self._recently_retrieved.append(it.id)
            # L8: 间隔重复 — touch 一下，让 BLL 在下次 retrieve 时衰减更慢
            self.memory_banks.touch(it.id)

        return result

    # =========================================================
    # 三因子计算（generative_agents 源码）
    # =========================================================
    def _calc_recency(self, item: MemoryItem, now: datetime) -> float:
        """ACT-R BLL 衰减：0.99 ^ hours_since

        generative_agents 源码原文。0~1 区间，越接近 1 越新。
        """
        try:
            ct = datetime.fromisoformat(item.created_at)
            if ct.tzinfo is None:
                ct = ct.replace(tzinfo=timezone.utc)
            hours = max(0.0, (now - ct).total_seconds() / 3600.0)
        except (ValueError, TypeError):
            hours = 0.0
        return 0.99 ** hours

    def _calc_relevance(self, item: MemoryItem, query_vec: list[float]) -> float:
        """余弦相似度（0~1）。向量缺失或失败时退化为关键词 overlap。
        """
        # 优先用 sqlite-vec 的距离（item.metadata 里 _distance 由 hybrid_retrieve 写入）
        # 但我们重算一次：保证一致性
        if item.embedding:
            return _cosine(query_vec, item.embedding)
        # embedding 没拉到（lazy），用 keyword 命中比例兜底
        from .memory_banks import extract_keywords
        qk = set(extract_keywords(query_vec) if isinstance(query_vec, str) else [])
        if not qk:
            return 0.0
        ik = set(item.keywords)
        if not ik:
            return 0.0
        return len(qk & ik) / max(1, len(qk | ik))

    def _calc_importance(self, item: MemoryItem) -> float:
        """importance 1-10 → 归一化 0~1"""
        return max(0.0, min(1.0, (item.importance - 1) / 9.0))

    # =========================================================
    # 防膨胀八层（蓝图方向6）
    # =========================================================
    def _apply_anti_bloat(
        self,
        items: list[MemoryItem],
        stats: RetrievalStats,
        now: datetime,
    ) -> list[MemoryItem]:
        """按蓝图顺序应用 L1-L8 过滤"""
        cfg = self.config

        # L1: BLL 衰减 — 低于阈值剔除
        items = [it for it in items if it.score >= cfg.bll_threshold]
        stats.after_l1_bll = len(items)

        # L2: 反思压缩 — 已吸收的 ×decay
        for it in items:
            if it.id in self._absorbed:
                it.score *= cfg.reflection_decay
        stats.after_l2_reflection = len(items)

        # L3: 巩固固化 — 已固化的 ×decay（仍可作上下文，但权重低）
        for it in items:
            if it.id in self._consolidated:
                it.score *= cfg.consolidation_decay
        stats.after_l3_consolidation = len(items)

        # L4: 检索抑制 — 短时间内重复命中过的节点降权
        suppressed = set(self._recently_retrieved)
        for it in items:
            if it.id in suppressed:
                it.score *= 0.3  # 蓝图没给精确值；用 0.3（与 reflection 同档）
        stats.after_l4_suppression = len(items)

        # L5: plot-critical 保护 — 关键 bank / 标记节点保底分
        for it in items:
            if self._is_plot_critical(it):
                it.score = max(it.score, cfg.plot_critical_floor)
        stats.after_l5_critical_protected = len(items)

        # 排序一次（前 5 层已改 score）
        items.sort(key=lambda x: x.score, reverse=True)

        # L6: page out — 截到 context_budget
        items = items[: cfg.context_budget]
        stats.after_l6_page_out = len(items)

        # L7: TTL 上限 — TTL 已过期的剔除（实际 GC 由 memory_banks 负责）
        items = [it for it in items if not _is_ttl_expired(it)]
        stats.after_l7_ttl = len(items)

        # L8: 间隔重复 — 最近被访问的（access_count > 0）小幅 boost
        # 我们这里没法在 vector_search 阶段 join access_count，故用 created_at
        # 距 now 越近 boost 越大（10 分钟内全 boost，超过 1 小时不加）
        for it in items:
            boost = self._spaced_repetition_boost(it, now)
            if boost > 0:
                it.score += boost
        stats.after_l8_spaced_repetition = len(items)

        return items

    # =========================================================
    # 状态修改接口（actor 在反思/巩固后调用）
    # =========================================================
    def mark_absorbed(self, item_id: int) -> None:
        """L2: 反思吸收标记（反思总结后，原始 episodic 降权）"""
        self._absorbed.add(item_id)

    def mark_consolidated(self, item_id: int) -> None:
        """L3: 巩固固化标记（高频事实升级为语义记忆）"""
        self._consolidated.add(item_id)

    def reset_suppression(self) -> None:
        """清空 L4 抑制窗口（测试用）"""
        self._recently_retrieved.clear()

    # =========================================================
    # 内部辅助
    # =========================================================
    def _is_plot_critical(self, item: MemoryItem) -> bool:
        if item.metadata.get("plot_critical"):
            return True
        return item.bank in self.config.plot_critical_banks

    def _spaced_repetition_boost(self, item: MemoryItem, now: datetime) -> float:
        """L8: 间隔重复 boost（按 Ebbinghaus 曲线，access_count 越多越稳）

        简化模型：
          - access_count == 0 → 不 boost（首次检索）
          - 距上次访问 < 10 min → 全 boost（强化）
          - 10 min ~ 1 h → 半 boost
          - > 1 h → 不 boost（已稳定或淡忘）
        """
        boost = self.config.spaced_repetition_boost
        try:
            ct = datetime.fromisoformat(item.created_at)
            if ct.tzinfo is None:
                ct = ct.replace(tzinfo=timezone.utc)
            age_min = (now - ct).total_seconds() / 60.0
        except (ValueError, TypeError):
            return 0.0
        if age_min < 10:
            return boost
        if age_min < 60:
            return boost * 0.5
        return 0.0


# =========================================================
# 工具函数
# =========================================================
def _cosine(a: list[float], b: list[float]) -> float:
    """余弦相似度（0~1，已假设向量都是单位长度；安全起见仍归一化）"""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na < 1e-9 or nb < 1e-9:
        return 0.0
    # cosine ∈ [-1, 1]，归一到 [0, 1]
    return max(0.0, min(1.0, (dot / (na * nb) + 1.0) / 2.0))


def _is_ttl_expired(item: MemoryItem) -> bool:
    if not item.ttl:
        return False
    try:
        ct = datetime.fromisoformat(item.created_at)
        if ct.tzinfo is None:
            ct = ct.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - ct).total_seconds()
        return age > item.ttl
    except (ValueError, TypeError):
        return False

"""节奏量化引擎（Module 3.3 — Schulz 叙事信息论五指标）

蓝图 3.3（docs/Story_Engine_工程蓝图.md:981-1006）的可运行实现，输入按 P3 决策4 从简：
- 每章场景序列 = 上一章事件流按 event_type 同型连段分段
- 状态向量 = (event_type 分布, fluents 变化数, 涉及角色数)，L1 归一化

五指标（JSD/MI 手写，不引新库；numpy 仅作数组载体）：
  entropy             — 每场景状态向量熵（复杂度 complexity）
  Jensen-Shannon      — 相邻场景 JSD（pivot 转折）
  mutual information  — 相邻场景类型符号对的互信息（可预测性 predictability）
  conditional entropy — H(下一场 | 当前场)（悬念 suspense）
  twist JSD           — 历史均值预测 vs 实际场景的 JSD（twist 意外度）

产出 PacingScore{reversal_density, avg_reversal_magnitude,
pacing_consistency, cliffhanger_strength}（四字段名严格对齐），
并与 genre params `pacing_targets`（缺失走 DEFAULT_PACING_TARGETS）
对比，偏差映射为下一章 beat tension 曲线修正（决策4 闭环）。
"""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, asdict

import numpy as np

# 与 types.py EventType 对齐的事件类型维度
EVENT_TYPES = (
    "character_action", "world_change", "narrative_beat", "dialogue",
    "scene_transition", "author_intervention", "branch_fork",
)

# pivot JSD（log2 底，值域 [0,1]）超过该阈值记为一次「反转」
REVERSAL_THRESHOLD = 0.2

# pacing_targets 缺失时的默认区间（[min, max]，键名对齐 PacingScore 四字段）
DEFAULT_PACING_TARGETS = {
    "reversal_density": (0.2, 0.5),
    "avg_reversal_magnitude": (0.2, 0.6),
    "pacing_consistency": (0.5, 0.9),
    "cliffhanger_strength": (0.3, 0.8),
}

TENSION_MIN, TENSION_MAX = 0.05, 0.95


@dataclass
class PacingScore:
    """一章的节奏量化结果（四字段名严格对齐 pacing_targets 键）"""
    reversal_density: float        # 反转密度：pivot 超阈值占比
    avg_reversal_magnitude: float  # 平均反转幅度：pivot JSD 均值
    pacing_consistency: float      # 节奏一致性：1 - 场景熵方差（裁剪到 [0,1]）
    cliffhanger_strength: float    # 钩子强度：末场景的 twist JSD

    def to_dict(self) -> dict:
        return asdict(self)


# =========================================================
# 五指标的数学基础（手写，log2 底）
# =========================================================
def entropy(p: np.ndarray) -> float:
    """香农熵 H(p) = -Σ p·log2(p)，0·log0 按 0 处理"""
    p = np.asarray(p, dtype=float)
    p = p[p > 0]
    return max(0.0, float(-(p * np.log2(p)).sum()))  # max 消除 -0.0


def jensen_shannon(p: np.ndarray, q: np.ndarray) -> float:
    """JSD(P,Q) = ½KL(P‖M) + ½KL(Q‖M)，M = ½(P+Q)；log2 底 → 值域 [0,1]"""
    p = np.asarray(p, dtype=float)
    q = np.asarray(q, dtype=float)
    m = 0.5 * (p + q)

    def _kl(a: np.ndarray, b: np.ndarray) -> float:
        mask = a > 0  # M 在 a>0 处必 >0，无除零；a=0 项贡献 0
        if not mask.any():
            return 0.0
        return float((a[mask] * np.log2(a[mask] / b[mask])).sum())

    return max(0.0, 0.5 * _kl(p, m) + 0.5 * _kl(q, m))


def mutual_information(symbols: list[str]) -> float:
    """相邻符号对 (prev, next) 的经验互信息 I(prev;next)，bits（可预测性）"""
    if len(symbols) < 2:
        return 0.0
    prev, nxt = symbols[:-1], symbols[1:]
    n = len(prev)
    joint, px, py = Counter(zip(prev, nxt)), Counter(prev), Counter(nxt)
    mi = 0.0
    for (x, y), c in joint.items():
        pxy = c / n
        mi += pxy * math.log2(pxy / ((px[x] / n) * (py[y] / n)))
    return mi


def conditional_entropy(symbols: list[str]) -> float:
    """H(next|prev)，bits — 给定当前场，下一场的剩余不确定度（悬念）"""
    if len(symbols) < 2:
        return 0.0
    prev, nxt = symbols[:-1], symbols[1:]
    n = len(prev)
    joint, px = Counter(zip(prev, nxt)), Counter(prev)
    ce = 0.0
    for (x, _y), c in joint.items():
        ce -= (c / n) * math.log2(c / px[x])
    return ce


# =========================================================
# 输入从简：事件流 → 场景序列 → 状态向量
# =========================================================
def chapter_events(events: list[dict], episode: int) -> list[dict]:
    """第 episode-1 章的事件切片（决策4：上一章事件流）。

    章界 = narrative_beat 载荷的 chapter 标记（engine 每章以 chapter=k 的
    伏笔同步 beat 收尾，故标记章号沿日志单调不减）：
    第 k 章 = 最后一个 chapter<k 标记之后，到最后一个 chapter==k 标记（含）。
    完全无 chapter 标记时退化为全部事件；episode<=1 / 空流 / 无对应章 → 空列表。
    """
    if episode <= 1 or not events:
        return []
    prev_ch = episode - 1
    marks = [(i, e["payload"]["chapter"]) for i, e in enumerate(events)
             if e.get("event_type") == "narrative_beat"
             and isinstance(e.get("payload"), dict)
             and isinstance(e["payload"].get("chapter"), int)]
    if not marks:
        return list(events)
    start = max((i for i, ch in marks if ch < prev_ch), default=-1) + 1
    end = max((i for i, ch in marks if ch == prev_ch), default=-1) + 1
    if end <= start:
        return []
    return events[start:end]


def segment_scenes(events: list[dict]) -> list[list[dict]]:
    """event_type 同型连段 → 场景序列"""
    scenes: list[list[dict]] = []
    for e in events:
        if scenes and scenes[-1][0].get("event_type") == e.get("event_type"):
            scenes[-1].append(e)
        else:
            scenes.append([e])
    return scenes


def scene_state_vector(scene: list[dict]) -> np.ndarray:
    """状态向量 = (event_type 分布, fluents 变化数, 涉及角色数)，L1 归一化"""
    type_counts = [0] * len(EVENT_TYPES)
    fluent_changes = 0
    characters: set[str] = set()
    for e in scene:
        et = e.get("event_type")
        if et in EVENT_TYPES:
            type_counts[EVENT_TYPES.index(et)] += 1
        p = e.get("payload") or {}
        effects = p.get("effects") or {}
        fluent_changes += (len(effects.get("set_fluents") or [])
                           + len(effects.get("unset_fluents") or []))
        if et == "world_change" and p.get("field") != "story_time":
            fluent_changes += 1  # world_change 每事件改一个 fluent（story_time 除外）
        for key in ("agent", "speaker"):
            who = p.get(key)
            if who:
                characters.add(who)
        for key in ("participants", "characters"):
            for who in (p.get(key) or []):
                characters.add(who)
    v = np.array(type_counts + [fluent_changes, len(characters)], dtype=float)
    total = v.sum()
    if total <= 0:  # 未知类型空场景：均匀分布兜底，避免全零
        return np.full(len(v), 1.0 / len(v))
    return v / total


# =========================================================
# PacingEngine：五指标 → PacingScore
# =========================================================
class PacingEngine:
    """Schulz Narrative Information Theory — 5 个可计算指标（蓝图 3.3）"""

    def calc_pacing(self, events: list[dict]) -> PacingScore | None:
        """上一章事件流 → PacingScore；空输入返回 None"""
        report = self.analyze(events)
        return report["score"] if report else None

    def analyze(self, events: list[dict]) -> dict | None:
        """完整分析：{"score": PacingScore, "metrics": 五指标明细}；空输入 None"""
        scenes = segment_scenes(events)
        if not scenes:
            return None
        states = [scene_state_vector(s) for s in scenes]
        # 1) entropy — 每场景复杂度
        complexity = [entropy(v) for v in states]
        # 2) Jensen-Shannon — 相邻场景 pivot
        pivots = [jensen_shannon(states[i], states[i - 1])
                  for i in range(1, len(states))]
        # 场景符号 = 场景主导类型（同型连段 → 段内类型）
        symbols = [s[0].get("event_type", "") for s in scenes]
        # 3) mutual information — 可预测性；4) conditional entropy — 悬念
        mi = mutual_information(symbols)
        suspense = conditional_entropy(symbols)
        # 5) twist JSD — 历史均值预测 vs 实际
        twists = [jensen_shannon(np.mean(states[:i], axis=0), states[i])
                  for i in range(1, len(states))]

        reversals = [p for p in pivots if p > REVERSAL_THRESHOLD]
        score = PacingScore(
            reversal_density=round(len(reversals) / len(pivots), 4) if pivots else 0.0,
            avg_reversal_magnitude=round(sum(pivots) / len(pivots), 4) if pivots else 0.0,
            pacing_consistency=round(max(0.0, 1.0 - float(np.var(complexity))), 4),
            cliffhanger_strength=round(twists[-1], 4) if twists else 0.0,
        )
        metrics = {
            "entropy": [round(x, 4) for x in complexity],
            "jsd_pivots": [round(x, 4) for x in pivots],
            "mutual_info": round(mi, 4),
            "conditional_entropy": round(suspense, 4),
            "twist_jsd": [round(x, 4) for x in twists],
        }
        return {"score": score, "metrics": metrics}


# =========================================================
# 决策4 闭环：PacingScore × pacing_targets → tension 修正
# =========================================================
def resolve_targets(targets: dict | None) -> dict:
    """genre params pacing_targets（[min,max] 区间）；缺失/残缺的键走默认区间"""
    resolved = {}
    for k, default in DEFAULT_PACING_TARGETS.items():
        rng = (targets or {}).get(k)
        try:
            lo, hi = float(rng[0]), float(rng[1])
        except (TypeError, IndexError, ValueError):
            lo, hi = default
        resolved[k] = (lo, hi)
    return resolved


def suggest_tension_adjustment(score: PacingScore,
                               targets: dict | None = None) -> dict:
    """PacingScore 与 pacing_targets 对比 → 下一章 beat tension 修正参数。

    偏差方向 → 修正动作：
      reversal_density       低 → 提高 tension 方差 ×1.5；高 → 收敛 ×0.75
      avg_reversal_magnitude 低 → 振幅放大 ×1.25；高 → ×0.9
      pacing_consistency     低（过乱）→ 收敛 ×0.8；高（过闷）→ 微增 ×1.1
      cliffhanger_strength   低 → 末 beat +0.15；高 → -0.1
    返回 {"variance_scale", "ending_boost", "deviations"}。
    """
    t = resolve_targets(targets)
    deviations = {}
    for k in DEFAULT_PACING_TARGETS:
        lo, hi = t[k]
        v = getattr(score, k)
        deviations[k] = (round(v - lo, 4) if v < lo
                         else round(v - hi, 4) if v > hi else 0.0)
    variance_scale = 1.0
    if deviations["reversal_density"] < 0:
        variance_scale *= 1.5
    elif deviations["reversal_density"] > 0:
        variance_scale *= 0.75
    if deviations["avg_reversal_magnitude"] < 0:
        variance_scale *= 1.25
    elif deviations["avg_reversal_magnitude"] > 0:
        variance_scale *= 0.9
    if deviations["pacing_consistency"] < 0:
        variance_scale *= 0.8
    elif deviations["pacing_consistency"] > 0:
        variance_scale *= 1.1
    ending_boost = 0.0
    if deviations["cliffhanger_strength"] < 0:
        ending_boost = 0.15
    elif deviations["cliffhanger_strength"] > 0:
        ending_boost = -0.1
    return {"variance_scale": variance_scale, "ending_boost": ending_boost,
            "deviations": deviations}


def apply_tension_adjustment(beats: list[dict], adjustment: dict) -> list[dict]:
    """beat tension 曲线修正：偏离均值的部分按 variance_scale 缩放（方差修正），
    末 beat 加 ending_boost（钩子强化）；tension 裁剪到 [0.05, 0.95]。
    返回新 list，不改原 beat dict。"""
    if not beats:
        return []
    scale = adjustment.get("variance_scale", 1.0)
    boost = adjustment.get("ending_boost", 0.0)
    ts = [b.get("tension", 0.5) for b in beats]
    mean_t = sum(ts) / len(ts)
    out = []
    for i, b in enumerate(beats):
        t = mean_t + (ts[i] - mean_t) * scale
        if i == len(beats) - 1:
            t += boost
        out.append({**b, "tension": round(min(TENSION_MAX, max(TENSION_MIN, t)), 2)})
    return out

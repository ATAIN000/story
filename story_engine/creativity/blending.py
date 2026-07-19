"""ConceptualBlending — 概念整合引擎简化版（Module 4.3，Phase 3 决策7）

蓝图 4.3 的最小可运行实现：
1. `generate_creative_seed(domain_a, domain_b)`：**1 次 LLM 调用**完成
   抽取两域结构 + 强制组合 + 阐述（单 prompt 三段指令），产出 emergent 文本。
2. `novelty`：emergent 与最近 3 章正文的余弦距离均值（复用 Phase 2 Embedder）；
   dummy embed 模式退化为字符二元组 Jaccard 距离（不触网、不加载模型）。
   （计划原文「最大余弦距离的均值」：emergent 为单文本，逐章取余弦距离后求均值。）
3. `surprise`：简化 = `1 - emergent 与当前 foreshadow_templates/beats 的最大相似度`
   —— 蓝图 -log P(该创意出现于既有套路) 的定性近似：与既有伏笔模板/beat 越不相似，
   读者越意外。非概率估计，仅作相对比较，注释说明。

成本门控（STORY_ENGINE_BLEND_EVERY）在调用方 Showrunner 实现；本类自身：
- LLM 异常 / 空响应 → 返回 None（调用方兜底为不附 seed，不阻塞决策卡）
- blend_domains 缺失或不足 2 个 → 返回 None（graceful 跳过，不崩）
- novelty / surprise 均 clamp 到 [0, 1]

不引入第三方库；同步/异步边界：本类方法是 async（LLM/embedding 均为异步设施）。
"""
from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass(frozen=True)
class CreativeSeed:
    """跨域融合创意种子 — 决策卡「可选灵感」

    domains: 参与融合的两个领域（来自 genre params blend_domains）
    emergent: LLM 单次调用产出的融合阐述文本
    novelty: 与最近 3 章正文的平均距离，∈ [0,1]，越大越新颖
    surprise: 1 - 与既有 foreshadow_templates/beats 的最大相似度，∈ [0,1]
    """
    domains: tuple[str, str]
    emergent: str
    novelty: float
    surprise: float


# ---------- 文本相似度（dummy 退化的 Jaccard；非 dummy 走 embedding 余弦） ----------

def _char_bigrams(text: str) -> set[str]:
    """字符二元组集合 — 中文无需分词的 Jaccard 词元"""
    chars = [c for c in text if not c.isspace()]
    if len(chars) < 2:
        return set(chars)
    return {"".join(chars[i:i + 2]) for i in range(len(chars) - 1)}


def jaccard_similarity(a: str, b: str) -> float:
    """字符二元组 Jaccard 相似度 ∈ [0,1]；两侧皆空视为完全相同（1.0）"""
    ta, tb = _char_bigrams(a), _char_bigrams(b)
    if not ta and not tb:
        return 1.0
    union = ta | tb
    if not union:
        return 1.0
    return len(ta & tb) / len(union)


def _cosine(va: list[float], vb: list[float]) -> float:
    dot = sum(x * y for x, y in zip(va, vb))
    na = sum(x * x for x in va) ** 0.5
    nb = sum(y * y for y in vb) ** 0.5
    if na < 1e-9 or nb < 1e-9:
        return 0.0
    return dot / (na * nb)


def _clamp01(v: float) -> float:
    return max(0.0, min(1.0, v))


class ConceptualBlending:
    """概念整合（决策7 简化版）：1 次 LLM + embedding/Jaccard novelty + 简化 surprise

    llm_call: 复用 kernel LLM 设施（Kernel.llm_call / LLMPool.call 签名：
              async (prompt, *, purpose=..., temperature=..., max_tokens=...) -> 带 .text）
    embedder: Phase 2 Embedder；None 或 is_dummy 时相似度退化为 Jaccard
    blend_domains: genre params 的领域池（romance 例：戏曲/医药/园林），随机取两域
    """

    def __init__(self, llm_call, embedder=None,
                 blend_domains: list[str] | None = None,
                 rng: random.Random | None = None):
        self._llm_call = llm_call
        self._embedder = embedder
        self._domains = list(blend_domains or [])
        self._rng = rng or random.Random()

    async def generate_creative_seed(
        self, domain_a: str | None = None, domain_b: str | None = None, *,
        recent_texts: list[str] | tuple = (),
        reference_texts: list[str] | tuple = (),
    ) -> CreativeSeed | None:
        """1 次 LLM 调用产出 CreativeSeed；任何失败/缺域 → None（不阻塞调用方）

        recent_texts: 最近若干章正文（取最后 3 条）用于 novelty
        reference_texts: 当前 foreshadow_templates/beats 文本，用于 surprise
        """
        if domain_a is None or domain_b is None:
            if len(self._domains) < 2:
                return None  # blend_domains 缺失/不足（如 wuxia 未配）— graceful 跳过
            domain_a, domain_b = self._rng.sample(self._domains, 2)
        if domain_a == domain_b:
            return None

        # ---- 单 prompt 三段指令：抽取结构 → 强制组合 → 阐述 emergent ----
        prompt = (
            "你是小说创意引擎，做一次概念整合（Conceptual Blending）。\n"
            f"领域甲：{domain_a}\n领域乙：{domain_b}\n"
            "第一步，分别抽取两个领域的核心结构（角色、规则、物象、流程）；\n"
            "第二步，把领域甲的结构强制映射进领域乙的框架，"
            "融合成一个可用于小说场景/机关/物件的创意；\n"
            "第三步，用 3-5 句话阐述这个融合创意在当前故事里的用法。\n"
            "只输出第三步的阐述文本，不要分析过程，不要分点，不要超过 200 字。")
        try:
            resp = await self._llm_call(
                prompt, purpose="creative_blend", temperature=0.9, max_tokens=512)
            emergent = (getattr(resp, "text", "") or "").strip()
        except Exception:
            return None  # LLM 异常/超时 → 不附 seed（决策7 兜底约束）
        if not emergent:
            return None  # 空响应（如 mock 模式未知 purpose）→ 不附 seed

        recent = [t for t in recent_texts if t][-3:]
        refs = [t for t in reference_texts if t]
        novelty = await self._novelty(emergent, recent)
        surprise = await self._surprise(emergent, refs)
        return CreativeSeed(domains=(domain_a, domain_b), emergent=emergent,
                            novelty=novelty, surprise=surprise)

    # ---------- novelty：与最近 3 章的平均距离 ----------
    async def _novelty(self, emergent: str, recent: list[str]) -> float:
        if not recent:
            return 1.0  # 无历史可比对（首章）→ 视为全新
        sims = await self._similarities(emergent, recent)
        # 余弦距离 = 1 - sim（sim ∈ [-1,1] → 距离 ∈ [0,2]，clamp 收进 [0,1]）；
        # Jaccard 同理 sim ∈ [0,1] → 距离 ∈ [0,1]
        return _clamp01(sum(1.0 - s for s in sims) / len(sims))

    # ---------- surprise：1 - 与既有套路的最大相似度 ----------
    async def _surprise(self, emergent: str, refs: list[str]) -> float:
        # -log P 的定性近似：与既有伏笔模板/beat 越不相似越意外；无参照 → 完全意外
        if not refs:
            return 1.0
        sims = await self._similarities(emergent, refs)
        return _clamp01(1.0 - max(sims))

    # ---------- 相似度后端：local embedding 余弦 / dummy 退化 Jaccard ----------
    async def _similarities(self, emergent: str, texts: list[str]) -> list[float]:
        if self._embedder is None or self._embedder.is_dummy:
            return [jaccard_similarity(emergent, t) for t in texts]
        vecs = await self._embedder.embed_batch([emergent, *texts])
        return [_cosine(vecs[0], v) for v in vecs[1:]]

"""CriticParliament — Critic 议会（蓝图 6.2，P4 决策2/3：赌注5 串联模式）

蓝图 1470-1561 的最小可运行实现（独立层，P4.5 才接线 engine）：

串联两阶段（赌注5 验证：多 critic 召回 100% vs 单 judge 80%，但假阳性 4 倍；
先单 judge 粗筛标记存疑段，再多 critic 精审，兼得高召回与低假阳性/成本）：
- Stage 1 `_single_judge_screen`：1 次 LLM 调用扫全章，输出存疑段列表
  （段落引文 quote + 存疑理由 reason）；空 → 直接返回 []（零 critic 成本）
- Stage 2：对存疑段按 `genre_params.active_critics` 维度并行 asyncio.gather，
  每维 1 次 LLM（temperature=0.3，critique 低温更确定）

两道后处理（全部按蓝图）：
- **quote 过滤** `_has_valid_evidence`：evidence 必须非空且每条能在章节原文中
  子串命中（防 CriticGPT 幻觉的可执行版），无 quote 的 critique 丢弃
- **共振加权** `_resonance_weighting`：多 critic 命中同一存疑段 →
  confidence="high"（Critique 附加字段，P4.1 已建）；单 critic 命中保持 "low"

铁律与兜底：
- 内部从不出数字分数（蓝图 1426-1428）：critic 只输出 verdict + quote + fix_directive
- LLM 返回空/不可解析（mock 模式 mock_script 对未知 purpose 返回 ""）→
  视为无存疑/无 critique → 不阻塞，这是 mock 路径零成本、现有测试零变化的关键
- 所有 LLM 解析失败路径兜底不抛异常（_critic 返回 None 即丢弃该 critique）
- 未知维度（插件写错名）跳过并记 warning，不崩（决策2）

LLM 设施：复用 P3.7 blending 已验证的 callable 注入模式
（async (prompt, *, purpose=, temperature=, max_tokens=) -> 带 .text 的对象）。
构造时可传 kernel（取其 llm_call，即 LLMPool.call 的薄包装）或直接传 llm_call；
两者皆无 → 一切调用返回 ""→ 不阻塞。测试注入 fake callable，不触网、不建 Kernel。
"""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass

import yaml

from .types_eval import Critique

logger = logging.getLogger(__name__)

# ---------- 维度库（决策2：蓝图 7 维 + emotion_arc repo 扩展第 8 维） ----------

# 蓝图 ALL_DIMENSIONS 7 维（逐字）
ALL_DIMENSIONS = [
    "plot_coherence",        # 情节连贯: 对照大纲+时间线
    "character_motivation",  # 角色动机: 对照角色卡
    "setting_consistency",   # 设定一致性: 对照 L1 世界状态(非原文!)
    "dialogue_authenticity",  # 对话真实度
    "sensory_detail",        # 感官细节
    "cliche_detection",      # 套路检测: 对照陈词滥调库
    "theme_depth",           # 主题深度
]
# repo 扩展：romance.yaml/wuxia.yaml 的 active_critics 含 emotion_arc（插件 yaml 不动）
EXTRA_DIMENSIONS = ["emotion_arc"]
KNOWN_DIMENSIONS = frozenset(ALL_DIMENSIONS) | frozenset(EXTRA_DIMENSIONS)

# 每维 prompt 用说明 + 正反例（各一行，critic prompt 的针对性指令）
DIMENSION_GUIDE: dict[str, tuple[str, str, str]] = {
    "plot_coherence": (
        "情节连贯：事件因果链是否成立，与前文/时间线是否矛盾",
        "正例：前章埋下的玉佩失窃，本章给出的线索与之呼应",
        "反例：角色凭空知道了前文从未交代的信息"),
    "character_motivation": (
        "角色动机：角色行为是否有符合其身份与目标的动机支撑",
        "正例：刘伯隐瞒行踪，因为他要掩盖赌债",
        "反例：角色毫无理由地做出违背自身目标的行为"),
    "setting_consistency": (
        "设定一致性：描写是否与世界状态/时代设定冲突（对照设定，非仅原文）",
        "正例：北宋公堂用「签筒」「惊堂木」等符合时代的器物",
        "反例：北宋背景出现明清才有的称谓或器物"),
    "dialogue_authenticity": (
        "对话真实度：台词是否符合人物身份、口吻与场合",
        "正例：包拯问案简短克制，句句指向证据",
        "反例：古代衙役说出现代口语或网络用语"),
    "sensory_detail": (
        "感官细节：关键场景是否有具体的视觉/听觉/嗅觉等感官描写",
        "正例：「惊堂木一拍，堂下霎时寂静」有声音有画面",
        "反例：通篇「很紧张」「气氛凝重」等笼统概括而无具象"),
    "cliche_detection": (
        "套路检测：是否落入陈词滥调与滥用桥段",
        "正例：破案靠证据链推进，而非巧合",
        "反例：「嘴角勾起一抹冷笑」「眼中闪过一丝精光」式套话"),
    "theme_depth": (
        "主题深度：是否触及主题层面，而非仅情节平推",
        "正例：断案过程折射律法与人情的张力",
        "反例：只有事件流水账，读不出任何意味"),
    "emotion_arc": (
        "情感弧线：本章情感是否有起伏与变化，而非全程一平到底",
        "正例：由期待到失落再到释然，情感有转折",
        "反例：整章情绪单一，人物反应始终雷同"),
}

# LLM 调用参数（蓝图：critique 低温更确定）
_TEMPERATURE = 0.3
_JUDGE_MAX_TOKENS = 2048
_CRITIC_MAX_TOKENS = 1024


@dataclass
class SuspectSegment:
    """judge 粗筛标记的存疑段（蓝图 SuspectSegment：段落引文 + 存疑理由）"""
    quote: str               # 存疑段落引文（须为章节原文子串，否则该段丢弃）
    reason: str = ""         # 存疑理由


class CriticParliament:
    """7+1 维专家 critic — 串联模式：单 judge 粗筛 → 多 critic 精审

    kernel: Kernel 实例（可选；取其 llm_call 作为 LLM 设施）
    genre: GenreBundle（可选；dimensions 从 genre.genre_params["active_critics"]
           加载——该 dict 即插件 params，active_critics 在其中；缺省/为空 →
           回退蓝图全量 ALL_DIMENSIONS 7 维。串联模式下空 judge 即零成本，
           回退不会带来意外调用。）
    llm_call: 直接注入的 LLM callable（测试 fake 注入点；优先级高于 kernel）
    """

    def __init__(self, kernel=None, genre=None, *, llm_call=None):
        if llm_call is not None:
            self._llm_call = llm_call
        elif kernel is not None:
            self._llm_call = kernel.llm_call
        else:
            self._llm_call = None
        active = list((getattr(genre, "genre_params", None) or {})
                      .get("active_critics") or [])
        self.dimensions = self._filter_dimensions(active or list(ALL_DIMENSIONS))

    @staticmethod
    def _filter_dimensions(names: list[str]) -> list[str]:
        """未知维度（插件写错名）跳过并记 warning，不崩（决策2）"""
        dims: list[str] = []
        for name in names:
            if name in KNOWN_DIMENSIONS:
                dims.append(name)
            else:
                logger.warning("CriticParliament: 未知 critic 维度「%s」，已跳过", name)
        return dims

    # ---------- 串联主流程 ----------
    async def assess(self, chapter: str, world_state=None) -> list[Critique]:
        """串联评估：单 judge 粗筛 → 多 critic 精审 → quote 过滤 → 共振加权"""
        chapter = chapter or ""
        if not chapter.strip():
            return []
        # Stage 1: 单 judge 粗筛（低成本,高速度）
        suspects = await self._single_judge_screen(chapter, world_state)
        if not suspects:
            return []  # 单 judge 未发现存疑，跳过多 critic（零成本）
        # Stage 2: 多 critic 对存疑段精审（每维 1 次 LLM，并行）
        results = await asyncio.gather(*(
            self._critic(dim, suspects, world_state) for dim in self.dimensions))
        critiques = [c for c in results if c is not None]
        # 过滤：无 quote-backed evidence 的 critique 丢弃（防幻觉）
        critiques = [c for c in critiques if self._has_valid_evidence(c, chapter)]
        # 共振加权：多 critic 命中同一存疑段 = 高置信（赌注5 发现）
        return self._resonance_weighting(critiques, suspects)

    # ---------- Stage 1：单 judge 粗筛 ----------
    async def _single_judge_screen(self, chapter: str,
                                   world_state=None) -> list[SuspectSegment]:
        prompt = (
            "你是小说质量粗筛员。通读下面的章节，标记「存疑段」——可能存在"
            "质量问题（情节矛盾、动机牵强、设定冲突、对话失真、套路化等）的段落。\n"
            "要求：\n"
            "- 没有问题就输出空列表 []；\n"
            "- 有问题就输出 YAML 列表，每项两个字段：\n"
            "  quote: 存疑段落的逐字原文引用（必须能在章节原文中逐字找到）\n"
            "  reason: 一句话存疑理由\n"
            "- 只输出 YAML 列表本身，不要任何解释。\n\n"
            f"章节原文：\n{chapter}")
        text = await self._call_llm(prompt, purpose="critic_judge",
                                    max_tokens=_JUDGE_MAX_TOKENS)
        return self._parse_suspects(text, chapter)

    def _parse_suspects(self, text: str, chapter: str) -> list[SuspectSegment]:
        """解析 judge 输出；任何失败 → []（视为无存疑，不阻塞）。

        quote 必须能在章节原文子串命中，否则该段丢弃（stage 1 级防幻觉，
        避免对幻觉段落浪费 stage 2 的 critic 调用）。
        """
        data = _extract_structured(text)
        if not isinstance(data, list):
            return []
        suspects: list[SuspectSegment] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            quote = str(item.get("quote") or "").strip()
            reason = str(item.get("reason") or "").strip()
            if quote and quote in chapter:
                suspects.append(SuspectSegment(quote=quote, reason=reason))
        return suspects

    # ---------- Stage 2：单维 critic ----------
    async def _critic(self, dimension: str, suspects: list[SuspectSegment],
                      world_state=None) -> Critique | None:
        """单个维度 critic——prompt 含维度说明 + 正反例 + 四字段输出要求。

        解析失败/空响应/异常 → None（丢弃该 critique，不抛异常、不阻塞）。
        """
        desc, good, bad = DIMENSION_GUIDE[dimension]
        seg_lines = "\n".join(
            f"{i + 1}. 引文：{s.quote}\n   粗筛理由：{s.reason or '（无）'}"
            for i, s in enumerate(suspects))
        prompt = (
            f"你是小说评审专家，只负责「{dimension}」这一个维度。\n"
            f"维度说明：{desc}\n{good}\n{bad}\n\n"
            "以下段落被粗筛标记为存疑（引自章节原文），请逐段从该维度审查：\n"
            f"{seg_lines}\n\n"
            "审查完毕，按 YAML 输出恰好这四个字段：\n"
            "verdict: PASS 或 FAIL（该维度是否有确实问题）\n"
            "evidence: 逐字引自上述引文的句子列表（FAIL 必须给出；无引用视为无效）\n"
            "fix_directive: 具体修改指令（FAIL 时给出怎么改）\n"
            "executable: yes/no/partial（该修改是否在文本生成能力之内）\n"
            "只输出 YAML，不要任何解释，不要输出数字分数。")
        text = await self._call_llm(prompt, purpose=f"critic_{dimension}",
                                    max_tokens=_CRITIC_MAX_TOKENS)
        return self._parse_critique(text, dimension)

    def _parse_critique(self, text: str, dimension: str) -> Critique | None:
        """解析 critic 输出；任何失败 → None（该 critique 丢弃，不抛异常）"""
        data = _extract_structured(text)
        if not isinstance(data, dict):
            return None
        verdict = str(data.get("verdict") or "").strip().upper()
        if verdict not in ("PASS", "FAIL"):
            return None
        raw_ev = data.get("evidence")
        if isinstance(raw_ev, str):
            evidence = [raw_ev]
        elif isinstance(raw_ev, list):
            evidence = [str(q) for q in raw_ev]
        else:
            evidence = []
        fix_directive = str(data.get("fix_directive") or "").strip()
        raw_exec = data.get("executable")
        if isinstance(raw_exec, bool):
            # YAML 1.1 陷阱：裸写 yes/no 会被 safe_load 解析成布尔
            executable = "yes" if raw_exec else "no"
        else:
            executable = str(raw_exec or "").strip().lower()
            if executable not in ("yes", "no", "partial"):
                # 缺失/乱值 → 保守记 no：不确定可执行的修订不自动触发（只记录，不阻塞）
                executable = "no"
        return Critique(dimension=dimension, verdict=verdict, evidence=evidence,
                        fix_directive=fix_directive, executable=executable)

    # ---------- quote 过滤 ----------
    @staticmethod
    def _has_valid_evidence(critique: Critique, chapter: str) -> bool:
        """evidence 非空且每条 quote 能在章节原文子串命中（防 CriticGPT 幻觉）"""
        quotes = [q.strip() for q in critique.evidence if q and q.strip()]
        if not quotes:
            return False
        return all(q in chapter for q in quotes)

    # ---------- 共振加权 ----------
    @staticmethod
    def _resonance_weighting(critiques: list[Critique],
                             suspects: list[SuspectSegment]) -> list[Critique]:
        """多 critic 命中同一存疑段 → 这些 critique confidence="high"；单命中保持 low"""
        # 每个存疑段被哪些维度命中（critique 的任一 quote 落在该段引文内）
        hits: list[set[str]] = [set() for _ in suspects]
        for c in critiques:
            for i, seg in enumerate(suspects):
                if any(q.strip() and q.strip() in seg.quote for q in c.evidence):
                    hits[i].add(c.dimension)
        resonant = [seg.quote for i, seg in enumerate(suspects) if len(hits[i]) >= 2]
        if not resonant:
            return critiques
        for c in critiques:
            if any(q.strip() and any(q.strip() in rq for rq in resonant)
                   for q in c.evidence):
                c.confidence = "high"
        return critiques

    # ---------- LLM 设施（callable 注入，P3.7 blending 同款模式） ----------
    async def _call_llm(self, prompt: str, *, purpose: str,
                        max_tokens: int) -> str:
        """统一 LLM 出口；无设施/异常/空响应 → ""（上层按不可解析处理，不阻塞）"""
        if self._llm_call is None:
            return ""
        try:
            resp = await self._llm_call(
                prompt, purpose=purpose, temperature=_TEMPERATURE,
                max_tokens=max_tokens)
            return (getattr(resp, "text", "") or "").strip()
        except Exception:
            return ""


def _extract_structured(text: str):
    """从 LLM 输出提取结构化内容：优先 ``` 代码块，否则全文；yaml.safe_load 解析。

    YAML 是 JSON 超集，json 输出同样可解析；任何异常 → None（调用方兜底）。
    """
    if not text:
        return None
    m = re.search(r"```(?:yaml|json)?\s*(.*?)```", text, re.S)
    candidate = m.group(1) if m else text
    try:
        return yaml.safe_load(candidate)
    except Exception:
        return None

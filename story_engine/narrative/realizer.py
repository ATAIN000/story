"""Module 5.3 语言 Realizer — 共创者模式（蓝图 5.3，Phase 5 计划决策4）+ Narrativizer

共创者而非翻译器：prompt 不是「翻译这段 IR」，而是「你是{插件 role}；这是本章
故事骨架（IR 概念级摘要）与质感目标（texture 数值翻成的创作指令）；请用以下
语言资源库素材创作一章」。IR 不携带「怎么讲好」，这个责任在 realizer。

- LanguageRealizer 基类：`_render_prompt(ir, sjuzhet, bundle)` =
  IR 结构化摘要（beats/events/dialogue 概念级描述，≤~800 字）
  + texture 目标数值翻成的创作指令（每语言一套模板）
  + LANGUAGE_RESOURCES 按 texture 数值采样（确定性取前 N 条，可测）
  + 插件 prompt 段 style/hard_requirements（P3.8 设施最小复制，见下方注释）
  → `realize()` 恰好 1 次 LLM 调用产文本
- ChineseRealizer：四字格/文言虚词/三级敬语/对仗模板（蓝图 1366-1375）
- EnglishRealizer：sentence_frames/legal_terms/alliteration/honorifics
  （长句嵌套/法律词汇/头韵/敬语，蓝图 1385-1390）
- Narrativizer.narrate(ir, sjuzhet)：realize → humanize（决策5）；
  语言选择 bundle.language（zh→ChineseRealizer，en→EnglishRealizer，
  未知→zh+warning）

burstiness / show-not-tell 不做二次 LLM：句长波动与 show-not-tell 写进渲染
指令（`_texture_block` / `_craft_rules`），由这 1 次生成调用承担（决策5）。
LLM 设施：callable 注入（P4.2 critic_parliament 同款签名），生产取
kernel.llm_call；无设施/异常 → 返回 ""（不阻塞，同 critic 兜底哲学）。

P6.3：`rewrite_paragraph()` 单段重写（写作台核心卖点）——本章骨架摘要 +
前后段衔接上下文 + 作者方向，恰好 1 次 LLM 调用，只产文本不回写。

P7.2 L3：构造时可选注入 kernel registry，把 active 的 story.language pack
（params.language 匹配本 realizer）的 `params.resources` 按键并集合并进
本实例资源池（list 类 pack 词条排在常量之前——采样取前 N 条方可命中 pack，
重复去重；dict 类按子键并集）；无 registry/零匹配 pack 时不动
类常量 LANGUAGE_RESOURCES，行为与基线逐字一致。
"""
from __future__ import annotations

import warnings

from ..types import GenreBundle
from .humanize import _filter_ai_isms, _inject_imperfection
from .ir import (
    INTERLINGUA_EN, INTERLINGUA_ZH, NarrativeIR, TextureParams,
)

# 复制自 engine.py P3.8（`_GENERIC_PROMPT` + `_prompt_config()` 合并逻辑，
# 三行相似胜过过早抽象）：engine 版是 StoryEngine 绑定方法（吃 self.bundle），
# 且 import engine 会拖入全栈依赖，故复制最小片段。键含义见
# plugins/genres/*.yaml 的 prompt 段（role/setting/characters/style/hard_requirements）。
_GENERIC_PROMPT = {
    "role": "故事作者",
    "setting": "虚构世界，遵循本题材设定",
    "characters": "以已定稿前情中登场的角色为准",
    "style": "800-1200字，叙事连贯",
    "hard_requirements": [],
}


def _plugin_prompt_config(bundle) -> dict:
    """题材插件 params.prompt（五键），缺段/缺键回退通用兜底（同 engine._prompt_config）"""
    cfg = dict(_GENERIC_PROMPT)
    cfg.update((getattr(bundle, "genre_params", None) or {}).get("prompt") or {})
    return cfg


# emotion/content 概念 ID → 本语言表达（复用 ir.py 公开表；无命中回退概念 ID 原文）
_INTERLINGUA = {"zh": INTERLINGUA_ZH, "en": INTERLINGUA_EN}

_SUMMARY_MAX_CHARS = 800   # IR 摘要硬封顶（落地要点：紧凑、概念级）


class LanguageRealizer:
    """语言 realizer 基类 — 共创者模式（赌注5修正）

    子类职责：填 `language` / `LANGUAGE_RESOURCES`，并按语言覆盖
    `_texture_block` / `_resource_block` / `_craft_rules`（中文模板为基类默认）。
    """

    language = "zh"
    LANGUAGE_RESOURCES: dict = {}

    def __init__(self, llm_call=None, *, registry=None):
        # llm_call: async (prompt, *, purpose=, temperature=, max_tokens=) -> 带 .text
        self._llm_call = llm_call
        # P7.2 L3：registry（kernel.registry）携带 story.language pack 时合并资源；
        # None / 零匹配 pack 时不动类常量，行为与基线逐字一致
        if registry is not None:
            self._merge_pack_resources(registry)

    # ---------- P7.2 L3：story.language pack 资源合并 ----------
    def _merge_pack_resources(self, registry) -> None:
        """匹配语言的 pack 资源并入本实例资源池（素材包计划 §3.2 键并集）。

        - 匹配规则：pack.params.language == self.language，不匹配跳过
        - list 值：pack 词条排在代码常量之前（采样确定性取前 N 条，pack 在前
          才可命中），重复词条去重（多 pack 按包序累进去重）
        - dict 值（敬语体系）：按子键并集，子键内追加去重（全量进 prompt，
          顺序无关）
        - 未知键 / 未知子键 / 类型不符：warning + 忽略（不崩）
        - texture_hints 本期不进 TextureParams（最小决策：忽略，仅在此注释说明）
        合并在实例副本上进行（实例属性遮蔽类常量），类常量不被污染。
        """
        merged = None
        pack_first: dict[str, list] = {}   # list 类：pack 词条按包序累积（排常量前）
        for pack in registry.packs("story.language"):
            params = getattr(pack, "params", None) or {}
            if params.get("language") != self.language:
                continue
            resources = params.get("resources")
            if not isinstance(resources, dict):
                warnings.warn(f"语言 pack {pack.name} 缺 resources 映射，忽略",
                              stacklevel=2)
                continue
            if merged is None:  # 懒拷贝：首个匹配 pack 时才建实例副本
                merged = {
                    k: ({sk: list(sv) for sk, sv in v.items()}
                        if isinstance(v, dict) else list(v))
                    for k, v in self.LANGUAGE_RESOURCES.items()
                }
            for key, value in resources.items():
                base = self.LANGUAGE_RESOURCES.get(key)
                if base is None:
                    warnings.warn(
                        f"语言 pack {pack.name} 含未知资源键 {key!r}，忽略",
                        stacklevel=2)
                    continue
                if isinstance(base, dict) and isinstance(value, dict):
                    for sub, words in value.items():
                        if not isinstance(base.get(sub), list) \
                                or not isinstance(words, list):
                            warnings.warn(
                                f"语言 pack {pack.name} 资源键 {key!r} 含未知"
                                f"子键或非列表 {sub!r}，忽略", stacklevel=2)
                            continue
                        merged[key][sub] += [w for w in words
                                             if w not in merged[key][sub]]
                elif isinstance(base, list) and isinstance(value, list):
                    bucket = pack_first.setdefault(key, [])
                    bucket += [w for w in value if w not in bucket]
                else:
                    warnings.warn(
                        f"语言 pack {pack.name} 资源键 {key!r} 类型与代码常量"
                        f"不符，忽略", stacklevel=2)
        if merged is not None:
            for key, words in pack_first.items():
                merged[key] = words + [w for w in merged[key] if w not in words]
            self.LANGUAGE_RESOURCES = merged

    # ---------- 主入口：1 次 LLM 调用 ----------
    async def realize(self, ir: NarrativeIR, sjuzhet=None, bundle=None,
                      *, recap: str | None = None,
                      worldview_text: str | None = None) -> str:
        """IR → 目标语言文本（共创模式，恰好 1 次 LLM 调用；无设施/异常 → ""）

        recap：可选前情提要文本（P5.12 ②，章节连续性上下文）；None 时 prompt
        与现状逐字一致。
        worldview_text：可选世界观设定文本（P12.3，双通道融合）；None/空 时
        prompt 与现状逐字一致。"""
        prompt = self._render_prompt(ir, sjuzhet, bundle, recap=recap,
                                     worldview_text=worldview_text)
        if self._llm_call is None:
            return ""
        try:
            resp = await self._llm_call(
                prompt, purpose="realize_chapter", temperature=0.7, max_tokens=4096)
            return (getattr(resp, "text", "") or "").strip()
        except Exception:
            return ""

    # ---------- P6.3：单段重写（写作台核心卖点，恰好 1 次 LLM 调用） ----------
    async def rewrite_paragraph(self, *, ir_context: str, original: str,
                                prev_para: str | None = None,
                                next_para: str | None = None,
                                direction: str = "", bundle=None) -> str:
        """单段重写：本章骨架摘要 + 前后段衔接上下文 + 作者方向 → 重写段文本。

        无设施/异常 → ""（同 realize 兜底哲学，由调用方转 note 说明）。
        P6.3 简化决策（成本/延迟）：单段重写不接 critic 自评迭代（章级质量
        门禁仍在 generate 路径）；本方法只产文本不回写——正文回写由前端
        「采用」走 textual 介入通道（P6.1 engine.update_chapter_text）。
        """
        prompt = self._paragraph_prompt(
            ir_context=ir_context, original=original, prev_para=prev_para,
            next_para=next_para, direction=direction, bundle=bundle)
        if self._llm_call is None:
            return ""
        try:
            resp = await self._llm_call(
                prompt, purpose="rewrite_paragraph", temperature=0.7,
                max_tokens=2048)
            return (getattr(resp, "text", "") or "").strip()
        except Exception:
            return ""

    def _paragraph_prompt(self, *, ir_context: str, original: str,
                          prev_para: str | None, next_para: str | None,
                          direction: str, bundle) -> str:
        """单段重写 prompt（中文模板；英文由 EnglishRealizer 覆盖）。

        风格要求按 P6.3 落地要点简化为「字数与原段相当 + 插件 style/
        hard_requirements」，不搬整章 texture 8 参数（段级任务用不上全套）。
        """
        pcfg = _plugin_prompt_config(bundle)
        hard_reqs = [
            "只输出重写后的该段正文本身（不含标题行、不含前后段）",
            f"字数与原段相当（原段约 {len(original)} 字）",
            pcfg["style"],
            *(pcfg.get("hard_requirements") or []),
        ]
        hard_txt = "\n".join(f"{i}. {r}" for i, r in enumerate(hard_reqs, 1))
        return (
            f"你是{pcfg['role']}。背景：{pcfg['setting']}。\n"
            f"人物：{pcfg['characters']}。\n\n"
            f"=== 本章故事骨架（IR 概念级摘要，把握走向与衔接） ===\n"
            f"{ir_context}\n\n"
            f"=== 待重写段落（仅重写此段） ===\n{original}\n\n"
            f"=== 前一段（衔接参考，不要改动） ===\n"
            f"{prev_para or '（本章首段，无前文）'}\n\n"
            f"=== 后一段（衔接参考，不要改动） ===\n"
            f"{next_para or '（本章末段，无后文）'}\n\n"
            f"=== 作者方向 ===\n{direction or '保持情节与视角不变，优化表达'}\n\n"
            f"=== 硬要求 ===\n{hard_txt}")

    # ---------- prompt 组装 ----------
    def _render_prompt(self, ir: NarrativeIR, sjuzhet=None, bundle=None,
                       *, recap: str | None = None,
                       worldview_text: str | None = None) -> str:
        pcfg = _plugin_prompt_config(bundle)
        hard_reqs = [pcfg["style"], *(pcfg.get("hard_requirements") or []),
                     *self._craft_rules()]
        hard_txt = "\n".join(f"{i}. {r}" for i, r in enumerate(hard_reqs, 1))
        # P5.12 ②：可选前情 recap 段（章节连续性上下文）；None/空串时整段缺席，
        # prompt 与现状逐字一致
        recap_txt = (
            f"=== 前情提要（已定稿章节结尾与未回收伏笔，保持连续性） ===\n{recap}\n\n"
            if recap else "")
        # P12.3：可选世界观设定段（双通道融合）；None/空串时整段缺席，
        # prompt 与现状逐字一致
        worldview_txt = (
            f"=== 世界观设定 ===\n{worldview_text}\n\n"
            if worldview_text else "")
        return (
            f"你是{pcfg['role']}。背景：{pcfg['setting']}。\n"
            f"人物：{pcfg['characters']}。\n\n"
            f"{worldview_txt}{recap_txt}"
            f"=== 本章故事骨架（IR 概念级摘要，供你再创作，不是待译原文） ===\n"
            f"{self._ir_summary(ir, sjuzhet)}\n\n"
            f"=== 质感目标（创作指令） ===\n{self._texture_block(ir.texture)}\n\n"
            f"=== 语言资源（按需取用，不必尽用） ===\n{self._resource_block(ir.texture)}\n\n"
            f"=== 硬要求 ===\n{hard_txt}\n\n"
            "请以骨架为骨、质感为目标，再创作本章正文。只输出正文本身。")

    def _ir_summary(self, ir: NarrativeIR, sjuzhet=None) -> str:
        """beats/events/dialogue 的概念级紧凑摘要（≤800 字，截断标注）。

        字段键用 IR 层词汇（phase/who/did/where/when/why——语言无关层），
        故中英文 realizer 共用本方法；情感概念经 interlingua 表映射到本语言。
        """
        lines: list[str] = []
        for b in ir.beats:
            prims = ",".join(str(p) for p in b.primitives) or "-"
            lines.append(
                f"[beat {b.beat_id}] phase={b.phase} tension={b.tension:.2f} "
                f"primitives={prims} arc={b.emotion_target}")
        for e in ir.events:
            parts = [f"{e.who} {e.did}"]
            if e.to_whom:
                parts.append(f"to={e.to_whom}")
            parts.append(f"@{e.where}")
            parts.append(f"when={e.when}")
            if e.how:
                parts.append(f"how={e.how}")
            if e.why:
                parts.append(f"why={e.why}")
            if e.subtext is not None:
                parts.append(f"subtext={e.subtext.map_to(self.language)}")
            lines.append("- " + " ".join(parts))
        table = _INTERLINGUA.get(self.language, {})
        for d in ir.dialogue_lines:
            emo = table.get(d.emotion_concept, d.emotion_concept)
            lines.append(
                f"- {d.speaker} illocution={d.illocution} politeness={d.politeness} "
                f"register={d.register} content={d.content_concept} emotion={emo}")
        if sjuzhet is not None:
            lines.append(
                f"[sjuzhet] pov={sjuzhet.pov} order={sjuzhet.order} "
                f"events={len(sjuzhet.events)}")
        text = "\n".join(lines)
        if len(text) > _SUMMARY_MAX_CHARS:
            text = text[:_SUMMARY_MAX_CHARS] + "\n...（截断 truncated）"
        return text or "（空骨架 empty）"

    # ---------- 以下三 hook 每语言一套（基类 = 中文模板） ----------
    def _texture_block(self, t: TextureParams) -> str:
        """8 个 texture 参数 → 中文创作指令（数值原样进 prompt，供模型对标）"""
        mean, var = t.sentence_length_distribution
        return "\n".join([
            f"- 敬语密度 {t.honorific_register:.2f}：越高称谓堆叠越多——"
            "下位者对上位者用敬称，自称用谦称",
            f"- 情感显隐度 {t.emotion_explicitness:.2f}：越低越以动作神态暗示情感，越少直陈",
            f"- 语域差 {t.register_switching:.2f}：叙述语与对话语的雅俗差异程度",
            f"- 四字格密度 {t.idiom_density:.2f}：控制四字格/成语的使用频率",
            f"- 句长分布 均值{mean:.0f}字、方差{var:.0f}：长短句交错，句长有意波动",
            f"- 含蓄度 {t.implicit_vs_explicit:.2f}：越高留白越多，情止于当止",
            f"- 视角距离：{t.perspective_distance}；时序：{t.temporal_ordering}",
        ])

    def _resource_block(self, t: TextureParams) -> str:
        """按 texture 数值从中文资源库确定性采样（取前 N 条，供选用而非堆砌）"""
        res = self.LANGUAGE_RESOURCES
        n_idiom = round(t.idiom_density * 10)          # 0.5 → ~5 条四字格
        n_func = max(1, round(t.implicit_vs_explicit * 5))
        n_para = round(t.register_switching * 5)
        lines = [
            f"四字格（建议约 {n_idiom} 条）："
            f"{'、'.join(res['四字格'][:n_idiom]) or '（本章免用）'}",
            f"文言虚词（点缀其间）：{'、'.join(res['文言虚词'][:n_func])}",
        ]
        if t.honorific_register >= 0.3:                # 敬语密度高 → 敬语表进 prompt
            hon = res["敬语体系"]
            lines.append("敬语体系：" + "；".join(
                f"{lvl}「{'、'.join(words)}」" for lvl, words in hon.items()))
        if n_para:
            lines.append(
                f"对仗模板（可用约 {n_para} 式）：{'；'.join(res['对仗模板'][:n_para])}")
        return "\n".join(lines)

    def _craft_rules(self) -> list[str]:
        """决策5：burstiness / show-not-tell 由渲染指令承担（追加进硬要求）"""
        return [
            "情感以动作、神态、物件呈现，不直接点名情绪（show-not-tell）",
            "句长有意波动：长短句交错，避免均匀句式",
        ]


class ChineseRealizer(LanguageRealizer):
    """中文共创者 — 携带中文特有的语言资源库（蓝图 1366-1375）"""

    language = "zh"
    LANGUAGE_RESOURCES = {
        "四字格": [
            "步履沉稳", "神色不动", "字字斟酌", "不动声色", "气定神闲",
            "掷地有声", "不怒自威", "明察秋毫", "洞若观火", "抽丝剥茧",
            "水落石出", "人心惶惶", "讳莫如深", "欲言又止", "将信将疑", "云淡风轻",
        ],
        "文言虚词": [
            "既", "亦", "乃", "者", "也", "矣", "焉", "之", "其", "而",
            "然", "盖", "夫", "遂", "方",
        ],
        "敬语体系": {   # 三级敬语（「本府」为府尹自称非敬称，不入表）
            "上位": ["大人", "阁下", "老爷", "明公", "尊驾", "恩相"],
            "下位": ["草民", "小人", "在下", "卑职", "晚辈", "小的", "鄙人"],
            "平级": ["先生", "兄长", "贤弟", "仁兄", "足下"],
        },
        "对仗模板": [
            "山重水复，柳暗花明", "月黑风高，夜深人静", "明枪易躲，暗箭难防",
            "棋差一着，满盘皆输", "福无双至，祸不单行", "一波未平，一波又起",
            "当局者迷，旁观者清", "善有善报，恶有恶报", "天网恢恢，疏而不漏",
            "来而不往，非礼也",
        ],
    }


class EnglishRealizer(LanguageRealizer):
    """英文共创者 — 携带英文特有的语言资源库（蓝图 1385-1390）"""

    language = "en"
    LANGUAGE_RESOURCES = {
        "sentence_frames": [   # 长句嵌套（蓝图 1385-1390）
            "It was not until the ink had dried that he understood what he had signed.",
            "The letter, which she had folded and unfolded a hundred times, lay heavy in her sleeve.",
            "Had the witness spoken sooner, the matter might have ended there.",
            "What troubled him was not the accusation itself, but the silence that followed it.",
            "No sooner had the gavel fallen than the crowd fell silent.",
            "The truth, when at last it came, came quietly.",
            "She answered, as was her habit, with a question of her own.",
            "There are confessions that acquit, and silences that condemn.",
            "He who enters this hall leaves his certainties at the door.",
            "That which is hidden in daylight is seldom found by torchlight.",
        ],
        "legal_terms": [   # 法律词汇
            "grievance", "counsel", "evidence", "petitioner", "testimony",
            "verdict", "plaintiff", "deposition", "perjury", "acquittal",
            "indictment", "oath",
        ],
        "alliteration": [   # 头韵修辞
            "safe and sound", "tried and true", "through thick and thin",
            "part and parcel", "wit and wisdom", "might and main",
            "fair and square", "hale and hearty", "high and dry", "prim and proper",
        ],
        "honorifics": [  # 敬语（资源相对贫瘠，蓝图原注）
            "Your Honor", "sir", "madam", "my lord",
            "Your Majesty", "esquire", "Your Excellency", "the honourable",
        ],
    }

    def _render_prompt(self, ir: NarrativeIR, sjuzhet=None, bundle=None,
                       *, recap: str | None = None,
                       worldview_text: str | None = None) -> str:
        pcfg = _plugin_prompt_config(bundle)
        hard_reqs = [pcfg["style"], *(pcfg.get("hard_requirements") or []),
                     *self._craft_rules()]
        hard_txt = "\n".join(f"{i}. {r}" for i, r in enumerate(hard_reqs, 1))
        # P5.12 ②：optional recap block (chapter continuity); absent when None,
        # keeping the prompt byte-identical to before
        recap_txt = (
            f"=== Previously on (finalized chapter endings and unpaid "
            f"foreshadowing — keep continuity) ===\n{recap}\n\n"
            if recap else "")
        # P12.3：optional worldview block (dual-channel fusion); absent when
        # None/empty, keeping the prompt byte-identical to before
        worldview_txt = (
            f"=== Worldview ===\n{worldview_text}\n\n"
            if worldview_text else "")
        return (
            f"You are {pcfg['role']}. Setting: {pcfg['setting']}.\n"
            f"Characters: {pcfg['characters']}.\n\n"
            f"{worldview_txt}{recap_txt}"
            f"=== Story skeleton (concept-level IR summary — raw material to "
            f"re-create from, not text to translate) ===\n"
            f"{self._ir_summary(ir, sjuzhet)}\n\n"
            f"=== Texture targets (as craft instructions) ===\n"
            f"{self._texture_block(ir.texture)}\n\n"
            f"=== Language resources (draw as needed, do not force) ===\n"
            f"{self._resource_block(ir.texture)}\n\n"
            f"=== Hard requirements ===\n{hard_txt}\n\n"
            "Re-create the chapter in English from this skeleton and these "
            "texture targets. Output the prose only.")

    def _paragraph_prompt(self, *, ir_context: str, original: str,
                          prev_para: str | None, next_para: str | None,
                          direction: str, bundle) -> str:
        """P6.3 single-paragraph rewrite prompt (English template). Style rules
        simplified per task brief: match the original length + plugin style/
        hard_requirements (full texture params not needed at paragraph level)."""
        pcfg = _plugin_prompt_config(bundle)
        hard_reqs = [
            "Output only the rewritten paragraph itself (no title line, no "
            "neighboring paragraphs)",
            f"Match the original length (~{len(original)} characters)",
            pcfg["style"],
            *(pcfg.get("hard_requirements") or []),
        ]
        hard_txt = "\n".join(f"{i}. {r}" for i, r in enumerate(hard_reqs, 1))
        return (
            f"You are {pcfg['role']}. Setting: {pcfg['setting']}.\n"
            f"Characters: {pcfg['characters']}.\n\n"
            f"=== Chapter skeleton (concept-level IR summary — for direction "
            f"and continuity) ===\n{ir_context}\n\n"
            f"=== Paragraph to rewrite (rewrite this one only) ===\n"
            f"{original}\n\n"
            f"=== Previous paragraph (continuity reference, do not change) "
            f"===\n{prev_para or '(first paragraph of the chapter)'}\n\n"
            f"=== Next paragraph (continuity reference, do not change) ===\n"
            f"{next_para or '(last paragraph of the chapter)'}\n\n"
            f"=== Author's direction ===\n"
            f"{direction or 'Keep plot and POV unchanged; polish the prose'}\n\n"
            f"=== Hard requirements ===\n{hard_txt}")

    def _texture_block(self, t: TextureParams) -> str:
        mean, var = t.sentence_length_distribution
        return "\n".join([
            f"- Honorific density {t.honorific_register:.2f}: higher means more "
            "stacked titles and deferential address",
            f"- Emotion explicitness {t.emotion_explicitness:.2f}: lower means more "
            "emotion shown through gesture and detail, less stated outright",
            f"- Register contrast {t.register_switching:.2f}: gap between narrative "
            "and dialogue registers",
            f"- Idiom density {t.idiom_density:.2f}: frequency of idioms and set phrases",
            f"- Sentence length mean {mean:.0f} words, variance {var:.0f}: deliberate "
            "burstiness, avoid uniform rhythm",
            f"- Implicitness {t.implicit_vs_explicit:.2f}: higher means more left "
            "unsaid between the lines",
            f"- Perspective distance: {t.perspective_distance}; temporal ordering: "
            f"{t.temporal_ordering}",
        ])

    def _resource_block(self, t: TextureParams) -> str:
        res = self.LANGUAGE_RESOURCES
        n_allit = round(t.idiom_density * 10)          # 头韵按习语密度采样
        n_frame = max(1, round(t.sentence_length_distribution[0] / 5))
        lines = [
            f"Alliteration (suggest ~{n_allit}): "
            f"{', '.join(res['alliteration'][:n_allit]) or '(none this chapter)'}",
            f"Legal register: {', '.join(res['legal_terms'][:6])}",
            f"Complex sentence frames: {' | '.join(res['sentence_frames'][:n_frame])}",
        ]
        if t.honorific_register >= 0.2:
            lines.append(f"Honorifics: {', '.join(res['honorifics'])}")
        return "\n".join(lines)

    def _craft_rules(self) -> list[str]:
        return [
            "Show, don't tell: render emotion through gesture and object, never name it",
            "Vary sentence length deliberately: short punches among long periods",
        ]


class Narrativizer:
    """编排器：IR → realizer → humanize（决策4/5，不接线 engine，P5.6 才接）

    kernel: Kernel 实例（可选；取其 llm_call 作 LLM 设施，registry 作 P7.2
        story.language pack 资源来源）
    bundle: GenreBundle（语言选择 + 插件 prompt 段来源；缺省给空壳）
    llm_call: 直接注入的 LLM callable（测试 fake 注入点；优先级高于 kernel）
    """

    def __init__(self, kernel=None, bundle: GenreBundle | None = None, *,
                 llm_call=None):
        self.kernel = kernel
        self.bundle = bundle if bundle is not None else GenreBundle(genre="", culture="")
        if llm_call is not None:
            self._llm_call = llm_call
        elif kernel is not None:
            self._llm_call = kernel.llm_call
        else:
            self._llm_call = None

    def select_realizer(self, language: str) -> LanguageRealizer:
        """zh→ChineseRealizer，en→EnglishRealizer，未知/缺省→zh（未知记 warning）

        P7.2 L3：kernel 携带 registry 时注入 realizer（story.language pack 资源
        并入资源池）；无 kernel/registry 时行为与基线逐字一致。"""
        lang = language or "zh"
        registry = getattr(self.kernel, "registry", None)
        if lang == "en":
            return EnglishRealizer(self._llm_call, registry=registry)
        if lang != "zh":
            warnings.warn(f"未知语言 {lang!r}，回退中文 Realizer", stacklevel=2)
        return ChineseRealizer(self._llm_call, registry=registry)

    async def narrate(self, ir: NarrativeIR, sjuzhet=None,
                      *, recap: str | None = None,
                      worldview_text: str | None = None) -> str:
        """realize（1 次 LLM）→ _filter_ai_isms → （env 门控的）_inject_imperfection

        recap：可选前情提要（P5.12 ②，engine IR-first 路径注入最近章节结尾 +
        未回收伏笔）；None 时 prompt 与现状逐字一致。
        worldview_text：可选世界观设定文本（P12.3 双通道融合，engine 注入
        WorldviewProfile.to_prompt_text()）；None/空 时 prompt 与现状逐字一致。
        """
        realizer = self.select_realizer(self.bundle.language)
        text = await realizer.realize(ir, sjuzhet, self.bundle, recap=recap,
                                      worldview_text=worldview_text)
        text = _filter_ai_isms(text, realizer.language)
        return _inject_imperfection(text, realizer.language)

"""设定一致性硬校验（正文文本层）——实体登记 + 漂移校验 + 回溯校验

背景（大唐01 12 章实测）：七步验证管事件层（事件前置条件），抓不到正文里的
设定漂移——金箍棒碎片→紧箍咒残片→定海神针、周天星斗大阵→逆星大阵、
斗战胜佛→齐天大帝、陈世嚣/明公混用、幻觉回溯（前文没有土地神却说"想起
土地神说过的话"）。engine.py 的"防术语漂移"是 prompt 软提醒，实测防不住。

本模块把软提醒升级为硬校验（系统实际检查）：
1. EntityLedger：实体登记表（人物/法器/阵法/封号/地名 + 别名），项目级持久化
2. check_entity_consistency：正文实体对照登记表，检出漂移/张冠李戴
3. check_callback_validity：正文回溯内容对照前文事件流，检出虚构前情

分层：LLM 负责抽取（entity_extract，thinking 关）；本模块负责校验（纯规则）。
校验产出 violations 进修正回路（复用 correct_chapter），失败记 warning 不阻塞。
"""
from __future__ import annotations

import json
import logging
import re
from difflib import SequenceMatcher
from pathlib import Path

logger = logging.getLogger(__name__)

ENTITY_TYPES = ("character", "artifact", "formation", "title", "location")


class EntityLedger:
    """实体登记表：canonical_name → {type, aliases, first_seen, mentions}

    别名机制管称呼统一：陈世嚣的 aliases 可含 "明公""陈大人"，
    正文出现任一别名都归并到同一实体；新称呼若与已知实体类型/语境吻合
    则登记为别名，若疑似张冠李戴（不同类型实体的名）则检出漂移。
    """

    def __init__(self):
        self.entities: dict[str, dict] = {}

    # ---------- 登记 ----------
    def register(self, name: str, type: str, chapter: int,
                 aliases: list[str] | None = None) -> dict:
        name = (name or "").strip()
        if not name:
            return {}
        existing = self.entities.get(name)
        if existing is None:
            existing = {
                "type": type if type in ENTITY_TYPES else "character",
                "aliases": [],
                "first_seen": chapter,
                "mentions": 0,
            }
            self.entities[name] = existing
        existing["mentions"] += 1
        for a in aliases or []:
            a = (a or "").strip()
            if a and a != name and a not in existing["aliases"]:
                existing["aliases"].append(a)
        return existing

    # ---------- 查询 ----------
    def lookup(self, name: str) -> str | None:
        """按 canonical 或 alias 查 → canonical；未登记 → None"""
        name = (name or "").strip()
        if not name:
            return None
        if name in self.entities:
            return name
        for canon, e in self.entities.items():
            if name in e["aliases"]:
                return canon
        return None

    def find_similar(self, name: str, type: str) -> list[tuple[str, float]]:
        """同类型实体里找相似名（漂移候选）→ [(canonical, 相似度)]，>0.5 按序。"""
        out = []
        for canon, e in self.entities.items():
            if e["type"] != type:
                continue
            sim = SequenceMatcher(None, name, canon).ratio()
            for alias in e["aliases"]:
                sim = max(sim, SequenceMatcher(None, name, alias).ratio())
            if sim > 0.5:
                out.append((canon, round(sim, 2)))
        return sorted(out, key=lambda x: -x[1])

    def is_same_family(self, name: str, type: str) -> str | None:
        """子串包含关系判定（部分-整体不算漂移）：name 与某已登记名互为
        子串 → 返回该 canonical（同一事物家族，如「封神榜」与「封神榜残页」、
        「天庭禁区」与「天庭」、「补天石血脉」与「补天石」）；否则 None。"""
        name = (name or "").strip()
        if not name:
            return None
        for canon, e in self.entities.items():
            if e["type"] != type:
                continue
            names = [canon, *e["aliases"]]
            for n in names:
                if len(name) >= 2 and len(n) >= 2 and (name in n or n in name):
                    return canon
        return None

    # ---------- 持久化 ----------
    def to_dict(self) -> dict:
        return {"entities": self.entities}

    @classmethod
    def from_dict(cls, data: dict) -> "EntityLedger":
        led = cls()
        ents = (data or {}).get("entities")
        if isinstance(ents, dict):
            led.entities = ents
        return led

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), ensure_ascii=False,
                                         indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "EntityLedger":
        p = Path(path)
        if not p.exists():
            return cls()
        try:
            return cls.from_dict(json.loads(p.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            return cls()


# ---------- 正文实体抽取 ----------
def extract_entities_rule(text: str, known_names: list[str]) -> list[dict]:
    """规则兜底抽取（零 LLM，保守——宁缺毋滥）：已知角色名匹配 +
    「」/《》标记名词捕获。不做后缀扫描（中文无词边界，后缀正则噪声太大，
    实测「想起万妖坑」「掌心金箍棒碎片」全被误抽——后缀法不可用）。

    返回 [{name, type}]，type 缺省 character（已知名）/ artifact（标记名词）。
    """
    found: dict[str, dict] = {}
    for name in known_names:
        if name and name in text:
            found[name] = {"name": name, "type": "character"}
    # 「」/《》内的名词多为法器/阵法/典籍（仙侠/玄幻语境）
    for m in re.finditer(r"[「『]([^「」『』]{2,10})[」』]", text):
        w = m.group(1)
        if w not in found:
            found[w] = {"name": w, "type": "artifact"}
    for m in re.finditer(r"《([^《》]{2,10})》", text):
        w = m.group(1)
        if w not in found:
            found[w] = {"name": w, "type": "artifact"}
    return list(found.values())


def _guess_type(name: str) -> str:
    if re.search(r"(大阵|阵法|星斗)", name):
        return "formation"
    if re.search(r"(宫|殿|山|坑|牢|台|海|河|林)$", name):
        return "location"
    if re.search(r"(帝|佛|圣|尊|王|君)$", name):
        return "title"
    return "artifact"


# ---------- LLM 实体抽取（主路径：干净抽完整名词，规则法抓不到词边界） ----------
_ENTITY_EXTRACT_PROMPT = (
    "从以下小说章节正文中，抽取所有专有名词实体（人物名/法器宝物/阵法法术/"
    "封号称号/地名场所）。要求：\n"
    "- 只抽真正的专有名词（如「金箍棒碎片」「周天星斗大阵」「斗战胜佛」"
    "「花果山」「刘浩」），不要普通词汇、动作、形容词\n"
    "- 同一事物的不同称呼归为一个条目，别名列 aliases（如「陈世嚣」"
    "别名「明公」「陈大人」）\n"
    "- type 只能是：character / artifact / formation / title / location\n"
    "- 严格输出 JSON：{\"entities\": [{\"name\": \"标准名\", \"type\": \"...\", "
    "\"aliases\": [\"别名1\"]}]}\n"
    "正文：\n")


async def extract_entities_llm(text: str, llm_call) -> list[dict]:
    """LLM 抽取正文实体（thinking 关）。失败 → 空列表（调用方走规则兜底）。"""
    try:
        resp = await llm_call(_ENTITY_EXTRACT_PROMPT + text[:6000],
                              purpose="entity_extract", temperature=0.3,
                              max_tokens=1024, no_retry=True)
        raw = resp.text if hasattr(resp, "text") else str(resp)
        start, end = raw.find("{"), raw.rfind("}")
        if start == -1 or end <= start:
            return []
        data = json.loads(raw[start:end + 1])
        out = []
        for e in (data.get("entities") or []):
            if isinstance(e, dict) and isinstance(e.get("name"), str) \
                    and e["name"].strip():
                out.append({
                    "name": e["name"].strip(),
                    "type": e.get("type") if e.get("type") in ENTITY_TYPES
                    else "character",
                    "aliases": [a for a in (e.get("aliases") or [])
                                if isinstance(a, str) and a.strip()],
                })
        return out
    except Exception:
        logger.warning("LLM 实体抽取失败（走规则兜底）", exc_info=True)
        return []


# ---------- 校验 1：名词一致性（漂移检测） ----------
def check_entity_consistency(text: str, ledger: EntityLedger,
                             chapter: int,
                             extracted: list[dict] | None = None) -> list[dict]:
    """正文实体对照登记表 → violations。

    extracted：本章实体清单（engine 传入 LLM 抽取结果，含 name/type/aliases）；
    缺省走规则兜底（cast 角色名 + 「」《》标记，保守）。
    规则：
    - 实体在登记表（canonical/alias 命中）→ 通过，aliases 登记归并
    - 未登记但与同类型已有实体相似度 >0.5 → 疑似漂移违规（列出候选）
    - 未登记且不相似 → 新登场，登记放行（不违规）
    """
    violations: list[dict] = []
    if ledger is None:
        return violations
    if extracted is None:
        known = list(ledger.entities.keys())
        for alias_list in (e["aliases"] for e in ledger.entities.values()):
            known.extend(alias_list)
        extracted = extract_entities_rule(text, known)
    for ent in extracted:
        name, etype = ent["name"], ent["type"]
        aliases = ent.get("aliases") or []
        canon = ledger.lookup(name)
        if canon:
            # 已登记：别名归并（称呼统一管理），mentions +1
            ledger.register(canon, etype, chapter, aliases=aliases)
            continue
        # 子串包含关系（部分-整体家族）→ 归并登记为别名，不报漂移
        # （如「封神榜」与已登记「封神榜残页」、「天庭禁区」与「天庭」）
        family = ledger.is_same_family(name, etype)
        if family:
            ledger.register(family, etype, chapter, aliases=[name, *aliases])
            continue
        similar = ledger.find_similar(name, etype)
        if similar:
            canon_sim, sim = similar[0]
            violations.append({
                "kind": "entity_drift",
                "entity": name, "type": etype,
                "reason": f"疑似设定漂移：「{name}」未登记，与已登记的「{canon_sim}」"
                          f"（同类，相似度 {sim}）高度相似——若是同一事物请沿用旧名，"
                          f"若是新事物请明确区分",
                "candidates": [c for c, _ in similar],
            })
        else:
            # 新登场：登记放行（含别名）
            ledger.register(name, etype, chapter, aliases=aliases)
    return violations


# 回溯标记分两类：
# 引用类（指向他人言论/行为，需校验前文对应）——「土地神说过的话」这类
_QUOTE_MARKERS = ("曾说过", "曾说", "说过的话", "说过", "他曾", "她曾",
                  "当年他", "当年她", "当年陈", "当年刘")
# 记忆类（角色内心回忆/情感记忆，正常写作手法，放行）——「想起母亲的脸」
# 不列入校验（_CALLBACK_MARKERS 不再含"想起/记得"等纯记忆词）
_CALLBACK_MARKERS = _QUOTE_MARKERS


# ---------- 校验 2：回溯有效性（虚构前情检测） ----------
def check_callback_validity(text: str,
                            prior_summaries: list[str]) -> list[dict]:
    """正文回溯内容对照前文事件摘要 → violations。

    只校验「引用类」回溯（某人曾说过/做过某事——应对应前文事件）；
    「记忆类」（想起母亲的脸/当年的感觉）是正常写作手法，放行。
    引用句内容的关键词在前文摘要中完全无匹配 → 疑似虚构前情（幻觉 callback）。
    prior_summaries：前文事件流的 summary 列表（engine 从 all_events 取）。
    """
    violations: list[dict] = []
    if not prior_summaries:
        return violations
    prior_blob = "。".join(prior_summaries)
    # 从前文提取特征名词集（2-4 字中文词），过滤泛词
    stop = {"的话", "说的", "说道", "忽然", "想起", "记得", "仿佛", "似乎",
            "一个", "没有", "什么", "不是", "就是"}
    prior_nouns = {n for n in re.findall(r"[\u4e00-\u9fa5]{2,4}", prior_blob)
                   if n not in stop}
    # 按句切，只查含「引用类」标记的句子（记忆类放行）
    sentences = re.split(r"(?<=[。！？…])", text)
    for sent in sentences:
        if not any(m in sent for m in _QUOTE_MARKERS):
            continue
        # 回溯句与前文的交集：含任一前文特征名词 → 有真实前情，放行
        if any(n in sent for n in prior_nouns):
            continue
        # 完全无交集 → 疑似虚构前情（幻觉 callback）
        violations.append({
            "kind": "fabricated_callback",
            "entity": sent.strip()[:30],
            "reason": f"疑似虚构前情：「{sent.strip()[:30]}…」中提到的内容"
                      f"在前文事件流中无对应记录——若是回忆/引用，"
                      f"请确认前文确有此事，否则删除或改为当下感知",
        })
    return violations


# ---------- 校验 3：字数门（正文层硬校验，独立于自评成败） ----------
def check_word_count(text: str, style: str) -> list[dict]:
    """字数对照题材 style 区间（收紧容差 lo×0.7/hi×1.3）。

    大唐01/02 实测：字数门原挂在自评闭环 L5，自评因网络超时退回时字数门
    根本没机会跑（644/2687/6172 字失控）。解耦成正文层独立规则校验
    （零 LLM），不依赖自评成败，违规进修正回路。
    """
    from ..evaluator.process_gates import parse_word_range
    lo, hi = parse_word_range(style)
    if (lo, hi) == (100, 20000):   # DEFAULT_WORD_RANGE（style 未配置）→ 不拦
        return []
    margin_lo = max(50, int(lo * 0.3))
    margin_hi = int(hi * 1.3)
    n = len(re.sub(r"\s", "", (text or "").strip()))
    if not (lo - margin_lo <= n <= margin_hi):
        return [{
            "kind": "word_count",
            "entity": f"{n}字",
            "reason": f"字数 {n} 超出容差区间 [{lo - margin_lo}, {margin_hi}]"
                      f"（genre style {lo}-{hi}）——过短补场景细节/对话节拍，"
                      f"过长拆分场次或删减支线",
        }]
    return []


# ---------- 前置注入：实体登记表 → prompt 段（生成前约束，源头防漂移） ----------
_TYPE_LABELS = {"character": "人物", "artifact": "法器/器物",
                "formation": "阵法/法术", "title": "封号/称号",
                "location": "地点/场所"}


def format_entities_for_prompt(ledger: EntityLedger) -> str:
    """把实体登记表格式化为 prompt 注入段（前置约束：生成前告诉 LLM 已建立
    设定，沿用勿改——漂移从源头不发生，而不是事后抓）。

    空表 → 空串（调用方判断：空串则整段缺席，prompt 与无注入时一致）。
    """
    if not ledger or not ledger.entities:
        return ""
    by_type: dict[str, list[str]] = {}
    for name, e in ledger.entities.items():
        t = e.get("type", "character")
        aliases = e.get("aliases") or []
        label = name + (f"（别称：{'/'.join(aliases)}）" if aliases else "")
        by_type.setdefault(t, []).append(label)
    parts = ["【已建立设定·沿用勿改】以下名称/称呼已在前文确立，"
             "本章必须沿用，不得改名或另造："]
    for t in ENTITY_TYPES:
        names = by_type.get(t)
        if names:
            parts.append(f"{_TYPE_LABELS[t]}：{'、'.join(names)}")
    return "\n".join(parts)

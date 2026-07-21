"""P11.1 Cast 解析层 — 题材阵容插件化（Actor 阵容不再绑定 mock_script）

parse_cast(genre_params) -> list[CastMember]，三级来源逐级兜底（永不崩）：
- L1：genre params 的 cast: 结构化段
  [{id, role?, goals?, voice_hint?, relations?: [{target, type, intensity}]}]
- L2：genre params 的 prompt.characters 文案解析（P3.1 五键格式：
  "沈砚清（医药世家独女，…）、顾明璋（…）"——按 、，,;； 切分，
  名字取（前文本，role/特点取（）内文本）
- fallback：两级都失败 → mock_script SEED 阵容 + warning（不崩）

goals 默认映射（cast 条目或 L2 解析结果缺 goals 时）：第 1 人 → main_track
对应轨道名；第 2/3 人 → tracks 列表按序第 2/3 条轨道名；更靠后或轨道
缺失 → 回落 main_track 轨道名。
"""
from __future__ import annotations

import logging
import re
import warnings
from dataclasses import dataclass, field

from .. import mock_script

logger = logging.getLogger(__name__)


@dataclass
class CastMember:
    id: str
    role: str = ""
    voice_hint: str = ""
    goals: list[str] = field(default_factory=list)
    relations: list[dict] = field(default_factory=list)  # [{target, type, intensity}]


# L2 人物串切分符：中文顿号/逗号/分号 + 半角逗号/分号
_SPLIT_CHARS = frozenset("、，,;；")
# 「名字（特点）」整串匹配：名字 = （前文本，role = 最外层（）内文本
_PAREN_RE = re.compile(r"^([^（()]+?)\s*[（(](.*)[）)]$")
# 剥掉所有（）组（判断括号串是否还剩名字内容用）
_PAREN_STRIP_RE = re.compile(r"[（(][^（()]*[）)]")


def _split_top_level(text: str) -> list[str]:
    """按 、，,;； 切分，但只在括号外切——「沈砚清（医药世家独女，通医理）、
    顾明璋（…）」的括号内逗号是特点描述，不是人物分隔符。"""
    chunks, buf, depth = [], [], 0
    for ch in text:
        if ch in "（(":
            depth += 1
        elif ch in "）)" and depth > 0:
            depth -= 1
        if ch in _SPLIT_CHARS and depth == 0:
            chunks.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    chunks.append("".join(buf))
    return chunks


def parse_cast(genre_params: dict) -> list[CastMember]:
    """L1 cast: 段优先；L2 prompt.characters 解析兜底；全失败回退 mock 种子 + warning"""
    params = genre_params or {}
    members = _parse_l1(params.get("cast"), params)
    if members:
        return members
    prompt = params.get("prompt") or {}
    members = _parse_l2(prompt.get("characters"), params)
    if members:
        return members
    warnings.warn(
        "题材插件无可用阵容（cast 段缺失且 prompt.characters 不可解析），"
        "回退 mock_script 种子阵容", stacklevel=2)
    return _mock_fallback()


# ---------- L1：cast: 结构化段 ----------
def _parse_l1(cast, params: dict) -> list[CastMember]:
    if cast is None:
        return []
    if not isinstance(cast, list):
        logger.warning("cast 段非列表（%r），忽略", cast)
        return []
    members = []
    for entry in cast:
        if not isinstance(entry, dict) or not str(entry.get("id") or "").strip():
            logger.warning("cast 条目缺 id（%r），跳过该条", entry)
            continue
        goals = entry.get("goals")
        members.append(CastMember(
            id=str(entry["id"]).strip(),
            role=str(entry.get("role") or ""),
            voice_hint=str(entry.get("voice_hint") or ""),
            goals=[str(g) for g in goals if str(g).strip()]
                  if isinstance(goals, list) else [],
            relations=_norm_relations(entry.get("relations")),
        ))
    return _fill_default_goals(members, params)


def _norm_relations(relations) -> list[dict]:
    out = []
    if not isinstance(relations, list):
        return out
    for r in relations:
        if not isinstance(r, dict) or not r.get("target") or not r.get("type"):
            logger.warning("cast relation 缺 target/type（%r），跳过该条", r)
            continue
        try:
            intensity = float(r.get("intensity", 0.5))
        except (TypeError, ValueError):
            intensity = 0.5
        out.append({"target": str(r["target"]), "type": str(r["type"]),
                    "intensity": intensity})
    return out


# ---------- L2：prompt.characters 文案解析 ----------
def _parse_l2(text, params: dict) -> list[CastMember]:
    if not isinstance(text, str) or not text.strip():
        return []
    members = []
    for chunk in _split_top_level(text):
        chunk = chunk.strip()
        if not chunk:
            continue
        m = _PAREN_RE.match(chunk)
        if m:
            name, role = m.group(1).strip(), m.group(2).strip()
        else:
            # 无括号段：整段作名字；纯括号串剥掉括号组后无内容 → 跳过
            name, role = _PAREN_STRIP_RE.sub("", chunk).strip(), ""
        if name:
            members.append(CastMember(id=name, role=role))
    return _fill_default_goals(members, params)


# ---------- goals 默认映射（轨道名） ----------
def _fill_default_goals(members: list[CastMember], params: dict) -> list[CastMember]:
    if not members:
        return members
    names = [str(t.get("name") or "")
             for t in params.get("tracks") or [] if isinstance(t, dict)]
    main_name = names[0] if names else ""
    main_id = params.get("main_track")
    for t in params.get("tracks") or []:
        if isinstance(t, dict) and t.get("id") == main_id:
            main_name = str(t.get("name") or "") or main_name
            break
    for i, member in enumerate(members):
        if member.goals:
            continue
        goal = main_name if i == 0 else (names[i] if i < len(names) else main_name)
        member.goals = [goal] if goal else []
    return members


# ---------- fallback：mock_script SEED 阵容 ----------
def _mock_fallback() -> list[CastMember]:
    rel_by_src: dict[str, list[dict]] = {}
    for key, r in mock_script.SEED_RELATIONS.items():
        src, _, target = key.partition("|")
        rel_by_src.setdefault(src, []).append(
            {"target": target, "type": r["type"], "intensity": r["intensity"]})
    return [
        CastMember(
            id=cid,
            role=meta.get("role", ""),
            voice_hint=meta.get("voice", ""),
            goals=list(mock_script.SEED_MINDS.get(cid, {}).get("goals", [])),
            relations=rel_by_src.get(cid, []),
        )
        for cid, meta in mock_script.SEED_CHARACTERS.items()
    ]

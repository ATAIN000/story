"""剧本反推开局（script-driven gacha）：台词脚本 + 作者补充 → 题材库匹配 + 人物推导

用户粘贴一段台词脚本（基本为对话式），LLM 从现有 315 题材库中匹配最适合的
题材，并推导人物原型/推荐骨架/文化。匹配结果挂靠现有题材（不做自由创作），
确认后进入正常 gacha 管线（世界观向导/人物/宏观/开工全部复用）。

成本控制：脚本截前 4000 字；单次 LLM 调用；purpose=script_analyze
（在 llm_pool._THINKING_NEVER_PREFIXES 中，任何模式下关闭 thinking）。
mock 模式走 mock_script.respond 的 script_analyze 分支（固定演示推荐）。
"""
from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

SCRIPT_MAX_CHARS = 4000

_ANALYZE_KEYS = ("genre_id", "reason", "culture", "preset", "characters")


def genre_catalog() -> str:
    """全量题材压缩清单（id|title|family|vibe 一行一个，约 8KB）。

    315 个题材全给 LLM 比抽样准——匹配精度优先于 prompt 长度。"""
    from .genre_taxonomy import all_taxa
    lines = [f"{t.id}|{t.title}|{t.family_title}|{t.vibe}" for t in all_taxa()]
    return "\n".join(lines)


def build_analyze_prompt(script_excerpt: str, author_note: str = "",
                         exclude_genres: list[str] | None = None) -> str:
    """构建分析 prompt（纯函数，可测）。

    exclude_genres：重 ROLL 时排除已推荐题材，要求 LLM 换个方向。"""
    parts = [
        "你是题材策划。用户有一段台词脚本（对话为主）和补充说明，"
        "请从下方题材库中匹配最适合的一个题材，并推导人物原型。",
        "脚本可能含转录备注、场景说明等非台词内容（如「## 备注」段），"
        "请忽略它们，只依据台词与剧情推断题材。",
        "",
        "【台词脚本（节选）】",
        script_excerpt,
        "",
    ]
    if author_note.strip():
        parts += ["【作者补充】", author_note.strip(), ""]
    if exclude_genres:
        parts += [
            f"【排除】不要推荐这些题材（换个方向）：{', '.join(exclude_genres)}",
            "",
        ]
    parts += [
        "【题材库】（格式：id|名称|族|调性）",
        genre_catalog(),
        "",
        "【输出要求】",
        "只输出一个 JSON 对象，不要任何其他文字：",
        "{",
        '  "genre_id": "库中最匹配题材的 id",',
        '  "reason": "匹配理由（50 字内，指出脚本中的依据）",',
        '  "culture": "推荐文化 id（默认 modern-chinese-urban 或 confucian_officialdom）",',
        '  "preset": "推荐世界观骨架 key（如 hard_reality / infinite_flow / shanhai_zhiguai 等）",',
        '  "characters": [',
        '    {"name": "中文人名（2-4字，有辨识度）", "role": "主角",',
        '     "traits": "性格特点（20字内）"},',
        '    {"name": "...", "role": "配角", "traits": "..."}',
        '  ],',
        '  "worldview_hints": {"conflict_type": "核心冲突类型", "tone": "整体调性"}',
        "}",
        "注意：genre_id 必须是题材库中实际存在的 id；characters 2-3 个，"
        "名字必须符合脚本调性，不要泛称（不要叫「主角」「对手」）。",
    ]
    return "\n".join(parts)


def parse_analyze_response(text: str) -> dict | None:
    """从 LLM 输出提取 JSON 对象（容忍前后废话；字段缺失/类型错 → None）。"""
    if not text:
        return None
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        data = json.loads(text[start:end + 1])
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    genre_id = data.get("genre_id")
    if not isinstance(genre_id, str) or not genre_id.strip():
        return None
    characters = data.get("characters")
    if not isinstance(characters, list):
        characters = []
    # 规范化人物条目：只保留有名字的 dict
    chars = []
    for c in characters:
        if isinstance(c, dict) and isinstance(c.get("name"), str) \
                and c["name"].strip():
            chars.append({
                "name": c["name"].strip(),
                "role": str(c.get("role") or "配角"),
                "traits": str(c.get("traits") or ""),
            })
    return {
        "genre_id": genre_id.strip(),
        "reason": str(data.get("reason") or ""),
        "culture": str(data.get("culture") or ""),
        "preset": str(data.get("preset") or ""),
        "characters": chars,
        "worldview_hints": data.get("worldview_hints")
        if isinstance(data.get("worldview_hints"), dict) else {},
    }


def _fallback_genre_id(genre_id: str) -> str | None:
    """genre_id 不在库时的模糊回退：按 id 前缀/title 匹配（LLM 可能写 title）。"""
    from .genre_taxonomy import all_taxa, taxon_by_id
    if taxon_by_id(genre_id) is not None:
        return genre_id
    lowered = genre_id.lower().strip()
    for t in all_taxa():
        if t.id.startswith(lowered) or t.title == genre_id:
            return t.id
    return None


async def analyze_script(script_text: str, author_note: str, llm_call,
                         exclude_genres: list[str] | None = None) -> dict | None:
    """台词脚本 → 题材匹配 + 人物推导。失败（LLM 异常/解析失败/题材不在库）→ None。

    llm_call：LLMPool.call 同签名 callable（async）。"""
    excerpt = (script_text or "").strip()[:SCRIPT_MAX_CHARS]
    if not excerpt:
        return None
    prompt = build_analyze_prompt(excerpt, author_note, exclude_genres)
    try:
        resp = await llm_call(prompt, purpose="script_analyze",
                              temperature=0.7, max_tokens=1024, no_retry=True)
    except Exception:
        logger.exception("script_analyze LLM 调用失败")
        return None
    text = resp.text if hasattr(resp, "text") else str(resp)
    parsed = parse_analyze_response(text)
    if parsed is None:
        logger.warning("script_analyze 响应解析失败 | 响应前 200 字: %s",
                       text[:200])
        return None
    genre_id = _fallback_genre_id(parsed["genre_id"])
    if genre_id is None:
        logger.warning("script_analyze 题材不在库 | genre_id=%s",
                       parsed["genre_id"])
        return None
    parsed["genre_id"] = genre_id
    return parsed

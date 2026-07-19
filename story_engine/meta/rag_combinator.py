"""RAGCombinator — 路径 B：从已注册插件库检索最相似模板（蓝图 Module 8 路径 B）

蓝图技术栈提到 sqlite-vec + bge-small-zh，但本任务范围（Phase 1）先用
关键词重叠度 + Jaccard 相似度做最简实现。Phase 2 接入真实向量库。
"""
from __future__ import annotations

from ..types_meta import StoryConfig, UserIntent


def _tokenize(text: str) -> set[str]:
    """中文简单分词：按 2-3 字滑窗 + 显式空格分词"""
    text = text.lower()
    tokens = set()
    # 按非中文字符切
    for chunk in text.replace(",", " ").replace("，", " ").split():
        tokens.add(chunk)
    # 2-3 字滑窗
    chars = [c for c in text if c.strip()]
    for n in (2, 3):
        for i in range(len(chars) - n + 1):
            tokens.add("".join(chars[i:i + n]))
    return tokens


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = a & b
    union = a | b
    return len(inter) / len(union)


class RAGCombinator:
    """路径 B：从已注册 Genre 插件库检索最相似模板"""

    def __init__(self, kernel):
        self.kernel = kernel

    def retrieve(self, intent: UserIntent) -> StoryConfig | None:
        plugins = self.kernel.registry.list_plugins("story.genre").get("story.genre", [])
        if not plugins:
            return None

        # intent → token 集
        query_text = " ".join([intent.theme, intent.culture_hint, intent.language])
        query_tokens = _tokenize(query_text)

        best_genre = None
        best_score = -1.0
        for genre_name in plugins:
            manifest = self.kernel.registry.get_manifest("story.genre", genre_name)
            # 把 manifest 关键字段拼起来当文档
            doc_parts = [genre_name, manifest.name]
            doc_parts.extend(manifest.params.get("taboo_list", []))
            doc_parts.append(manifest.params.get("pacing_curve", ""))
            doc_parts.extend(manifest.params.get("emotion_arcs", []))
            for t in manifest.params.get("tracks", []):
                doc_parts.append(t.get("name", ""))
            doc_text = " ".join(str(p) for p in doc_parts)
            doc_tokens = _tokenize(doc_text)
            score = _jaccard(query_tokens, doc_tokens)
            if score > best_score:
                best_score = score
                best_genre = genre_name

        if best_genre is None or best_score <= 0:
            return None

        # 文化匹配（同 RuleConfigurator 简单逻辑）
        culture = "confucian_officialdom"  # 当前唯一可用
        try:
            self.kernel.registry.validate_combo(best_genre, culture)
        except Exception:
            return None

        manifest = self.kernel.registry.get_manifest("story.genre", best_genre)
        return StoryConfig(
            genre=best_genre, culture=culture,
            language=intent.language or "zh",
            target_length=intent.target_length,
            platform=intent.platform,
            evaluation_weights=dict(manifest.params.get("evaluation_weights", {})),
            active_critics=list(manifest.params.get("active_critics", [])),
            source="rag",
            matched_template=best_genre,
        )

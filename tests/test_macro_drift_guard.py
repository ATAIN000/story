"""第二波④ macro 术语漂移防护测试 — _macro_context_text 约束后缀

验证：有宏观内容时渲染末尾带「专有名词一致性纪律」约束（防刀劳鬼式漂移）；
空 ctx 仍返回空串（零行为漂移）。
"""
from story_engine.engine import StoryEngine


def test_macro_text_appends_drift_guard_when_content_present():
    ctx = {
        "beat": "中点反转",
        "beat_description": "主角发现真相",
        "episode_synopsis": "主角与反派首次正面交锋",
        "key_events_required": ["发现古剑封印", "与追杀者交锋"],
    }
    text = StoryEngine._macro_context_text(ctx)
    assert text
    assert "纪律" in text
    assert "前情未铺垫" in text


def test_macro_text_empty_ctx_returns_empty_string():
    """空 ctx → 空串，不附加约束（与无 macro_plan 路径行为一致）"""
    assert StoryEngine._macro_context_text({}) == ""


def test_macro_text_drift_guard_only_key_events():
    """仅 key_events_required 时也带约束（最易漂移的字段）"""
    ctx = {"key_events_required": ["遭遇刀劳鬼袭击"]}
    text = StoryEngine._macro_context_text(ctx)
    assert "纪律" in text
    # 原始内容仍在
    assert "刀劳鬼" in text

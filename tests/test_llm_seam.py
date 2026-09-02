"""能力 seam 契约测试（借鉴 DSH Service Definition/Provider/Consumer 三角）。

验证默认 Provider（LLMPool / Embedder）满足 seam 接口（Protocol），
且 critic model 覆盖（STORY_ENGINE_CRITIC_MODEL）接线生效。
"""
from __future__ import annotations

import os

from story_engine.kernel.embed_seam import EmbedProvider
from story_engine.kernel.embedding import Embedder
from story_engine.kernel.llm_pool import LLMPool
from story_engine.kernel.llm_seam import LLMProvider, critic_model


# ---------- seam 契约：默认 Provider 满足接口 ----------
def test_llmpool_satisfies_llm_provider():
    pool = LLMPool()
    assert isinstance(pool, LLMProvider)      # runtime_checkable Protocol
    assert hasattr(pool, "call") and hasattr(pool, "call_stream")
    assert hasattr(pool, "is_mock") and hasattr(pool, "model")


def test_embedder_satisfies_embed_provider():
    emb = Embedder(mode="dummy")               # dummy 模式不拉模型
    assert isinstance(emb, EmbedProvider)
    assert hasattr(emb, "embed") and hasattr(emb, "embed_batch")
    assert emb.is_dummy is True


# ---------- critic model 覆盖接线 ----------
def test_critic_model_from_env(monkeypatch):
    monkeypatch.setenv("STORY_ENGINE_CRITIC_MODEL", "glm-5.2-pro")
    assert critic_model() == "glm-5.2-pro"


def test_critic_model_default_none(monkeypatch):
    monkeypatch.delenv("STORY_ENGINE_CRITIC_MODEL", raising=False)
    assert critic_model() is None
    assert critic_model("fallback-model") == "fallback-model"


def test_critic_parliament_reads_critic_model(monkeypatch):
    """CriticParliament 构造时读 env 设定 _critic_model（第三波⑥已接线）。"""
    from story_engine.evaluator.critic_parliament import CriticParliament
    monkeypatch.setenv("STORY_ENGINE_CRITIC_MODEL", "glm-5.2-pro")
    cp = CriticParliament(llm_call=None)
    assert cp._critic_model == "glm-5.2-pro"


def test_critic_parliament_default_none(monkeypatch):
    from story_engine.evaluator.critic_parliament import CriticParliament
    monkeypatch.delenv("STORY_ENGINE_CRITIC_MODEL", raising=False)
    cp = CriticParliament(llm_call=None)
    assert cp._critic_model is None


# ---------- kernel.llm_call 透传 model ----------
def test_kernel_llm_call_passes_model():
    """kernel.llm_call 的 model 参数透传到 LLMPool.call（critic 更强模型生效）。"""
    import asyncio
    import tempfile
    from pathlib import Path
    from story_engine.kernel.syscalls import Kernel

    captured = {}

    class FakePool:
        is_mock = True
        model = "gen-model"
        base_url = ""

        async def call(self, prompt, **kw):
            captured.update(kw)
            from story_engine.kernel.llm_pool import LLMResponse
            return LLMResponse(text="ok", model=kw.get("model") or "gen-model",
                               tokens_in=0, tokens_out=0, latency_ms=0)

        async def call_stream(self, prompt, **kw):
            yield "x"

    async def _run():
        tmp = Path(tempfile.mkdtemp())
        k = Kernel(tmp, plugin_dir=None)
        k.llm = FakePool()
        await k.llm_call("test", purpose="critic", model="strong-model")
        k.close()

    asyncio.run(_run())
    assert captured.get("model") == "strong-model"

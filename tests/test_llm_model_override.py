"""第三波⑥ LLMPool model 覆盖测试 — call() / _openai_call 的 model 参数

验证：call(model=X) 时 model 覆盖到达 _openai_call；不传则 None（_openai_call
内部回落 self.model）。这是 critic 用更强模型评估的底层设施。
"""
import pytest

from story_engine.kernel.llm_pool import LLMPool, LLMResponse


@pytest.mark.asyncio
async def test_call_passes_model_override_to_openai(monkeypatch):
    monkeypatch.setenv("STORY_ENGINE_LLM_MODE", "openai")
    monkeypatch.setenv("STORY_ENGINE_LLM_API_KEY", "test-key")
    monkeypatch.setenv("STORY_ENGINE_LLM_MODEL", "base-model")
    pool = LLMPool()
    captured = {}

    async def fake_openai(self, prompt, temp, mt, **kw):
        captured["model"] = kw.get("model")
        eff = kw.get("model") or self.model
        return LLMResponse(text="ok", model=eff)

    monkeypatch.setattr(LLMPool, "_openai_call", fake_openai)
    await pool.call("prompt", purpose="critic_x", model="critic-strong")
    assert captured["model"] == "critic-strong"


@pytest.mark.asyncio
async def test_call_without_model_passes_none(monkeypatch):
    monkeypatch.setenv("STORY_ENGINE_LLM_MODE", "openai")
    monkeypatch.setenv("STORY_ENGINE_LLM_API_KEY", "test-key")
    monkeypatch.setenv("STORY_ENGINE_LLM_MODEL", "base-model")
    pool = LLMPool()
    captured = {}

    async def fake_openai(self, prompt, temp, mt, **kw):
        captured["model"] = kw.get("model")
        return LLMResponse(text="ok", model=self.model)

    monkeypatch.setattr(LLMPool, "_openai_call", fake_openai)
    await pool.call("prompt", purpose="generate")
    # 不传 model → None 传给 _openai_call（其内部回落 self.model）
    assert captured["model"] is None


@pytest.mark.asyncio
async def test_openai_call_uses_model_override_for_body(monkeypatch):
    """_openai_call 直接：model 覆盖用于 body 和 response.model"""
    monkeypatch.setenv("STORY_ENGINE_LLM_MODE", "openai")
    monkeypatch.setenv("STORY_ENGINE_LLM_API_KEY", "test-key")
    monkeypatch.setenv("STORY_ENGINE_LLM_MODEL", "base-model")
    pool = LLMPool()
    body_captured = {}

    class _FakeResp:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": "ok"}}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1}}

    class _FakeClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, *, headers=None, json=None):
            body_captured.update(json)
            return _FakeResp()

    monkeypatch.setattr("story_engine.kernel.llm_pool.httpx.AsyncClient",
                        _FakeClient)
    resp = await pool._openai_call("prompt", 0.5, 1000, model="critic-strong")
    assert body_captured["model"] == "critic-strong"
    assert resp.model == "critic-strong"

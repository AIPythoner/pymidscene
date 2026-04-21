from __future__ import annotations

from typing import Any

from pymidscene.core.ai_model.models.qwen import QwenVLModel


def test_qwen_model_passes_qwen_family_to_service_caller(monkeypatch: Any) -> None:
    captured: dict[str, Any] = {}

    def fake_call_ai(*, messages: list[dict[str, Any]], model_config: Any, stream: bool, on_chunk: Any) -> dict[str, Any]:
        captured["messages"] = messages
        captured["model_config"] = model_config
        captured["stream"] = stream
        captured["on_chunk"] = on_chunk
        return {"content": '{"ok": true}', "usage": None, "isStreamed": False}

    monkeypatch.setattr("pymidscene.core.ai_model.models.qwen.call_ai", fake_call_ai)

    model = QwenVLModel(model_name="qwen-vl-max", api_key="test-key")
    result = model.call([
        {"role": "user", "content": "hello"},
    ])

    assert result["content"] == '{"ok": true}'
    assert captured["model_config"].model_family == "qwen2.5-vl"
    assert captured["model_config"].model_name == "qwen-vl-max"


def test_qwen_model_from_env_uses_default_base_url(monkeypatch: Any) -> None:
    monkeypatch.setenv("MIDSCENE_QWEN_API_KEY", "env-key")
    monkeypatch.delenv("MIDSCENE_QWEN_BASE_URL", raising=False)

    model = QwenVLModel.from_env("qwen-vl-max")

    assert model.api_key == "env-key"
    assert model.base_url == QwenVLModel.DEFAULT_BASE_URL

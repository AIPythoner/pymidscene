from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from pymidscene.core.ai_model import service_caller
from pymidscene.core.ai_model.service_caller import ModelConfig


class _FakeCompletionClient:
    def __init__(self, response: Any) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self.response


class _FakeChatClient:
    def __init__(self, response: Any) -> None:
        self.completions = _FakeCompletionClient(response)


class _FakeOpenAIClient:
    def __init__(self, response: Any) -> None:
        self.chat = _FakeChatClient(response)


def _make_response(
    *,
    content: str | None,
    reasoning_content: str | None = None,
    usage: Any = None,
) -> SimpleNamespace:
    message = SimpleNamespace(
        content=content,
        reasoning_content=reasoning_content,
    )
    choice = SimpleNamespace(message=message)
    return SimpleNamespace(choices=[choice], usage=usage)


def test_safe_parse_json_with_repair_normalizes_repaired_json() -> None:
    parsed = service_caller.safe_parse_json_with_repair(
        '{type: " Tap ", param: {" prompt ": " Login button "}}'
    )

    assert parsed == {
        "type": "Tap",
        "param": {"prompt": "Login button"},
    }


def test_safe_parse_json_with_repair_raises_on_invalid_json(monkeypatch: Any) -> None:
    monkeypatch.setattr(service_caller, "repair_json", lambda _value: "still invalid json")

    try:
        service_caller.safe_parse_json_with_repair("{broken")
    except ValueError as exc:
        assert "failed to parse LLM response into JSON" in str(exc)
    else:
        raise AssertionError("Expected ValueError for invalid JSON")


def test_call_ai_returns_reasoning_content(monkeypatch: Any) -> None:
    response = _make_response(
        content='{"result": "ok"}',
        reasoning_content="chain of thought summary",
        usage=SimpleNamespace(
            prompt_tokens=11,
            completion_tokens=7,
            total_tokens=18,
            prompt_tokens_details=SimpleNamespace(cached_tokens=3),
        ),
    )
    fake_client = _FakeOpenAIClient(response)

    monkeypatch.setattr(service_caller, "create_chat_client", lambda _config: fake_client)

    result = service_caller.call_ai(
        messages=[{"role": "user", "content": "hello"}],
        model_config=ModelConfig(model_name="test-model", retry_count=0),
    )

    assert result["content"] == '{"result": "ok"}'
    assert result["reasoning_content"] == "chain of thought summary"
    assert result["usage"].total_tokens == 18
    assert result["usage"].cached_input == 3


def test_call_ai_rejects_empty_content(monkeypatch: Any) -> None:
    fake_client = _FakeOpenAIClient(_make_response(content=""))

    monkeypatch.setattr(service_caller, "create_chat_client", lambda _config: fake_client)

    try:
        service_caller.call_ai(
            messages=[{"role": "user", "content": "hello"}],
            model_config=ModelConfig(model_name="test-model", retry_count=0),
        )
    except ValueError as exc:
        assert "empty content from AI model" in str(exc)
    else:
        raise AssertionError("Expected ValueError for empty model content")


def test_call_ai_applies_qwen_high_resolution_by_model_family(monkeypatch: Any) -> None:
    response = _make_response(content='{"result": "ok"}')
    fake_client = _FakeOpenAIClient(response)

    monkeypatch.setattr(service_caller, "create_chat_client", lambda _config: fake_client)

    service_caller.call_ai(
        messages=[{"role": "user", "content": "hello"}],
        model_config=ModelConfig(
            model_name="custom-vision-model",
            model_family="qwen2.5-vl",
            retry_count=0,
        ),
    )

    assert fake_client.chat.completions.calls[0]["extra_body"] == {
        "vl_high_resolution_images": True,
    }

import json
import urllib.error

import pytest

from services.OllamaSummarizationService import OllamaSummarizationService


class FakeOllamaResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_supported_models_allow_requested_v1_models():
    assert OllamaSummarizationService.is_supported_model("qwen3:8b")
    assert OllamaSummarizationService.is_supported_model("llama3.1:8b")
    assert not OllamaSummarizationService.is_supported_model("qwen3")
    assert not OllamaSummarizationService.is_supported_model("mistral")


def test_summarize_posts_to_ollama_and_parses_response(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return FakeOllamaResponse(
            {
                "response": json.dumps(
                    {
                        "title": "Local Summary",
                        "tags": ["local", "ollama"],
                        "summary": "A local model produced this.",
                    }
                )
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    service = OllamaSummarizationService(base_url="http://localhost:11434", model="qwen3:8b", timeout_seconds=12)

    result = service.summarize("Transcript text", "Summarize clearly.", model="llama3.1:8b")

    assert captured["url"] == "http://localhost:11434/api/generate"
    assert captured["timeout"] == 12
    assert captured["payload"]["model"] == "llama3.1:8b"
    assert captured["payload"]["format"] == "json"
    assert result["title"] == "Local Summary"
    assert result["tags"] == ["local", "ollama"]
    assert result["summary"] == "A local model produced this."


def test_summarize_rejects_unsupported_model():
    service = OllamaSummarizationService(model="not-supported")

    with pytest.raises(ValueError, match="Unsupported local summary model"):
        service.summarize("Transcript", "Prompt")


def test_summarize_reports_ollama_connection_failure(monkeypatch):
    def fake_urlopen(request, timeout):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    service = OllamaSummarizationService(base_url="http://localhost:11434", model="qwen3:8b")

    with pytest.raises(RuntimeError, match="Is Ollama running"):
        service.summarize("Transcript", "Prompt")

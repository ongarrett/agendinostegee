from pathlib import Path

from models.dto.SummarizeRequestDTO import SummarizeRequestDTO

REPO_ROOT = Path(__file__).resolve().parents[3]
DASHBOARD_JS = REPO_ROOT / "src" / "static" / "dashboard.js"
QUEUE_JS = REPO_ROOT / "src" / "static" / "processing_queue.js"


def test_single_summary_request_defaults_to_local_qwen_model():
    request = SummarizeRequestDTO(prompt_id="prompt")

    assert request.summary_provider == "local"
    assert request.summary_model == "qwen3:8b"


def test_summary_picker_defaults_to_local_ai_and_keeps_gemini_optional():
    source = DASHBOARD_JS.read_text()

    assert 'const defaultProvider = "local";' in source
    assert (
        '<option value="local" ${defaultProvider === "local" ? "selected" : ""}>Local AI (Ollama)</option>' in source
    )
    assert '<option value="gemini" ${defaultProvider === "gemini" ? "selected" : ""}>Gemini</option>' in source


def test_summary_picker_uses_exact_local_model_value():
    source = DASHBOARD_JS.read_text()

    assert 'const provider = $("#summary-provider-select")?.value || "local";' in source
    assert 'const model = $("#summary-local-model-select")?.value || "qwen3:8b";' in source
    assert '<option value="qwen3:8b">qwen3:8b</option>' in source


def test_summary_notifications_are_provider_specific():
    source = DASHBOARD_JS.read_text()

    assert "function summaryProviderLabel(providerConfig)" in source
    assert "Local AI / Ollama" in source
    assert 'return "Gemini";' in source
    assert "Generating summary with ${providerLabel}" in source
    assert "Generating summaries with ${providerLabel}" in source


def test_local_summary_errors_include_ollama_setup_commands():
    source = DASHBOARD_JS.read_text()

    assert "ollama serve" in source
    assert "ollama pull qwen3:8b" in source


def test_processing_queue_labels_local_summaries_with_model():
    source = QUEUE_JS.read_text()

    assert "function jobProviderLabel(job)" in source
    assert "Local AI / Ollama" in source
    assert "job.summary_model" in source
    assert "Gemini" in source

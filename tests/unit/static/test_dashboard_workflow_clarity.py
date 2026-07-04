from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_dashboard_transcription_defaults_to_local_whisper():
    source = (ROOT / "src/static/dashboard.js").read_text()

    assert 'data-engine="whisper" title="Transcribe with local Whisper"' in source
    assert 'const engine = transcribeBtn.dataset.engine || "whisper";' in source
    assert 'const engine = engineItem.dataset.engine || "whisper";' in source
    assert "Gemini optional" in source


def test_dashboard_archive_progress_copy_is_operational():
    source = (ROOT / "src/templates/dashboard/home.html").read_text()

    assert "Archive Progress" in source
    assert "awaiting transcription" in source
    assert "Transcribe Awaiting" in source
    assert "Generate Missing Embeddings" in source
    assert "View Failures" in source
    assert "> pending<" not in source


def test_processing_queue_description_explains_generic_ledger_role():
    source = (ROOT / "src/templates/dashboard/processing_queue.html").read_text()

    assert "Processing Queue shows queued and historical jobs across transcription and summary workflows." in source


def test_summary_pipeline_description_explains_batch_summary_role():
    source = (ROOT / "src/templates/dashboard/summary_pipeline.html").read_text()

    assert (
        "Summary Pipeline is the durable batch workspace for generating missing summaries "
        "using Local AI / Ollama by default."
    ) in source

# Summarization

Generate structured AI summaries from transcripts using Google Gemini or local Ollama models with customizable system prompts.

![Summarization](screenshots/summarization.png)

---

## Overview

Once a recording has been transcribed, you can generate a structured summary using Gemini or local AI through Ollama. Summaries include a **title**, **tags**, and a **full markdown body**. You can create multiple summary versions per recording using different system prompts.

## How It Works

1. Make sure the recording has been transcribed first.
2. Click **Summarize** and choose a summary provider:
   - **Local AI (Ollama)** for local generation with `qwen3:8b` or `llama3.1:8b`.
   - **Gemini** for explicit cloud generation.
3. Choose a **system prompt** from the available categories (e.g. `Generale / SintesiAdattiva`, `IT&Engineering / VerbaleIT`).
4. The selected provider generates a structured JSON response containing:
   - **Title** - a concise summary title.
   - **Tags** - relevant keywords for categorization.
   - **Summary** - full markdown content with sections, bullet points, and structure defined by the prompt.
5. The result is saved to the database using the same summary version format.

## Local Ollama Setup

Install and start Ollama, then pull at least one supported model:

```bash
ollama pull qwen3:8b
ollama pull llama3.1:8b
```

Optional `.env` settings:

```env
SUMMARY_PROVIDER=local
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_SUMMARY_MODEL=qwen3:8b
```

Local summary generation requires Ollama to be running at `OLLAMA_BASE_URL`. Batch summarization and queued summary jobs default to **Local AI** and preserve the selected provider and model. Single-recording summaries still allow Gemini or Local AI from the same prompt picker.

If local summary jobs fail because Ollama is not running or the model is missing, AgenDino reports:

```text
Local AI/Ollama is not available. Start Ollama with `ollama serve` and confirm qwen3:8b is installed.
```

## Summary Pipeline

Open **Summary Pipeline** from the left navigation to process large archives safely over multiple sessions.

The pipeline:
- Shows missing, ready, queued, running, completed, failed, and skipped counts.
- Uses **Local AI / Ollama / `qwen3:8b`** by default.
- Allows Gemini only when selected in the provider dropdown.
- Queues the next 25, next 50, or all missing summaries.
- Persists jobs in SQLite so pending work survives server restarts.
- Supports pause, resume, retry failed, and clear completed jobs.
- Skips queued jobs if a summary already exists by the time the job runs.

The existing dashboard **Generate Missing Summaries** button now queues work through the Summary Pipeline instead of running a long synchronous archive summarization request.

## Multiple Summary Versions

You can re-summarize the same recording with a different prompt at any time. Each summary is saved as a separate version - previous summaries are never overwritten.

This is useful when you want different perspectives on the same meeting (e.g. an executive recap vs. a detailed action tracker).

## Editing Summaries

After generation, you can inline-edit:
- **Title** - click to edit.
- **Tags** - add, remove, or modify tags.
- **Content** - edit the full markdown body.

All changes are saved to the database.

## System Prompts

Summaries are shaped by the system prompt you choose. See [Custom System Prompts](custom-system-prompts.md) for how to add your own.

---

**Related:** [Transcription](transcription.md) · [Task Generation](task-generation.md) · [Custom System Prompts](custom-system-prompts.md)

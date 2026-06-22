# Summarization

Generate structured AI summaries from transcripts using Google Gemini or local Ollama models with customizable system prompts.

![Summarization](screenshots/summarization.png)

---

## Overview

Once a recording has been transcribed, you can generate a structured summary using Gemini or local AI through Ollama. Summaries include a **title**, **tags**, and a **full markdown body**. You can create multiple summary versions per recording using different system prompts.

## How It Works

1. Make sure the recording has been transcribed first.
2. Click **Summarize** and choose a summary provider:
   - **Gemini** for cloud generation.
   - **Local AI (Ollama)** for local generation with `llama3.1`, `qwen3`, or `mistral`.
3. Choose a **system prompt** from the available categories (e.g. `Generale / SintesiAdattiva`, `IT&Engineering / VerbaleIT`).
4. The selected provider generates a structured JSON response containing:
   - **Title** - a concise summary title.
   - **Tags** - relevant keywords for categorization.
   - **Summary** - full markdown content with sections, bullet points, and structure defined by the prompt.
5. The result is saved to the database using the same summary version format.

## Local Ollama Setup

Install and start Ollama, then pull at least one supported model:

```bash
ollama pull llama3.1
ollama pull qwen3
ollama pull mistral
```

Optional `.env` settings:

```env
SUMMARY_PROVIDER=gemini
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_SUMMARY_MODEL=llama3.1
```

Local summary generation requires Ollama to be running at `OLLAMA_BASE_URL`. Batch summarization and queued summary jobs preserve the selected provider and model.

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

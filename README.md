# AgenDino

[![Tests](https://github.com/DStt/agendino/actions/workflows/tests.yml/badge.svg)](https://github.com/DStt/agendino/actions/workflows/tests.yml)
[![Style](https://github.com/DStt/agendino/actions/workflows/style.yml/badge.svg)](https://github.com/DStt/agendino/actions/workflows/style.yml)

AgenDino is a web-based dashboard for managing, transcribing, and summarizing audio recordings from [HiDock](https://www.hidock.com/) USB devices. It uses Google Gemini, local Whisper, and optional local Ollama models for AI-powered transcription, summarization, task extraction, and knowledge retrieval - all from a single self-hosted interface.

![Dashboard](docs/screenshots/dashboard.png)

## Features

| Feature | Description |
|---------|-------------|
| [HiDock USB Integration](docs/hidock-integration.md) | Detect, sync, and manage recordings from HiDock H1 / H1E / P1 devices |
| [Recording Management](docs/recording-management.md) | Upload, organize with folders, play back, and delete audio files |
| [AI Transcription](docs/transcription.md) | Cloud (Gemini) and local (Whisper) speech-to-text with speaker diarization |
| [AI Summarization](docs/summarization.md) | Structured summaries with Gemini or local Ollama models, customizable prompts, and multiple versions |
| [Task Generation](docs/task-generation.md) | Extract Jira-style tasks and subtasks from meeting summaries |
| [Calendar](docs/calendar.md) | Manual events, iCal subscriptions (Google Calendar, Outlook), recording linking |
| [Daily Recap](docs/daily-recap.md) | AI-generated end-of-day narrative from events and meetings |
| [Proactive Analysis](docs/proactive-analysis.md) | Detect schedule conflicts, back-to-back meetings, and overloaded days |
| [Knowledge Base](docs/knowledge-base.md) | RAG search and Q&A over all your summaries, plus interactive mind maps |
| [Notion Publishing](docs/notion-publishing.md) | Publish summaries as rich Notion sub-pages |
| [Authentication](docs/authentication.md) | Optional single-user login with session cookies and IP banning |
| [Custom Prompts](docs/custom-system-prompts.md) | Add your own summarization prompts organized by language and category |

## Quick Start

```bash
git clone https://github.com/DStt/agendino.git
cd agendino
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

Create a `.env` file with your Gemini API key:

```env
GEMINI_API_KEY=your-gemini-api-key
```

Start the server:

```bash
cd src
fastapi dev main.py
```

Open **http://127.0.0.1:8000** in your browser.

→ Full setup guide: [Getting Started](docs/getting-started.md)

### Optional Local Summaries With Ollama

Install and start [Ollama](https://ollama.com/), then pull one or more supported models:

```bash
ollama pull llama3.1
ollama pull qwen3
ollama pull mistral
```

In the summarization prompt picker, choose **Local AI (Ollama)** and select `llama3.1`, `qwen3`, or `mistral`. Optional `.env` settings:

```env
SUMMARY_PROVIDER=gemini
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_SUMMARY_MODEL=llama3.1
```

## Private Remote Access With Tailscale

To use AgenDino from another device on your private Tailscale network, keep Tailscale running on this Mac and on the other device, then run:

```bash
make serve-tailnet
```

Or run the helper directly:

```bash
./scripts/serve-tailnet
```

The helper starts the same FastAPI app on `0.0.0.0:8000` so tailnet devices can reach it. If the Tailscale CLI is available, it prints this Mac's Tailscale IP and the URL to open:

```text
http://<tailscale-ip>:8000
```

This is intended for private tailnet access only. It does not enable Tailscale Funnel and does not publish AgenDino to the public internet. Stop the server with `Ctrl+C`.

## Documentation

Browse the full documentation at **[docs/index.md](docs/index.md)**.

| Section | Topics |
|---------|--------|
| **Setup** | [Getting Started](docs/getting-started.md) |
| **Core** | [HiDock](docs/hidock-integration.md) · [Recordings](docs/recording-management.md) · [Calendar](docs/calendar.md) |
| **AI** | [Transcription](docs/transcription.md) · [Summarization](docs/summarization.md) · [Tasks](docs/task-generation.md) · [Recap](docs/daily-recap.md) · [Knowledge](docs/knowledge-base.md) · [Proactor](docs/proactive-analysis.md) |
| **Advanced** | [Notion](docs/notion-publishing.md) · [Auth](docs/authentication.md) · [Prompts](docs/custom-system-prompts.md) |
| **Reference** | [API Endpoints](docs/api-reference.md) · [Project Structure](docs/project-structure.md) |

## Running Tests

```bash
pytest
```

## License

This project is for personal use.

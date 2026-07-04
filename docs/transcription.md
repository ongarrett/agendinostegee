# Transcription

Convert audio recordings to text using local Whisper by default, with Gemini available when explicitly selected.

![Transcription](screenshots/transcription.png)

---

## Overview

AgenDino offers two transcription engines. **Local Whisper is the default** for dashboard transcription actions. Gemini remains available from the engine dropdown when you explicitly want cloud transcription.

## Engine Comparison

| Feature | Whisper (Local) | Gemini (Cloud) |
|---------|---------------|-----------------|
| **Runs on** | Your machine | Google Cloud |
| **Speaker diarization** | ❌ Not included | ✅ Automatic |
| **Speaker labels** | ❌ No | ✅ Yes |
| **Timestamps** | ✅ Yes | ✅ Yes |
| **Long recordings** | ✅ Full transcription | ⚠️ May truncate |
| **Privacy** | Fully offline | Audio sent to Google |
| **First-use setup** | Model download (~500 MB for `small`) | Gemini API key |
| **Speed** | Depends on hardware | Fast (cloud) |

## Using Whisper Transcription

1. Select a recording.
2. Click the **Transcribe** button (microphone icon).
3. On first use, the Whisper model is downloaded automatically.
4. Transcription runs entirely on your machine - no audio is uploaded.

## Using Gemini Transcription

1. Select a synced or uploaded recording.
2. Click the **dropdown arrow** next to the Transcribe button and choose **Gemini**.
3. Gemini processes the audio and returns a transcript with speaker diarization, labels, and timestamps.
4. The transcript is saved to the database.

### Whisper Configuration

Configure Whisper via environment variables in `.env`:

| Variable | Default | Options |
|----------|---------|---------|
| `WHISPER_MODEL_SIZE` | `small` | `tiny`, `base`, `small`, `medium`, `large-v3` |
| `WHISPER_DEVICE` | `cpu` | `cpu`, `cuda` (requires NVIDIA GPU + CUDA toolkit) |
| `WHISPER_COMPUTE_TYPE` | `auto` | `auto`, `int8`, `float16`, `float32` |

Larger models produce better accuracy but require more RAM and processing time. The `small` model is a good balance for most use cases.

## Editing Transcripts

After transcription, you can edit the transcript text directly from the dashboard. Changes are saved to the database.

---

**Related:** [Summarization](summarization.md) · [Recording Management](recording-management.md)

from __future__ import annotations

import os
import time
import csv
from io import StringIO
from datetime import datetime

from fastapi import Request
from fastapi.templating import Jinja2Templates

from models.DBRecording import DBRecording
from models.DBTask import DBTask
from repositories.LocalRecordingsRepository import LocalRecordingsRepository, ALLOWED_AUDIO_EXTENSIONS
from repositories.SqliteDBRepository import SqliteDBRepository
from repositories.SystemPromptsRepository import SystemPromptsRepository
from services.SummarizationService import SummarizationService
from services.TaskGenerationService import TaskGenerationService
from services.TranscriptionService import TranscriptionService
from services.WhisperTranscriptionService import WhisperTranscriptionService
from services.OllamaSummarizationService import OllamaSummarizationService

VERY_SHORT_DURATION_SECONDS = 10

MIME_TYPES = {
    "hda": "audio/mpeg",
    "mp3": "audio/mpeg",
    "wav": "audio/wav",
    "m4a": "audio/mp4",
    "ogg": "audio/ogg",
    "webm": "audio/webm",
    "flac": "audio/flac",
    "aac": "audio/aac",
    "wma": "audio/x-ms-wma",
}


class DashboardController:
    def __init__(
        self,
        sqlite_db_repository: SqliteDBRepository,
        local_recordings_repository: LocalRecordingsRepository,
        transcription_service: TranscriptionService,
        summarization_service: SummarizationService,
        task_generation_service: TaskGenerationService,
        system_prompts_repository: SystemPromptsRepository,
        template_path: str,
        publish_services: dict[str, object] | None = None,
        whisper_transcription_service: WhisperTranscriptionService | None = None,
        ollama_summarization_service: OllamaSummarizationService | None = None,
        default_summary_provider: str = "local",
        default_ollama_summary_model: str = "qwen3:8b",
        auth_enabled: bool = False,
    ):
        self._sqlite_db_repository = sqlite_db_repository
        self._local_recordings_repository = local_recordings_repository
        self._transcription_service = transcription_service
        self._summarization_service = summarization_service
        self._task_generation_service = task_generation_service
        self._system_prompts_repository = system_prompts_repository
        self._templates = Jinja2Templates(directory=template_path)
        self._publish_services: dict[str, object] = publish_services or {}
        self._whisper_transcription_service = whisper_transcription_service
        self._ollama_summarization_service = ollama_summarization_service
        self._default_summary_provider = default_summary_provider
        self._default_ollama_summary_model = default_ollama_summary_model
        self._auth_enabled = auth_enabled

    @staticmethod
    def _bare_name(name: str) -> str:
        """Strip any known audio extension from the filename."""
        root, ext = os.path.splitext(name)
        if ext.lower() in ALLOWED_AUDIO_EXTENSIONS:
            return root
        return name

    @staticmethod
    def _parse_recording_datetime(bare_name: str) -> str | None:
        try:
            parts = bare_name.split("-")
            if len(parts) >= 2:
                dt_str = f"{parts[0]}-{parts[1]}"
                dt = datetime.strptime(dt_str, "%Y%b%d-%H%M%S")
                return dt.strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, IndexError):
            pass
        return None

    def home(self, request: Request):
        return self._templates.TemplateResponse(
            request=request,
            name="dashboard/home.html",
            context={"active_page": "dashboard", "auth_enabled": self._auth_enabled},
        )

    def list_local_recordings(self):
        return self._local_recordings_repository.get_all()

    @staticmethod
    def _transcription_status_message(status: str | None) -> str:
        messages = {
            "corrupt_audio": "This file could not be decoded. It may be damaged or unsupported.",
            "no_speech_detected": "Whisper completed but detected no speech segments.",
            "retryable_failure": "This appears retryable. You can run Retry Failed Only.",
            "pending": "No transcript found. This recording has not been transcribed yet.",
            "very_short": "This recording is very short or has only a few transcript segments.",
            "transcribed": "Successfully transcribed.",
            "unknown": "The transcription state is unknown.",
        }
        return messages.get(status or "unknown", messages["unknown"])

    @staticmethod
    def _archive_health_counts(recordings: list[dict]) -> dict:
        db_recordings = [rec for rec in recordings if rec.get("in_db")]
        counts = {
            "total_recordings": len(recordings),
            "transcribed": 0,
            "pending_transcription": 0,
            "awaiting_transcription": 0,
            "retryable_failures": 0,
            "no_speech_detected": 0,
            "corrupt_audio": 0,
            "very_short": 0,
            "unknown_transcription": 0,
            "missing_summaries": 0,
            "missing_embeddings": 0,
            "indexed": 0,
        }
        for rec in db_recordings:
            status = rec.get("transcription_status") or "unknown"
            if rec.get("has_transcript"):
                counts["transcribed"] += 1
            elif status in ("pending", "retryable_failure", "unknown"):
                counts["awaiting_transcription"] += 1
            if status == "pending":
                counts["pending_transcription"] += 1
            elif status == "retryable_failure":
                counts["retryable_failures"] += 1
            elif status == "no_speech_detected":
                counts["no_speech_detected"] += 1
            elif status == "corrupt_audio":
                counts["corrupt_audio"] += 1
            elif status == "very_short":
                counts["very_short"] += 1
            elif status == "unknown":
                counts["unknown_transcription"] += 1
            if rec.get("has_transcript") and not rec.get("has_summary"):
                counts["missing_summaries"] += 1
            if rec.get("embedding_status") == "indexed":
                counts["indexed"] += 1
            else:
                counts["missing_embeddings"] += 1
        return counts

    @staticmethod
    def _work_remaining_recommendation(counts: dict) -> dict:
        if counts.get("awaiting_transcription", 0) > 0:
            return {
                "key": "transcribe",
                "label": "Next: Transcribe awaiting recordings",
                "action": "transcribe_awaiting",
            }
        if counts.get("missing_summaries", 0) > 0:
            return {
                "key": "summaries",
                "label": "Next: Generate missing summaries",
                "action": "generate_missing_summaries",
            }
        if counts.get("missing_embeddings", 0) > 0:
            return {
                "key": "embeddings",
                "label": "Next: Generate embeddings",
                "action": "index_unindexed",
            }
        return {
            "key": "complete",
            "label": "Archive is fully processed",
            "action": None,
        }

    def get_recordings_status(self) -> dict:
        local_files = self._local_recordings_repository.get_all()
        db_recordings = self._sqlite_db_repository.get_recordings()
        latest_summaries = self._sqlite_db_repository.get_latest_summaries_map()
        collections = self._sqlite_db_repository.get_collections_with_counts()
        recording_collections = self._sqlite_db_repository.get_recording_collections_map()
        saved_views = self._sqlite_db_repository.get_saved_views()
        embedding_statuses = self._sqlite_db_repository.get_recording_embedding_status_map()

        # Map bare name → local filename (preserving actual extension)
        local_map: dict[str, str] = {}
        for f in local_files:
            local_map[self._bare_name(f)] = f

        db_map = {self._bare_name(r.name): r for r in db_recordings}

        all_names = set()
        all_names.update(local_map.keys())
        all_names.update(db_map.keys())

        recordings = []
        for bare_name in sorted(
            all_names,
            key=lambda n: (
                db_map.get(n).recorded_at
                if db_map.get(n) and db_map.get(n).recorded_at
                else self._parse_recording_datetime(n) or ""
            ),
            reverse=True,
        ):
            on_local = bare_name in local_map
            db_rec = db_map.get(bare_name)
            latest_summary = latest_summaries.get(bare_name)

            # Determine file extension
            file_ext = "hda"
            if db_rec:
                file_ext = db_rec.file_extension
            elif on_local:
                _, ext = os.path.splitext(local_map[bare_name])
                file_ext = ext.lstrip(".").lower() if ext else "hda"

            # Parse date/time: DB recorded_at > name-parsed date
            rec_date = None
            rec_time = None
            db_recorded_at = db_rec.recorded_at if db_rec else None
            if db_recorded_at:
                parts = db_recorded_at.split(" ", 1)
                rec_date = parts[0]
                rec_time = parts[1] if len(parts) > 1 else None
            if not rec_date:
                parsed_dt = self._parse_recording_datetime(bare_name)
                if parsed_dt:
                    rec_date, rec_time = parsed_dt.split(" ", 1)

            # Duration from DB
            duration = None
            if db_rec and db_rec.duration and db_rec.duration > 0:
                duration = db_rec.duration

            # Size from local file
            size = None
            if on_local:
                local_filename = local_map[bare_name]
                size = self._local_recordings_repository.get_file_size(local_filename)

            recordings.append(
                {
                    "name": bare_name,
                    "on_device": False,
                    "on_local": on_local,
                    "in_db": db_rec is not None,
                    "file_extension": file_ext,
                    "duration": duration,
                    "size": size,
                    "date": rec_date,
                    "time": rec_time,
                    "recorded_at": db_recorded_at,
                    "recording_type": None,
                    "db_label": db_rec.label if db_rec else None,
                    "db_id": db_rec.id if db_rec else None,
                    "db_title": latest_summary.title if latest_summary else None,
                    "db_tags": latest_summary.tags.split(",") if latest_summary and latest_summary.tags else [],
                    "has_transcript": (
                        db_rec.transcript is not None and len(db_rec.transcript) > 0 if db_rec else False
                    ),
                    "has_summary": latest_summary is not None,
                    "summary_count": len(self._sqlite_db_repository.get_summaries(bare_name)) if db_rec else 0,
                    "notion_url": latest_summary.notion_url if latest_summary else None,
                    "folder": db_rec.folder if db_rec else "/",
                    "collections": recording_collections.get(bare_name, []),
                    "collection_ids": [c["id"] for c in recording_collections.get(bare_name, [])],
                    "embedding_status": embedding_statuses.get(bare_name, {}).get("status", "not indexed"),
                    "embedding_model": embedding_statuses.get(bare_name, {}).get("model"),
                    "embedding_error": embedding_statuses.get(bare_name, {}).get("error"),
                    "embedding_indexed_at": embedding_statuses.get(bare_name, {}).get("indexed_at"),
                    "transcription_status": db_rec.transcription_status if db_rec else "pending",
                    "transcription_error": db_rec.transcription_error if db_rec else None,
                    "transcription_attempted_at": db_rec.transcription_attempted_at if db_rec else None,
                    "transcription_segment_count": db_rec.transcription_segment_count if db_rec else None,
                    "transcription_language": db_rec.transcription_language if db_rec else None,
                    "transcription_language_probability": (
                        db_rec.transcription_language_probability if db_rec else None
                    ),
                    "transcription_skipped": db_rec.transcription_skipped if db_rec else False,
                    "transcription_message": self._transcription_status_message(
                        db_rec.transcription_status if db_rec else "pending"
                    ),
                }
            )

        # Build folder tree
        folders = self._sqlite_db_repository.get_recording_folders()

        archive_counts = self._archive_health_counts(recordings)
        summary_pipeline = self._sqlite_db_repository.get_summary_pipeline_status(
            provider="local",
            model=self._default_ollama_summary_model,
        )
        summary_counts = summary_pipeline.get("counts", {})
        archive_counts["summary_queued"] = summary_counts.get("queued", summary_counts.get("pending", 0))
        archive_counts["summary_failed"] = summary_counts.get("failed", 0)

        return {
            "device": {
                "connected": False,
                "model": None,
            },
            "storage": None,
            "counts": {
                "device": 0,
                "local": len(local_files),
                "db": len(db_recordings),
                **archive_counts,
            },
            "recordings": recordings,
            "folders": folders,
            "collections": collections,
            "saved_views": saved_views,
            "summary_pipeline": summary_pipeline,
            "work_remaining": self._work_remaining_recommendation(archive_counts),
        }

    def upload_recording(self, filename: str, file_data: bytes, label: str = "") -> dict:
        """Save an uploaded audio file locally and insert a DB record."""
        _, ext = os.path.splitext(filename)
        ext_lower = ext.lower()
        if ext_lower not in ALLOWED_AUDIO_EXTENSIONS:
            allowed = ", ".join(sorted(ALLOWED_AUDIO_EXTENSIONS))
            return {"ok": False, "error": f"Unsupported file type '{ext}'. Allowed: {allowed}"}

        file_ext = ext_lower.lstrip(".")
        bare_name = self._bare_name(filename)

        # Reject duplicates
        if self._local_recordings_repository.exists(filename):
            return {"ok": False, "error": f"A file named '{filename}' already exists"}
        if self._sqlite_db_repository.get_recording_by_name(bare_name):
            return {"ok": False, "error": f"A recording named '{bare_name}' already exists in the database"}

        # Save file to local_recordings
        self._local_recordings_repository.save(filename, file_data)

        # Extract audio duration using mutagen
        duration = self._get_audio_duration(self._local_recordings_repository.get_path(filename))

        # Insert DB record
        db_rec = DBRecording(
            id=None,
            name=bare_name,
            label=label or bare_name,
            duration=duration,
            file_extension=file_ext,
            created_at=datetime.now(),
        )
        new_id = self._sqlite_db_repository.insert_recording(db_rec)

        return {
            "ok": True,
            "name": bare_name,
            "file_extension": file_ext,
            "db_id": new_id,
            "message": f"Uploaded '{filename}' successfully",
        }

    @staticmethod
    def _get_audio_duration(file_path: str) -> int:
        """Extract audio duration in seconds using mutagen. Returns 0 on failure."""
        try:
            from mutagen import File as MutagenFile

            audio = MutagenFile(file_path)
            if audio and audio.info and audio.info.length:
                return int(audio.info.length)
        except Exception:
            pass
        return 0

    def update_recording_datetime(self, name: str, recorded_at: str) -> dict:
        """Update the recorded_at datetime for a recording."""
        bare_name = self._bare_name(name)
        # Validate datetime format
        try:
            datetime.strptime(recorded_at, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            try:
                datetime.strptime(recorded_at, "%Y-%m-%d %H:%M")
                recorded_at = f"{recorded_at}:00"
            except ValueError:
                return {"ok": False, "error": "Invalid datetime format. Use YYYY-MM-DD HH:MM:SS or YYYY-MM-DD HH:MM"}

        updated = self._sqlite_db_repository.update_recording(bare_name, recorded_at=recorded_at)
        if not updated:
            return {"ok": False, "error": f"Recording '{bare_name}' not found"}
        return {"ok": True, "name": bare_name, "recorded_at": recorded_at}

    def delete_recording(
        self,
        name: str,
        delete_local: bool,
        delete_db: bool,
    ) -> dict:
        bare_name = self._bare_name(name)
        db_rec = self._sqlite_db_repository.get_recording_by_name(bare_name)
        file_ext = db_rec.file_extension if db_rec else "hda"
        local_filename = f"{bare_name}.{file_ext}"
        results = []
        errors = []

        if delete_local:
            deleted = self._local_recordings_repository.delete(local_filename)
            if deleted:
                results.append("local file")
            else:
                errors.append("Local file not found")

        if delete_db:
            deleted = self._sqlite_db_repository.delete_recording(bare_name)
            if deleted:
                results.append("database record")
            else:
                errors.append("Database record not found")

        if errors and not results:
            return {"ok": False, "error": "; ".join(errors)}

        message = f"Deleted '{bare_name}' from: {', '.join(results)}"
        if errors:
            message += f" (warnings: {'; '.join(errors)})"

        return {"ok": True, "message": message, "deleted": results, "warnings": errors}

    def _resolve_local_filename(self, bare_name: str) -> tuple[str, str]:
        """Return (local_filename, file_extension) for a recording.

        Checks the DB first, then scans local files for any known extension.
        """
        db_rec = self._sqlite_db_repository.get_recording_by_name(bare_name)
        if db_rec:
            ext = db_rec.file_extension
            local_name = f"{bare_name}.{ext}"
            if self._local_recordings_repository.exists(local_name):
                return local_name, ext

        # Fallback: scan local files for any known extension
        for ext_dot in ALLOWED_AUDIO_EXTENSIONS:
            candidate = f"{bare_name}{ext_dot}"
            if self._local_recordings_repository.exists(candidate):
                return candidate, ext_dot.lstrip(".")
        return f"{bare_name}.hda", "hda"

    def transcribe_recording(self, name: str, engine: str = "whisper") -> dict:
        bare_name = self._bare_name(name)
        local_filename, file_ext = self._resolve_local_filename(bare_name)

        if not self._local_recordings_repository.exists(local_filename):
            return {"ok": False, "error": f"Local file '{local_filename}' not found"}

        db_rec = self._sqlite_db_repository.get_recording_by_name(bare_name)
        if db_rec and db_rec.transcript:
            return {
                "ok": True,
                "transcript": db_rec.transcript,
                "cached": True,
                "transcription_status": db_rec.transcription_status,
            }

        audio_path = self._local_recordings_repository.get_path(local_filename)
        mime_type = MIME_TYPES.get(file_ext, "audio/mpeg")

        # Select transcription engine
        if engine == "whisper":
            if not self._whisper_transcription_service:
                return {"ok": False, "error": "Whisper transcription service is not available"}
            svc = self._whisper_transcription_service
        else:
            svc = self._transcription_service

        try:
            transcript = svc.transcribe(audio_path, mime_type=mime_type)
        except Exception as e:
            error = f"Transcription failed: {str(e)}"
            status = self._classify_transcription_error(error)
            self._sqlite_db_repository.update_transcription_metadata(
                bare_name,
                status,
                error=error,
                attempted=True,
                skipped=False,
            )
            return {
                "ok": False,
                "error": error,
                "transcription_status": status,
                "transcription_message": self._transcription_status_message(status),
            }

        metadata = getattr(svc, "last_result", {}) if engine == "whisper" else {}
        status = self._classify_transcription_success(transcript, db_rec, metadata)
        self._sqlite_db_repository.save_transcript(bare_name, transcript)
        self._sqlite_db_repository.update_transcription_metadata(
            bare_name,
            status,
            error=None,
            segment_count=metadata.get("segment_count"),
            language=metadata.get("language"),
            language_probability=metadata.get("language_probability"),
            vad_removed_duration=metadata.get("vad_removed_duration"),
            attempted=True,
            skipped=False,
        )
        return {
            "ok": True,
            "transcript": transcript,
            "cached": False,
            "transcription_status": status,
            "transcription_message": self._transcription_status_message(status),
            "metadata": metadata,
        }

    @staticmethod
    def _has_saved_transcript(db_rec) -> bool:
        return db_rec is not None and db_rec.transcript is not None and len(db_rec.transcript) > 0

    @staticmethod
    def _classify_transcription_error(error: str) -> str:
        return SqliteDBRepository.classify_transcription_error(error)

    @staticmethod
    def _classify_transcription_success(transcript: str, db_rec: DBRecording | None, metadata: dict) -> str:
        segment_count = metadata.get("segment_count")
        duration = db_rec.duration if db_rec else None
        if not transcript or not transcript.strip() or segment_count == 0:
            return "no_speech_detected"
        if (duration and duration <= VERY_SHORT_DURATION_SECONDS) or (
            segment_count is not None and 1 <= segment_count <= 3
        ):
            return "very_short"
        return "transcribed"

    def list_untranscribed_recordings(self) -> dict:
        recordings = self._sqlite_db_repository.get_recordings()
        untranscribed = []
        for rec in recordings:
            if self._has_saved_transcript(rec):
                continue
            if rec.transcription_status not in ("pending", "retryable_failure", "unknown"):
                continue
            local_filename, _ = self._resolve_local_filename(rec.name)
            if not self._local_recordings_repository.exists(local_filename):
                continue
            untranscribed.append(
                {
                    "name": rec.name,
                    "label": rec.label,
                    "file_extension": rec.file_extension,
                    "recorded_at": rec.recorded_at,
                    "transcription_status": rec.transcription_status,
                    "transcription_error": rec.transcription_error,
                }
            )
        return {"ok": True, "count": len(untranscribed), "recordings": untranscribed}

    def transcribe_recordings(self, names: list[str], engine: str = "whisper") -> dict:
        unique_names = []
        seen = set()
        for name in names:
            bare_name = self._bare_name(name)
            if bare_name and bare_name not in seen:
                unique_names.append(bare_name)
                seen.add(bare_name)

        if not unique_names:
            return {"ok": False, "error": "No recordings selected"}

        results = []
        counts = {
            "transcribed": 0,
            "very_short": 0,
            "no_speech_detected": 0,
            "corrupt_audio": 0,
            "retryable_failure": 0,
            "skipped_existing": 0,
            "failed": 0,
        }

        for bare_name in unique_names:
            db_rec = self._sqlite_db_repository.get_recording_by_name(bare_name)
            if db_rec is None:
                counts["failed"] += 1
                results.append({"name": bare_name, "status": "failed", "error": "Recording not found in database"})
                continue

            if self._has_saved_transcript(db_rec):
                counts["skipped_existing"] += 1
                results.append({"name": bare_name, "status": "skipped_existing"})
                continue

            result = self.transcribe_recording(bare_name, engine=engine)
            if result.get("ok"):
                if result.get("cached"):
                    counts["skipped_existing"] += 1
                    results.append({"name": bare_name, "status": "skipped_existing"})
                elif result.get("transcription_status") == "no_speech_detected":
                    counts["no_speech_detected"] += 1
                    results.append(
                        {
                            "name": bare_name,
                            "status": "no_speech_detected",
                            "message": result.get("transcription_message"),
                        }
                    )
                elif result.get("transcription_status") == "very_short":
                    counts["very_short"] += 1
                    results.append({"name": bare_name, "status": "very_short"})
                else:
                    counts["transcribed"] += 1
                    results.append({"name": bare_name, "status": result.get("transcription_status", "transcribed")})
            else:
                status = result.get("transcription_status", "retryable_failure")
                if status == "corrupt_audio":
                    counts["corrupt_audio"] += 1
                elif status == "retryable_failure":
                    counts["retryable_failure"] += 1
                counts["failed"] += 1
                results.append(
                    {
                        "name": bare_name,
                        "status": status,
                        "error": result.get("error", "Transcription failed"),
                        "message": result.get("transcription_message"),
                    }
                )

        return {"ok": counts["failed"] == 0, "counts": counts, "results": results}

    def transcribe_untranscribed_recordings(self, engine: str = "whisper") -> dict:
        untranscribed = self.list_untranscribed_recordings()
        names = [rec["name"] for rec in untranscribed["recordings"]]
        if not names:
            return {
                "ok": True,
                "counts": {
                    "transcribed": 0,
                    "very_short": 0,
                    "no_speech_detected": 0,
                    "corrupt_audio": 0,
                    "retryable_failure": 0,
                    "skipped_existing": 0,
                    "failed": 0,
                },
                "results": [],
                "message": "No untranscribed local recordings found.",
            }
        return self.transcribe_recordings(names, engine=engine)

    def mark_no_speech_as_skipped(self) -> dict:
        result = self._sqlite_db_repository.mark_no_speech_as_skipped()
        return {
            **result,
            "message": f"Marked {result.get('count', 0)} no-speech recording(s) as skipped.",
        }

    def export_transcription_failure_report_csv(self) -> str:
        rows = self._sqlite_db_repository.get_transcription_failure_report()
        fieldnames = [
            "recording_name",
            "title",
            "date",
            "file_path",
            "transcription_status",
            "segment_count",
            "duration",
            "language",
            "language_probability",
            "error_message",
            "recommended_action",
        ]
        output = StringIO()
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field) for field in fieldnames})
        return output.getvalue()

    def get_audio_file_path(self, name: str) -> tuple[str | None, str]:
        """Return (file_path, file_extension) or (None, '') if not found."""
        bare_name = self._bare_name(name)
        local_filename, file_ext = self._resolve_local_filename(bare_name)
        if not self._local_recordings_repository.exists(local_filename):
            return None, ""
        return self._local_recordings_repository.get_path(local_filename), file_ext

    def get_transcript(self, name: str) -> dict:
        bare_name = self._bare_name(name)
        rec = self._sqlite_db_repository.get_recording_by_name(bare_name)
        rec = rec if isinstance(rec, DBRecording) else None
        transcript = self._sqlite_db_repository.get_transcript(bare_name)
        if transcript:
            return {
                "ok": True,
                "transcript": transcript,
                "transcription_status": rec.transcription_status if rec else "transcribed",
            }
        status = rec.transcription_status if rec else "pending"
        return {
            "ok": False,
            "error": self._transcription_status_message(status),
            "transcription_status": status,
            "transcription_error": rec.transcription_error if rec else None,
        }

    def update_transcript(self, name: str, transcript: str) -> dict:
        bare_name = self._bare_name(name)
        updated = self._sqlite_db_repository.update_transcript(bare_name, transcript)
        if not updated:
            return {"ok": False, "error": f"Recording '{bare_name}' not found"}
        return {"ok": True, "name": bare_name, "transcript": transcript}

    def list_system_prompts(self) -> dict:
        prompts = self._system_prompts_repository.get_all()
        return {"ok": True, "prompts": prompts}

    def summarize_recording(
        self,
        name: str,
        prompt_id: str,
        summary_provider: str | None = None,
        summary_model: str | None = None,
    ) -> dict:
        bare_name = self._bare_name(name)

        transcript = self._sqlite_db_repository.get_transcript(bare_name)
        if not transcript:
            return {"ok": False, "error": "No transcript found - transcribe the recording first"}

        prompt_content = self._system_prompts_repository.get_prompt_content(prompt_id)
        if not prompt_content:
            return {"ok": False, "error": f"System prompt '{prompt_id}' not found"}

        recording_datetime = self._parse_recording_datetime(bare_name)
        provider = self._normalize_summary_provider(summary_provider)
        model = None
        if provider == "local":
            model = OllamaSummarizationService.normalize_model(summary_model or self._default_ollama_summary_model)

        try:
            result = self._summarize_with_provider(
                provider,
                transcript,
                prompt_content,
                recording_datetime=recording_datetime,
                summary_model=model,
            )
        except Exception as e:
            return {"ok": False, "error": f"Summarization failed: {str(e)}"}

        summary = result.get("summary", "")
        title = result.get("title", "")
        tags = result.get("tags", [])
        tags_str = ",".join(tags)

        saved = self._sqlite_db_repository.save_summarization_result(
            bare_name,
            summary,
            title,
            tags_str,
            prompt_id=prompt_id,
        )
        return {
            "ok": True,
            "summary_id": saved.id,
            "version": saved.version,
            "summary": summary,
            "title": title,
            "tags": tags,
            "summary_provider": provider,
            "summary_model": model,
        }

    def _normalize_summary_provider(self, provider: str | None) -> str:
        selected = (provider or self._default_summary_provider or "gemini").strip().lower()
        if selected in ("local", "local_ai", "ollama"):
            return "local"
        return "gemini"

    def _summarize_with_provider(
        self,
        provider: str,
        transcript: str,
        prompt_content: str,
        recording_datetime: str | None = None,
        summary_model: str | None = None,
    ) -> dict:
        if provider == "local":
            if not self._ollama_summarization_service:
                raise RuntimeError("Local AI summarization service is not available")
            return self._ollama_summarization_service.summarize(
                transcript,
                prompt_content,
                recording_datetime=recording_datetime,
                model=summary_model,
            )
        return self._summarization_service.summarize(
            transcript,
            prompt_content,
            recording_datetime=recording_datetime,
        )

    @staticmethod
    def _has_saved_summary(db_rec) -> bool:
        return db_rec is not None and db_rec.summary is not None

    @staticmethod
    def _is_transient_gemini_error(error: str) -> bool:
        transient_markers = ("429", "503", "RESOURCE_EXHAUSTED", "UNAVAILABLE", "rate limit", "high demand")
        return any(marker.lower() in (error or "").lower() for marker in transient_markers)

    def list_missing_summaries(self) -> dict:
        recordings = self._sqlite_db_repository.get_recordings()
        missing = []
        for rec in recordings:
            if not self._has_saved_transcript(rec) or self._has_saved_summary(rec):
                continue
            missing.append(
                {
                    "name": rec.name,
                    "label": rec.label,
                    "file_extension": rec.file_extension,
                    "recorded_at": rec.recorded_at,
                }
            )
        return {"ok": True, "count": len(missing), "recordings": missing}

    def summarize_recordings(
        self,
        names: list[str],
        prompt_id: str,
        rate_limit_delay_seconds: float = 0.0,
        max_retries: int = 0,
        summary_provider: str | None = None,
        summary_model: str | None = None,
    ) -> dict:
        unique_names = []
        seen = set()
        for name in names:
            bare_name = self._bare_name(name)
            if bare_name and bare_name not in seen:
                unique_names.append(bare_name)
                seen.add(bare_name)

        if not unique_names:
            return {"ok": False, "error": "No recordings selected"}

        prompt_content = self._system_prompts_repository.get_prompt_content(prompt_id)
        if not prompt_content:
            return {"ok": False, "error": f"System prompt '{prompt_id}' not found"}

        results = []
        counts = {"summarized": 0, "skipped_existing": 0, "skipped_no_transcript": 0, "failed": 0}
        delay_seconds = max(float(rate_limit_delay_seconds or 0), 0.0)
        retries = max(int(max_retries or 0), 0)
        provider = self._normalize_summary_provider(summary_provider)

        for index, bare_name in enumerate(unique_names):
            db_rec = self._sqlite_db_repository.get_recording_by_name(bare_name)
            if db_rec is None:
                counts["failed"] += 1
                results.append({"name": bare_name, "status": "failed", "error": "Recording not found in database"})
                continue

            if not self._has_saved_transcript(db_rec):
                counts["skipped_no_transcript"] += 1
                results.append({"name": bare_name, "status": "skipped_no_transcript"})
                continue

            if self._has_saved_summary(db_rec):
                counts["skipped_existing"] += 1
                results.append({"name": bare_name, "status": "skipped_existing"})
                continue

            result = None
            for attempt in range(retries + 1):
                result = self.summarize_recording(
                    bare_name,
                    prompt_id,
                    summary_provider=provider,
                    summary_model=summary_model,
                )
                if result.get("ok"):
                    break
                error = result.get("error", "")
                if attempt >= retries:
                    break
                if provider == "gemini" and not self._is_transient_gemini_error(error):
                    break
                if delay_seconds > 0:
                    time.sleep(delay_seconds)

            if result and result.get("ok"):
                counts["summarized"] += 1
                results.append(
                    {
                        "name": bare_name,
                        "status": "summarized",
                        "summary_id": result.get("summary_id"),
                        "version": result.get("version"),
                        "title": result.get("title"),
                        "summary_provider": result.get("summary_provider"),
                        "summary_model": result.get("summary_model"),
                    }
                )
            else:
                counts["failed"] += 1
                results.append(
                    {
                        "name": bare_name,
                        "status": "failed",
                        "error": result.get("error", "Summarization failed") if result else "Summarization failed",
                    }
                )

            if delay_seconds > 0 and index < len(unique_names) - 1:
                time.sleep(delay_seconds)

        return {"ok": counts["failed"] == 0, "counts": counts, "results": results}

    def summarize_missing_summaries(
        self,
        prompt_id: str,
        rate_limit_delay_seconds: float = 0.0,
        max_retries: int = 0,
        summary_provider: str | None = None,
        summary_model: str | None = None,
    ) -> dict:
        missing = self.list_missing_summaries()
        names = [rec["name"] for rec in missing["recordings"]]
        if not names:
            return {
                "ok": True,
                "counts": {"summarized": 0, "skipped_existing": 0, "skipped_no_transcript": 0, "failed": 0},
                "results": [],
                "message": "No transcript-bearing recordings are missing summaries.",
            }
        return self.summarize_recordings(
            names,
            prompt_id,
            rate_limit_delay_seconds=rate_limit_delay_seconds,
            max_retries=max_retries,
            summary_provider=summary_provider,
            summary_model=summary_model,
        )

    def get_summaries(self, name: str) -> dict:
        bare_name = self._bare_name(name)
        summaries = self._sqlite_db_repository.get_summaries(bare_name)
        if not summaries:
            return {"ok": False, "error": "No summary found"}

        return {
            "ok": True,
            "summaries": [
                {
                    "id": s.id,
                    "version": s.version,
                    "title": s.title or "",
                    "tags": s.tags.split(",") if s.tags else [],
                    "summary": s.summary,
                    "prompt_id": s.prompt_id,
                    "notion_url": s.notion_url,
                    "created_at": s.created_at.isoformat() if s.created_at else None,
                }
                for s in summaries
            ],
        }

    def get_summary(self, name: str) -> dict:
        bare_name = self._bare_name(name)
        db_rec = self._sqlite_db_repository.get_recording_by_name(bare_name)
        if db_rec and db_rec.summary:
            tags = db_rec.tags.split(",") if db_rec.tags else []
            return {"ok": True, "summary": db_rec.summary, "title": db_rec.title or "", "tags": tags}

        result = self.get_summaries(name)
        if not result.get("ok"):
            return result
        latest = (result.get("summaries") or [None])[0]
        if not latest:
            return {"ok": False, "error": "No summary found"}
        return {
            "ok": True,
            "summary": latest.get("summary", ""),
            "title": latest.get("title", ""),
            "tags": latest.get("tags", []),
        }

    def update_summary(
        self, summary_id: int, title: str | None = None, tags: list[str] | None = None, summary: str | None = None
    ) -> dict:
        if title is None and tags is None and summary is None:
            return {"ok": False, "error": "Nothing to update"}

        updated = self._sqlite_db_repository.get_summary_by_id(summary_id)
        if not updated:
            return {"ok": False, "error": f"Summary '{summary_id}' not found"}

        if title is not None or tags is not None:
            next_title = title.strip() if title is not None else (updated.title or "")
            next_tags = tags if tags is not None else (updated.tags.split(",") if updated.tags else [])
            tags_list = [t.strip() for t in next_tags if t.strip()]
            updated = self._sqlite_db_repository.update_summary_metadata(summary_id, next_title, ",".join(tags_list))
            if not updated:
                return {"ok": False, "error": f"Summary '{summary_id}' not found"}

        if summary is not None:
            updated = self._sqlite_db_repository.update_summary_content(summary_id, summary)
            if not updated:
                return {"ok": False, "error": f"Summary '{summary_id}' not found"}

        return {
            "ok": True,
            "summary_id": updated.id,
            "title": updated.title or "",
            "tags": updated.tags.split(",") if updated.tags else [],
            "summary": updated.summary,
        }

    def update_summary_metadata(self, summary_id: int, title: str, tags: list[str]) -> dict:
        return self.update_summary(summary_id=summary_id, title=title, tags=tags)

    def update_recording_metadata(self, name: str, title: str, tags: list[str]) -> dict:
        bare_name = self._bare_name(name)
        db_rec = self._sqlite_db_repository.get_recording_by_name(bare_name)
        if not db_rec:
            return {"ok": False, "error": f"Recording '{bare_name}' not found"}
        tags_list = [t.strip() for t in tags if t.strip()]
        self._sqlite_db_repository.update_title_and_tags(bare_name, title.strip(), ",".join(tags_list))
        return {"ok": True, "title": title.strip(), "tags": tags_list}

    # ─── Collections ─────────────────────────────────────────────

    def get_collections(self) -> dict:
        return {"ok": True, "collections": self._sqlite_db_repository.get_collections_with_counts()}

    def create_collection(self, name: str, description: str | None = None) -> dict:
        clean_name = name.strip()
        if not clean_name:
            return {"ok": False, "error": "Collection name is required"}
        collection = self._sqlite_db_repository.create_collection(clean_name, description)
        return {"ok": True, "collection": collection}

    def get_recording_collections(self, name: str) -> dict:
        bare_name = self._bare_name(name)
        if not self._sqlite_db_repository.get_recording_by_name(bare_name):
            return {"ok": False, "error": f"Recording '{bare_name}' not found"}
        return {
            "ok": True,
            "name": bare_name,
            "collections": self._sqlite_db_repository.get_recording_collections(bare_name),
        }

    def set_recording_collections(self, name: str, collection_ids: list[int]) -> dict:
        bare_name = self._bare_name(name)
        clean_ids = sorted({int(collection_id) for collection_id in collection_ids})
        updated = self._sqlite_db_repository.set_recording_collections(bare_name, clean_ids)
        if not updated:
            return {"ok": False, "error": f"Recording '{bare_name}' not found"}
        return {
            "ok": True,
            "name": bare_name,
            "collections": self._sqlite_db_repository.get_recording_collections(bare_name),
        }

    def add_recording_to_collection(self, name: str, collection_id: int) -> dict:
        bare_name = self._bare_name(name)
        updated = self._sqlite_db_repository.add_recording_to_collection(bare_name, collection_id)
        if not updated:
            return {"ok": False, "error": "Recording or collection not found"}
        return {"ok": True, "name": bare_name, "collection_id": collection_id}

    def bulk_add_recordings_to_collection(self, names: list[str], collection_id: int) -> dict:
        unique_names = []
        seen = set()
        for name in names:
            bare_name = self._bare_name(name)
            if bare_name and bare_name not in seen:
                unique_names.append(bare_name)
                seen.add(bare_name)

        if not unique_names:
            return {"ok": False, "error": "No recordings selected"}

        collections = self._sqlite_db_repository.get_collections_with_counts()
        collection = next((c for c in collections if int(c["id"]) == int(collection_id)), None)
        if not collection:
            return {"ok": False, "error": "Collection not found"}

        added = 0
        skipped = 0
        failed = []
        for bare_name in unique_names:
            updated = self._sqlite_db_repository.add_recording_to_collection(bare_name, int(collection_id))
            if updated:
                added += 1
            else:
                skipped += 1
                failed.append({"name": bare_name, "error": "Recording not found"})

        collection_name = collection["name"]
        return {
            "ok": len(failed) == 0,
            "collection_id": int(collection_id),
            "collection_name": collection_name,
            "counts": {
                "requested": len(unique_names),
                "added": added,
                "skipped": skipped,
                "failed": len(failed),
            },
            "failed": failed,
            "message": f"{added} recordings added to {collection_name}.",
        }

    def remove_recording_from_collection(self, name: str, collection_id: int) -> dict:
        bare_name = self._bare_name(name)
        removed = self._sqlite_db_repository.remove_recording_from_collection(bare_name, collection_id)
        if not removed:
            return {"ok": False, "error": "Recording or collection membership not found"}
        return {"ok": True, "name": bare_name, "collection_id": collection_id}

    # ─── Saved Views ─────────────────────────────────────────────

    def get_saved_views(self) -> dict:
        return {"ok": True, "saved_views": self._sqlite_db_repository.get_saved_views()}

    def create_saved_view(
        self,
        name: str,
        search_query: str = "",
        collection_id: int | None = None,
        date_filter: str = "",
        folder: str | None = None,
    ) -> dict:
        clean_name = name.strip()
        if not clean_name:
            return {"ok": False, "error": "Saved view name is required"}
        normalized_folder = self._normalize_folder_path(folder) if folder is not None else None
        try:
            saved_view = self._sqlite_db_repository.create_saved_view(
                name=clean_name,
                search_query=search_query,
                collection_id=collection_id,
                date_filter=date_filter,
                folder=normalized_folder,
            )
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True, "saved_view": saved_view}

    def delete_saved_view(self, saved_view_id: int) -> dict:
        deleted = self._sqlite_db_repository.delete_saved_view(saved_view_id)
        if not deleted:
            return {"ok": False, "error": f"Saved view '{saved_view_id}' not found"}
        return {"ok": True, "deleted": saved_view_id}

    _DESTINATION_META: dict[str, dict] = {
        "notion": {"label": "Notion", "icon": "bi-journal-bookmark"},
    }

    def get_publish_destinations(self) -> dict:
        destinations = []
        for key, svc in self._publish_services.items():
            if hasattr(svc, "is_configured") and svc.is_configured:
                meta = self._DESTINATION_META.get(key, {})
                destinations.append(
                    {
                        "id": key,
                        "label": meta.get("label", key.capitalize()),
                        "icon": meta.get("icon", "bi-share"),
                    }
                )
        return {"ok": True, "destinations": destinations}

    def publish_recording(self, name: str, destination: str) -> dict:
        bare_name = self._bare_name(name)
        db_rec = self._sqlite_db_repository.get_recording_by_name(bare_name)
        if not db_rec:
            return {"ok": False, "error": "No summary found - summarize the recording first"}
        summaries = self._sqlite_db_repository.get_summaries(bare_name)
        if not summaries:
            return {"ok": False, "error": "No summary found - summarize the recording first"}
        return self.publish_summary(summaries[0].id, destination)

    def publish_summary(self, summary_id: int, destination: str) -> dict:
        svc = self._publish_services.get(destination)
        if not svc:
            return {"ok": False, "error": f"Unknown publish destination: {destination}"}

        summary = self._sqlite_db_repository.get_summary_by_id(summary_id)
        if not summary:
            return {"ok": False, "error": "Summary not found"}

        title = summary.title or summary.recording_name
        tags = summary.tags.split(",") if summary.tags else []

        publish_title = title
        recording_dt = self._parse_recording_datetime(summary.recording_name)
        if recording_dt:
            date_only = recording_dt.split(" ")[0]
            publish_title = f"{date_only} {title}"

        try:
            result = svc.publish_summary(
                title=publish_title,
                summary_markdown=summary.summary,
                tags=tags,
                recording_name=summary.recording_name,
            )
            if result.get("ok") and result.get("url"):
                self._sqlite_db_repository.save_notion_url(summary_id, result["url"])
            return result
        except Exception as e:
            return {"ok": False, "error": f"Publish failed: {str(e)}"}

    # ─── Tasks ───────────────────────────────────────────────────

    def generate_tasks(self, summary_id: int) -> dict:
        summary = self._sqlite_db_repository.get_summary_by_id(summary_id)
        if not summary:
            return {"ok": False, "error": f"Summary '{summary_id}' not found"}

        if not summary.summary or not summary.summary.strip():
            return {"ok": False, "error": "Summary is empty - cannot generate tasks"}

        # Delete existing tasks for this summary (regeneration replaces old ones)
        self._sqlite_db_repository.delete_tasks_by_summary(summary_id)

        try:
            raw_tasks = self._task_generation_service.generate_tasks(
                summary_text=summary.summary,
                summary_title=summary.title,
            )
        except Exception as e:
            return {"ok": False, "error": f"Task generation failed: {str(e)}"}

        if not raw_tasks:
            return {"ok": False, "error": "AI returned no tasks"}

        # Convert raw dicts to DBTask objects
        db_tasks = []
        for t in raw_tasks:
            subtasks = [
                DBTask(id=None, summary_id=summary_id, title=s["title"], description=s.get("description", ""))
                for s in t.get("subtasks", [])
            ]
            db_task = DBTask(
                id=None,
                summary_id=summary_id,
                title=t["title"],
                description=t.get("description", ""),
                subtasks=subtasks,
            )
            db_tasks.append(db_task)

        saved = self._sqlite_db_repository.insert_tasks(db_tasks)
        return {
            "ok": True,
            "summary_id": summary_id,
            "tasks": [task.to_dict() for task in saved],
        }

    def get_tasks(self, summary_id: int) -> dict:
        tasks = self._sqlite_db_repository.get_tasks_by_summary(summary_id)
        return {
            "ok": True,
            "summary_id": summary_id,
            "tasks": [task.to_dict() for task in tasks],
        }

    def update_task(
        self, task_id: int, title: str | None = None, description: str | None = None, status: str | None = None
    ) -> dict:
        updated = self._sqlite_db_repository.update_task(task_id, title=title, description=description, status=status)
        if not updated:
            return {"ok": False, "error": f"Task '{task_id}' not found"}
        return {"ok": True, "task": updated.to_dict()}

    def delete_task(self, task_id: int) -> dict:
        deleted = self._sqlite_db_repository.delete_task(task_id)
        if not deleted:
            return {"ok": False, "error": f"Task '{task_id}' not found"}
        return {"ok": True, "deleted": task_id}

    # ─── Folders ─────────────────────────────────────────────────

    @staticmethod
    def _normalize_folder_path(path: str) -> str:
        """Normalize a folder path: strip whitespace, ensure leading /, collapse slashes."""
        path = path.strip()
        if not path:
            return "/"
        # Collapse multiple slashes, strip trailing slash (unless root)
        parts = [p for p in path.split("/") if p]
        if not parts:
            return "/"
        return "/" + "/".join(parts)

    def get_folders(self) -> dict:
        folders = self._sqlite_db_repository.get_recording_folders()
        return {"ok": True, "folders": folders}

    def create_folder(self, path: str) -> dict:
        """Create a folder (virtual - just validate the path)."""
        normalized = self._normalize_folder_path(path)
        if normalized == "/":
            return {"ok": False, "error": "Cannot create root folder"}
        # Folders are implicit - they exist as long as a recording uses them.
        # We return success; the folder will appear once a recording is moved there.
        return {"ok": True, "path": normalized}

    def move_recording(self, name: str, folder: str) -> dict:
        bare_name = self._bare_name(name)
        normalized = self._normalize_folder_path(folder)
        db_rec = self._sqlite_db_repository.get_recording_by_name(bare_name)
        if not db_rec:
            return {"ok": False, "error": f"Recording '{bare_name}' not found in database"}
        moved = self._sqlite_db_repository.move_recording_to_folder(bare_name, normalized)
        if not moved:
            return {"ok": False, "error": "Failed to move recording"}
        return {"ok": True, "name": bare_name, "folder": normalized}

    def bulk_move_recordings(self, names: list[str], folder: str) -> dict:
        normalized = self._normalize_folder_path(folder)
        bare_names = [self._bare_name(n) for n in names]
        count = self._sqlite_db_repository.bulk_move_recordings_to_folder(bare_names, normalized)
        return {"ok": True, "moved": count, "folder": normalized}

    def rename_folder(self, old_path: str, new_path: str) -> dict:
        old_normalized = self._normalize_folder_path(old_path)
        new_normalized = self._normalize_folder_path(new_path)
        if old_normalized == "/":
            return {"ok": False, "error": "Cannot rename root folder"}
        if new_normalized == "/":
            return {"ok": False, "error": "New name cannot be root"}
        count = self._sqlite_db_repository.rename_folder(old_normalized, new_normalized)
        return {"ok": True, "old_path": old_normalized, "new_path": new_normalized, "updated": count}

    def delete_folder(self, path: str, move_to: str = "/") -> dict:
        normalized = self._normalize_folder_path(path)
        move_to_normalized = self._normalize_folder_path(move_to)
        if normalized == "/":
            return {"ok": False, "error": "Cannot delete root folder"}
        count = self._sqlite_db_repository.delete_folder(normalized, move_to_normalized)
        return {"ok": True, "path": normalized, "moved_to": move_to_normalized, "moved_count": count}

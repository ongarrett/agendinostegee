from controllers.DashboardController import DashboardController
from repositories.SqliteDBRepository import SqliteDBRepository
from services.OllamaSummarizationService import OllamaSummarizationService

LOCAL_OLLAMA_UNAVAILABLE_MESSAGE = (
    "Local AI/Ollama is not available. Start Ollama with `ollama serve` and confirm qwen3:8b is installed."
)


class ProcessingQueueService:
    def __init__(
        self,
        sqlite_db_repository: SqliteDBRepository,
        dashboard_controller: DashboardController,
    ):
        self._sqlite_db_repository = sqlite_db_repository
        self._dashboard_controller = dashboard_controller

    def list_jobs(self, status: str = "", job_type: str = "") -> dict:
        return {
            "ok": True,
            "counts": self._sqlite_db_repository.get_processing_queue_counts(job_type=job_type),
            "jobs": self._sqlite_db_repository.list_processing_queue_jobs(status=status, job_type=job_type),
        }

    def summary_pipeline_status(self) -> dict:
        return self._sqlite_db_repository.get_summary_pipeline_status(provider="local", model="qwen3:8b")

    def enqueue_transcribe_newest(
        self,
        limit: int,
        collection_id: int | None = None,
        engine: str = "whisper",
    ) -> dict:
        names = self._sqlite_db_repository.get_untranscribed_recording_names(
            limit=limit,
            collection_id=collection_id,
        )
        result = self._sqlite_db_repository.enqueue_processing_jobs("transcribe", names, engine=engine)
        return self._with_selection_count(result, len(names))

    def enqueue_transcribe_collection(self, collection_id: int, engine: str = "whisper") -> dict:
        names = self._sqlite_db_repository.get_untranscribed_recording_names(collection_id=collection_id)
        result = self._sqlite_db_repository.enqueue_processing_jobs("transcribe", names, engine=engine)
        return self._with_selection_count(result, len(names))

    def enqueue_transcribe_retryable_failures(self, engine: str = "whisper") -> dict:
        names = self._sqlite_db_repository.get_recording_names_by_transcription_status(["retryable_failure"])
        result = self._sqlite_db_repository.enqueue_processing_jobs("transcribe", names, engine=engine)
        return self._with_selection_count(result, len(names))

    def enqueue_transcribe_pending(self, engine: str = "whisper") -> dict:
        names = self._sqlite_db_repository.get_recording_names_by_transcription_status(["pending"])
        result = self._sqlite_db_repository.enqueue_processing_jobs("transcribe", names, engine=engine)
        return self._with_selection_count(result, len(names))

    def enqueue_summarize_newest(
        self,
        limit: int,
        prompt_id: str,
        collection_id: int | None = None,
        summary_provider: str = "local",
        summary_model: str | None = "qwen3:8b",
    ) -> dict:
        summary_model = self._normalize_summary_model(summary_provider, summary_model)
        names = self._sqlite_db_repository.get_missing_summary_recording_names(
            limit=limit,
            collection_id=collection_id,
        )
        result = self._sqlite_db_repository.enqueue_processing_jobs(
            "summarize",
            names,
            prompt_id=prompt_id,
            summary_provider=summary_provider,
            summary_model=summary_model,
            skip_statuses=("pending", "running", "completed"),
        )
        return self._with_selection_count(result, len(names))

    def enqueue_summarize_collection(
        self,
        collection_id: int,
        prompt_id: str,
        summary_provider: str = "local",
        summary_model: str | None = "qwen3:8b",
    ) -> dict:
        summary_model = self._normalize_summary_model(summary_provider, summary_model)
        names = self._sqlite_db_repository.get_missing_summary_recording_names(collection_id=collection_id)
        result = self._sqlite_db_repository.enqueue_processing_jobs(
            "summarize",
            names,
            prompt_id=prompt_id,
            summary_provider=summary_provider,
            summary_model=summary_model,
            skip_statuses=("pending", "running", "completed"),
        )
        return self._with_selection_count(result, len(names))

    def enqueue_summarize_missing(
        self,
        prompt_id: str,
        summary_provider: str = "local",
        summary_model: str | None = "qwen3:8b",
    ) -> dict:
        summary_model = self._normalize_summary_model(summary_provider, summary_model)
        names = self._sqlite_db_repository.get_missing_summary_recording_names()
        result = self._sqlite_db_repository.enqueue_processing_jobs(
            "summarize",
            names,
            prompt_id=prompt_id,
            summary_provider=summary_provider,
            summary_model=summary_model,
            skip_statuses=("pending", "running", "completed"),
        )
        return self._with_selection_count(result, len(names))

    def enqueue_summary_pipeline(
        self,
        prompt_id: str,
        limit: int | None = None,
        summary_provider: str = "local",
        summary_model: str | None = "qwen3:8b",
    ) -> dict:
        if limit is None:
            result = self.enqueue_summarize_missing(
                prompt_id=prompt_id,
                summary_provider=summary_provider,
                summary_model=summary_model,
            )
        else:
            result = self.enqueue_summarize_newest(
                limit=limit,
                prompt_id=prompt_id,
                summary_provider=summary_provider,
                summary_model=summary_model,
            )
        result["pipeline"] = self.summary_pipeline_status()
        return result

    def pause_summary_pipeline(self) -> dict:
        state = self._sqlite_db_repository.set_app_state("summary_pipeline_paused", "true")
        return {"ok": True, "paused": True, "state": state, "pipeline": self.summary_pipeline_status()}

    def resume_summary_pipeline(self, max_jobs: int = 5, max_retries: int = 1) -> dict:
        state = self._sqlite_db_repository.set_app_state("summary_pipeline_paused", "false")
        result = self.process_next(max_jobs=max_jobs, reset_running=True, max_retries=max_retries)
        result["paused"] = False
        result["state"] = state
        result["pipeline"] = self.summary_pipeline_status()
        return result

    def retry_failed_summary_jobs(self) -> dict:
        result = self._sqlite_db_repository.retry_failed_processing_jobs("summarize")
        result["pipeline"] = self.summary_pipeline_status()
        result["message"] = f"Queued {result['retried']} failed summary job(s) for retry."
        return result

    def clear_completed_summary_jobs(self) -> dict:
        result = self._sqlite_db_repository.clear_processing_jobs("summarize", ("completed", "skipped"))
        result["pipeline"] = self.summary_pipeline_status()
        result["message"] = f"Cleared {result['cleared']} completed/skipped summary job(s)."
        return result

    @staticmethod
    def _with_selection_count(result: dict, selected_count: int) -> dict:
        result["selected_count"] = selected_count
        result["message"] = (
            f"Queued {result['counts']['enqueued']} job(s). "
            f"Skipped {result['counts']['skipped_active']} already pending/running job(s)."
        )
        return result

    @staticmethod
    def _normalize_summary_provider(summary_provider: str | None) -> str:
        selected = (summary_provider or "gemini").strip().lower()
        if selected in ("local", "local_ai", "ollama"):
            return "local"
        return "gemini"

    @classmethod
    def _normalize_summary_model(cls, summary_provider: str | None, summary_model: str | None) -> str | None:
        if cls._normalize_summary_provider(summary_provider) != "local":
            return None
        return OllamaSummarizationService.normalize_model(summary_model)

    def process_next(self, max_jobs: int = 1, reset_running: bool = False, max_retries: int = 0) -> dict:
        if reset_running:
            self._sqlite_db_repository.reset_running_processing_jobs()

        summary_paused = self._sqlite_db_repository.get_app_state("summary_pipeline_paused", "false") == "true"
        results = []
        counts = {
            "processed": 0,
            "completed": 0,
            "failed": 0,
            "skipped": 0,
            "transcribe": 0,
            "summarize": 0,
            "gemini": 0,
            "local": 0,
            "retries": 0,
        }
        for _ in range(max_jobs):
            exclude_job_types = ["summarize"] if summary_paused else None
            job = self._sqlite_db_repository.claim_next_processing_queue_job(exclude_job_types=exclude_job_types)
            if not job:
                break
            result = self._process_job_with_retries(job, max_retries=max_retries)
            results.append(result)
            counts["processed"] += 1
            counts[job["job_type"]] = counts.get(job["job_type"], 0) + 1
            if job["job_type"] == "summarize":
                provider = self._normalize_summary_provider(job.get("summary_provider"))
                counts[provider] = counts.get(provider, 0) + 1
            counts["retries"] += result.get("retries", 0)
            if result["status"] == "completed":
                counts["completed"] += 1
            elif result["status"] == "skipped":
                counts["skipped"] += 1
            else:
                counts["failed"] += 1

        return {
            "ok": counts["failed"] == 0,
            "counts": counts,
            "results": results,
            "queue_counts": self._sqlite_db_repository.get_processing_queue_counts(),
            "pipeline": self.summary_pipeline_status(),
        }

    def _process_job_with_retries(self, job: dict, max_retries: int = 0) -> dict:
        retries = max(int(max_retries or 0), 0)
        result = None
        for attempt in range(retries + 1):
            result = self._process_job(job)
            result["retries"] = attempt
            if result["status"] in ("completed", "skipped"):
                return result
        return result

    def _process_job(self, job: dict) -> dict:
        if job["job_type"] == "transcribe":
            result = self._dashboard_controller.transcribe_recording(
                job["recording_name"],
                engine=job["engine"] or "whisper",
            )
        elif job["job_type"] == "summarize":
            job = self._validate_summary_job(job)
            if job.get("validation_error"):
                result = {"ok": False, "error": job["validation_error"]}
            elif self._recording_has_summary(job["recording_name"]):
                updated = self._sqlite_db_repository.update_processing_queue_job_status(
                    job["id"],
                    "skipped",
                    error="Summary already exists",
                )
                return {
                    "job_id": job["id"],
                    "recording_name": job["recording_name"],
                    "job_type": job["job_type"],
                    "status": "skipped",
                    "job": updated,
                }
            else:
                result = self._dashboard_controller.summarize_recording(
                    job["recording_name"],
                    job["prompt_id"],
                    summary_provider=job.get("summary_provider"),
                    summary_model=job.get("summary_model"),
                )
        else:
            result = {"ok": False, "error": f"Unsupported job type '{job['job_type']}'"}

        if result.get("ok"):
            updated = self._sqlite_db_repository.update_processing_queue_job_status(job["id"], "completed")
            return {
                "job_id": job["id"],
                "recording_name": job["recording_name"],
                "job_type": job["job_type"],
                "status": "completed",
                "job": updated,
            }

        error = result.get("error", "Processing failed")
        if job["job_type"] == "summarize" and self._normalize_summary_provider(job.get("summary_provider")) == "local":
            error = self._local_summary_error_message(error)
        updated = self._sqlite_db_repository.update_processing_queue_job_status(job["id"], "failed", error=error)
        return {
            "job_id": job["id"],
            "recording_name": job["recording_name"],
            "job_type": job["job_type"],
            "status": "failed",
            "error": error,
            "job": updated,
        }

    def _validate_summary_job(self, job: dict) -> dict:
        provider = self._normalize_summary_provider(job.get("summary_provider"))
        if provider != "local":
            return {**job, "summary_provider": provider}

        model = OllamaSummarizationService.normalize_model(job.get("summary_model"))
        if not OllamaSummarizationService.is_supported_model(model):
            supported = ", ".join(sorted(OllamaSummarizationService.supported_models()))
            return {
                **job,
                "summary_provider": provider,
                "summary_model": model,
                "validation_error": f"Unsupported local summary model '{model}'. Supported models: {supported}",
            }

        if model != job.get("summary_model"):
            updated = self._sqlite_db_repository.update_processing_queue_job_summary_model(job["id"], model)
            if updated:
                job = updated
        return {**job, "summary_provider": provider, "summary_model": model}

    def _recording_has_summary(self, name: str) -> bool:
        recording = self._sqlite_db_repository.get_recording_by_name(name)
        return bool(recording and recording.summary and recording.summary.strip())

    @staticmethod
    def _local_summary_error_message(error: str) -> str:
        lowered = (error or "").lower()
        unavailable_markers = (
            "connection refused",
            "failed to establish",
            "urlopen error",
            "ollama",
            "not available",
            "not found",
        )
        if any(marker in lowered for marker in unavailable_markers):
            return LOCAL_OLLAMA_UNAVAILABLE_MESSAGE
        return error

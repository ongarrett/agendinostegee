from controllers.DashboardController import DashboardController
from repositories.SqliteDBRepository import SqliteDBRepository


class ProcessingQueueService:
    def __init__(
        self,
        sqlite_db_repository: SqliteDBRepository,
        dashboard_controller: DashboardController,
    ):
        self._sqlite_db_repository = sqlite_db_repository
        self._dashboard_controller = dashboard_controller

    def list_jobs(self, status: str = "") -> dict:
        return {
            "ok": True,
            "counts": self._sqlite_db_repository.get_processing_queue_counts(),
            "jobs": self._sqlite_db_repository.list_processing_queue_jobs(status=status),
        }

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

    def enqueue_summarize_newest(
        self,
        limit: int,
        prompt_id: str,
        collection_id: int | None = None,
        summary_provider: str = "gemini",
        summary_model: str | None = None,
    ) -> dict:
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
        )
        return self._with_selection_count(result, len(names))

    def enqueue_summarize_collection(
        self,
        collection_id: int,
        prompt_id: str,
        summary_provider: str = "gemini",
        summary_model: str | None = None,
    ) -> dict:
        names = self._sqlite_db_repository.get_missing_summary_recording_names(collection_id=collection_id)
        result = self._sqlite_db_repository.enqueue_processing_jobs(
            "summarize",
            names,
            prompt_id=prompt_id,
            summary_provider=summary_provider,
            summary_model=summary_model,
        )
        return self._with_selection_count(result, len(names))

    def enqueue_summarize_missing(
        self,
        prompt_id: str,
        summary_provider: str = "gemini",
        summary_model: str | None = None,
    ) -> dict:
        names = self._sqlite_db_repository.get_missing_summary_recording_names()
        result = self._sqlite_db_repository.enqueue_processing_jobs(
            "summarize",
            names,
            prompt_id=prompt_id,
            summary_provider=summary_provider,
            summary_model=summary_model,
        )
        return self._with_selection_count(result, len(names))

    @staticmethod
    def _with_selection_count(result: dict, selected_count: int) -> dict:
        result["selected_count"] = selected_count
        result["message"] = (
            f"Queued {result['counts']['enqueued']} job(s). "
            f"Skipped {result['counts']['skipped_active']} already pending/running job(s)."
        )
        return result

    def process_next(self, max_jobs: int = 1, reset_running: bool = False) -> dict:
        if reset_running:
            self._sqlite_db_repository.reset_running_processing_jobs()

        results = []
        counts = {"completed": 0, "failed": 0}
        for _ in range(max_jobs):
            job = self._sqlite_db_repository.claim_next_processing_queue_job()
            if not job:
                break
            result = self._process_job(job)
            results.append(result)
            if result["status"] == "completed":
                counts["completed"] += 1
            else:
                counts["failed"] += 1

        return {
            "ok": counts["failed"] == 0,
            "counts": counts,
            "results": results,
            "queue_counts": self._sqlite_db_repository.get_processing_queue_counts(),
        }

    def _process_job(self, job: dict) -> dict:
        if job["job_type"] == "transcribe":
            result = self._dashboard_controller.transcribe_recording(
                job["recording_name"],
                engine=job["engine"] or "whisper",
            )
        elif job["job_type"] == "summarize":
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
        updated = self._sqlite_db_repository.update_processing_queue_job_status(job["id"], "failed", error=error)
        return {
            "job_id": job["id"],
            "recording_name": job["recording_name"],
            "job_type": job["job_type"],
            "status": "failed",
            "error": error,
            "job": updated,
        }

from datetime import datetime, timedelta

import pytest

from models.DBRecording import DBRecording
from repositories.SqliteDBRepository import SqliteDBRepository
from services.ProcessingQueueService import ProcessingQueueService


class FakeDashboardController:
    def __init__(self):
        self.transcribed = []
        self.summarized = []
        self.fail_transcribe = set()
        self.fail_summarize = set()

    def transcribe_recording(self, name, engine="whisper"):
        self.transcribed.append({"name": name, "engine": engine})
        if name in self.fail_transcribe:
            return {"ok": False, "error": "Transcription failed"}
        return {"ok": True, "transcript": "Transcript"}

    def summarize_recording(self, name, prompt_id, summary_provider=None, summary_model=None):
        self.summarized.append(
            {
                "name": name,
                "prompt_id": prompt_id,
                "summary_provider": summary_provider,
                "summary_model": summary_model,
            }
        )
        if name in self.fail_summarize:
            return {"ok": False, "error": "Summarization failed"}
        return {"ok": True, "summary_id": 1, "version": 1}


@pytest.fixture
def queue_db(tmp_path):
    return SqliteDBRepository(
        "processing_queue_test.db",
        str(tmp_path),
        "settings/db_init.sql",
    )


def insert_recording(db, name, days_old=0, transcript=None, summary=None):
    db.insert_recording(
        DBRecording(
            id=None,
            name=name,
            label=name,
            duration=60,
            created_at=datetime.now() - timedelta(days=days_old),
            transcript=transcript,
        )
    )
    if summary:
        db.save_summarization_result(name, title=f"{name} title", tags="", summary=summary)


def test_enqueue_transcribe_newest_uses_whisper_and_limits_untranscribed(queue_db):
    insert_recording(queue_db, "old", days_old=2)
    insert_recording(queue_db, "new", days_old=0)
    insert_recording(queue_db, "already-transcribed", transcript="Done")
    service = ProcessingQueueService(queue_db, FakeDashboardController())

    result = service.enqueue_transcribe_newest(limit=1)
    jobs = service.list_jobs()["jobs"]

    assert result["counts"]["enqueued"] == 1
    assert jobs[0]["recording_name"] == "new"
    assert jobs[0]["engine"] == "whisper"


def test_enqueue_summarize_newest_selects_transcribed_missing_summary(queue_db):
    insert_recording(queue_db, "missing-summary", transcript="Transcript")
    insert_recording(queue_db, "has-summary", transcript="Transcript", summary="Summary")
    insert_recording(queue_db, "no-transcript")
    service = ProcessingQueueService(queue_db, FakeDashboardController())

    result = service.enqueue_summarize_newest(limit=25, prompt_id="en/general/Brief")
    jobs = service.list_jobs()["jobs"]

    assert result["counts"]["enqueued"] == 1
    assert jobs[0]["recording_name"] == "missing-summary"
    assert jobs[0]["prompt_id"] == "en/general/Brief"


def test_enqueue_summarize_newest_persists_local_provider_and_model(queue_db):
    insert_recording(queue_db, "missing-summary", transcript="Transcript")
    service = ProcessingQueueService(queue_db, FakeDashboardController())

    result = service.enqueue_summarize_newest(
        limit=25,
        prompt_id="en/general/Brief",
        summary_provider="local",
        summary_model="qwen3:8b",
    )
    jobs = service.list_jobs()["jobs"]

    assert result["counts"]["enqueued"] == 1
    assert jobs[0]["summary_provider"] == "local"
    assert jobs[0]["summary_model"] == "qwen3:8b"


def test_enqueue_summarize_newest_normalizes_legacy_local_model_alias(queue_db):
    insert_recording(queue_db, "missing-summary", transcript="Transcript")
    service = ProcessingQueueService(queue_db, FakeDashboardController())

    result = service.enqueue_summarize_newest(
        limit=25,
        prompt_id="en/general/Brief",
        summary_provider="local",
        summary_model="qwen3",
    )
    jobs = service.list_jobs()["jobs"]

    assert result["counts"]["enqueued"] == 1
    assert jobs[0]["summary_model"] == "qwen3:8b"


def test_pending_local_summary_jobs_are_migrated_to_exact_model_ids(tmp_path):
    db_name = "processing_queue_migration_test.db"
    db = SqliteDBRepository(db_name, str(tmp_path), "settings/db_init.sql")
    insert_recording(db, "alpha", transcript="Transcript")
    insert_recording(db, "beta", transcript="Transcript")
    db.enqueue_processing_jobs(
        "summarize",
        ["alpha", "beta"],
        prompt_id="prompt",
        summary_provider="local",
        summary_model="qwen3",
    )
    beta_job = [job for job in db.list_processing_queue_jobs() if job["recording_name"] == "beta"][0]
    db.update_processing_queue_job_status(beta_job["id"], "failed", error="old failure")

    migrated_db = SqliteDBRepository(db_name, str(tmp_path), "settings/db_init.sql")
    jobs = migrated_db.list_processing_queue_jobs()

    assert {job["recording_name"]: job["summary_model"] for job in jobs} == {
        "alpha": "qwen3:8b",
        "beta": "qwen3:8b",
    }


def test_collection_transcription_is_scoped_to_collection(queue_db):
    insert_recording(queue_db, "in-collection")
    insert_recording(queue_db, "outside")
    collection = queue_db.create_collection("Strategy")
    queue_db.add_recording_to_collection("in-collection", collection["id"])
    service = ProcessingQueueService(queue_db, FakeDashboardController())

    result = service.enqueue_transcribe_collection(collection["id"])
    jobs = service.list_jobs()["jobs"]

    assert result["counts"]["enqueued"] == 1
    assert jobs[0]["recording_name"] == "in-collection"


def test_duplicate_pending_jobs_are_skipped(queue_db):
    insert_recording(queue_db, "alpha")
    service = ProcessingQueueService(queue_db, FakeDashboardController())

    first = service.enqueue_transcribe_newest(limit=25)
    second = service.enqueue_transcribe_newest(limit=25)

    assert first["counts"]["enqueued"] == 1
    assert second["counts"]["enqueued"] == 0
    assert second["counts"]["skipped_active"] == 1


def test_retry_failed_only_queues_retryable_failures_not_corrupt_or_no_speech(queue_db):
    insert_recording(queue_db, "retryable")
    insert_recording(queue_db, "corrupt")
    insert_recording(queue_db, "silent")
    queue_db.update_transcription_metadata("retryable", "retryable_failure", error="timed out")
    queue_db.update_transcription_metadata("corrupt", "corrupt_audio", error="Invalid data found")
    queue_db.update_transcription_metadata("silent", "no_speech_detected", segment_count=0)
    service = ProcessingQueueService(queue_db, FakeDashboardController())

    result = service.enqueue_transcribe_retryable_failures()
    jobs = service.list_jobs()["jobs"]

    assert result["counts"]["enqueued"] == 1
    assert [job["recording_name"] for job in jobs] == ["retryable"]


def test_process_next_updates_completed_and_failed_statuses(queue_db):
    insert_recording(queue_db, "ok")
    insert_recording(queue_db, "bad")
    dashboard = FakeDashboardController()
    dashboard.fail_transcribe.add("bad")
    service = ProcessingQueueService(queue_db, dashboard)
    queue_db.enqueue_processing_jobs("transcribe", ["ok", "bad"], engine="whisper")

    result = service.process_next(max_jobs=2)
    jobs = service.list_jobs()["jobs"]

    assert result["counts"]["processed"] == 2
    assert result["counts"]["completed"] == 1
    assert result["counts"]["failed"] == 1
    assert result["counts"]["transcribe"] == 2
    assert {job["recording_name"]: job["status"] for job in jobs} == {
        "ok": "completed",
        "bad": "failed",
    }
    assert dashboard.transcribed == [
        {"name": "ok", "engine": "whisper"},
        {"name": "bad", "engine": "whisper"},
    ]


def test_process_next_passes_summary_provider_and_model(queue_db):
    insert_recording(queue_db, "alpha", transcript="Transcript")
    dashboard = FakeDashboardController()
    service = ProcessingQueueService(queue_db, dashboard)
    queue_db.enqueue_processing_jobs(
        "summarize",
        ["alpha"],
        prompt_id="prompt",
        summary_provider="local",
        summary_model="qwen3:8b",
    )

    result = service.process_next(max_jobs=1)

    assert result["counts"]["completed"] == 1
    assert dashboard.summarized == [
        {
            "name": "alpha",
            "prompt_id": "prompt",
            "summary_provider": "local",
            "summary_model": "qwen3:8b",
        }
    ]


def test_process_next_normalizes_legacy_local_model_before_execution(queue_db):
    insert_recording(queue_db, "alpha", transcript="Transcript")
    dashboard = FakeDashboardController()
    service = ProcessingQueueService(queue_db, dashboard)
    queue_db.enqueue_processing_jobs(
        "summarize",
        ["alpha"],
        prompt_id="prompt",
        summary_provider="local",
        summary_model="llama3.1",
    )

    result = service.process_next(max_jobs=1)
    jobs = service.list_jobs()["jobs"]

    assert result["counts"]["completed"] == 1
    assert dashboard.summarized[0]["summary_model"] == "llama3.1:8b"
    assert jobs[0]["summary_model"] == "llama3.1:8b"


def test_process_next_rejects_unsupported_local_model_before_execution(queue_db):
    insert_recording(queue_db, "alpha", transcript="Transcript")
    dashboard = FakeDashboardController()
    service = ProcessingQueueService(queue_db, dashboard)
    queue_db.enqueue_processing_jobs(
        "summarize",
        ["alpha"],
        prompt_id="prompt",
        summary_provider="local",
        summary_model="unsupported",
    )

    result = service.process_next(max_jobs=1)

    assert result["counts"]["failed"] == 1
    assert "Unsupported local summary model" in result["results"][0]["error"]
    assert dashboard.summarized == []


def test_process_next_retries_failed_job_before_success(queue_db):
    insert_recording(queue_db, "alpha", transcript="Transcript")
    dashboard = FakeDashboardController()
    dashboard.fail_summarize.add("alpha")
    service = ProcessingQueueService(queue_db, dashboard)
    queue_db.enqueue_processing_jobs(
        "summarize",
        ["alpha"],
        prompt_id="prompt",
        summary_provider="local",
        summary_model="qwen3:8b",
    )

    original_summarize = dashboard.summarize_recording
    attempts = {"count": 0}

    def fail_once_then_succeed(*args, **kwargs):
        attempts["count"] += 1
        if attempts["count"] == 1:
            return {"ok": False, "error": "Temporary local model error"}
        dashboard.fail_summarize.clear()
        return original_summarize(*args, **kwargs)

    dashboard.summarize_recording = fail_once_then_succeed

    result = service.process_next(max_jobs=1, max_retries=1)

    assert result["counts"]["completed"] == 1
    assert result["counts"]["failed"] == 0
    assert result["counts"]["local"] == 1
    assert result["counts"]["retries"] == 1


def test_resume_resets_running_jobs_before_processing(queue_db):
    insert_recording(queue_db, "alpha")
    dashboard = FakeDashboardController()
    service = ProcessingQueueService(queue_db, dashboard)
    queue_db.enqueue_processing_jobs("transcribe", ["alpha"], engine="whisper")
    claimed = queue_db.claim_next_processing_queue_job()

    assert claimed["status"] == "running"

    result = service.process_next(max_jobs=1, reset_running=True)

    assert result["counts"]["completed"] == 1
    assert service.list_jobs()["jobs"][0]["status"] == "completed"

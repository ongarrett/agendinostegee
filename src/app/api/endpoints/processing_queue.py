from fastapi import APIRouter, Depends

from app import depends
from models.dto.ProcessingQueueRequestDTO import (
    ProcessQueueRequestDTO,
    QueueSummarizationRequestDTO,
    QueueTranscriptionRequestDTO,
)
from services.ProcessingQueueService import ProcessingQueueService

router = APIRouter()


@router.get("/jobs")
async def list_processing_queue_jobs(
    status: str = "",
    job_type: str = "",
    processing_queue_service: ProcessingQueueService = Depends(depends.get_processing_queue_service),
):
    return processing_queue_service.list_jobs(status=status, job_type=job_type)


@router.get("/summary-pipeline")
async def get_summary_pipeline_status(
    processing_queue_service: ProcessingQueueService = Depends(depends.get_processing_queue_service),
):
    return processing_queue_service.summary_pipeline_status()


@router.post("/enqueue/transcribe-newest")
async def enqueue_transcribe_newest(
    body: QueueTranscriptionRequestDTO,
    processing_queue_service: ProcessingQueueService = Depends(depends.get_processing_queue_service),
):
    return processing_queue_service.enqueue_transcribe_newest(
        limit=body.limit or 25,
        collection_id=body.collection_id,
        engine=body.engine,
    )


@router.post("/enqueue/transcribe-collection")
async def enqueue_transcribe_collection(
    body: QueueTranscriptionRequestDTO,
    processing_queue_service: ProcessingQueueService = Depends(depends.get_processing_queue_service),
):
    if body.collection_id is None:
        return {"ok": False, "error": "collection_id is required"}
    return processing_queue_service.enqueue_transcribe_collection(body.collection_id, engine=body.engine)


@router.post("/enqueue/transcribe-retryable")
async def enqueue_transcribe_retryable_failures(
    body: QueueTranscriptionRequestDTO = QueueTranscriptionRequestDTO(),
    processing_queue_service: ProcessingQueueService = Depends(depends.get_processing_queue_service),
):
    return processing_queue_service.enqueue_transcribe_retryable_failures(engine=body.engine)


@router.post("/enqueue/transcribe-pending")
async def enqueue_transcribe_pending(
    body: QueueTranscriptionRequestDTO = QueueTranscriptionRequestDTO(),
    processing_queue_service: ProcessingQueueService = Depends(depends.get_processing_queue_service),
):
    return processing_queue_service.enqueue_transcribe_pending(engine=body.engine)


@router.post("/enqueue/summarize-newest")
async def enqueue_summarize_newest(
    body: QueueSummarizationRequestDTO,
    processing_queue_service: ProcessingQueueService = Depends(depends.get_processing_queue_service),
):
    return processing_queue_service.enqueue_summarize_newest(
        limit=body.limit or 25,
        collection_id=body.collection_id,
        prompt_id=body.prompt_id,
        summary_provider=body.summary_provider,
        summary_model=body.summary_model,
    )


@router.post("/enqueue/summarize-collection")
async def enqueue_summarize_collection(
    body: QueueSummarizationRequestDTO,
    processing_queue_service: ProcessingQueueService = Depends(depends.get_processing_queue_service),
):
    if body.collection_id is None:
        return {"ok": False, "error": "collection_id is required"}
    return processing_queue_service.enqueue_summarize_collection(
        body.collection_id,
        prompt_id=body.prompt_id,
        summary_provider=body.summary_provider,
        summary_model=body.summary_model,
    )


@router.post("/enqueue/summarize-missing")
async def enqueue_summarize_missing(
    body: QueueSummarizationRequestDTO,
    processing_queue_service: ProcessingQueueService = Depends(depends.get_processing_queue_service),
):
    return processing_queue_service.enqueue_summarize_missing(
        prompt_id=body.prompt_id,
        summary_provider=body.summary_provider,
        summary_model=body.summary_model,
    )


@router.post("/summary-pipeline/enqueue")
async def enqueue_summary_pipeline(
    body: QueueSummarizationRequestDTO,
    processing_queue_service: ProcessingQueueService = Depends(depends.get_processing_queue_service),
):
    return processing_queue_service.enqueue_summary_pipeline(
        limit=body.limit,
        prompt_id=body.prompt_id,
        summary_provider=body.summary_provider,
        summary_model=body.summary_model,
    )


@router.post("/summary-pipeline/pause")
async def pause_summary_pipeline(
    processing_queue_service: ProcessingQueueService = Depends(depends.get_processing_queue_service),
):
    return processing_queue_service.pause_summary_pipeline()


@router.post("/summary-pipeline/resume")
async def resume_summary_pipeline(
    body: ProcessQueueRequestDTO = ProcessQueueRequestDTO(max_jobs=5, max_retries=1, reset_running=True),
    processing_queue_service: ProcessingQueueService = Depends(depends.get_processing_queue_service),
):
    return processing_queue_service.resume_summary_pipeline(max_jobs=body.max_jobs, max_retries=body.max_retries)


@router.post("/summary-pipeline/retry-failed")
async def retry_failed_summary_jobs(
    processing_queue_service: ProcessingQueueService = Depends(depends.get_processing_queue_service),
):
    return processing_queue_service.retry_failed_summary_jobs()


@router.post("/summary-pipeline/clear-completed")
async def clear_completed_summary_jobs(
    processing_queue_service: ProcessingQueueService = Depends(depends.get_processing_queue_service),
):
    return processing_queue_service.clear_completed_summary_jobs()


@router.post("/clear-completed/{job_type}")
async def clear_completed_jobs(
    job_type: str,
    processing_queue_service: ProcessingQueueService = Depends(depends.get_processing_queue_service),
):
    return processing_queue_service.clear_completed_jobs(job_type=job_type)


@router.post("/clear-failed")
async def clear_failed_jobs(
    processing_queue_service: ProcessingQueueService = Depends(depends.get_processing_queue_service),
):
    return processing_queue_service.clear_failed_jobs()


@router.post("/process-next")
async def process_next_job(
    body: ProcessQueueRequestDTO = ProcessQueueRequestDTO(),
    processing_queue_service: ProcessingQueueService = Depends(depends.get_processing_queue_service),
):
    return processing_queue_service.process_next(
        max_jobs=body.max_jobs,
        reset_running=body.reset_running,
        max_retries=body.max_retries,
    )


@router.post("/resume")
async def resume_processing_queue(
    body: ProcessQueueRequestDTO = ProcessQueueRequestDTO(max_jobs=5, reset_running=True),
    processing_queue_service: ProcessingQueueService = Depends(depends.get_processing_queue_service),
):
    return processing_queue_service.process_next(
        max_jobs=body.max_jobs, reset_running=True, max_retries=body.max_retries
    )

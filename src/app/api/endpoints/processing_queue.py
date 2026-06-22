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
    processing_queue_service: ProcessingQueueService = Depends(depends.get_processing_queue_service),
):
    return processing_queue_service.list_jobs(status=status)


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


@router.post("/process-next")
async def process_next_job(
    body: ProcessQueueRequestDTO = ProcessQueueRequestDTO(),
    processing_queue_service: ProcessingQueueService = Depends(depends.get_processing_queue_service),
):
    return processing_queue_service.process_next(max_jobs=body.max_jobs, reset_running=body.reset_running)


@router.post("/resume")
async def resume_processing_queue(
    body: ProcessQueueRequestDTO = ProcessQueueRequestDTO(max_jobs=5, reset_running=True),
    processing_queue_service: ProcessingQueueService = Depends(depends.get_processing_queue_service),
):
    return processing_queue_service.process_next(max_jobs=body.max_jobs, reset_running=True)

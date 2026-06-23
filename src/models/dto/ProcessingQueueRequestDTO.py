from pydantic import BaseModel, Field


class QueueTranscriptionRequestDTO(BaseModel):
    limit: int | None = Field(default=None, ge=1, le=500)
    collection_id: int | None = None
    engine: str = "whisper"


class QueueSummarizationRequestDTO(BaseModel):
    limit: int | None = Field(default=None, ge=1, le=500)
    collection_id: int | None = None
    prompt_id: str
    summary_provider: str = "local"
    summary_model: str | None = "qwen3:8b"


class ProcessQueueRequestDTO(BaseModel):
    max_jobs: int = Field(default=1, ge=1, le=50)
    max_retries: int = Field(default=0, ge=0, le=5)
    reset_running: bool = False

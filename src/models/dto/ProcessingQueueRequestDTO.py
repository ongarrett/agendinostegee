from pydantic import BaseModel, Field


class QueueTranscriptionRequestDTO(BaseModel):
    limit: int | None = Field(default=None, ge=1, le=500)
    collection_id: int | None = None
    engine: str = "whisper"


class QueueSummarizationRequestDTO(BaseModel):
    limit: int | None = Field(default=None, ge=1, le=500)
    collection_id: int | None = None
    prompt_id: str
    summary_provider: str = "gemini"
    summary_model: str | None = None


class ProcessQueueRequestDTO(BaseModel):
    max_jobs: int = Field(default=1, ge=1, le=50)
    reset_running: bool = False

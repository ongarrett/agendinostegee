from pydantic import BaseModel, Field


class SummarizeRequestDTO(BaseModel):
    prompt_id: str
    summary_provider: str = "gemini"
    summary_model: str | None = None


class BulkSummarizeRequestDTO(BaseModel):
    prompt_id: str
    names: list[str] = Field(default_factory=list)
    rate_limit_delay_seconds: float = 1.0
    max_retries: int = 1
    summary_provider: str = "local"
    summary_model: str | None = "qwen3:8b"

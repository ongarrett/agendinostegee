from pydantic import BaseModel, Field


class SummarizeRequestDTO(BaseModel):
    prompt_id: str


class BulkSummarizeRequestDTO(BaseModel):
    prompt_id: str
    names: list[str] = Field(default_factory=list)
    rate_limit_delay_seconds: float = 1.0
    max_retries: int = 1

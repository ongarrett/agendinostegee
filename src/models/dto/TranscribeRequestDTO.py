from pydantic import BaseModel, Field


class TranscribeRequestDTO(BaseModel):
    engine: str = "whisper"  # "gemini" or "whisper"


class BulkTranscribeRequestDTO(BaseModel):
    names: list[str] = Field(default_factory=list)
    engine: str = "whisper"  # "gemini" or "whisper"

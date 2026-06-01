from pydantic import BaseModel


class GenerateEmbeddingsRequestDTO(BaseModel):
    names: list[str]
    force: bool = False


class SemanticSearchRequestDTO(BaseModel):
    query: str
    top_k: int = 10


class RecordingQARequestDTO(BaseModel):
    question: str
    names: list[str] = []
    collection_id: int | None = None
    top_k: int = 6

from pydantic import BaseModel


class GenerateEmbeddingsRequestDTO(BaseModel):
    names: list[str]
    force: bool = False


class SemanticSearchRequestDTO(BaseModel):
    query: str
    top_k: int = 10

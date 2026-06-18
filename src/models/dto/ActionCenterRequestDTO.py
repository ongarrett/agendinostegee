from pydantic import BaseModel, Field


class ActionCenterExtractRequestDTO(BaseModel):
    names: list[str] = Field(default_factory=list)
    collection_id: int | None = None
    force: bool = False


class ActionCenterStatusRequestDTO(BaseModel):
    status: str

from pydantic import BaseModel


class CreateSavedViewRequestDTO(BaseModel):
    name: str
    search_query: str = ""
    collection_id: int | None = None
    date_filter: str = ""
    folder: str | None = None

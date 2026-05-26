from google import genai


class GeminiEmbeddingService:
    def __init__(self, api_key: str, model: str):
        self._client = genai.Client(api_key=api_key)
        self.model = model

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        result = self._client.models.embed_content(
            model=self.model,
            contents=texts,
        )
        embeddings = result.embeddings or []
        return [embedding.values for embedding in embeddings if embedding.values is not None]

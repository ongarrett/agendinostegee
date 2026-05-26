from __future__ import annotations

import hashlib
import math
import re

from repositories.SqliteDBRepository import SqliteDBRepository
from services.GeminiEmbeddingService import GeminiEmbeddingService


class SemanticSearchService:
    def __init__(
        self,
        sqlite_db_repository: SqliteDBRepository,
        embedding_service: GeminiEmbeddingService,
    ):
        self._sqlite_db_repository = sqlite_db_repository
        self._embedding_service = embedding_service

    @staticmethod
    def _safe_error(exc: Exception) -> str:
        message = str(exc)
        return re.sub(r"AIza[0-9A-Za-z_-]+", "[redacted-api-key]", message)

    @staticmethod
    def _build_index_text(source: dict) -> str:
        parts = [
            source.get("title") or source.get("label") or source.get("name") or "",
            source.get("tags") or "",
            source.get("summary") or "",
            source.get("transcript") or "",
        ]
        return "\n\n".join(part.strip() for part in parts if part and part.strip())

    @staticmethod
    def _content_hash(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    @staticmethod
    def _preview(text: str, limit: int = 240) -> str:
        clean = " ".join((text or "").split())
        if len(clean) <= limit:
            return clean
        return clean[: limit - 3].rstrip() + "..."

    @staticmethod
    def _cosine_similarity(left: list[float], right: list[float]) -> float:
        if not left or not right or len(left) != len(right):
            return 0.0
        dot = sum(a * b for a, b in zip(left, right))
        left_norm = math.sqrt(sum(a * a for a in left))
        right_norm = math.sqrt(sum(b * b for b in right))
        if left_norm == 0 or right_norm == 0:
            return 0.0
        return dot / (left_norm * right_norm)

    def index_recordings(self, names: list[str], force: bool = False) -> dict:
        clean_names = [name.strip() for name in names if name and name.strip()]
        if not clean_names:
            return {"ok": False, "error": "Select at least one recording to index."}

        results = []
        for name in clean_names:
            source = self._sqlite_db_repository.get_recording_embedding_source(name)
            if not source:
                results.append({"name": name, "status": "failed", "error": "Recording not found."})
                continue

            text = self._build_index_text(source)
            content_hash = self._content_hash(text) if text else None

            if not text:
                error = "No transcript, summary, title, or tags available to index."
                self._sqlite_db_repository.save_recording_embedding(
                    name=name,
                    status="failed",
                    model=self._embedding_service.model,
                    content_hash=content_hash,
                    error=error,
                )
                results.append({"name": name, "status": "failed", "error": error})
                continue

            if (
                not force
                and source.get("embedding_status") == "indexed"
                and source.get("embedding_model") == self._embedding_service.model
                and source.get("content_hash") == content_hash
            ):
                results.append({"name": name, "status": "indexed", "skipped": True})
                continue

            try:
                embeddings = self._embedding_service.embed_texts([text])
                if not embeddings:
                    raise RuntimeError("Embedding provider returned no vectors.")
                self._sqlite_db_repository.save_recording_embedding(
                    name=name,
                    status="indexed",
                    model=self._embedding_service.model,
                    content_hash=content_hash,
                    embedding=embeddings[0],
                    error=None,
                )
                results.append({"name": name, "status": "indexed", "skipped": False})
            except Exception as exc:
                error = f"Embedding failed: {self._safe_error(exc)}"
                self._sqlite_db_repository.save_recording_embedding(
                    name=name,
                    status="failed",
                    model=self._embedding_service.model,
                    content_hash=content_hash,
                    error=error,
                )
                results.append({"name": name, "status": "failed", "error": error})

        indexed = sum(1 for item in results if item["status"] == "indexed" and not item.get("skipped"))
        skipped = sum(1 for item in results if item.get("skipped"))
        failed = sum(1 for item in results if item["status"] == "failed")
        return {
            "ok": failed == 0,
            "counts": {
                "indexed": indexed,
                "skipped": skipped,
                "failed": failed,
            },
            "results": results,
        }

    def search(self, query: str, top_k: int = 10) -> dict:
        clean_query = (query or "").strip()
        if not clean_query:
            return {"ok": False, "error": "Enter a semantic search query."}

        indexed = self._sqlite_db_repository.get_indexed_recording_embeddings()
        if not indexed:
            return {
                "ok": True,
                "results": [],
                "message": "No indexed recordings yet. Generate embeddings for recordings first.",
            }

        try:
            query_embeddings = self._embedding_service.embed_texts([clean_query])
            if not query_embeddings:
                raise RuntimeError("Embedding provider returned no query vector.")
        except Exception as exc:
            return {
                "ok": False,
                "error": (
                    "Semantic search failed. Check GEMINI_API_KEY and GEMINI_EMBEDDING_MODEL, "
                    f"then try again. Details: {self._safe_error(exc)}"
                ),
            }

        query_embedding = query_embeddings[0]
        results = []
        for item in indexed:
            score = self._cosine_similarity(query_embedding, item["embedding"])
            results.append(
                {
                    "name": item["name"],
                    "title": item["title"] or item["label"] or item["name"],
                    "tags": [tag.strip() for tag in (item["tags"] or "").split(",") if tag.strip()],
                    "summary_preview": self._preview(item["summary"]),
                    "transcript_preview": self._preview(item["transcript"]),
                    "score": round(score, 4),
                    "indexed_at": item["indexed_at"],
                }
            )

        results.sort(key=lambda item: item["score"], reverse=True)
        safe_top_k = min(max(int(top_k or 10), 1), 50)
        return {"ok": True, "results": results[:safe_top_k]}

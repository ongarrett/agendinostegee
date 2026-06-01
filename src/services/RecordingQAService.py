from __future__ import annotations

from repositories.SqliteDBRepository import SqliteDBRepository
from services.GeminiEmbeddingService import GeminiEmbeddingService
from services.GeminiQAService import GeminiQAService
from services.SemanticSearchService import SemanticSearchService

MAX_CONTEXT_SOURCES = 8
MAX_SOURCE_CHARS = 5000


class RecordingQAService:
    def __init__(
        self,
        sqlite_db_repository: SqliteDBRepository,
        embedding_service: GeminiEmbeddingService,
        qa_service: GeminiQAService,
    ):
        self._sqlite_db_repository = sqlite_db_repository
        self._embedding_service = embedding_service
        self._qa_service = qa_service

    @staticmethod
    def _clean_names(names: list[str] | None) -> list[str]:
        seen = set()
        clean = []
        for name in names or []:
            stripped = (name or "").strip()
            if stripped and stripped not in seen:
                seen.add(stripped)
                clean.append(stripped)
        return clean

    @staticmethod
    def _source_text(source: dict) -> str:
        parts = [
            f"Title: {source.get('title') or source.get('label') or source.get('name')}",
            f"Tags: {source.get('tags') or ''}",
            f"Summary:\n{source.get('summary') or ''}",
            f"Transcript:\n{source.get('transcript') or ''}",
        ]
        text = "\n\n".join(part.strip() for part in parts if part and part.strip())
        if len(text) <= MAX_SOURCE_CHARS:
            return text
        return text[: MAX_SOURCE_CHARS - 3].rstrip() + "..."

    @staticmethod
    def _has_context(source: dict) -> bool:
        return bool((source.get("summary") or "").strip() or (source.get("transcript") or "").strip())

    @staticmethod
    def _safe_top_k(top_k: int | None) -> int:
        return min(max(int(top_k or 6), 1), MAX_CONTEXT_SOURCES)

    @staticmethod
    def _citation_key(citation: dict) -> tuple[int, str]:
        return (int(citation["source_id"]), citation["recording_name"])

    def _rank_sources(self, question: str, sources: list[dict]) -> tuple[list[dict], str, str | None]:
        indexed = [
            source for source in sources if source.get("embedding_status") == "indexed" and source.get("embedding")
        ]
        if not indexed:
            return sources, "text fallback", "No indexed embeddings were available in this selection."

        try:
            question_embeddings = self._embedding_service.embed_texts([question])
            if not question_embeddings:
                raise RuntimeError("Embedding provider returned no query vector.")
        except Exception as exc:
            return (
                sources,
                "text fallback",
                f"Embedding ranking was unavailable: {SemanticSearchService._safe_error(exc)}",
            )

        query_embedding = question_embeddings[0]
        scored = []
        for source in sources:
            embedding = source.get("embedding")
            if source.get("embedding_status") == "indexed" and embedding:
                score = SemanticSearchService._cosine_similarity(query_embedding, embedding)
            else:
                score = -1.0
            source = {**source, "qa_score": score}
            scored.append(source)
        scored.sort(key=lambda item: item["qa_score"], reverse=True)
        return scored, "semantic", None

    def _build_context(self, sources: list[dict]) -> tuple[str, list[dict], dict[tuple[int, str], dict]]:
        context_parts = []
        source_refs = []
        citation_lookup = {}
        for idx, source in enumerate(sources, start=1):
            title = source.get("title") or source.get("label") or source.get("name")
            ref = {
                "source_id": idx,
                "recording_name": source["name"],
                "title": title,
                "embedding_status": source.get("embedding_status") or "not indexed",
            }
            source_refs.append(ref)
            citation_lookup[self._citation_key(ref)] = ref
            context_parts.append(
                f"[{idx}] Recording: {source['name']}\n"
                f"Title: {title}\n"
                f"Embedding status: {ref['embedding_status']}\n\n"
                f"{self._source_text(source)}"
            )
        return "\n\n---\n\n".join(context_parts), source_refs, citation_lookup

    def ask(
        self,
        question: str,
        names: list[str] | None = None,
        collection_id: int | None = None,
        top_k: int | None = 6,
    ) -> dict:
        clean_question = (question or "").strip()
        if not clean_question:
            return {"ok": False, "error": "Enter a question first."}

        clean_names = self._clean_names(names)
        if not clean_names and collection_id is None:
            return {"ok": False, "error": "Select recordings or choose a collection before asking AI."}

        sources = self._sqlite_db_repository.get_recording_qa_sources(
            names=clean_names or None,
            collection_id=collection_id,
        )
        if not sources:
            return {
                "ok": False,
                "error": "No matching recordings were found for this question.",
                "sources": [],
            }

        sources_with_context = [source for source in sources if self._has_context(source)]
        if not sources_with_context:
            return {
                "ok": True,
                "answer": (
                    "I do not have enough transcript or summary context in the selected recordings to answer that."
                ),
                "citations": [],
                "sources": [],
                "retrieval": {
                    "mode": "none",
                    "message": "Selected recordings do not have transcript or summary text yet.",
                },
            }

        ranked_sources, retrieval_mode, retrieval_message = self._rank_sources(clean_question, sources_with_context)
        selected_sources = ranked_sources[: self._safe_top_k(top_k)]
        context, source_refs, citation_lookup = self._build_context(selected_sources)

        try:
            qa_result = self._qa_service.answer(clean_question, context)
        except Exception as exc:
            return {
                "ok": False,
                "error": (
                    "AI Q&A failed. Check GEMINI_API_KEY and GEMINI_MODEL, then try again. "
                    f"Details: {SemanticSearchService._safe_error(exc)}"
                ),
                "sources": source_refs,
            }

        citations = []
        seen_citations = set()
        for citation in qa_result.get("citations", []):
            try:
                key = self._citation_key(citation)
            except (KeyError, TypeError, ValueError):
                continue
            ref = citation_lookup.get(key)
            if ref and key not in seen_citations:
                citations.append(ref)
                seen_citations.add(key)

        return {
            "ok": True,
            "answer": qa_result.get("answer")
            or "I do not have enough information in the selected recordings to answer that.",
            "citations": citations,
            "sources": source_refs,
            "retrieval": {
                "mode": retrieval_mode,
                "message": retrieval_message,
            },
            "ai_generated": True,
        }

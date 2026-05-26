from datetime import datetime

import pytest

from models.DBRecording import DBRecording
from repositories.SqliteDBRepository import SqliteDBRepository
from services.SemanticSearchService import SemanticSearchService


class FakeEmbeddingService:
    model = "fake-embedding-model"

    def __init__(self):
        self.calls = []

    def embed_texts(self, texts):
        self.calls.extend(texts)
        embeddings = []
        for text in texts:
            lower = text.lower()
            if "beta" in lower:
                embeddings.append([0.0, 1.0])
            else:
                embeddings.append([1.0, 0.0])
        return embeddings


class FailingEmbeddingService(FakeEmbeddingService):
    def embed_texts(self, texts):
        raise RuntimeError("API key not valid: AIza" + ("x" * 35))


@pytest.fixture
def semantic_db(tmp_path):
    return SqliteDBRepository(
        "semantic_test.db",
        str(tmp_path),
        "settings/db_init.sql",
    )


def insert_recording(db, name, transcript="", summary="", title="", tags=""):
    db.insert_recording(
        DBRecording(
            id=None,
            name=name,
            label=name,
            duration=10,
            created_at=datetime.now(),
            transcript=transcript,
        )
    )
    if summary or title or tags:
        db.save_summarization_result(name, summary=summary, title=title, tags=tags)


def test_index_recording_updates_status(semantic_db):
    insert_recording(
        semantic_db,
        "alpha",
        transcript="Alpha transcript",
        summary="Alpha summary",
        title="Alpha",
        tags="strategy",
    )
    embedding_service = FakeEmbeddingService()
    service = SemanticSearchService(semantic_db, embedding_service)

    result = service.index_recordings(["alpha"])

    assert result["ok"] is True
    assert result["counts"]["indexed"] == 1
    assert semantic_db.get_recording_embedding_status_map()["alpha"]["status"] == "indexed"
    assert semantic_db.get_indexed_recording_embeddings()[0]["embedding"] == [1.0, 0.0]


def test_index_recording_skips_current_embedding_without_force(semantic_db):
    insert_recording(semantic_db, "alpha", transcript="Alpha transcript")
    embedding_service = FakeEmbeddingService()
    service = SemanticSearchService(semantic_db, embedding_service)

    assert service.index_recordings(["alpha"])["counts"]["indexed"] == 1
    second = service.index_recordings(["alpha"])

    assert second["counts"]["skipped"] == 1
    assert len(embedding_service.calls) == 1


def test_regenerate_embedding_reindexes_with_force(semantic_db):
    insert_recording(semantic_db, "alpha", transcript="Alpha transcript")
    embedding_service = FakeEmbeddingService()
    service = SemanticSearchService(semantic_db, embedding_service)

    service.index_recordings(["alpha"])
    result = service.index_recordings(["alpha"], force=True)

    assert result["counts"]["indexed"] == 1
    assert len(embedding_service.calls) == 2


def test_semantic_search_returns_sorted_indexed_results(semantic_db):
    insert_recording(semantic_db, "alpha", transcript="Alpha transcript", summary="Alpha summary", title="Alpha")
    insert_recording(semantic_db, "beta", transcript="Beta transcript", summary="Beta summary", title="Beta")
    service = SemanticSearchService(semantic_db, FakeEmbeddingService())
    service.index_recordings(["alpha", "beta"])

    result = service.search("alpha")

    assert result["ok"] is True
    assert [item["name"] for item in result["results"]] == ["alpha", "beta"]
    assert result["results"][0]["score"] > result["results"][1]["score"]


def test_semantic_search_handles_no_indexed_recordings(semantic_db):
    service = SemanticSearchService(semantic_db, FakeEmbeddingService())

    result = service.search("strategy")

    assert result["ok"] is True
    assert result["results"] == []
    assert "No indexed recordings" in result["message"]


def test_embedding_failure_marks_status_and_redacts_key(semantic_db):
    insert_recording(semantic_db, "alpha", transcript="Alpha transcript")
    service = SemanticSearchService(semantic_db, FailingEmbeddingService())

    result = service.index_recordings(["alpha"])

    assert result["ok"] is False
    error = semantic_db.get_recording_embedding_status_map()["alpha"]["error"]
    assert "failed" in error.lower()
    assert "AIza" not in error
    assert "[redacted-api-key]" in error

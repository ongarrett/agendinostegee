from datetime import datetime

import pytest

from models.DBRecording import DBRecording
from repositories.SqliteDBRepository import SqliteDBRepository
from services.RecordingQAService import RecordingQAService


class FakeEmbeddingService:
    model = "fake-embedding-model"

    def embed_texts(self, texts):
        text = texts[0].lower()
        if "beta" in text:
            return [[0.0, 1.0]]
        return [[1.0, 0.0]]


class FakeQAService:
    def __init__(self, citations=None):
        self.calls = []
        self.citations = citations or [{"source_id": 1, "recording_name": "alpha", "title": "Alpha Title"}]

    def answer(self, question, context):
        self.calls.append({"question": question, "context": context})
        return {
            "answer": "Alpha is the grounded answer [1].",
            "citations": self.citations,
        }


@pytest.fixture
def qa_db(tmp_path):
    return SqliteDBRepository(
        "qa_test.db",
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


def test_ask_selected_recordings_uses_text_fallback_when_not_indexed(qa_db):
    insert_recording(
        qa_db,
        "alpha",
        transcript="Alpha transcript has the decision.",
        summary="Alpha summary",
        title="Alpha Title",
    )
    qa_service = FakeQAService()
    service = RecordingQAService(qa_db, FakeEmbeddingService(), qa_service)

    result = service.ask("What was decided?", names=["alpha"])

    assert result["ok"] is True
    assert result["answer"] == "Alpha is the grounded answer [1]."
    assert result["citations"][0]["recording_name"] == "alpha"
    assert result["retrieval"]["mode"] == "text fallback"
    assert "Alpha transcript" in qa_service.calls[0]["context"]


def test_ask_collection_retrieves_collection_recordings(qa_db):
    insert_recording(qa_db, "alpha", transcript="Alpha transcript", title="Alpha Title", summary="Alpha summary")
    insert_recording(qa_db, "beta", transcript="Beta transcript", title="Beta Title", summary="Beta summary")
    collection = qa_db.create_collection("Strategy")
    qa_db.add_recording_to_collection("beta", collection["id"])
    qa_service = FakeQAService(citations=[{"source_id": 1, "recording_name": "beta", "title": "Beta Title"}])
    service = RecordingQAService(qa_db, FakeEmbeddingService(), qa_service)

    result = service.ask("What happened?", collection_id=collection["id"])

    assert result["ok"] is True
    assert result["sources"][0]["recording_name"] == "beta"
    assert "Beta transcript" in qa_service.calls[0]["context"]
    assert "Alpha transcript" not in qa_service.calls[0]["context"]


def test_ask_ranks_indexed_sources_with_embeddings(qa_db):
    insert_recording(qa_db, "alpha", transcript="Alpha transcript", title="Alpha Title", summary="Alpha summary")
    insert_recording(qa_db, "beta", transcript="Beta transcript", title="Beta Title", summary="Beta summary")
    qa_db.save_recording_embedding("alpha", status="indexed", model="fake", embedding=[1.0, 0.0])
    qa_db.save_recording_embedding("beta", status="indexed", model="fake", embedding=[0.0, 1.0])
    qa_service = FakeQAService()
    service = RecordingQAService(qa_db, FakeEmbeddingService(), qa_service)

    result = service.ask("Tell me about beta", names=["alpha", "beta"])

    assert result["ok"] is True
    assert result["retrieval"]["mode"] == "semantic"
    assert result["sources"][0]["recording_name"] == "beta"


def test_ask_with_no_context_returns_insufficient_context(qa_db):
    insert_recording(qa_db, "alpha")
    qa_service = FakeQAService()
    service = RecordingQAService(qa_db, FakeEmbeddingService(), qa_service)

    result = service.ask("What happened?", names=["alpha"])

    assert result["ok"] is True
    assert "not have enough" in result["answer"]
    assert result["sources"] == []
    assert qa_service.calls == []


def test_ask_filters_hallucinated_citations(qa_db):
    insert_recording(qa_db, "alpha", transcript="Alpha transcript", title="Alpha Title", summary="Alpha summary")
    qa_service = FakeQAService(citations=[{"source_id": 2, "recording_name": "ghost", "title": "Ghost"}])
    service = RecordingQAService(qa_db, FakeEmbeddingService(), qa_service)

    result = service.ask("What happened?", names=["alpha"])

    assert result["ok"] is True
    assert result["citations"] == []
    assert result["sources"][0]["recording_name"] == "alpha"

from datetime import datetime

import pytest

from models.DBRecording import DBRecording
from repositories.SqliteDBRepository import SqliteDBRepository
from services.ActionIntelligenceService import ActionIntelligenceService


class FakeExtractor:
    def __init__(self, payload=None, error=None):
        self.payload = payload or {
            "action_items": [
                {
                    "text": "Send the launch plan",
                    "owner": "Stephanie",
                    "due_date": "",
                    "topics": ["Launch"],
                    "confidence": "high",
                    "source_excerpt": "Stephanie will send the launch plan.",
                }
            ],
            "decisions": [{"text": "Use SQLite for phase one", "topics": ["Architecture"]}],
            "risks": [{"text": "Timeline may slip", "owner": "", "topics": ["Delivery"]}],
            "open_questions": [{"text": "Who owns QA?", "owner": ""}],
            "people": ["Stephanie"],
            "topics": ["Launch"],
        }
        self.error = error
        self.calls = []

    def extract(self, source_text, recording_title=""):
        self.calls.append({"source_text": source_text, "recording_title": recording_title})
        if self.error:
            raise self.error
        return self.payload


@pytest.fixture
def action_db(tmp_path):
    return SqliteDBRepository(
        "action_center_test.db",
        str(tmp_path),
        "settings/db_init.sql",
    )


def insert_recording(db, name="alpha", transcript="", summary="", title="Alpha Title", tags="strategy"):
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
        db.save_summarization_result(name, title=title, tags=tags, summary=summary)


def test_parse_extraction_json_normalizes_items():
    raw = """
    {
      "action_items": [{"text": "Follow up", "owner": "Sam", "topics": "AI, Roadmap"}],
      "decisions": ["Ship phase one"],
      "risks": [],
      "open_questions": [],
      "people": ["Sam"],
      "topics": ["AI"]
    }
    """

    parsed = ActionIntelligenceService.parse_extraction_response(raw)

    assert parsed["action_items"][0]["text"] == "Follow up"
    assert parsed["action_items"][0]["owner"] == "Sam"
    assert parsed["action_items"][0]["topics"] == ["AI", "Roadmap"]
    assert parsed["decisions"][0]["text"] == "Ship phase one"


def test_extract_persists_and_filters_items(action_db):
    insert_recording(action_db, transcript="Transcript text", summary="Summary text")
    service = ActionIntelligenceService(action_db, FakeExtractor())

    result = service.extract_selected(["alpha"])

    assert result["counts"]["items"] == 4
    listed = service.list_items(item_type="action_item", owner="Stephanie", topic="Launch")
    assert len(listed["items"]) == 1
    assert listed["items"][0]["text"] == "Send the launch plan"
    assert listed["items"][0]["recording_name"] == "alpha"


def test_update_status_and_dismiss_item(action_db):
    insert_recording(action_db, summary="Summary text")
    service = ActionIntelligenceService(action_db, FakeExtractor())
    service.extract_selected(["alpha"])
    item = service.list_items(item_type="action_item")["items"][0]

    updated = service.update_item_status(item["id"], "done")
    dismissed = service.dismiss_item(item["id"])

    assert updated["ok"] is True
    assert updated["item"]["status"] == "done"
    assert dismissed["ok"] is True
    assert dismissed["item"]["status"] == "dismissed"
    assert service.list_items(item_type="action_item")["items"] == []
    assert service.list_items(item_type="action_item", include_dismissed=True)["items"][0]["status"] == "dismissed"


def test_skips_already_extracted_recording(action_db):
    insert_recording(action_db, summary="Summary text")
    extractor = FakeExtractor()
    service = ActionIntelligenceService(action_db, extractor)

    first = service.extract_selected(["alpha"])
    second = service.extract_selected(["alpha"])

    assert first["counts"]["items"] == 4
    assert second["counts"]["skipped"] == 1
    assert len(extractor.calls) == 1


def test_force_refresh_preserves_manually_completed_status(action_db):
    insert_recording(action_db, summary="Summary text")
    service = ActionIntelligenceService(action_db, FakeExtractor())
    service.extract_selected(["alpha"])
    item = service.list_items(item_type="action_item")["items"][0]
    service.update_item_status(item["id"], "done")

    result = service.extract_selected(["alpha"], force=True)
    items = service.list_items(item_type="action_item", include_dismissed=True)["items"]

    assert result["counts"]["items"] >= 1
    assert len(items) == 1
    assert items[0]["status"] == "done"


def test_fallback_when_gemini_fails(action_db):
    insert_recording(
        action_db,
        summary="Action: Send update\nDecision: Keep SQLite\nRisk: Timeline may slip\nQuestion: Who owns QA?",
    )
    service = ActionIntelligenceService(action_db, FakeExtractor(error=RuntimeError("Gemini down")))

    result = service.extract_selected(["alpha"])
    listed = service.list_items()

    assert result["counts"]["extracted"] == 1
    assert result["results"][0]["status"] == "fallback"
    assert {item["item_type"] for item in listed["items"]} == {
        "action_item",
        "decision",
        "risk",
        "open_question",
    }

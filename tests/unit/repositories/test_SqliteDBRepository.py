import os
import uuid
from datetime import datetime
from random import randint

import pytest

from models.DBRecording import DBRecording
from repositories.SqliteDBRepository import SqliteDBRepository


class TestSqliteDBRepository:

    @pytest.fixture
    def init_path(self):
        path = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(path, "../../../settings/db_init.sql")

    @pytest.fixture
    def db(self, tmp_path, init_path):
        return SqliteDBRepository("test_unit.db", str(tmp_path), init_path)

    @pytest.fixture
    def sample_recording(self):
        return DBRecording(
            id=None,
            name=f"2026Mar27-094938-Wip{randint(1, 99):02d}",
            label="Test Recording",
            duration=120,
            created_at=datetime(2026, 3, 27, 9, 49, 38),
        )

    def test_insert_and_get_recordings(self, db, sample_recording):
        row_id = db.insert_recording(sample_recording)
        assert row_id is not None

        recordings = db.get_recordings()
        assert len(recordings) == 1
        assert recordings[0].name == sample_recording.name
        assert recordings[0].label == sample_recording.label
        assert recordings[0].duration == sample_recording.duration

    def test_get_recording_by_name(self, db, sample_recording):
        db.insert_recording(sample_recording)

        found = db.get_recording_by_name(sample_recording.name)
        assert found is not None
        assert found.name == sample_recording.name

    def test_get_recording_by_name_not_found(self, db):
        result = db.get_recording_by_name("nonexistent")
        assert result is None

    def test_save_and_get_transcript(self, db, sample_recording):
        db.insert_recording(sample_recording)
        assert db.get_transcript(sample_recording.name) is None

        db.save_transcript(sample_recording.name, "Hello, this is a transcript.")
        transcript = db.get_transcript(sample_recording.name)
        assert transcript == "Hello, this is a transcript."

        rec = db.get_recording_by_name(sample_recording.name)
        assert rec.transcription_status == "transcribed"
        assert rec.transcription_segment_count == 1

    def test_update_transcription_metadata_for_corrupt_audio(self, db, sample_recording):
        db.insert_recording(sample_recording)

        updated = db.update_transcription_metadata(
            sample_recording.name,
            "corrupt_audio",
            error="Invalid data found when processing input",
        )

        rec = db.get_recording_by_name(sample_recording.name)
        assert updated is True
        assert rec.transcription_status == "corrupt_audio"
        assert "Invalid data" in rec.transcription_error
        assert rec.transcription_attempted_at is not None

    def test_failure_report_includes_recommended_action(self, db, sample_recording):
        db.insert_recording(sample_recording)
        db.update_transcription_metadata(sample_recording.name, "retryable_failure", error="timed out")

        report = db.get_transcription_failure_report()

        assert len(report) == 1
        assert report[0]["recording_name"] == sample_recording.name
        assert report[0]["transcription_status"] == "retryable_failure"
        assert report[0]["recommended_action"] == "Retry failed only"

    def test_backfill_classifies_failed_transcription_queue_errors(self, db, sample_recording):
        db.insert_recording(sample_recording)
        db.enqueue_processing_jobs("transcribe", [sample_recording.name], engine="whisper")
        job = db.claim_next_processing_queue_job()
        db.update_processing_queue_job_status(
            job["id"],
            "failed",
            error="FFmpeg decode error: Invalid data found when processing input",
        )

        result = db.backfill_transcription_statuses()
        rec = db.get_recording_by_name(sample_recording.name)

        assert result["ok"] is True
        assert rec.transcription_status == "corrupt_audio"

    def test_update_transcript(self, db, sample_recording):
        db.insert_recording(sample_recording)
        db.save_transcript(sample_recording.name, "Before")

        updated = db.update_transcript(sample_recording.name, "After")
        assert updated is True
        assert db.get_transcript(sample_recording.name) == "After"

    def test_update_transcript_not_found(self, db):
        updated = db.update_transcript("ghost", "text")
        assert updated is False

    def test_get_transcript_not_found(self, db):
        result = db.get_transcript("nonexistent")
        assert result is None

    def test_save_and_get_summary(self, db, sample_recording):
        db.insert_recording(sample_recording)
        assert db.get_summary(sample_recording.name) is None

        db.save_summary(sample_recording.name, "# Summary\nThis is a test.")
        summary = db.get_summary(sample_recording.name)
        assert summary == "# Summary\nThis is a test."

    def test_get_summary_not_found(self, db):
        result = db.get_summary("nonexistent")
        assert result is None

    def test_save_summarization_result(self, db, sample_recording):
        db.insert_recording(sample_recording)

        db.save_summarization_result(
            sample_recording.name,
            summary="Full summary text",
            title="Meeting Notes",
            tags="meeting,notes,work",
        )

        rec = db.get_recording_by_name(sample_recording.name)
        assert rec.summary == "Full summary text"
        assert rec.title == "Meeting Notes"
        assert rec.tags == "meeting,notes,work"
        # label should also be updated to the title
        assert rec.label == "Meeting Notes"

    def test_update_title_and_tags(self, db, sample_recording):
        db.insert_recording(sample_recording)

        db.update_title_and_tags(sample_recording.name, "New Title", "tag1,tag2")

        rec = db.get_recording_by_name(sample_recording.name)
        assert rec.title == "New Title"
        assert rec.tags == "tag1,tag2"
        assert rec.label == "New Title"

    def test_update_summary_content(self, db, sample_recording):
        db.insert_recording(sample_recording)
        saved = db.save_summarization_result(
            sample_recording.name,
            summary="Old summary",
            title="Meeting Notes",
            tags="meeting,notes,work",
        )

        updated = db.update_summary_content(saved.id, "New summary")
        assert updated is not None
        assert updated.summary == "New summary"

    def test_update_summary_content_not_found(self, db):
        updated = db.update_summary_content(999999, "New summary")
        assert updated is None

    def test_delete_recording(self, db, sample_recording):
        db.insert_recording(sample_recording)
        assert db.get_recording_by_name(sample_recording.name) is not None

        result = db.delete_recording(sample_recording.name)
        assert result is True
        assert db.get_recording_by_name(sample_recording.name) is None

    def test_delete_recording_not_found(self, db):
        result = db.delete_recording("nonexistent")
        assert result is False

    def test_save_notion_url(self, db, sample_recording):
        db.insert_recording(sample_recording)

        db.save_notion_url(sample_recording.name, "https://notion.so/page123")

        rec = db.get_recording_by_name(sample_recording.name)
        assert rec.notion_url == "https://notion.so/page123"

    def test_multiple_recordings(self, db):
        for i in range(5):
            rec = DBRecording(
                id=None,
                name=f"rec_{i}",
                label=f"Recording {i}",
                duration=i * 60,
                created_at=datetime(2026, 4, 1),
            )
            db.insert_recording(rec)

        all_recs = db.get_recordings()
        assert len(all_recs) == 5

    def test_migration_on_existing_db(self, tmp_path, init_path):
        """Creating a repo twice on the same db should trigger migration path without error."""
        db1 = SqliteDBRepository("migrate_test.db", str(tmp_path), init_path)
        rec = DBRecording(id=None, name="test", label="Test", duration=10, created_at=datetime.now())
        db1.insert_recording(rec)

        # Second instantiation triggers _migrate_db instead of _initialize_db
        db2 = SqliteDBRepository("migrate_test.db", str(tmp_path), init_path)
        recordings = db2.get_recordings()
        assert len(recordings) == 1

    def test_create_collection(self, db):
        collection = db.create_collection("AI Strategy", "Strategic AI conversations")

        assert collection["id"] is not None
        assert collection["name"] == "AI Strategy"
        assert collection["description"] == "Strategic AI conversations"
        assert collection["count"] == 0

    def test_create_collection_reuses_existing_name_case_insensitive(self, db):
        first = db.create_collection("Features")
        second = db.create_collection("features")

        assert second["id"] == first["id"]
        assert second["created"] is False

    def test_add_and_remove_recording_collection(self, db, sample_recording):
        db.insert_recording(sample_recording)
        collection = db.create_collection("Catch-Up")

        added = db.add_recording_to_collection(sample_recording.name, collection["id"])
        assert added is True

        collections = db.get_recording_collections(sample_recording.name)
        assert [c["name"] for c in collections] == ["Catch-Up"]

        counts = db.get_collections_with_counts()
        assert counts[0]["count"] == 1

        removed = db.remove_recording_from_collection(sample_recording.name, collection["id"])
        assert removed is True
        assert db.get_recording_collections(sample_recording.name) == []

    def test_many_to_many_collection_membership(self, db):
        rec_a = DBRecording(id=None, name="rec-a", label="Rec A", duration=10, created_at=datetime.now())
        rec_b = DBRecording(id=None, name="rec-b", label="Rec B", duration=20, created_at=datetime.now())
        db.insert_recording(rec_a)
        db.insert_recording(rec_b)
        strategy = db.create_collection("AI Strategy")
        podcast = db.create_collection("Podcast Ideas")

        db.add_recording_to_collection("rec-a", strategy["id"])
        db.add_recording_to_collection("rec-a", podcast["id"])
        db.add_recording_to_collection("rec-b", strategy["id"])

        rec_a_collections = db.get_recording_collections("rec-a")
        assert {c["name"] for c in rec_a_collections} == {"AI Strategy", "Podcast Ideas"}

        counts = {c["name"]: c["count"] for c in db.get_collections_with_counts()}
        assert counts["AI Strategy"] == 2
        assert counts["Podcast Ideas"] == 1

    def test_set_recording_collections_replaces_membership(self, db, sample_recording):
        db.insert_recording(sample_recording)
        first = db.create_collection("Leadership")
        second = db.create_collection("Audience Strategy")

        updated = db.set_recording_collections(sample_recording.name, [first["id"], second["id"]])
        assert updated is True
        assert {c["name"] for c in db.get_recording_collections(sample_recording.name)} == {
            "Leadership",
            "Audience Strategy",
        }

        db.set_recording_collections(sample_recording.name, [second["id"]])
        assert [c["name"] for c in db.get_recording_collections(sample_recording.name)] == ["Audience Strategy"]

    def test_recording_collections_map(self, db, sample_recording):
        db.insert_recording(sample_recording)
        collection = db.create_collection("Editorial Workflows")
        db.add_recording_to_collection(sample_recording.name, collection["id"])

        mapping = db.get_recording_collections_map()
        assert mapping[sample_recording.name][0]["name"] == "Editorial Workflows"

    def test_create_saved_view(self, db):
        collection = db.create_collection("AI Strategy")

        saved_view = db.create_saved_view(
            name="Strategy this week",
            search_query="roadmap",
            collection_id=collection["id"],
            date_filter="2026-05-25",
            folder="/work",
        )

        assert saved_view["id"] is not None
        assert saved_view["name"] == "Strategy this week"
        assert saved_view["search_query"] == "roadmap"
        assert saved_view["collection_id"] == collection["id"]
        assert saved_view["collection_name"] == "AI Strategy"
        assert saved_view["date_filter"] == "2026-05-25"
        assert saved_view["folder"] == "/work"

    def test_get_saved_views(self, db):
        db.create_saved_view("Catch-Up", search_query="weekly")
        db.create_saved_view("Features", date_filter="2026-05-25")

        saved_views = db.get_saved_views()

        assert [view["name"] for view in saved_views] == ["Catch-Up", "Features"]

    def test_delete_saved_view(self, db):
        saved_view = db.create_saved_view("Delete me", search_query="old")

        deleted = db.delete_saved_view(saved_view["id"])

        assert deleted is True
        assert db.get_saved_views() == []

    def test_delete_saved_view_not_found(self, db):
        assert db.delete_saved_view(999999) is False

    def test_create_saved_view_duplicate_name_raises(self, db):
        db.create_saved_view("Reports")

        with pytest.raises(ValueError):
            db.create_saved_view("reports")

    def test_embedding_status_defaults_to_not_indexed(self, db, sample_recording):
        db.insert_recording(sample_recording)

        statuses = db.get_recording_embedding_status_map()

        assert statuses[sample_recording.name]["status"] == "not indexed"
        assert statuses[sample_recording.name]["model"] is None

    def test_save_and_get_indexed_recording_embedding(self, db, sample_recording):
        db.insert_recording(sample_recording)

        saved = db.save_recording_embedding(
            sample_recording.name,
            status="indexed",
            model="gemini-embedding-001",
            content_hash="abc123",
            embedding=[0.1, 0.2, 0.3],
        )

        assert saved is True
        statuses = db.get_recording_embedding_status_map()
        assert statuses[sample_recording.name]["status"] == "indexed"
        indexed = db.get_indexed_recording_embeddings()
        assert indexed[0]["name"] == sample_recording.name
        assert indexed[0]["embedding"] == [0.1, 0.2, 0.3]

    def test_save_failed_recording_embedding(self, db, sample_recording):
        db.insert_recording(sample_recording)

        db.save_recording_embedding(
            sample_recording.name,
            status="failed",
            model="gemini-embedding-001",
            error="No content",
        )

        statuses = db.get_recording_embedding_status_map()
        assert statuses[sample_recording.name]["status"] == "failed"
        assert statuses[sample_recording.name]["error"] == "No content"
        assert db.get_indexed_recording_embeddings() == []

    def test_get_recording_embedding_source_includes_latest_text(self, db, sample_recording):
        db.insert_recording(sample_recording)
        db.save_transcript(sample_recording.name, "Transcript text")
        db.save_summarization_result(
            sample_recording.name,
            title="Strategy Call",
            tags="ai,roadmap",
            summary="Summary text",
        )

        source = db.get_recording_embedding_source(sample_recording.name)

        assert source["name"] == sample_recording.name
        assert source["title"] == "Strategy Call"
        assert source["tags"] == "ai,roadmap"
        assert source["summary"] == "Summary text"
        assert source["transcript"] == "Transcript text"

    def test_get_recording_qa_sources_by_names(self, db):
        rec_a = DBRecording(id=None, name="alpha", label="Alpha", duration=10, created_at=datetime.now())
        rec_b = DBRecording(id=None, name="beta", label="Beta", duration=10, created_at=datetime.now())
        db.insert_recording(rec_a)
        db.insert_recording(rec_b)
        db.save_transcript("alpha", "Alpha transcript")
        db.save_summarization_result("alpha", title="Alpha Title", tags="strategy", summary="Alpha summary")
        db.save_recording_embedding("alpha", status="indexed", model="fake", embedding=[1.0, 0.0])

        sources = db.get_recording_qa_sources(names=["alpha"])

        assert [source["name"] for source in sources] == ["alpha"]
        assert sources[0]["title"] == "Alpha Title"
        assert sources[0]["summary"] == "Alpha summary"
        assert sources[0]["transcript"] == "Alpha transcript"
        assert sources[0]["embedding"] == [1.0, 0.0]

    def test_get_recording_qa_sources_by_collection(self, db):
        rec_a = DBRecording(id=None, name="alpha", label="Alpha", duration=10, created_at=datetime.now())
        rec_b = DBRecording(id=None, name="beta", label="Beta", duration=10, created_at=datetime.now())
        db.insert_recording(rec_a)
        db.insert_recording(rec_b)
        collection = db.create_collection("Strategy")
        db.add_recording_to_collection("beta", collection["id"])

        sources = db.get_recording_qa_sources(collection_id=collection["id"])

        assert [source["name"] for source in sources] == ["beta"]

    def test_get_recording_names_by_collection(self, db):
        rec_a = DBRecording(id=None, name="alpha", label="Alpha", duration=10, created_at=datetime.now())
        rec_b = DBRecording(id=None, name="beta", label="Beta", duration=10, created_at=datetime.now())
        db.insert_recording(rec_a)
        db.insert_recording(rec_b)
        collection = db.create_collection("Strategy")
        db.add_recording_to_collection("beta", collection["id"])

        assert db.get_recording_names_by_collection(collection["id"]) == ["beta"]

    def test_get_unindexed_recording_names(self, db):
        rec_a = DBRecording(id=None, name="alpha", label="Alpha", duration=10, created_at=datetime.now())
        rec_b = DBRecording(id=None, name="beta", label="Beta", duration=10, created_at=datetime.now())
        rec_c = DBRecording(id=None, name="gamma", label="Gamma", duration=10, created_at=datetime.now())
        db.insert_recording(rec_a)
        db.insert_recording(rec_b)
        db.insert_recording(rec_c)
        db.save_recording_embedding("alpha", status="indexed", model="fake", embedding=[1.0, 0.0])
        db.save_recording_embedding("beta", status="failed", model="fake", error="No content")

        assert db.get_unindexed_recording_names() == ["beta", "gamma"]

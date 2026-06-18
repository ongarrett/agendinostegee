import os
from datetime import datetime

import pytest

from models.DBRecording import DBRecording
from repositories.LocalRecordingsRepository import LocalRecordingsRepository
from repositories.SqliteDBRepository import SqliteDBRepository
from services.BulkImportService import BulkImportService, SUMMARY_NEEDS_REVIEW, UNSUPPORTED_REASON


@pytest.fixture
def bulk_import_service(tmp_path):
    db = SqliteDBRepository(
        db_name="bulk_import.db",
        db_path=str(tmp_path),
        init_sql_script=os.path.join(os.path.dirname(__file__), "../../../settings/db_init.sql"),
    )
    local_repo = LocalRecordingsRepository(str(tmp_path / "local_recordings"))
    return BulkImportService(db, local_repo), db, local_repo


def test_upload_preview_pairs_mp3_and_txt_by_filename_similarity(bulk_import_service):
    service, _db, _local_repo = bulk_import_service
    files = [
        ("client-call.mp3", b"audio"),
        ("client call transcript summary.txt", b"Transcript\nHello\n\nSummary\nDone"),
    ]

    result = service.preview_upload(files)

    assert result["ok"] is True
    assert result["counts"]["pairs"] == 1
    pair = result["pairs"][0]
    assert pair["audio_file"] == "client-call.mp3"
    assert pair["text_file"] == "client call transcript summary.txt"
    assert pair["status"] == "matched"
    assert pair["summary_status"] == "detected"
    assert pair["transcript_status"] == "detected"


def test_upload_preview_treats_hda_as_audio_only_import(bulk_import_service):
    service, _db, _local_repo = bulk_import_service
    files = [("2026Jun01-090000-Rec01.hda", b"hda audio")]

    result = service.preview_upload(files)

    assert result["ok"] is True
    assert result["counts"]["pairs"] == 1
    assert result["counts"]["audio_only"] == 1
    assert result["counts"]["importable"] == 1
    assert result["counts"]["unsupported"] == 0
    assert result["counts"]["unmatched"] == 0
    item = result["pairs"][0]
    assert item["audio_file"] == "2026Jun01-090000-Rec01.hda"
    assert item["text_file"] is None
    assert item["status"] == "audio only"
    assert item["summary_status"] == "missing"
    assert item["transcript_status"] == "missing"


def test_upload_confirm_imports_mp3_without_companion_txt(bulk_import_service):
    service, db, local_repo = bulk_import_service
    files = [("audio-only.mp3", b"mp3 audio")]

    result = service.confirm_upload(files)

    assert result["ok"] is True
    assert result["counts"]["imported"] == 1
    assert result["counts"]["audio_only"] == 1
    assert result["counts"]["unmatched"] == 0
    assert local_repo.exists("audio-only.mp3")

    recording = db.get_recording_by_name("audio-only")
    assert recording is not None
    assert recording.file_extension == "mp3"
    assert recording.transcript is None
    assert db.get_summaries("audio-only") == []


def test_upload_confirm_imports_hda_without_companion_txt(bulk_import_service):
    service, db, local_repo = bulk_import_service
    files = [("device-recording.hda", b"hda audio")]

    result = service.confirm_upload(files)

    assert result["ok"] is True
    assert result["counts"]["imported"] == 1
    assert result["counts"]["audio_only"] == 1
    assert local_repo.exists("device-recording.hda")

    recording = db.get_recording_by_name("device-recording")
    assert recording is not None
    assert recording.file_extension == "hda"
    assert recording.transcript is None
    assert db.get_summaries("device-recording") == []


def test_upload_confirm_still_imports_paired_mp3_and_txt(bulk_import_service):
    service, db, local_repo = bulk_import_service
    files = [
        ("paired-session.mp3", b"mp3 audio"),
        ("paired session.txt", b"Transcript\nSpeaker 1: imported text\n\nSummary\nImported summary"),
    ]

    result = service.confirm_upload(files)

    assert result["ok"] is True
    assert result["counts"]["imported"] == 1
    assert result["counts"]["audio_only"] == 0
    assert local_repo.exists("paired-session.mp3")
    assert db.get_transcript("paired-session") == "Speaker 1: imported text"
    summary = db.get_summaries("paired-session")[0]
    assert summary.summary == "Imported summary"
    assert summary.prompt_id == "bulk_import"


def test_upload_preview_explains_unsupported_file_types(bulk_import_service):
    service, _db, _local_repo = bulk_import_service
    files = [("notes.pdf", b"not supported")]

    result = service.preview_upload(files)

    assert result["counts"]["unsupported"] == 1
    assert result["unsupported"][0]["reason"] == UNSUPPORTED_REASON
    assert ".hda" in result["unsupported"][0]["reason"]
    assert ".mp3" in result["unsupported"][0]["reason"]
    assert ".txt" in result["unsupported"][0]["reason"]


def test_upload_preview_marks_unclear_txt_summary_as_needs_review(bulk_import_service):
    service, _db, _local_repo = bulk_import_service
    files = [("standup.mp3", b"audio"), ("standup.txt", b"Speaker 1: everything is one blob")]

    result = service.preview_upload(files)

    pair = result["pairs"][0]
    assert pair["status"] == "needs review"
    assert pair["summary_status"] == "needs review"
    assert pair["transcript_status"] == "detected"


def test_upload_confirm_imports_pair_without_regenerating_text(bulk_import_service):
    service, db, local_repo = bulk_import_service
    files = [
        ("planning.mp3", b"audio"),
        ("planning.txt", b"Transcript\nSpeaker 1: hello\n\nSummary\nKeep the summary"),
    ]

    result = service.confirm_upload(files)

    assert result["ok"] is True
    assert result["counts"]["imported"] == 1
    assert local_repo.exists("planning.mp3")
    assert db.get_transcript("planning") == "Speaker 1: hello"
    summary = db.get_summaries("planning")[0]
    assert summary.summary == "Keep the summary"
    assert summary.prompt_id == "bulk_import"


def test_hinotes_export_uses_content_before_transcription_as_summary(bulk_import_service):
    service, db, _local_repo = bulk_import_service
    hinotes_text = """📅 About Meeting
Date: 2026-05-24
Participants: Stephanie, Team

📒 Meeting Outline
- Launch plan
- Follow up

📋 Overview
The meeting covered migration risks and next steps.

🎯 Todo List
- Send the revised proposal

Transcription
Stephanie: Let's preserve this transcript exactly.
Team: Agreed.
"""
    files = [("hinotes-demo.mp3", b"audio"), ("hinotes-demo.txt", hinotes_text.encode("utf-8"))]

    preview = service.preview_upload(files)
    pair = preview["pairs"][0]
    assert pair["status"] == "matched"
    assert pair["summary_status"] == "detected"
    assert pair["transcript_status"] == "detected"

    result = service.confirm_upload(files)

    assert result["counts"]["imported"] == 1
    assert db.get_transcript("hinotes-demo") == "Stephanie: Let's preserve this transcript exactly.\nTeam: Agreed."
    summary = db.get_summaries("hinotes-demo")[0]
    assert "📅 About Meeting" in summary.summary
    assert "📒 Meeting Outline" in summary.summary
    assert "📋 Overview" in summary.summary
    assert "🎯 Todo List" in summary.summary
    assert "Transcription" not in summary.summary


def test_upload_confirm_saves_needs_review_summary_for_unclear_text(bulk_import_service):
    service, db, _local_repo = bulk_import_service
    files = [("retro.mp3", b"audio"), ("retro.txt", b"Speaker 1: no headings here")]

    result = service.confirm_upload(files)

    assert result["counts"]["imported"] == 1
    assert db.get_transcript("retro") == "Speaker 1: no headings here"
    summary = db.get_summaries("retro")[0]
    assert summary.summary == SUMMARY_NEEDS_REVIEW
    assert summary.tags == "needs-review"


def test_folder_preview_uses_same_pairing_logic(bulk_import_service, tmp_path):
    service, _db, _local_repo = bulk_import_service
    source = tmp_path / "library"
    source.mkdir()
    (source / "team-sync.mp3").write_bytes(b"audio")
    (source / "team sync notes.txt").write_text("Transcript\nHi\n\nSummary\nDone", encoding="utf-8")

    result = service.preview_folder(str(source))

    assert result["ok"] is True
    assert result["mode"] == "folder"
    assert result["counts"]["pairs"] == 1
    assert result["pairs"][0]["status"] == "matched"


def test_duplicate_audio_pair_is_skipped_duplicate(bulk_import_service):
    service, db, _local_repo = bulk_import_service
    db.insert_recording(
        DBRecording(
            id=None,
            name="client",
            label="Client",
            duration=0,
            file_extension="mp3",
            created_at=datetime.now(),
        )
    )
    files = [("client.mp3", b"audio"), ("client.txt", b"Transcript\nHi\n\nSummary\nDone")]

    result = service.preview_upload(files)

    assert result["pairs"][0]["status"] == "skipped duplicate"
    assert "already exists" in result["pairs"][0]["reason"]

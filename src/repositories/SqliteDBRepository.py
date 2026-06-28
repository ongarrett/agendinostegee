import json
import os
import sqlite3

from models.DBActionCenterItem import DBActionCenterItem
from models.DBCalendarEvent import DBCalendarEvent
from models.DBDailyRecap import DBDailyRecap
from models.DBRecording import DBRecording
from models.DBSummary import DBSummary
from models.DBTask import DBTask
from models.DBSharedCalendar import DBSharedCalendar

TRANSCRIPTION_STATUSES = {
    "transcribed",
    "no_speech_detected",
    "corrupt_audio",
    "retryable_failure",
    "pending",
    "very_short",
    "unknown",
}
VERY_SHORT_DURATION_SECONDS = 10
RECORDING_SELECT_COLUMNS = (
    "id, name, label, duration, file_extension, recorded_at, created_at, transcript, folder, "
    "transcription_status, transcription_error, transcription_attempted_at, transcription_segment_count, "
    "transcription_language, transcription_language_probability, transcription_vad_removed_duration, "
    "transcription_skipped"
)


class SqliteDBRepository:
    def __init__(self, db_name: str, db_path: str, init_sql_script: str):
        self._db_path = os.path.join(db_path, db_name)
        if not os.path.exists(self._db_path):
            self._initialize_db(init_sql_script)
        self._ensure_recording_columns()
        self._ensure_collection_tables()
        self._ensure_saved_view_tables()
        self._ensure_embedding_tables()
        self._ensure_action_center_tables()
        self._ensure_app_state_table()
        self._ensure_processing_queue_tables()
        self.backfill_transcription_statuses()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _initialize_db(self, init_sql_script: str) -> None:
        with open(init_sql_script, "r") as f:
            sql = f.read()
        conn = self._connect()
        conn.executescript(sql)
        conn.commit()
        conn.close()

    def _ensure_recording_columns(self) -> None:
        """Migration: add recording metadata columns if missing on existing DB."""
        conn = self._connect()
        try:
            try:
                conn.execute("SELECT file_extension FROM recording LIMIT 1")
            except Exception:
                conn.execute("ALTER TABLE recording ADD COLUMN file_extension TEXT NOT NULL DEFAULT 'hda'")
                conn.commit()
            try:
                conn.execute("SELECT recorded_at FROM recording LIMIT 1")
            except Exception:
                conn.execute("ALTER TABLE recording ADD COLUMN recorded_at TEXT DEFAULT NULL")
                conn.commit()
            try:
                conn.execute("SELECT folder FROM recording LIMIT 1")
            except Exception:
                conn.execute("ALTER TABLE recording ADD COLUMN folder TEXT NOT NULL DEFAULT '/'")
                conn.commit()
            self._ensure_column(conn, "recording", "transcription_status", "TEXT NOT NULL DEFAULT 'pending'")
            self._ensure_column(conn, "recording", "transcription_error", "TEXT DEFAULT NULL")
            self._ensure_column(conn, "recording", "transcription_attempted_at", "TEXT DEFAULT NULL")
            self._ensure_column(conn, "recording", "transcription_segment_count", "INTEGER DEFAULT NULL")
            self._ensure_column(conn, "recording", "transcription_language", "TEXT DEFAULT NULL")
            self._ensure_column(conn, "recording", "transcription_language_probability", "REAL DEFAULT NULL")
            self._ensure_column(conn, "recording", "transcription_vad_removed_duration", "REAL DEFAULT NULL")
            self._ensure_column(conn, "recording", "transcription_skipped", "INTEGER NOT NULL DEFAULT 0")
            conn.commit()
        finally:
            conn.close()

    def _ensure_collection_tables(self) -> None:
        """Migration: add collection tables for existing local databases."""
        conn = self._connect()
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS collection
                (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    name        TEXT    NOT NULL UNIQUE,
                    description TEXT    DEFAULT NULL,
                    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS recording_collection
                (
                    recording_id  INTEGER NOT NULL,
                    collection_id INTEGER NOT NULL,
                    created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
                    PRIMARY KEY (recording_id, collection_id),
                    FOREIGN KEY (recording_id) REFERENCES recording (id) ON DELETE CASCADE,
                    FOREIGN KEY (collection_id) REFERENCES collection (id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_recording_collection_recording
                    ON recording_collection (recording_id);
                CREATE INDEX IF NOT EXISTS idx_recording_collection_collection
                    ON recording_collection (collection_id);
            """)
            conn.commit()
        finally:
            conn.close()

    def _ensure_saved_view_tables(self) -> None:
        """Migration: add saved view tables for existing local databases."""
        conn = self._connect()
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS saved_view
                (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    name          TEXT    NOT NULL UNIQUE,
                    search_query  TEXT    NOT NULL DEFAULT '',
                    collection_id INTEGER DEFAULT NULL,
                    date_filter   TEXT    NOT NULL DEFAULT '',
                    folder        TEXT    DEFAULT NULL,
                    created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
                    FOREIGN KEY (collection_id) REFERENCES collection (id) ON DELETE SET NULL
                );

                CREATE INDEX IF NOT EXISTS idx_saved_view_collection
                    ON saved_view (collection_id);
            """)
            conn.commit()
        finally:
            conn.close()

    def _ensure_embedding_tables(self) -> None:
        """Migration: add recording embedding table for existing local databases."""
        conn = self._connect()
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS recording_embedding
                (
                    recording_id  INTEGER PRIMARY KEY,
                    status        TEXT    NOT NULL DEFAULT 'not indexed',
                    model         TEXT    DEFAULT NULL,
                    content_hash  TEXT    DEFAULT NULL,
                    embedding     TEXT    DEFAULT NULL,
                    error         TEXT    DEFAULT NULL,
                    indexed_at    TEXT    DEFAULT NULL,
                    created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
                    updated_at    TEXT    NOT NULL DEFAULT (datetime('now')),
                    FOREIGN KEY (recording_id) REFERENCES recording (id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_recording_embedding_status
                    ON recording_embedding (status);
            """)
            conn.commit()
        finally:
            conn.close()

    def _ensure_action_center_tables(self) -> None:
        """Migration: add action center tables for existing local databases."""
        conn = self._connect()
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS action_center_item
                (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    recording_id    INTEGER NOT NULL,
                    recording_name  TEXT    NOT NULL,
                    recording_title TEXT    DEFAULT NULL,
                    item_type       TEXT    NOT NULL,
                    text            TEXT    NOT NULL,
                    owner           TEXT    DEFAULT NULL,
                    due_date        TEXT    DEFAULT NULL,
                    topics          TEXT    DEFAULT NULL,
                    confidence      TEXT    DEFAULT NULL,
                    status          TEXT    NOT NULL DEFAULT 'open',
                    source_excerpt  TEXT    DEFAULT NULL,
                    source_hash     TEXT    DEFAULT NULL,
                    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
                    updated_at      TEXT    NOT NULL DEFAULT (datetime('now')),
                    FOREIGN KEY (recording_id) REFERENCES recording (id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_action_center_item_recording
                    ON action_center_item (recording_id);
                CREATE INDEX IF NOT EXISTS idx_action_center_item_type
                    ON action_center_item (item_type);
                CREATE INDEX IF NOT EXISTS idx_action_center_item_owner
                    ON action_center_item (owner);
                CREATE INDEX IF NOT EXISTS idx_action_center_item_status
                    ON action_center_item (status);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_action_center_item_unique_source
                    ON action_center_item (recording_id, item_type, text, source_hash);
            """)
            conn.commit()
        finally:
            conn.close()

    def _ensure_processing_queue_tables(self) -> None:
        """Migration: add processing queue tables for existing local databases."""
        conn = self._connect()
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS processing_queue
                (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_type        TEXT    NOT NULL,
                    recording_id    INTEGER NOT NULL,
                    recording_name  TEXT    NOT NULL,
                    recording_title TEXT    DEFAULT NULL,
                    status          TEXT    NOT NULL DEFAULT 'pending',
                    engine          TEXT    DEFAULT NULL,
                    summary_provider TEXT   DEFAULT NULL,
                    summary_model   TEXT    DEFAULT NULL,
                    prompt_id       TEXT    DEFAULT NULL,
                    error           TEXT    DEFAULT NULL,
                    error_history   TEXT    DEFAULT NULL,
                    attempts        INTEGER NOT NULL DEFAULT 0,
                    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
                    updated_at      TEXT    NOT NULL DEFAULT (datetime('now')),
                    started_at      TEXT    DEFAULT NULL,
                    completed_at    TEXT    DEFAULT NULL,
                    FOREIGN KEY (recording_id) REFERENCES recording (id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_processing_queue_status
                    ON processing_queue (status);
                CREATE INDEX IF NOT EXISTS idx_processing_queue_type_status
                    ON processing_queue (job_type, status);
                CREATE INDEX IF NOT EXISTS idx_processing_queue_recording
                    ON processing_queue (recording_id);
            """)
            self._ensure_column(conn, "processing_queue", "summary_provider", "TEXT DEFAULT NULL")
            self._ensure_column(conn, "processing_queue", "summary_model", "TEXT DEFAULT NULL")
            self._ensure_column(conn, "processing_queue", "error_history", "TEXT DEFAULT NULL")
            self._migrate_processing_queue_summary_models(conn)
            conn.commit()
        finally:
            conn.close()

    def _ensure_app_state_table(self) -> None:
        """Migration: add small key/value state table for durable local workflow flags."""
        conn = self._connect()
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS app_state
                (
                    key        TEXT PRIMARY KEY,
                    value      TEXT    NOT NULL,
                    updated_at TEXT    NOT NULL DEFAULT (datetime('now'))
                );
            """)
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        columns = [row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        if column not in columns:
            try:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
            except sqlite3.OperationalError as exc:
                if "duplicate column name" not in str(exc).lower():
                    raise

    @staticmethod
    def _migrate_processing_queue_summary_models(conn: sqlite3.Connection) -> None:
        """Normalize old local summary jobs that used short Ollama model names."""
        migrations = {
            "qwen3": "qwen3:8b",
            "llama3.1": "llama3.1:8b",
        }
        for old_model, new_model in migrations.items():
            conn.execute(
                """
                UPDATE processing_queue
                SET summary_model = ?,
                    updated_at = datetime('now')
                WHERE job_type = 'summarize'
                  AND status IN ('pending', 'running', 'failed')
                  AND COALESCE(summary_provider, '') IN ('local', 'local_ai', 'ollama')
                  AND summary_model = ?
                """,
                (new_model, old_model),
            )

    @staticmethod
    def _estimate_transcript_segment_count(transcript: str | None) -> int | None:
        if not transcript or not transcript.strip():
            return 0 if transcript is not None else None
        lines = [line for line in transcript.splitlines() if line.strip()]
        return len(lines) if lines else 1

    @staticmethod
    def _initial_transcription_status(recording: DBRecording) -> str:
        if recording.transcript and recording.transcript.strip():
            if recording.duration and recording.duration <= VERY_SHORT_DURATION_SECONDS:
                return "very_short"
            return "transcribed"
        if recording.duration and recording.duration <= VERY_SHORT_DURATION_SECONDS:
            return "very_short"
        return "pending"

    @staticmethod
    def classify_transcription_error(error: str | None) -> str:
        text = (error or "").lower()
        corrupt_markers = (
            "invalid data found when processing input",
            "ffmpeg",
            "decode",
            "unsupported",
            "corrupt",
            "damaged",
            "averror",
            "could not open input",
        )
        if any(marker in text for marker in corrupt_markers):
            return "corrupt_audio"
        if "no speech" in text or "0 segment" in text or "zero segment" in text:
            return "no_speech_detected"
        retryable_markers = (
            "timeout",
            "timed out",
            "temporarily",
            "temporary",
            "interrupted",
            "unavailable",
            "resource exhausted",
            "rate limit",
            "connection",
        )
        if any(marker in text for marker in retryable_markers):
            return "retryable_failure"
        return "retryable_failure"

    @staticmethod
    def transcription_status_message(status: str | None) -> str:
        messages = {
            "corrupt_audio": "This file could not be decoded. It may be damaged or unsupported.",
            "no_speech_detected": "Whisper completed but detected no speech segments.",
            "retryable_failure": "This appears retryable. You can run Retry Failed Only.",
            "pending": "No transcript found. This recording has not been transcribed yet.",
            "very_short": "This recording is very short or has only a few transcript segments.",
            "unknown": "The transcription state is unknown.",
        }
        return messages.get(status or "unknown", messages["unknown"])

    def get_recordings(self) -> list[DBRecording]:
        conn = self._connect()
        try:
            result = conn.execute(f"SELECT {RECORDING_SELECT_COLUMNS} FROM recording")
            db_files = result.fetchall()
            recordings = [DBRecording.from_dict(row) for row in db_files]
            for rec in recordings:
                self._hydrate_latest_summary_fields(conn, rec)
            return recordings
        finally:
            conn.close()

    def get_recording_by_name(self, name: str) -> DBRecording | None:
        conn = self._connect()
        try:
            result = conn.execute(
                f"SELECT {RECORDING_SELECT_COLUMNS} FROM recording WHERE name = ?",
                (name,),
            )
            row = result.fetchone()
            if row:
                rec = DBRecording.from_dict(row)
                self._hydrate_latest_summary_fields(conn, rec)
                return rec
            return None
        finally:
            conn.close()

    @staticmethod
    def _hydrate_latest_summary_fields(conn: sqlite3.Connection, rec: DBRecording) -> None:
        latest = conn.execute(
            """
            SELECT summary, title, tags, notion_url
            FROM summary
            WHERE recording_id = ?
            ORDER BY version DESC
            LIMIT 1
            """,
            (rec.id,),
        ).fetchone()
        if latest:
            rec.summary = latest["summary"]
            rec.title = latest["title"]
            rec.tags = latest["tags"]
            rec.notion_url = latest["notion_url"]

    def insert_recording(self, db_recording: DBRecording) -> int:
        conn = self._connect()
        try:
            status = self._initial_transcription_status(db_recording)
            result = conn.execute(
                """
                INSERT INTO recording (
                    id, name, label, duration, file_extension, created_at, transcript, folder,
                    transcription_status, transcription_segment_count
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    db_recording.id,
                    db_recording.name,
                    db_recording.label,
                    db_recording.duration,
                    db_recording.file_extension,
                    db_recording.created_at,
                    db_recording.transcript,
                    db_recording.folder,
                    status,
                    self._estimate_transcript_segment_count(db_recording.transcript),
                ),
            )
            conn.commit()
            return result.lastrowid
        finally:
            conn.close()

    def save_transcript(self, name: str, transcript: str) -> None:
        conn = self._connect()
        try:
            segment_count = self._estimate_transcript_segment_count(transcript)
            recording = conn.execute("SELECT duration FROM recording WHERE name = ?", (name,)).fetchone()
            duration = int(recording["duration"] or 0) if recording else 0
            status = "transcribed"
            if not transcript or not transcript.strip():
                status = "no_speech_detected"
            elif duration and duration <= VERY_SHORT_DURATION_SECONDS:
                status = "very_short"
            conn.execute(
                """
                UPDATE recording
                SET transcript = ?,
                    transcription_status = ?,
                    transcription_error = NULL,
                    transcription_attempted_at = COALESCE(transcription_attempted_at, datetime('now')),
                    transcription_segment_count = ?,
                    transcription_skipped = 0
                WHERE name = ?
                """,
                (transcript, status, segment_count, name),
            )
            conn.commit()
        finally:
            conn.close()

    def update_recording(self, name: str, recorded_at: str | None = None, duration: int | None = None) -> bool:
        """Update recording fields (recorded_at, duration)."""
        conn = self._connect()
        try:
            existing = conn.execute("SELECT id FROM recording WHERE name = ?", (name,)).fetchone()
            if not existing:
                return False
            updates = []
            params = []
            if recorded_at is not None:
                updates.append("recorded_at = ?")
                params.append(recorded_at)
            if duration is not None:
                updates.append("duration = ?")
                params.append(duration)
            if not updates:
                return False
            params.append(name)
            conn.execute(f"UPDATE recording SET {', '.join(updates)} WHERE name = ?", params)
            conn.commit()
            return True
        finally:
            conn.close()

    def update_transcript(self, name: str, transcript: str) -> bool:
        conn = self._connect()
        try:
            segment_count = self._estimate_transcript_segment_count(transcript)
            recording = conn.execute("SELECT duration FROM recording WHERE name = ?", (name,)).fetchone()
            duration = int(recording["duration"] or 0) if recording else 0
            status = "transcribed"
            if not transcript or not transcript.strip():
                status = "no_speech_detected"
            elif duration and duration <= VERY_SHORT_DURATION_SECONDS:
                status = "very_short"
            result = conn.execute(
                """
                UPDATE recording
                SET transcript = ?,
                    transcription_status = ?,
                    transcription_error = NULL,
                    transcription_segment_count = ?,
                    transcription_skipped = 0
                WHERE name = ?
                """,
                (transcript, status, segment_count, name),
            )
            conn.commit()
            return result.rowcount > 0
        finally:
            conn.close()

    def get_transcript(self, name: str) -> str | None:
        conn = self._connect()
        try:
            result = conn.execute("SELECT transcript FROM recording WHERE name = ?", (name,))
            row = result.fetchone()
            if row:
                return row["transcript"]
            return None
        finally:
            conn.close()

    def update_transcription_metadata(
        self,
        name: str,
        status: str,
        error: str | None = None,
        segment_count: int | None = None,
        language: str | None = None,
        language_probability: float | None = None,
        vad_removed_duration: float | None = None,
        attempted: bool = True,
        skipped: bool | None = None,
    ) -> bool:
        if status not in TRANSCRIPTION_STATUSES:
            status = "unknown"
        conn = self._connect()
        try:
            assignments = [
                "transcription_status = ?",
                "transcription_error = ?",
                "transcription_segment_count = ?",
                "transcription_language = ?",
                "transcription_language_probability = ?",
                "transcription_vad_removed_duration = ?",
            ]
            params = [status, error, segment_count, language, language_probability, vad_removed_duration]
            if attempted:
                assignments.append("transcription_attempted_at = datetime('now')")
            if skipped is not None:
                assignments.append("transcription_skipped = ?")
                params.append(1 if skipped else 0)
            params.append(name)
            result = conn.execute(
                f"UPDATE recording SET {', '.join(assignments)} WHERE name = ?",
                params,
            )
            conn.commit()
            return result.rowcount > 0
        finally:
            conn.close()

    def mark_no_speech_as_skipped(self) -> dict:
        conn = self._connect()
        try:
            result = conn.execute("""
                UPDATE recording
                SET transcription_skipped = 1
                WHERE transcription_status = 'no_speech_detected'
                """)
            conn.commit()
            return {"ok": True, "count": result.rowcount}
        finally:
            conn.close()

    def backfill_transcription_statuses(self) -> dict:
        """Classify existing rows from transcript text, duration, and failed queue errors only."""
        conn = self._connect()
        counts = {
            "transcribed": 0,
            "very_short": 0,
            "pending": 0,
            "retryable_failure": 0,
            "corrupt_audio": 0,
            "no_speech_detected": 0,
            "unknown": 0,
        }
        try:
            rows = conn.execute("""
                SELECT id, name, duration, transcript, transcription_status
                FROM recording
                """).fetchall()
            for row in rows:
                existing = row["transcription_status"] or "pending"
                if existing in ("corrupt_audio", "retryable_failure", "no_speech_detected") and not row["transcript"]:
                    counts[existing] += 1
                    continue

                error_row = conn.execute(
                    """
                    SELECT error, completed_at, updated_at
                    FROM processing_queue
                    WHERE recording_id = ?
                      AND job_type = 'transcribe'
                      AND status = 'failed'
                      AND error IS NOT NULL
                    ORDER BY COALESCE(completed_at, updated_at, created_at) DESC, id DESC
                    LIMIT 1
                    """,
                    (row["id"],),
                ).fetchone()
                transcript = row["transcript"]
                segment_count = self._estimate_transcript_segment_count(transcript)
                if transcript and transcript.strip():
                    status = "transcribed"
                    if row["duration"] and int(row["duration"]) <= VERY_SHORT_DURATION_SECONDS:
                        status = "very_short"
                    error = None
                    attempted_at = None
                elif error_row:
                    error = error_row["error"]
                    status = self.classify_transcription_error(error)
                    attempted_at = error_row["completed_at"] or error_row["updated_at"]
                elif row["duration"] and int(row["duration"]) <= VERY_SHORT_DURATION_SECONDS:
                    status = "very_short"
                    error = None
                    attempted_at = None
                else:
                    status = "pending"
                    error = None
                    attempted_at = None

                counts[status] = counts.get(status, 0) + 1
                conn.execute(
                    """
                    UPDATE recording
                    SET transcription_status = ?,
                        transcription_error = ?,
                        transcription_segment_count = ?,
                        transcription_attempted_at = COALESCE(transcription_attempted_at, ?)
                    WHERE id = ?
                    """,
                    (status, error, segment_count, attempted_at, row["id"]),
                )
            conn.commit()
            return {"ok": True, "counts": counts}
        finally:
            conn.close()

    def get_transcription_failure_report(self) -> list[dict]:
        conn = self._connect()
        try:
            rows = conn.execute("""
                SELECT
                    r.name,
                    r.label,
                    r.duration,
                    r.recorded_at,
                    r.created_at,
                    r.file_extension,
                    r.transcription_status,
                    r.transcription_error,
                    r.transcription_segment_count,
                    r.transcription_language,
                    r.transcription_language_probability,
                    r.transcription_skipped
                FROM recording r
                WHERE r.transcription_status IN (
                    'pending',
                    'retryable_failure',
                    'corrupt_audio',
                    'no_speech_detected',
                    'very_short',
                    'unknown'
                )
                ORDER BY COALESCE(r.recorded_at, r.created_at) DESC, r.name
                """).fetchall()
            return [self._transcription_report_row(row) for row in rows]
        finally:
            conn.close()

    @classmethod
    def _transcription_report_row(cls, row: sqlite3.Row) -> dict:
        status = row["transcription_status"] or "unknown"
        recommendations = {
            "pending": "Retry never attempted",
            "retryable_failure": "Retry failed only",
            "corrupt_audio": "Review or replace source audio",
            "no_speech_detected": (
                "Mark no speech as skipped" if not row["transcription_skipped"] else "Already skipped"
            ),
            "very_short": "Review if valuable",
            "unknown": "Review manually",
        }
        return {
            "recording_name": row["name"],
            "title": row["label"],
            "date": row["recorded_at"] or row["created_at"],
            "file_path": f"local_recordings/{row['name']}.{row['file_extension']}",
            "transcription_status": status,
            "segment_count": row["transcription_segment_count"],
            "duration": row["duration"],
            "language": row["transcription_language"],
            "language_probability": row["transcription_language_probability"],
            "error_message": row["transcription_error"],
            "recommended_action": recommendations.get(status, "Review manually"),
        }

    @staticmethod
    def _next_summary_version(conn: sqlite3.Connection, recording_id: int) -> int:
        row = conn.execute(
            "SELECT COALESCE(MAX(version), 0) AS max_version FROM summary WHERE recording_id = ?", (recording_id,)
        ).fetchone()
        return int(row["max_version"]) + 1

    def save_summarization_result(
        self, name: str, summary: str, title: str, tags: str, prompt_id: str | None = None
    ) -> DBSummary:
        conn = self._connect()
        try:
            recording_row = conn.execute("SELECT id FROM recording WHERE name = ?", (name,)).fetchone()
            if not recording_row:
                raise ValueError(f"Recording '{name}' not found")

            recording_id = int(recording_row["id"])
            version = self._next_summary_version(conn, recording_id)

            result = conn.execute(
                """
                INSERT INTO summary (recording_id, version, title, tags, summary, prompt_id)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (recording_id, version, title, tags, summary, prompt_id),
            )

            if title and title.strip():
                conn.execute("UPDATE recording SET label = ? WHERE id = ?", (title.strip(), recording_id))

            conn.commit()
            return DBSummary(
                id=result.lastrowid,
                recording_id=recording_id,
                recording_name=name,
                version=version,
                summary=summary,
                title=title,
                tags=tags,
                prompt_id=prompt_id,
            )
        finally:
            conn.close()

    def get_summaries(self, name: str) -> list[DBSummary]:
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT
                    s.id,
                    s.recording_id,
                    r.name AS recording_name,
                    s.version,
                    s.title,
                    s.tags,
                    s.summary,
                    s.prompt_id,
                    s.notion_url,
                    s.created_at
                FROM summary s
                JOIN recording r ON r.id = s.recording_id
                WHERE r.name = ?
                ORDER BY s.version DESC
                """,
                (name,),
            ).fetchall()
            return [DBSummary.from_dict(row) for row in rows]
        finally:
            conn.close()

    def get_summary(self, name: str) -> str | None:
        summaries = self.get_summaries(name)
        return summaries[0].summary if summaries else None

    def save_summary(self, name: str, summary: str) -> None:
        self.save_summarization_result(name=name, summary=summary, title="", tags="", prompt_id=None)

    def get_summary_by_id(self, summary_id: int) -> DBSummary | None:
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT
                    s.id,
                    s.recording_id,
                    r.name AS recording_name,
                    s.version,
                    s.title,
                    s.tags,
                    s.summary,
                    s.prompt_id,
                    s.notion_url,
                    s.created_at
                FROM summary s
                JOIN recording r ON r.id = s.recording_id
                WHERE s.id = ?
                """,
                (summary_id,),
            ).fetchone()
            return DBSummary.from_dict(row) if row else None
        finally:
            conn.close()

    def update_summary_metadata(self, summary_id: int, title: str, tags: str) -> DBSummary | None:
        conn = self._connect()
        try:
            row = conn.execute("SELECT id, recording_id FROM summary WHERE id = ?", (summary_id,)).fetchone()
            if not row:
                return None

            conn.execute("UPDATE summary SET title = ?, tags = ? WHERE id = ?", (title, tags, summary_id))

            # Keep recording.label aligned to the latest summary title.
            latest = conn.execute(
                "SELECT id, title FROM summary WHERE recording_id = ? ORDER BY version DESC LIMIT 1",
                (row["recording_id"],),
            ).fetchone()
            if latest and int(latest["id"]) == summary_id and title.strip():
                conn.execute("UPDATE recording SET label = ? WHERE id = ?", (title.strip(), row["recording_id"]))

            conn.commit()
            return self.get_summary_by_id(summary_id)
        finally:
            conn.close()

    def update_summary_content(self, summary_id: int, summary: str) -> DBSummary | None:
        conn = self._connect()
        try:
            row = conn.execute("SELECT id FROM summary WHERE id = ?", (summary_id,)).fetchone()
            if not row:
                return None

            conn.execute("UPDATE summary SET summary = ? WHERE id = ?", (summary, summary_id))
            conn.commit()
            return self.get_summary_by_id(summary_id)
        finally:
            conn.close()

    def update_title_and_tags(self, name: str, title: str, tags: str) -> None:
        summaries = self.get_summaries(name)
        if not summaries:
            self.save_summarization_result(name=name, summary="", title=title, tags=tags, prompt_id=None)
            return
        self.update_summary_metadata(summaries[0].id, title, tags)

    def get_latest_summaries_map(self) -> dict[str, DBSummary]:
        conn = self._connect()
        try:
            rows = conn.execute("""
                SELECT
                    s.id,
                    s.recording_id,
                    r.name AS recording_name,
                    s.version,
                    s.title,
                    s.tags,
                    s.summary,
                    s.prompt_id,
                    s.notion_url,
                    s.created_at
                FROM summary s
                JOIN recording r ON r.id = s.recording_id
                JOIN (
                    SELECT recording_id, MAX(version) AS max_version
                    FROM summary
                    GROUP BY recording_id
                ) m ON m.recording_id = s.recording_id AND m.max_version = s.version
                """).fetchall()
            return {row["recording_name"]: DBSummary.from_dict(row) for row in rows}
        finally:
            conn.close()

    def delete_recording(self, name: str) -> bool:
        conn = self._connect()
        try:
            result = conn.execute("DELETE FROM recording WHERE name = ?", (name,))
            conn.commit()
            return result.rowcount > 0
        finally:
            conn.close()

    # ─── Collection operations ───────────────────────────────────

    def create_collection(self, name: str, description: str | None = None) -> dict:
        conn = self._connect()
        try:
            clean_name = name.strip()
            clean_description = description.strip() if description and description.strip() else None
            existing = conn.execute(
                "SELECT id, name, description, created_at FROM collection WHERE lower(name) = lower(?)",
                (clean_name,),
            ).fetchone()
            if existing:
                return {
                    "id": existing["id"],
                    "name": existing["name"],
                    "description": existing["description"],
                    "created_at": existing["created_at"],
                    "count": self._collection_count(conn, int(existing["id"])),
                    "created": False,
                }

            result = conn.execute(
                "INSERT INTO collection (name, description) VALUES (?, ?)",
                (clean_name, clean_description),
            )
            conn.commit()
            collection_id = int(result.lastrowid)
            return {
                "id": collection_id,
                "name": clean_name,
                "description": clean_description,
                "created_at": conn.execute(
                    "SELECT created_at FROM collection WHERE id = ?",
                    (collection_id,),
                ).fetchone()["created_at"],
                "count": 0,
                "created": True,
            }
        finally:
            conn.close()

    @staticmethod
    def _collection_count(conn: sqlite3.Connection, collection_id: int) -> int:
        row = conn.execute(
            "SELECT COUNT(*) AS count FROM recording_collection WHERE collection_id = ?",
            (collection_id,),
        ).fetchone()
        return int(row["count"]) if row else 0

    def get_collections_with_counts(self) -> list[dict]:
        conn = self._connect()
        try:
            rows = conn.execute("""
                SELECT
                    c.id,
                    c.name,
                    c.description,
                    c.created_at,
                    COUNT(rc.recording_id) AS count
                FROM collection c
                LEFT JOIN recording_collection rc ON rc.collection_id = c.id
                GROUP BY c.id, c.name, c.description, c.created_at
                ORDER BY lower(c.name)
            """).fetchall()
            return [
                {
                    "id": row["id"],
                    "name": row["name"],
                    "description": row["description"],
                    "created_at": row["created_at"],
                    "count": row["count"],
                }
                for row in rows
            ]
        finally:
            conn.close()

    def get_recording_collections_map(self) -> dict[str, list[dict]]:
        conn = self._connect()
        try:
            rows = conn.execute("""
                SELECT r.name AS recording_name, c.id, c.name, c.description
                FROM recording_collection rc
                JOIN recording r ON r.id = rc.recording_id
                JOIN collection c ON c.id = rc.collection_id
                ORDER BY lower(c.name)
            """).fetchall()
            mapping: dict[str, list[dict]] = {}
            for row in rows:
                mapping.setdefault(row["recording_name"], []).append(
                    {
                        "id": row["id"],
                        "name": row["name"],
                        "description": row["description"],
                    }
                )
            return mapping
        finally:
            conn.close()

    def get_recording_collections(self, name: str) -> list[dict]:
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT c.id, c.name, c.description, c.created_at
                FROM recording_collection rc
                JOIN recording r ON r.id = rc.recording_id
                JOIN collection c ON c.id = rc.collection_id
                WHERE r.name = ?
                ORDER BY lower(c.name)
            """,
                (name,),
            ).fetchall()
            return [
                {
                    "id": row["id"],
                    "name": row["name"],
                    "description": row["description"],
                    "created_at": row["created_at"],
                }
                for row in rows
            ]
        finally:
            conn.close()

    def set_recording_collections(self, name: str, collection_ids: list[int]) -> bool:
        conn = self._connect()
        try:
            recording = conn.execute("SELECT id FROM recording WHERE name = ?", (name,)).fetchone()
            if not recording:
                return False
            recording_id = int(recording["id"])
            clean_ids = sorted({int(collection_id) for collection_id in collection_ids})
            if clean_ids:
                placeholders = ",".join(["?"] * len(clean_ids))
                valid_rows = conn.execute(
                    f"SELECT id FROM collection WHERE id IN ({placeholders})",
                    clean_ids,
                ).fetchall()
                valid_ids = {int(row["id"]) for row in valid_rows}
            else:
                valid_ids = set()

            conn.execute("DELETE FROM recording_collection WHERE recording_id = ?", (recording_id,))
            for collection_id in sorted(valid_ids):
                conn.execute(
                    """
                    INSERT OR IGNORE INTO recording_collection (recording_id, collection_id)
                    VALUES (?, ?)
                    """,
                    (recording_id, collection_id),
                )
            conn.commit()
            return True
        finally:
            conn.close()

    def add_recording_to_collection(self, name: str, collection_id: int) -> bool:
        conn = self._connect()
        try:
            recording = conn.execute("SELECT id FROM recording WHERE name = ?", (name,)).fetchone()
            collection = conn.execute("SELECT id FROM collection WHERE id = ?", (collection_id,)).fetchone()
            if not recording or not collection:
                return False
            conn.execute(
                """
                INSERT OR IGNORE INTO recording_collection (recording_id, collection_id)
                VALUES (?, ?)
                """,
                (recording["id"], collection["id"]),
            )
            conn.commit()
            return True
        finally:
            conn.close()

    def remove_recording_from_collection(self, name: str, collection_id: int) -> bool:
        conn = self._connect()
        try:
            recording = conn.execute("SELECT id FROM recording WHERE name = ?", (name,)).fetchone()
            if not recording:
                return False
            result = conn.execute(
                "DELETE FROM recording_collection WHERE recording_id = ? AND collection_id = ?",
                (recording["id"], collection_id),
            )
            conn.commit()
            return result.rowcount > 0
        finally:
            conn.close()

    # ─── Saved view operations ───────────────────────────────────

    @staticmethod
    def _saved_view_from_row(row: sqlite3.Row) -> dict:
        return {
            "id": row["id"],
            "name": row["name"],
            "search_query": row["search_query"] or "",
            "collection_id": row["collection_id"],
            "collection_name": row["collection_name"] if "collection_name" in row.keys() else None,
            "date_filter": row["date_filter"] or "",
            "folder": row["folder"],
            "created_at": row["created_at"],
        }

    def get_saved_views(self) -> list[dict]:
        conn = self._connect()
        try:
            rows = conn.execute("""
                SELECT
                    sv.id,
                    sv.name,
                    sv.search_query,
                    sv.collection_id,
                    c.name AS collection_name,
                    sv.date_filter,
                    sv.folder,
                    sv.created_at
                FROM saved_view sv
                LEFT JOIN collection c ON c.id = sv.collection_id
                ORDER BY lower(sv.name)
            """).fetchall()
            return [self._saved_view_from_row(row) for row in rows]
        finally:
            conn.close()

    def create_saved_view(
        self,
        name: str,
        search_query: str = "",
        collection_id: int | None = None,
        date_filter: str = "",
        folder: str | None = None,
    ) -> dict:
        conn = self._connect()
        try:
            clean_name = name.strip()
            existing = conn.execute(
                "SELECT id FROM saved_view WHERE lower(name) = lower(?)",
                (clean_name,),
            ).fetchone()
            if existing:
                raise ValueError(f"Saved view '{clean_name}' already exists")

            if collection_id is not None:
                collection = conn.execute("SELECT id FROM collection WHERE id = ?", (collection_id,)).fetchone()
                if not collection:
                    collection_id = None

            result = conn.execute(
                """
                INSERT INTO saved_view (name, search_query, collection_id, date_filter, folder)
                VALUES (?, ?, ?, ?, ?)
                """,
                (clean_name, search_query.strip(), collection_id, date_filter.strip(), folder),
            )
            conn.commit()
            saved_view_id = int(result.lastrowid)
            return self.get_saved_view_by_id(saved_view_id)
        finally:
            conn.close()

    def get_saved_view_by_id(self, saved_view_id: int) -> dict | None:
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT
                    sv.id,
                    sv.name,
                    sv.search_query,
                    sv.collection_id,
                    c.name AS collection_name,
                    sv.date_filter,
                    sv.folder,
                    sv.created_at
                FROM saved_view sv
                LEFT JOIN collection c ON c.id = sv.collection_id
                WHERE sv.id = ?
                """,
                (saved_view_id,),
            ).fetchone()
            return self._saved_view_from_row(row) if row else None
        finally:
            conn.close()

    def delete_saved_view(self, saved_view_id: int) -> bool:
        conn = self._connect()
        try:
            result = conn.execute("DELETE FROM saved_view WHERE id = ?", (saved_view_id,))
            conn.commit()
            return result.rowcount > 0
        finally:
            conn.close()

    # ─── Recording embedding operations ──────────────────────────

    def get_recording_embedding_status_map(self) -> dict[str, dict]:
        conn = self._connect()
        try:
            rows = conn.execute("""
                SELECT
                    r.name,
                    re.status,
                    re.model,
                    re.error,
                    re.indexed_at,
                    re.updated_at
                FROM recording r
                LEFT JOIN recording_embedding re ON re.recording_id = r.id
            """).fetchall()
            return {
                row["name"]: {
                    "status": row["status"] or "not indexed",
                    "model": row["model"],
                    "error": row["error"],
                    "indexed_at": row["indexed_at"],
                    "updated_at": row["updated_at"],
                }
                for row in rows
            }
        finally:
            conn.close()

    def get_recording_embedding_source(self, name: str) -> dict | None:
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT
                    r.id,
                    r.name,
                    r.label,
                    r.transcript,
                    s.title,
                    s.tags,
                    s.summary,
                    re.status,
                    re.model,
                    re.content_hash
                FROM recording r
                LEFT JOIN recording_embedding re ON re.recording_id = r.id
                LEFT JOIN (
                    SELECT s1.*
                    FROM summary s1
                    JOIN (
                        SELECT recording_id, MAX(version) AS max_version
                        FROM summary
                        GROUP BY recording_id
                    ) latest
                        ON latest.recording_id = s1.recording_id
                        AND latest.max_version = s1.version
                ) s ON s.recording_id = r.id
                WHERE r.name = ?
                """,
                (name,),
            ).fetchone()
            if not row:
                return None
            return {
                "id": row["id"],
                "name": row["name"],
                "label": row["label"],
                "transcript": row["transcript"] or "",
                "title": row["title"] or "",
                "tags": row["tags"] or "",
                "summary": row["summary"] or "",
                "embedding_status": row["status"] or "not indexed",
                "embedding_model": row["model"],
                "content_hash": row["content_hash"],
            }
        finally:
            conn.close()

    def get_recording_names_by_collection(self, collection_id: int) -> list[str]:
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT r.name
                FROM recording_collection rc
                JOIN recording r ON r.id = rc.recording_id
                WHERE rc.collection_id = ?
                ORDER BY r.name
                """,
                (collection_id,),
            ).fetchall()
            return [row["name"] for row in rows]
        finally:
            conn.close()

    def get_unindexed_recording_names(self) -> list[str]:
        conn = self._connect()
        try:
            rows = conn.execute("""
                SELECT r.name
                FROM recording r
                LEFT JOIN recording_embedding re ON re.recording_id = r.id
                WHERE re.status IS NULL OR re.status != 'indexed'
                ORDER BY r.name
            """).fetchall()
            return [row["name"] for row in rows]
        finally:
            conn.close()

    def save_recording_embedding(
        self,
        name: str,
        status: str,
        model: str | None = None,
        content_hash: str | None = None,
        embedding: list[float] | None = None,
        error: str | None = None,
    ) -> bool:
        conn = self._connect()
        try:
            recording = conn.execute("SELECT id FROM recording WHERE name = ?", (name,)).fetchone()
            if not recording:
                return False
            embedding_json = json.dumps(embedding) if embedding is not None else None
            indexed_at_expr = "datetime('now')" if status == "indexed" else "NULL"
            conn.execute(
                f"""
                INSERT INTO recording_embedding
                    (recording_id, status, model, content_hash, embedding, error, indexed_at, updated_at)
                VALUES
                    (?, ?, ?, ?, ?, ?, {indexed_at_expr}, datetime('now'))
                ON CONFLICT(recording_id) DO UPDATE SET
                    status = excluded.status,
                    model = excluded.model,
                    content_hash = excluded.content_hash,
                    embedding = excluded.embedding,
                    error = excluded.error,
                    indexed_at = {indexed_at_expr},
                    updated_at = datetime('now')
                """,
                (recording["id"], status, model, content_hash, embedding_json, error),
            )
            conn.commit()
            return True
        finally:
            conn.close()

    def get_indexed_recording_embeddings(self) -> list[dict]:
        conn = self._connect()
        try:
            rows = conn.execute("""
                SELECT
                    r.name,
                    r.label,
                    r.transcript,
                    s.title,
                    s.tags,
                    s.summary,
                    re.model,
                    re.embedding,
                    re.indexed_at
                FROM recording_embedding re
                JOIN recording r ON r.id = re.recording_id
                LEFT JOIN (
                    SELECT s1.*
                    FROM summary s1
                    JOIN (
                        SELECT recording_id, MAX(version) AS max_version
                        FROM summary
                        GROUP BY recording_id
                    ) latest
                        ON latest.recording_id = s1.recording_id
                        AND latest.max_version = s1.version
                ) s ON s.recording_id = r.id
                WHERE re.status = 'indexed' AND re.embedding IS NOT NULL
            """).fetchall()
            indexed = []
            for row in rows:
                try:
                    embedding = json.loads(row["embedding"])
                except (TypeError, json.JSONDecodeError):
                    continue
                indexed.append(
                    {
                        "name": row["name"],
                        "label": row["label"],
                        "title": row["title"] or "",
                        "tags": row["tags"] or "",
                        "summary": row["summary"] or "",
                        "transcript": row["transcript"] or "",
                        "model": row["model"],
                        "embedding": embedding,
                        "indexed_at": row["indexed_at"],
                    }
                )
            return indexed
        finally:
            conn.close()

    def get_recording_qa_sources(
        self,
        names: list[str] | None = None,
        collection_id: int | None = None,
    ) -> list[dict]:
        conn = self._connect()
        try:
            joins = []
            where = []
            params = []
            if collection_id is not None:
                joins.append("JOIN recording_collection rc ON rc.recording_id = r.id")
                where.append("rc.collection_id = ?")
                params.append(collection_id)
            if names:
                placeholders = ",".join(["?"] * len(names))
                where.append(f"r.name IN ({placeholders})")
                params.extend(names)
            where_sql = f"WHERE {' AND '.join(where)}" if where else ""
            join_sql = "\n".join(joins)
            rows = conn.execute(
                f"""
                SELECT
                    r.name,
                    r.label,
                    r.transcript,
                    s.title,
                    s.tags,
                    s.summary,
                    re.status,
                    re.model,
                    re.embedding,
                    re.indexed_at
                FROM recording r
                {join_sql}
                LEFT JOIN recording_embedding re ON re.recording_id = r.id
                LEFT JOIN (
                    SELECT s1.*
                    FROM summary s1
                    JOIN (
                        SELECT recording_id, MAX(version) AS max_version
                        FROM summary
                        GROUP BY recording_id
                    ) latest
                        ON latest.recording_id = s1.recording_id
                        AND latest.max_version = s1.version
                ) s ON s.recording_id = r.id
                {where_sql}
                ORDER BY r.name
                """,
                params,
            ).fetchall()
            sources = []
            for row in rows:
                embedding = None
                if row["embedding"]:
                    try:
                        embedding = json.loads(row["embedding"])
                    except (TypeError, json.JSONDecodeError):
                        embedding = None
                sources.append(
                    {
                        "name": row["name"],
                        "label": row["label"],
                        "title": row["title"] or "",
                        "tags": row["tags"] or "",
                        "summary": row["summary"] or "",
                        "transcript": row["transcript"] or "",
                        "embedding_status": row["status"] or "not indexed",
                        "embedding_model": row["model"],
                        "embedding": embedding,
                        "indexed_at": row["indexed_at"],
                    }
                )
            return sources
        finally:
            conn.close()

    # ─── Action Center operations ────────────────────────────────

    @staticmethod
    def _action_center_item_from_row(row) -> DBActionCenterItem:
        return DBActionCenterItem.from_dict(row)

    def get_action_center_sources(
        self,
        names: list[str] | None = None,
        collection_id: int | None = None,
        summarized_only: bool = False,
        transcribed_only: bool = False,
    ) -> list[dict]:
        conn = self._connect()
        try:
            joins = []
            where = []
            params = []
            if collection_id is not None:
                joins.append("JOIN recording_collection rc ON rc.recording_id = r.id")
                where.append("rc.collection_id = ?")
                params.append(collection_id)
            if names:
                placeholders = ",".join(["?"] * len(names))
                where.append(f"r.name IN ({placeholders})")
                params.extend(names)
            if summarized_only:
                where.append("s.summary IS NOT NULL AND length(trim(s.summary)) > 0")
            if transcribed_only:
                where.append("r.transcript IS NOT NULL AND length(trim(r.transcript)) > 0")

            where_sql = f"WHERE {' AND '.join(where)}" if where else ""
            join_sql = "\n".join(joins)
            rows = conn.execute(
                f"""
                SELECT
                    r.id,
                    r.name,
                    r.label,
                    r.recorded_at,
                    r.created_at,
                    r.transcript,
                    s.title,
                    s.tags,
                    s.summary,
                    s.created_at AS summary_created_at
                FROM recording r
                {join_sql}
                LEFT JOIN (
                    SELECT s1.*
                    FROM summary s1
                    JOIN (
                        SELECT recording_id, MAX(version) AS max_version
                        FROM summary
                        GROUP BY recording_id
                    ) latest
                        ON latest.recording_id = s1.recording_id
                        AND latest.max_version = s1.version
                ) s ON s.recording_id = r.id
                {where_sql}
                ORDER BY COALESCE(r.recorded_at, r.created_at) DESC, r.name
                """,
                params,
            ).fetchall()
            return [
                {
                    "id": row["id"],
                    "name": row["name"],
                    "label": row["label"],
                    "recording_title": row["title"] or row["label"] or row["name"],
                    "recorded_at": row["recorded_at"],
                    "created_at": row["created_at"],
                    "summary": row["summary"] or "",
                    "summary_tags": row["tags"] or "",
                    "transcript": row["transcript"] or "",
                }
                for row in rows
            ]
        finally:
            conn.close()

    def has_action_center_items_for_recording(self, recording_id: int) -> bool:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT COUNT(*) AS count FROM action_center_item WHERE recording_id = ?",
                (recording_id,),
            ).fetchone()
            return bool(row and int(row["count"]) > 0)
        finally:
            conn.close()

    def delete_open_action_center_items_for_recording(self, recording_id: int) -> int:
        conn = self._connect()
        try:
            result = conn.execute(
                """
                DELETE FROM action_center_item
                WHERE recording_id = ?
                  AND status IN ('open', 'pending')
                """,
                (recording_id,),
            )
            conn.commit()
            return result.rowcount
        finally:
            conn.close()

    def save_action_center_items(self, items: list[DBActionCenterItem]) -> list[DBActionCenterItem]:
        conn = self._connect()
        saved = []
        try:
            for item in items:
                topics_json = json.dumps(item.topics or [])
                result = conn.execute(
                    """
                    INSERT INTO action_center_item
                        (
                            recording_id,
                            recording_name,
                            recording_title,
                            item_type,
                            text,
                            owner,
                            due_date,
                            topics,
                            confidence,
                            status,
                            source_excerpt,
                            source_hash,
                            updated_at
                        )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                    ON CONFLICT(recording_id, item_type, text, source_hash) DO UPDATE SET
                        recording_title = excluded.recording_title,
                        owner = COALESCE(action_center_item.owner, excluded.owner),
                        due_date = COALESCE(action_center_item.due_date, excluded.due_date),
                        topics = excluded.topics,
                        confidence = excluded.confidence,
                        source_excerpt = excluded.source_excerpt,
                        updated_at = datetime('now')
                    """,
                    (
                        item.recording_id,
                        item.recording_name,
                        item.recording_title,
                        item.item_type,
                        item.text,
                        item.owner,
                        item.due_date,
                        topics_json,
                        item.confidence,
                        item.status,
                        item.source_excerpt,
                        item.source_hash,
                    ),
                )
                item.id = result.lastrowid or item.id
                saved.append(item)
            conn.commit()
            return saved
        finally:
            conn.close()

    def list_action_center_items(
        self,
        item_type: str | None = None,
        owner: str | None = None,
        topic: str | None = None,
        recording_name: str | None = None,
        date_filter: str | None = None,
        include_dismissed: bool = False,
    ) -> list[DBActionCenterItem]:
        conn = self._connect()
        try:
            where = []
            params = []
            if item_type:
                where.append("item_type = ?")
                params.append(item_type)
            if owner:
                where.append("owner = ?")
                params.append(owner)
            if topic:
                where.append("topics LIKE ?")
                params.append(f"%{topic}%")
            if recording_name:
                where.append("recording_name = ?")
                params.append(recording_name)
            if date_filter:
                where.append("date(created_at) = ?")
                params.append(date_filter)
            if not include_dismissed:
                where.append("status != 'dismissed'")
            where_sql = f"WHERE {' AND '.join(where)}" if where else ""
            rows = conn.execute(
                f"""
                SELECT *
                FROM action_center_item
                {where_sql}
                ORDER BY
                    CASE item_type
                        WHEN 'action_item' THEN 1
                        WHEN 'risk' THEN 2
                        WHEN 'open_question' THEN 3
                        WHEN 'decision' THEN 4
                        ELSE 5
                    END,
                    created_at DESC,
                    id DESC
                """,
                params,
            ).fetchall()
            return [self._action_center_item_from_row(row) for row in rows]
        finally:
            conn.close()

    def update_action_center_item_status(self, item_id: int, status: str) -> DBActionCenterItem | None:
        conn = self._connect()
        try:
            existing = conn.execute("SELECT id FROM action_center_item WHERE id = ?", (item_id,)).fetchone()
            if not existing:
                return None
            conn.execute(
                "UPDATE action_center_item SET status = ?, updated_at = datetime('now') WHERE id = ?",
                (status, item_id),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM action_center_item WHERE id = ?", (item_id,)).fetchone()
            return self._action_center_item_from_row(row) if row else None
        finally:
            conn.close()

    def get_action_center_filter_options(self) -> dict:
        conn = self._connect()
        try:
            owners = [row["owner"] for row in conn.execute("""
                    SELECT DISTINCT owner
                    FROM action_center_item
                    WHERE owner IS NOT NULL AND trim(owner) != ''
                    ORDER BY owner
                    """).fetchall()]
            recordings = [{"name": row["recording_name"], "title": row["recording_title"]} for row in conn.execute("""
                    SELECT DISTINCT recording_name, recording_title
                    FROM action_center_item
                    ORDER BY recording_title, recording_name
                    """).fetchall()]
            topic_set = set()
            rows = conn.execute(
                "SELECT topics FROM action_center_item WHERE topics IS NOT NULL AND trim(topics) != ''"
            ).fetchall()
            for row in rows:
                try:
                    topic_set.update(json.loads(row["topics"]))
                except (TypeError, json.JSONDecodeError):
                    topic_set.update(part.strip() for part in row["topics"].split(",") if part.strip())
            return {
                "owners": owners,
                "topics": sorted(topic for topic in topic_set if topic),
                "recordings": recordings,
            }
        finally:
            conn.close()

    # ─── Folder operations ────────────────────────────────────────

    def get_recording_folders(self) -> list[str]:
        """Return all distinct folder paths used by recordings, sorted."""
        conn = self._connect()
        try:
            rows = conn.execute("SELECT DISTINCT folder FROM recording ORDER BY folder").fetchall()
            folders = [row["folder"] for row in rows]
            if "/" not in folders:
                folders.insert(0, "/")
            return folders
        finally:
            conn.close()

    def move_recording_to_folder(self, name: str, folder: str) -> bool:
        """Move a recording to a different folder."""
        conn = self._connect()
        try:
            result = conn.execute("UPDATE recording SET folder = ? WHERE name = ?", (folder, name))
            conn.commit()
            return result.rowcount > 0
        finally:
            conn.close()

    def rename_folder(self, old_path: str, new_path: str) -> int:
        """Rename a folder and all its sub-folders. Returns number of updated recordings."""
        conn = self._connect()
        try:
            # Exact match
            result1 = conn.execute(
                "UPDATE recording SET folder = ? WHERE folder = ?",
                (new_path, old_path),
            )
            count = result1.rowcount
            # Sub-folders: old_path + '/' prefix → new_path + '/' prefix
            if not old_path.endswith("/"):
                old_prefix = old_path + "/"
            else:
                old_prefix = old_path
            if not new_path.endswith("/"):
                new_prefix = new_path + "/"
            else:
                new_prefix = new_path
            rows = conn.execute(
                "SELECT id, folder FROM recording WHERE folder LIKE ?",
                (old_prefix + "%",),
            ).fetchall()
            for row in rows:
                updated_folder = new_prefix + row["folder"][len(old_prefix) :]
                conn.execute("UPDATE recording SET folder = ? WHERE id = ?", (updated_folder, row["id"]))
                count += 1
            conn.commit()
            return count
        finally:
            conn.close()

    def delete_folder(self, folder_path: str, move_to: str = "/") -> int:
        """Move all recordings from a folder (and sub-folders) to *move_to*. Returns count."""
        conn = self._connect()
        try:
            result1 = conn.execute(
                "UPDATE recording SET folder = ? WHERE folder = ?",
                (move_to, folder_path),
            )
            count = result1.rowcount
            prefix = folder_path if folder_path.endswith("/") else folder_path + "/"
            result2 = conn.execute(
                "UPDATE recording SET folder = ? WHERE folder LIKE ?",
                (move_to, prefix + "%"),
            )
            count += result2.rowcount
            conn.commit()
            return count
        finally:
            conn.close()

    def bulk_move_recordings_to_folder(self, names: list[str], folder: str) -> int:
        """Move multiple recordings to a folder. Returns number updated."""
        conn = self._connect()
        try:
            count = 0
            for name in names:
                result = conn.execute("UPDATE recording SET folder = ? WHERE name = ?", (folder, name))
                count += result.rowcount
            conn.commit()
            return count
        finally:
            conn.close()

    def save_notion_url(self, summary_id_or_name: int | str, url: str) -> None:
        conn = self._connect()
        try:
            if isinstance(summary_id_or_name, int):
                conn.execute("UPDATE summary SET notion_url = ? WHERE id = ?", (url, summary_id_or_name))
            else:
                row = conn.execute(
                    """
                    SELECT s.id
                    FROM summary s
                    JOIN recording r ON r.id = s.recording_id
                    WHERE r.name = ?
                    ORDER BY s.version DESC
                    LIMIT 1
                    """,
                    (summary_id_or_name,),
                ).fetchone()
                if row:
                    conn.execute("UPDATE summary SET notion_url = ? WHERE id = ?", (url, row["id"]))
                else:
                    recording = conn.execute(
                        "SELECT id FROM recording WHERE name = ?", (summary_id_or_name,)
                    ).fetchone()
                    if recording:
                        version = self._next_summary_version(conn, int(recording["id"]))
                        conn.execute(
                            """
                            INSERT INTO summary (recording_id, version, title, tags, summary, prompt_id, notion_url)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                            """,
                            (int(recording["id"]), version, "", "", "", None, url),
                        )
            conn.commit()
        finally:
            conn.close()

    # ─── Task CRUD ───────────────────────────────────────────────

    def insert_task(self, task: DBTask) -> DBTask:
        conn = self._connect()
        try:
            result = conn.execute(
                """
                INSERT INTO task (summary_id, parent_task_id, title, description, status)
                VALUES (?, ?, ?, ?, ?)
                """,
                (task.summary_id, task.parent_task_id, task.title, task.description, task.status),
            )
            conn.commit()
            task.id = result.lastrowid
            return task
        finally:
            conn.close()

    def insert_tasks(self, tasks: list[DBTask]) -> list[DBTask]:
        conn = self._connect()
        try:
            created = []
            for task in tasks:
                result = conn.execute(
                    """
                    INSERT INTO task (summary_id, parent_task_id, title, description, status)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (task.summary_id, task.parent_task_id, task.title, task.description, task.status),
                )
                task.id = result.lastrowid

                # Insert subtasks with the parent id set
                for sub in task.subtasks:
                    sub.parent_task_id = task.id
                    sub.summary_id = task.summary_id
                    sub_result = conn.execute(
                        """
                        INSERT INTO task (summary_id, parent_task_id, title, description, status)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (sub.summary_id, sub.parent_task_id, sub.title, sub.description, sub.status),
                    )
                    sub.id = sub_result.lastrowid

                created.append(task)
            conn.commit()
            return created
        finally:
            conn.close()

    def get_tasks_by_summary(self, summary_id: int) -> list[DBTask]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM task WHERE summary_id = ? ORDER BY created_at ASC, id ASC",
                (summary_id,),
            ).fetchall()

            task_map: dict[int, DBTask] = {}
            top_level: list[DBTask] = []

            for row in rows:
                task = DBTask.from_dict(row)
                task_map[task.id] = task

            for task in task_map.values():
                if task.parent_task_id and task.parent_task_id in task_map:
                    task_map[task.parent_task_id].subtasks.append(task)
                else:
                    top_level.append(task)

            return top_level
        finally:
            conn.close()

    def get_task_by_id(self, task_id: int) -> DBTask | None:
        conn = self._connect()
        try:
            row = conn.execute("SELECT * FROM task WHERE id = ?", (task_id,)).fetchone()
            return DBTask.from_dict(row) if row else None
        finally:
            conn.close()

    def update_task(
        self, task_id: int, title: str | None = None, description: str | None = None, status: str | None = None
    ) -> DBTask | None:
        conn = self._connect()
        try:
            existing = conn.execute("SELECT * FROM task WHERE id = ?", (task_id,)).fetchone()
            if not existing:
                return None

            new_title = title if title is not None else existing["title"]
            new_description = description if description is not None else existing["description"]
            new_status = status if status is not None else existing["status"]

            conn.execute(
                "UPDATE task SET title = ?, description = ?, status = ? WHERE id = ?",
                (new_title, new_description, new_status, task_id),
            )
            conn.commit()
            return self.get_task_by_id(task_id)
        finally:
            conn.close()

    def delete_task(self, task_id: int) -> bool:
        conn = self._connect()
        try:
            result = conn.execute("DELETE FROM task WHERE id = ?", (task_id,))
            conn.commit()
            return result.rowcount > 0
        finally:
            conn.close()

    def delete_tasks_by_summary(self, summary_id: int) -> int:
        conn = self._connect()
        try:
            result = conn.execute("DELETE FROM task WHERE summary_id = ?", (summary_id,))
            conn.commit()
            return result.rowcount
        finally:
            conn.close()

    def has_tasks_for_summary(self, summary_id: int) -> bool:
        conn = self._connect()
        try:
            row = conn.execute("SELECT COUNT(*) as cnt FROM task WHERE summary_id = ?", (summary_id,)).fetchone()
            return row["cnt"] > 0
        finally:
            conn.close()

    # ─── Calendar CRUD ────────────────────────────────────────────

    def _ensure_calendar_tables(self) -> None:
        """Create calendar tables if they don't exist (migration-safe)."""
        conn = self._connect()
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS shared_calendar (
                    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
                    name                  TEXT    NOT NULL,
                    ical_url              TEXT    NOT NULL,
                    color                 TEXT    NOT NULL DEFAULT '#0d6efd',
                    is_enabled            INTEGER NOT NULL DEFAULT 1,
                    sync_interval_minutes INTEGER NOT NULL DEFAULT 30,
                    last_synced_at        TEXT    DEFAULT NULL,
                    last_error            TEXT    DEFAULT NULL,
                    created_at            TEXT    NOT NULL DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS calendar_event (
                    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                    provider           TEXT    NOT NULL DEFAULT 'local',
                    external_id        TEXT    DEFAULT NULL,
                    shared_calendar_id INTEGER DEFAULT NULL,
                    title              TEXT    NOT NULL,
                    description        TEXT    DEFAULT NULL,
                    start_at           TEXT    NOT NULL,
                    end_at             TEXT    NOT NULL,
                    is_all_day         INTEGER NOT NULL DEFAULT 0,
                    location           TEXT    DEFAULT NULL,
                    meeting_url        TEXT    DEFAULT NULL,
                    status             TEXT    NOT NULL DEFAULT 'confirmed',
                    created_at         TEXT    NOT NULL DEFAULT (datetime('now')),
                    UNIQUE (provider, external_id),
                    FOREIGN KEY (shared_calendar_id) REFERENCES shared_calendar (id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_calendar_event_start ON calendar_event (start_at);

                CREATE TABLE IF NOT EXISTS recording_event_link (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    recording_id INTEGER NOT NULL,
                    event_id     INTEGER NOT NULL,
                    link_source  TEXT    NOT NULL DEFAULT 'manual',
                    created_at   TEXT    NOT NULL DEFAULT (datetime('now')),
                    FOREIGN KEY (recording_id) REFERENCES recording (id) ON DELETE CASCADE,
                    FOREIGN KEY (event_id) REFERENCES calendar_event (id) ON DELETE CASCADE,
                    UNIQUE (recording_id, event_id)
                );
                CREATE INDEX IF NOT EXISTS idx_recording_event_link_recording ON recording_event_link (recording_id);
                CREATE INDEX IF NOT EXISTS idx_recording_event_link_event ON recording_event_link (event_id);

                CREATE TABLE IF NOT EXISTS daily_recap (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    date         TEXT    NOT NULL UNIQUE,
                    title        TEXT    DEFAULT NULL,
                    highlights   TEXT    DEFAULT NULL,
                    recap        TEXT    DEFAULT NULL,
                    action_items TEXT    DEFAULT NULL,
                    blockers     TEXT    DEFAULT NULL,
                    created_at   TEXT    NOT NULL DEFAULT (datetime('now')),
                    updated_at   TEXT    NOT NULL DEFAULT (datetime('now'))
                );
                CREATE INDEX IF NOT EXISTS idx_daily_recap_date ON daily_recap (date);
            """)
            # Migration: add shared_calendar_id column if missing on existing DB
            try:
                conn.execute("SELECT shared_calendar_id FROM calendar_event LIMIT 1")
            except Exception:
                conn.execute("ALTER TABLE calendar_event ADD COLUMN shared_calendar_id INTEGER DEFAULT NULL")
            # Migration: add status column if missing on existing DB
            try:
                conn.execute("SELECT status FROM calendar_event LIMIT 1")
            except Exception:
                conn.execute("ALTER TABLE calendar_event ADD COLUMN status TEXT NOT NULL DEFAULT 'confirmed'")
            conn.commit()
        finally:
            conn.close()

    def insert_calendar_event(self, event: DBCalendarEvent) -> DBCalendarEvent:
        self._ensure_calendar_tables()
        conn = self._connect()
        try:
            result = conn.execute(
                """
                INSERT INTO calendar_event (provider, external_id, title, description, start_at, end_at,
                                            is_all_day, location, meeting_url)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.provider,
                    event.external_id,
                    event.title,
                    event.description,
                    event.start_at,
                    event.end_at,
                    int(event.is_all_day),
                    event.location,
                    event.meeting_url,
                ),
            )
            conn.commit()
            event.id = result.lastrowid
            return event
        finally:
            conn.close()

    def update_calendar_event(
        self,
        event_id: int,
        title: str | None = None,
        description: str | None = None,
        start_at: str | None = None,
        end_at: str | None = None,
        is_all_day: bool | None = None,
        location: str | None = None,
        meeting_url: str | None = None,
    ) -> DBCalendarEvent | None:
        self._ensure_calendar_tables()
        conn = self._connect()
        try:
            existing = conn.execute("SELECT * FROM calendar_event WHERE id = ?", (event_id,)).fetchone()
            if not existing:
                return None
            new_title = title if title is not None else existing["title"]
            new_desc = description if description is not None else existing["description"]
            new_start = start_at if start_at is not None else existing["start_at"]
            new_end = end_at if end_at is not None else existing["end_at"]
            new_all_day = int(is_all_day) if is_all_day is not None else existing["is_all_day"]
            new_location = location if location is not None else existing["location"]
            new_meeting_url = meeting_url if meeting_url is not None else existing["meeting_url"]
            conn.execute(
                """
                UPDATE calendar_event SET title=?, description=?, start_at=?, end_at=?,
                       is_all_day=?, location=?, meeting_url=?
                WHERE id=?
                """,
                (new_title, new_desc, new_start, new_end, new_all_day, new_location, new_meeting_url, event_id),
            )
            conn.commit()
            return self.get_calendar_event_by_id(event_id)
        finally:
            conn.close()

    def delete_calendar_event(self, event_id: int) -> bool:
        self._ensure_calendar_tables()
        conn = self._connect()
        try:
            result = conn.execute("DELETE FROM calendar_event WHERE id = ?", (event_id,))
            conn.commit()
            return result.rowcount > 0
        finally:
            conn.close()

    def get_calendar_event_by_id(self, event_id: int) -> DBCalendarEvent | None:
        self._ensure_calendar_tables()
        conn = self._connect()
        try:
            row = conn.execute("SELECT * FROM calendar_event WHERE id = ?", (event_id,)).fetchone()
            if not row:
                return None
            event = DBCalendarEvent.from_dict(row)
            event.linked_recordings = self._get_linked_recordings(conn, event_id)
            return event
        finally:
            conn.close()

    def get_calendar_events_for_day(self, date_str: str) -> list[DBCalendarEvent]:
        """Get all events that overlap with the given day (YYYY-MM-DD)."""
        self._ensure_calendar_tables()
        conn = self._connect()
        try:
            day_start = f"{date_str} 00:00:00"
            day_end = f"{date_str} 23:59:59"
            rows = conn.execute(
                """
                SELECT ce.*, sc.color AS calendar_color
                FROM calendar_event ce
                LEFT JOIN shared_calendar sc ON sc.id = ce.shared_calendar_id
                WHERE ce.start_at <= ? AND ce.end_at >= ?
                ORDER BY ce.start_at ASC
                """,
                (day_end, day_start),
            ).fetchall()
            events = []
            for row in rows:
                event = DBCalendarEvent.from_dict(row)
                event.calendar_color = row["calendar_color"] if "calendar_color" in row.keys() else None
                event.linked_recordings = self._get_linked_recordings(conn, event.id)
                events.append(event)
            return events
        finally:
            conn.close()

    def get_calendar_events_for_month(self, year: int, month: int) -> list[DBCalendarEvent]:
        """Get all events in a given month."""
        self._ensure_calendar_tables()
        conn = self._connect()
        try:
            month_start = f"{year:04d}-{month:02d}-01 00:00:00"
            if month == 12:
                month_end = f"{year + 1:04d}-01-01 00:00:00"
            else:
                month_end = f"{year:04d}-{month + 1:02d}-01 00:00:00"
            rows = conn.execute(
                """
                SELECT ce.*, sc.color AS calendar_color
                FROM calendar_event ce
                LEFT JOIN shared_calendar sc ON sc.id = ce.shared_calendar_id
                WHERE ce.start_at < ? AND ce.end_at >= ?
                ORDER BY ce.start_at ASC
                """,
                (month_end, month_start),
            ).fetchall()
            events = []
            for row in rows:
                event = DBCalendarEvent.from_dict(row)
                event.calendar_color = row["calendar_color"] if "calendar_color" in row.keys() else None
                event.linked_recordings = self._get_linked_recordings(conn, event.id)
                events.append(event)
            return events
        finally:
            conn.close()

    def get_calendar_events_for_range(self, start_date: str, end_date: str) -> list[DBCalendarEvent]:
        """Get all events that overlap with the given date range (YYYY-MM-DD)."""
        self._ensure_calendar_tables()
        conn = self._connect()
        try:
            range_start = f"{start_date} 00:00:00"
            range_end = f"{end_date} 23:59:59"
            rows = conn.execute(
                """
                SELECT ce.*, sc.color AS calendar_color, sc.name AS calendar_name
                FROM calendar_event ce
                LEFT JOIN shared_calendar sc ON sc.id = ce.shared_calendar_id
                WHERE ce.start_at <= ? AND ce.end_at >= ?
                ORDER BY ce.start_at ASC
                """,
                (range_end, range_start),
            ).fetchall()
            events = []
            for row in rows:
                event = DBCalendarEvent.from_dict(row)
                event.calendar_color = row["calendar_color"] if "calendar_color" in row.keys() else None
                event.calendar_name = row["calendar_name"] if "calendar_name" in row.keys() else None
                event.linked_recordings = self._get_linked_recordings(conn, event.id)
                events.append(event)
            return events
        finally:
            conn.close()

    def _get_linked_recordings(self, conn, event_id: int) -> list[dict]:
        rows = conn.execute(
            """
            SELECT r.id as recording_id, r.name, r.label, r.transcript,
                   rel.link_source
            FROM recording_event_link rel
            JOIN recording r ON r.id = rel.recording_id
            WHERE rel.event_id = ?
            ORDER BY r.name ASC
            """,
            (event_id,),
        ).fetchall()
        result = []
        for row in rows:
            # Check latest summary
            summary_row = conn.execute(
                """
                SELECT id, title, tags, summary FROM summary
                WHERE recording_id = ? ORDER BY version DESC LIMIT 1
                """,
                (row["recording_id"],),
            ).fetchone()
            result.append(
                {
                    "recording_id": row["recording_id"],
                    "name": row["name"],
                    "label": row["label"],
                    "link_source": row["link_source"],
                    "has_transcript": row["transcript"] is not None and len(row["transcript"]) > 0,
                    "has_summary": summary_row is not None,
                    "summary_id": summary_row["id"] if summary_row else None,
                    "summary_title": summary_row["title"] if summary_row else None,
                    "summary_tags": summary_row["tags"].split(",") if summary_row and summary_row["tags"] else [],
                    "summary_text": summary_row["summary"] if summary_row else None,
                }
            )
        return result

    def link_recording_to_event(self, recording_id: int, event_id: int, link_source: str = "manual") -> bool:
        self._ensure_calendar_tables()
        conn = self._connect()
        try:
            conn.execute(
                "INSERT OR IGNORE INTO recording_event_link (recording_id, event_id, link_source) VALUES (?, ?, ?)",
                (recording_id, event_id, link_source),
            )
            conn.commit()
            return True
        finally:
            conn.close()

    def unlink_recording_from_event(self, recording_id: int, event_id: int) -> bool:
        self._ensure_calendar_tables()
        conn = self._connect()
        try:
            result = conn.execute(
                "DELETE FROM recording_event_link WHERE recording_id = ? AND event_id = ?",
                (recording_id, event_id),
            )
            conn.commit()
            return result.rowcount > 0
        finally:
            conn.close()

    def get_events_for_recording(self, recording_id: int) -> list[DBCalendarEvent]:
        self._ensure_calendar_tables()
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT ce.* FROM calendar_event ce
                JOIN recording_event_link rel ON rel.event_id = ce.id
                WHERE rel.recording_id = ?
                ORDER BY ce.start_at ASC
                """,
                (recording_id,),
            ).fetchall()
            return [DBCalendarEvent.from_dict(row) for row in rows]
        finally:
            conn.close()

    def get_recordings_for_day(self, date_str: str) -> list[dict]:
        """Get recordings whose recorded_at or name-parsed date matches the given day."""
        conn = self._connect()
        try:
            rows = conn.execute("SELECT id, name, label, duration, recorded_at, transcript FROM recording").fetchall()
            result = []
            for row in rows:
                if row["recorded_at"]:
                    rec_date = row["recorded_at"][:10]
                else:
                    rec_date = self._parse_recording_date_from_name(row["name"])
                if rec_date == date_str:
                    summary_row = conn.execute(
                        "SELECT title, tags FROM summary WHERE recording_id = ? ORDER BY version DESC LIMIT 1",
                        (row["id"],),
                    ).fetchone()
                    result.append(
                        {
                            "recording_id": row["id"],
                            "name": row["name"],
                            "label": row["label"],
                            "duration": row["duration"],
                            "has_transcript": row["transcript"] is not None and len(row["transcript"]) > 0,
                            "has_summary": summary_row is not None,
                            "summary_title": summary_row["title"] if summary_row else None,
                            "summary_tags": (
                                summary_row["tags"].split(",") if summary_row and summary_row["tags"] else []
                            ),
                        }
                    )
            return result
        finally:
            conn.close()

    @staticmethod
    def _parse_recording_date_from_name(name: str) -> str | None:
        """Parse recording name like '2026Apr01-152300-Rec13' → '2026-04-01'."""
        from datetime import datetime as dt

        try:
            parts = name.split("-")
            if len(parts) >= 2:
                dt_str = f"{parts[0]}-{parts[1]}"
                parsed = dt.strptime(dt_str, "%Y%b%d-%H%M%S")
                return parsed.strftime("%Y-%m-%d")
        except (ValueError, IndexError):
            pass
        return None

    # ─── Daily Recap CRUD ──────────────────────────────────────────

    def save_daily_recap(self, recap: DBDailyRecap) -> DBDailyRecap:
        """Insert or replace the daily recap for a given date."""
        self._ensure_calendar_tables()
        conn = self._connect()
        try:
            highlights_json = json.dumps(recap.highlights) if recap.highlights else None
            action_items_json = json.dumps(recap.action_items) if recap.action_items else None
            blockers_json = json.dumps(recap.blockers) if recap.blockers else None

            conn.execute(
                """
                INSERT INTO daily_recap (date, title, highlights, recap, action_items, blockers, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(date) DO UPDATE SET
                    title = excluded.title,
                    highlights = excluded.highlights,
                    recap = excluded.recap,
                    action_items = excluded.action_items,
                    blockers = excluded.blockers,
                    updated_at = datetime('now')
                """,
                (recap.date, recap.title, highlights_json, recap.recap, action_items_json, blockers_json),
            )
            conn.commit()
            return self.get_daily_recap(recap.date)
        finally:
            conn.close()

    def get_daily_recap(self, date_str: str) -> DBDailyRecap | None:
        """Get the stored daily recap for a given date."""
        self._ensure_calendar_tables()
        conn = self._connect()
        try:
            row = conn.execute("SELECT * FROM daily_recap WHERE date = ?", (date_str,)).fetchone()
            if not row:
                return None
            return DBDailyRecap.from_dict(row)
        finally:
            conn.close()

    def delete_daily_recap(self, date_str: str) -> bool:
        """Delete the daily recap for a given date."""
        self._ensure_calendar_tables()
        conn = self._connect()
        try:
            result = conn.execute("DELETE FROM daily_recap WHERE date = ?", (date_str,))
            conn.commit()
            return result.rowcount > 0
        finally:
            conn.close()

    def get_daily_recaps_for_month(self, year: int, month: int) -> list[str]:
        """Return list of date strings that have stored recaps for a given month."""
        self._ensure_calendar_tables()
        conn = self._connect()
        try:
            month_start = f"{year:04d}-{month:02d}-01"
            if month == 12:
                month_end = f"{year + 1:04d}-01-01"
            else:
                month_end = f"{year:04d}-{month + 1:02d}-01"
            rows = conn.execute(
                "SELECT date FROM daily_recap WHERE date >= ? AND date < ? ORDER BY date",
                (month_start, month_end),
            ).fetchall()
            return [row["date"] for row in rows]
        finally:
            conn.close()

    # ─── Shared Calendar CRUD ─────────────────────────────────────

    def get_shared_calendars(self) -> list[DBSharedCalendar]:
        """Get all shared calendars with event counts."""
        self._ensure_calendar_tables()
        conn = self._connect()
        try:
            rows = conn.execute("""
                SELECT sc.*,
                       (SELECT COUNT(*) FROM calendar_event ce WHERE ce.shared_calendar_id = sc.id) AS event_count
                FROM shared_calendar sc
                ORDER BY sc.name ASC
                """).fetchall()
            calendars = []
            for row in rows:
                cal = DBSharedCalendar.from_dict(row)
                cal.event_count = row["event_count"]
                calendars.append(cal)
            return calendars
        finally:
            conn.close()

    def get_shared_calendar_by_id(self, calendar_id: int) -> DBSharedCalendar | None:
        self._ensure_calendar_tables()
        conn = self._connect()
        try:
            row = conn.execute("SELECT * FROM shared_calendar WHERE id = ?", (calendar_id,)).fetchone()
            return DBSharedCalendar.from_dict(row) if row else None
        finally:
            conn.close()

    def insert_shared_calendar(self, cal: DBSharedCalendar) -> DBSharedCalendar:
        self._ensure_calendar_tables()
        conn = self._connect()
        try:
            result = conn.execute(
                """
                INSERT INTO shared_calendar (name, ical_url, color, is_enabled, sync_interval_minutes)
                VALUES (?, ?, ?, ?, ?)
                """,
                (cal.name, cal.ical_url, cal.color, int(cal.is_enabled), cal.sync_interval_minutes),
            )
            conn.commit()
            cal.id = result.lastrowid
            return cal
        finally:
            conn.close()

    def update_shared_calendar(self, calendar_id: int, **kwargs) -> DBSharedCalendar | None:
        self._ensure_calendar_tables()
        conn = self._connect()
        try:
            existing = conn.execute("SELECT * FROM shared_calendar WHERE id = ?", (calendar_id,)).fetchone()
            if not existing:
                return None
            name = kwargs.get("name", existing["name"])
            ical_url = kwargs.get("ical_url", existing["ical_url"])
            color = kwargs.get("color", existing["color"])
            is_enabled = int(kwargs["is_enabled"]) if "is_enabled" in kwargs else existing["is_enabled"]
            sync_interval = kwargs.get("sync_interval_minutes", existing["sync_interval_minutes"])
            conn.execute(
                """
                UPDATE shared_calendar SET name=?, ical_url=?, color=?, is_enabled=?, sync_interval_minutes=?
                WHERE id=?
                """,
                (name, ical_url, color, is_enabled, sync_interval, calendar_id),
            )
            conn.commit()
            return self.get_shared_calendar_by_id(calendar_id)
        finally:
            conn.close()

    def delete_shared_calendar(self, calendar_id: int) -> bool:
        """Delete a shared calendar and all its synced events."""
        self._ensure_calendar_tables()
        conn = self._connect()
        try:
            conn.execute("DELETE FROM calendar_event WHERE shared_calendar_id = ?", (calendar_id,))
            result = conn.execute("DELETE FROM shared_calendar WHERE id = ?", (calendar_id,))
            conn.commit()
            return result.rowcount > 0
        finally:
            conn.close()

    def sync_shared_calendar_events(
        self,
        calendar_id: int,
        provider_name: str,
        events: list[DBCalendarEvent],
    ) -> dict:
        """
        Upsert events from an iCal feed. Deletes stale events no longer in the feed.
        """
        self._ensure_calendar_tables()
        conn = self._connect()
        try:
            incoming_eids = {ev.external_id for ev in events if ev.external_id}

            existing_rows = conn.execute(
                "SELECT id, external_id FROM calendar_event WHERE shared_calendar_id = ?",
                (calendar_id,),
            ).fetchall()

            existing_map = {row["external_id"]: row["id"] for row in existing_rows}

            inserted = 0
            updated = 0

            for ev in events:
                if ev.external_id in existing_map:
                    conn.execute(
                        """
                        UPDATE calendar_event
                        SET title=?, description=?, start_at=?, end_at=?, is_all_day=?,
                            location=?, meeting_url=?, status=?
                        WHERE id=?
                        """,
                        (
                            ev.title,
                            ev.description,
                            ev.start_at,
                            ev.end_at,
                            int(ev.is_all_day),
                            ev.location,
                            ev.meeting_url,
                            ev.status,
                            existing_map[ev.external_id],
                        ),
                    )
                    updated += 1
                else:
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO calendar_event
                            (provider, external_id, shared_calendar_id, title, description,
                             start_at, end_at, is_all_day, location, meeting_url, status)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            provider_name,
                            ev.external_id,
                            calendar_id,
                            ev.title,
                            ev.description,
                            ev.start_at,
                            ev.end_at,
                            int(ev.is_all_day),
                            ev.location,
                            ev.meeting_url,
                            ev.status,
                        ),
                    )
                    inserted += 1

            stale_eids = set(existing_map.keys()) - incoming_eids
            deleted = 0
            for eid in stale_eids:
                conn.execute("DELETE FROM calendar_event WHERE id = ?", (existing_map[eid],))
                deleted += 1

            conn.execute(
                "UPDATE shared_calendar SET last_synced_at = datetime('now'), last_error = NULL WHERE id = ?",
                (calendar_id,),
            )
            conn.commit()

            return {"inserted": inserted, "updated": updated, "deleted": deleted}
        finally:
            conn.close()

    def set_shared_calendar_error(self, calendar_id: int, error: str) -> None:
        self._ensure_calendar_tables()
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE shared_calendar SET last_error = ? WHERE id = ?",
                (error, calendar_id),
            )
            conn.commit()
        finally:
            conn.close()

    # ─── Processing Queue ─────────────────────────────────────────

    @staticmethod
    def _processing_job_from_row(row: sqlite3.Row) -> dict:
        return {
            "id": row["id"],
            "job_type": row["job_type"],
            "recording_id": row["recording_id"],
            "recording_name": row["recording_name"],
            "recording_title": row["recording_title"],
            "status": row["status"],
            "engine": row["engine"],
            "summary_provider": row["summary_provider"],
            "summary_model": row["summary_model"],
            "prompt_id": row["prompt_id"],
            "error": row["error"],
            "error_history": row["error_history"],
            "attempts": row["attempts"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "started_at": row["started_at"],
            "completed_at": row["completed_at"],
        }

    def get_app_state(self, key: str, default: str | None = None) -> str | None:
        conn = self._connect()
        try:
            row = conn.execute("SELECT value FROM app_state WHERE key = ?", (key,)).fetchone()
            return row["value"] if row else default
        finally:
            conn.close()

    def set_app_state(self, key: str, value: str) -> dict:
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO app_state (key, value, updated_at)
                VALUES (?, ?, datetime('now'))
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = datetime('now')
                """,
                (key, value),
            )
            conn.commit()
            row = conn.execute("SELECT key, value, updated_at FROM app_state WHERE key = ?", (key,)).fetchone()
            return {"key": row["key"], "value": row["value"], "updated_at": row["updated_at"]}
        finally:
            conn.close()

    def list_processing_queue_jobs(self, status: str = "", job_type: str = "") -> list[dict]:
        conn = self._connect()
        try:
            params: list[str] = []
            where_parts = []
            if status:
                where_parts.append("pq.status = ?")
                params.append(status)
            if job_type:
                where_parts.append("pq.job_type = ?")
                params.append(job_type)
            where = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""
            rows = conn.execute(
                f"""
                SELECT pq.*
                FROM processing_queue pq
                {where}
                ORDER BY
                    CASE pq.status
                        WHEN 'running' THEN 0
                        WHEN 'pending' THEN 1
                        WHEN 'failed' THEN 2
                        ELSE 3
                    END,
                    pq.created_at ASC,
                    pq.id ASC
                """,
                params,
            ).fetchall()
            return [self._processing_job_from_row(row) for row in rows]
        finally:
            conn.close()

    def get_processing_queue_counts(self, job_type: str = "") -> dict:
        conn = self._connect()
        try:
            params = []
            where = ""
            if job_type:
                where = "WHERE job_type = ?"
                params.append(job_type)
            rows = conn.execute(
                f"""
                SELECT status, COUNT(*) AS count
                FROM processing_queue
                {where}
                GROUP BY status
            """,
                params,
            ).fetchall()
            counts = {"pending": 0, "running": 0, "completed": 0, "failed": 0, "skipped": 0}
            for row in rows:
                counts[row["status"]] = int(row["count"])
            counts["total"] = sum(counts.values())
            return counts
        finally:
            conn.close()

    def enqueue_processing_jobs(
        self,
        job_type: str,
        names: list[str],
        engine: str | None = None,
        summary_provider: str | None = None,
        summary_model: str | None = None,
        prompt_id: str | None = None,
        skip_statuses: tuple[str, ...] = ("pending", "running"),
    ) -> dict:
        conn = self._connect()
        try:
            enqueued = []
            skipped = []
            failed = []
            seen = set()
            for name in names:
                clean_name = (name or "").strip()
                if not clean_name or clean_name in seen:
                    continue
                seen.add(clean_name)
                rec = conn.execute(
                    """
                    SELECT
                        r.id,
                        r.name,
                        COALESCE(
                            NULLIF((
                                SELECT s.title
                                FROM summary s
                                WHERE s.recording_id = r.id
                                ORDER BY s.version DESC
                                LIMIT 1
                            ), ''),
                            NULLIF(r.label, ''),
                            r.name
                        ) AS recording_title
                    FROM recording r
                    WHERE r.name = ?
                    """,
                    (clean_name,),
                ).fetchone()
                if not rec:
                    failed.append({"name": clean_name, "error": "Recording not found"})
                    continue

                placeholders = ",".join(["?"] * len(skip_statuses))
                active = conn.execute(
                    f"""
                    SELECT id, status
                    FROM processing_queue
                    WHERE job_type = ?
                      AND recording_id = ?
                      AND COALESCE(engine, '') = COALESCE(?, '')
                      AND COALESCE(summary_provider, '') = COALESCE(?, '')
                      AND COALESCE(summary_model, '') = COALESCE(?, '')
                      AND COALESCE(prompt_id, '') = COALESCE(?, '')
                      AND status IN ({placeholders})
                    LIMIT 1
                    """,
                    (
                        job_type,
                        rec["id"],
                        engine,
                        summary_provider,
                        summary_model,
                        prompt_id,
                        *skip_statuses,
                    ),
                ).fetchone()
                if active:
                    skipped.append({"name": clean_name, "status": active["status"], "job_id": active["id"]})
                    continue

                result = conn.execute(
                    """
                    INSERT INTO processing_queue
                        (
                            job_type,
                            recording_id,
                            recording_name,
                            recording_title,
                            status,
                            engine,
                            summary_provider,
                            summary_model,
                            prompt_id
                        )
                    VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, ?)
                    """,
                    (
                        job_type,
                        rec["id"],
                        rec["name"],
                        rec["recording_title"],
                        engine,
                        summary_provider,
                        summary_model,
                        prompt_id,
                    ),
                )
                enqueued.append({"name": clean_name, "job_id": int(result.lastrowid)})
            conn.commit()
            return {
                "ok": len(failed) == 0,
                "counts": {
                    "enqueued": len(enqueued),
                    "skipped_active": len(skipped),
                    "failed": len(failed),
                },
                "enqueued": enqueued,
                "skipped": skipped,
                "failed": failed,
            }
        finally:
            conn.close()

    def claim_next_processing_queue_job(
        self,
        exclude_job_types: list[str] | None = None,
        job_type: str | None = None,
    ) -> dict | None:
        conn = self._connect()
        try:
            params = []
            excluded_sql = ""
            job_type_sql = ""
            if job_type:
                job_type_sql = "AND job_type = ?"
                params.append(job_type)
            if exclude_job_types:
                placeholders = ",".join(["?"] * len(exclude_job_types))
                excluded_sql = f"AND job_type NOT IN ({placeholders})"
                params.extend(exclude_job_types)
            row = conn.execute(
                f"""
                SELECT *
                FROM processing_queue
                WHERE status = 'pending'
                  {job_type_sql}
                  {excluded_sql}
                ORDER BY created_at ASC, id ASC
                LIMIT 1
                """,
                params,
            ).fetchone()
            if not row:
                return None
            conn.execute(
                """
                UPDATE processing_queue
                SET status = 'running',
                    attempts = attempts + 1,
                    error = NULL,
                    started_at = datetime('now'),
                    updated_at = datetime('now')
                WHERE id = ?
                """,
                (row["id"],),
            )
            conn.commit()
            updated = conn.execute("SELECT * FROM processing_queue WHERE id = ?", (row["id"],)).fetchone()
            return self._processing_job_from_row(updated)
        finally:
            conn.close()

    def update_processing_queue_job_status(self, job_id: int, status: str, error: str | None = None) -> dict | None:
        conn = self._connect()
        try:
            completed_expr = "datetime('now')" if status in ("completed", "failed", "skipped") else "completed_at"
            error_history_expr = (
                "trim(COALESCE(error_history || char(10), '') || datetime('now') || ' - ' || ?)"
                if status == "failed" and error
                else "error_history"
            )
            params = [status, error]
            if status == "failed" and error:
                params.append(error)
            params.append(job_id)
            conn.execute(
                f"""
                UPDATE processing_queue
                SET status = ?,
                    error = ?,
                    error_history = {error_history_expr},
                    completed_at = {completed_expr},
                    updated_at = datetime('now')
                WHERE id = ?
                """,
                params,
            )
            conn.commit()
            row = conn.execute("SELECT * FROM processing_queue WHERE id = ?", (job_id,)).fetchone()
            return self._processing_job_from_row(row) if row else None
        finally:
            conn.close()

    def update_processing_queue_job_summary_model(self, job_id: int, summary_model: str) -> dict | None:
        conn = self._connect()
        try:
            conn.execute(
                """
                UPDATE processing_queue
                SET summary_model = ?,
                    updated_at = datetime('now')
                WHERE id = ?
                """,
                (summary_model, job_id),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM processing_queue WHERE id = ?", (job_id,)).fetchone()
            return self._processing_job_from_row(row) if row else None
        finally:
            conn.close()

    def reset_running_processing_jobs(self, job_type: str | None = None) -> int:
        conn = self._connect()
        try:
            params = []
            job_type_filter = ""
            if job_type:
                job_type_filter = "AND job_type = ?"
                params.append(job_type)
            result = conn.execute(
                f"""
                UPDATE processing_queue
                SET status = 'pending',
                    updated_at = datetime('now')
                WHERE status = 'running'
                  {job_type_filter}
                """,
                params,
            )
            conn.commit()
            return result.rowcount
        finally:
            conn.close()

    def retry_failed_processing_jobs(
        self,
        job_type: str,
        summary_provider: str | None = None,
        summary_model: str | None = None,
    ) -> dict:
        conn = self._connect()
        try:
            if job_type == "summarize":
                skipped = conn.execute("""
                    UPDATE processing_queue
                    SET status = 'skipped',
                        error = 'Summary already exists',
                        completed_at = datetime('now'),
                        updated_at = datetime('now')
                    WHERE job_type = 'summarize'
                      AND status = 'failed'
                      AND EXISTS (
                          SELECT 1
                          FROM summary s
                          WHERE s.recording_id = processing_queue.recording_id
                      )
                    """)
                provider_update_sql = ""
                provider_params: list[str] = []
                if summary_provider:
                    provider_update_sql = ", summary_provider = ?, summary_model = ?"
                    provider_params = [summary_provider, summary_model]

                result = conn.execute(f"""
                    UPDATE processing_queue
                    SET status = 'pending',
                        error = NULL,
                        started_at = NULL,
                        completed_at = NULL,
                        updated_at = datetime('now')
                        {provider_update_sql}
                    WHERE job_type = 'summarize'
                      AND status = 'failed'
                      AND NOT EXISTS (
                          SELECT 1
                          FROM summary s
                          WHERE s.recording_id = processing_queue.recording_id
                      )
                    """, provider_params)
            else:
                skipped = None
                result = conn.execute(
                    """
                    UPDATE processing_queue
                    SET status = 'pending',
                        error = NULL,
                        started_at = NULL,
                        completed_at = NULL,
                        updated_at = datetime('now')
                    WHERE job_type = ?
                      AND status = 'failed'
                    """,
                    (job_type,),
                )
            conn.commit()
            return {
                "ok": True,
                "retried": result.rowcount,
                "skipped": skipped.rowcount if skipped else 0,
            }
        finally:
            conn.close()

    def clear_processing_jobs(self, job_type: str, statuses: tuple[str, ...]) -> dict:
        if not statuses:
            return {"ok": True, "cleared": 0}
        conn = self._connect()
        try:
            placeholders = ",".join(["?"] * len(statuses))
            result = conn.execute(
                f"""
                DELETE FROM processing_queue
                WHERE job_type = ?
                  AND status IN ({placeholders})
                """,
                (job_type, *statuses),
            )
            conn.commit()
            return {"ok": True, "cleared": result.rowcount}
        finally:
            conn.close()

    def get_untranscribed_recording_names(
        self, limit: int | None = None, collection_id: int | None = None
    ) -> list[str]:
        conn = self._connect()
        try:
            params: list[object] = []
            collection_join = ""
            collection_where = ""
            if collection_id is not None:
                collection_join = "JOIN recording_collection rc ON rc.recording_id = r.id"
                collection_where = "AND rc.collection_id = ?"
                params.append(collection_id)
            params.append(limit if limit is not None else -1)
            rows = conn.execute(
                f"""
                SELECT r.name
                FROM recording r
                {collection_join}
                WHERE (r.transcript IS NULL OR trim(r.transcript) = '')
                  AND COALESCE(r.transcription_status, 'pending') IN ('pending', 'retryable_failure', 'unknown')
                  {collection_where}
                ORDER BY COALESCE(r.recorded_at, r.created_at) DESC, r.id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
            return [row["name"] for row in rows]
        finally:
            conn.close()

    def get_recording_names_by_transcription_status(
        self,
        statuses: list[str],
        limit: int | None = None,
        collection_id: int | None = None,
    ) -> list[str]:
        clean_statuses = [status for status in statuses if status in TRANSCRIPTION_STATUSES]
        if not clean_statuses:
            return []
        conn = self._connect()
        try:
            params: list[object] = clean_statuses.copy()
            collection_join = ""
            collection_where = ""
            if collection_id is not None:
                collection_join = "JOIN recording_collection rc ON rc.recording_id = r.id"
                collection_where = "AND rc.collection_id = ?"
                params.append(collection_id)
            params.append(limit if limit is not None else -1)
            placeholders = ",".join(["?"] * len(clean_statuses))
            rows = conn.execute(
                f"""
                SELECT r.name
                FROM recording r
                {collection_join}
                WHERE COALESCE(r.transcription_status, 'pending') IN ({placeholders})
                  AND (r.transcript IS NULL OR trim(r.transcript) = '')
                  {collection_where}
                ORDER BY COALESCE(r.recorded_at, r.created_at) DESC, r.id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
            return [row["name"] for row in rows]
        finally:
            conn.close()

    def get_missing_summary_recording_names(
        self,
        limit: int | None = None,
        collection_id: int | None = None,
    ) -> list[str]:
        conn = self._connect()
        try:
            params: list[object] = []
            collection_join = ""
            collection_where = ""
            if collection_id is not None:
                collection_join = "JOIN recording_collection rc ON rc.recording_id = r.id"
                collection_where = "AND rc.collection_id = ?"
                params.append(collection_id)
            params.append(limit if limit is not None else -1)
            rows = conn.execute(
                f"""
                SELECT r.name
                FROM recording r
                {collection_join}
                WHERE r.transcript IS NOT NULL
                  AND trim(r.transcript) != ''
                  AND NOT EXISTS (
                      SELECT 1
                      FROM summary s
                      WHERE s.recording_id = r.id
                  )
                  {collection_where}
                ORDER BY COALESCE(r.recorded_at, r.created_at) DESC, r.id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
            return [row["name"] for row in rows]
        finally:
            conn.close()

    def get_summary_pipeline_status(self, provider: str = "local", model: str | None = "qwen3:8b") -> dict:
        conn = self._connect()
        try:
            total_missing = conn.execute("""
                SELECT COUNT(*) AS count
                FROM recording r
                WHERE r.transcript IS NOT NULL
                  AND trim(r.transcript) != ''
                  AND NOT EXISTS (
                      SELECT 1
                      FROM summary s
                      WHERE s.recording_id = r.id
                  )
                """).fetchone()["count"]
            ready = conn.execute("""
                SELECT COUNT(*) AS count
                FROM recording r
                WHERE r.transcript IS NOT NULL
                  AND trim(r.transcript) != ''
                  AND NOT EXISTS (
                      SELECT 1
                      FROM summary s
                      WHERE s.recording_id = r.id
                  )
                  AND NOT EXISTS (
                      SELECT 1
                      FROM processing_queue pq
                      WHERE pq.job_type = 'summarize'
                        AND pq.recording_id = r.id
                        AND pq.status IN ('pending', 'running', 'completed')
                  )
                """).fetchone()["count"]
            queue_rows = conn.execute("""
                SELECT status, COUNT(*) AS count
                FROM processing_queue
                WHERE job_type = 'summarize'
                GROUP BY status
                """).fetchall()
            queue_counts = {"pending": 0, "running": 0, "completed": 0, "failed": 0, "skipped": 0}
            for row in queue_rows:
                queue_counts[row["status"]] = int(row["count"])
            current = conn.execute("""
                SELECT *
                FROM processing_queue
                WHERE job_type = 'summarize'
                  AND status = 'running'
                ORDER BY started_at ASC, id ASC
                LIMIT 1
                """).fetchone()
            last_updated = conn.execute("""
                SELECT MAX(updated_at) AS last_updated
                FROM processing_queue
                WHERE job_type = 'summarize'
                """).fetchone()["last_updated"]
            avg_seconds = conn.execute("""
                SELECT AVG((julianday(completed_at) - julianday(started_at)) * 86400.0) AS avg_seconds
                FROM processing_queue
                WHERE job_type = 'summarize'
                  AND status = 'completed'
                  AND started_at IS NOT NULL
                  AND completed_at IS NOT NULL
                """).fetchone()["avg_seconds"]
            eta_seconds = None
            if avg_seconds and queue_counts["pending"]:
                eta_seconds = int(float(avg_seconds) * queue_counts["pending"])

            return {
                "ok": True,
                "paused": self.get_app_state("summary_pipeline_paused", "false") == "true",
                "provider": provider,
                "model": model,
                "total_missing": int(total_missing),
                "ready": int(ready),
                "counts": {
                    **queue_counts,
                    "queued": queue_counts["pending"],
                    "total": sum(queue_counts.values()),
                },
                "current_job": self._processing_job_from_row(current) if current else None,
                "average_summary_seconds": int(float(avg_seconds)) if avg_seconds else None,
                "estimated_seconds_remaining": eta_seconds,
                "last_updated": last_updated,
            }
        finally:
            conn.close()

from datetime import datetime


class DBRecording:
    def __init__(
        self,
        id: int,
        name: str,
        label: str,
        duration: int,
        created_at: datetime,
        transcript: str | None = None,
        file_extension: str = "hda",
        recorded_at: str | None = None,
        folder: str = "/",
        summary: str | None = None,
        title: str | None = None,
        tags: str | None = None,
        notion_url: str | None = None,
        transcription_status: str = "pending",
        transcription_error: str | None = None,
        transcription_attempted_at: str | None = None,
        transcription_segment_count: int | None = None,
        transcription_language: str | None = None,
        transcription_language_probability: float | None = None,
        transcription_vad_removed_duration: float | None = None,
        transcription_skipped: bool = False,
    ):
        self.id = id
        self.name = name
        self.label = label
        self.duration = duration
        self.created_at = created_at
        self.transcript = transcript
        self.file_extension = file_extension
        self.recorded_at = recorded_at
        self.folder = folder
        # Compatibility fields: populated from latest summary when available.
        self.summary = summary
        self.title = title
        self.tags = tags
        self.notion_url = notion_url
        self.transcription_status = transcription_status
        self.transcription_error = transcription_error
        self.transcription_attempted_at = transcription_attempted_at
        self.transcription_segment_count = transcription_segment_count
        self.transcription_language = transcription_language
        self.transcription_language_probability = transcription_language_probability
        self.transcription_vad_removed_duration = transcription_vad_removed_duration
        self.transcription_skipped = transcription_skipped

    @staticmethod
    def from_dict(data):
        keys = data.keys()
        return DBRecording(
            id=data["id"],
            name=data["name"],
            label=data["label"],
            duration=data["duration"],
            created_at=datetime.fromisoformat(data["created_at"]),
            transcript=data["transcript"] if "transcript" in keys else None,
            file_extension=data["file_extension"] if "file_extension" in keys else "hda",
            recorded_at=data["recorded_at"] if "recorded_at" in keys else None,
            folder=data["folder"] if "folder" in keys else "/",
            summary=data["summary"] if "summary" in keys else None,
            title=data["title"] if "title" in keys else None,
            tags=data["tags"] if "tags" in keys else None,
            notion_url=data["notion_url"] if "notion_url" in keys else None,
            transcription_status=data["transcription_status"] if "transcription_status" in keys else "pending",
            transcription_error=data["transcription_error"] if "transcription_error" in keys else None,
            transcription_attempted_at=(
                data["transcription_attempted_at"] if "transcription_attempted_at" in keys else None
            ),
            transcription_segment_count=(
                data["transcription_segment_count"] if "transcription_segment_count" in keys else None
            ),
            transcription_language=data["transcription_language"] if "transcription_language" in keys else None,
            transcription_language_probability=(
                data["transcription_language_probability"] if "transcription_language_probability" in keys else None
            ),
            transcription_vad_removed_duration=(
                data["transcription_vad_removed_duration"] if "transcription_vad_removed_duration" in keys else None
            ),
            transcription_skipped=bool(data["transcription_skipped"]) if "transcription_skipped" in keys else False,
        )

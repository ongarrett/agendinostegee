import json
from datetime import datetime


class DBActionCenterItem:
    def __init__(
        self,
        id: int | None,
        recording_id: int,
        recording_name: str,
        recording_title: str | None,
        item_type: str,
        text: str,
        owner: str | None = None,
        due_date: str | None = None,
        topics: list[str] | None = None,
        confidence: str | None = None,
        status: str = "open",
        source_excerpt: str | None = None,
        source_hash: str | None = None,
        created_at: datetime | str | None = None,
        updated_at: datetime | str | None = None,
    ):
        self.id = id
        self.recording_id = recording_id
        self.recording_name = recording_name
        self.recording_title = recording_title
        self.item_type = item_type
        self.text = text
        self.owner = owner
        self.due_date = due_date
        self.topics = topics or []
        self.confidence = confidence
        self.status = status
        self.source_excerpt = source_excerpt
        self.source_hash = source_hash
        self.created_at = created_at
        self.updated_at = updated_at

    @staticmethod
    def from_dict(data):
        raw_topics = data["topics"] if "topics" in data.keys() else None
        try:
            topics = json.loads(raw_topics) if raw_topics else []
        except (TypeError, json.JSONDecodeError):
            topics = [part.strip() for part in str(raw_topics or "").split(",") if part.strip()]
        return DBActionCenterItem(
            id=data["id"],
            recording_id=data["recording_id"],
            recording_name=data["recording_name"],
            recording_title=data["recording_title"],
            item_type=data["item_type"],
            text=data["text"],
            owner=data["owner"],
            due_date=data["due_date"],
            topics=topics,
            confidence=data["confidence"],
            status=data["status"],
            source_excerpt=data["source_excerpt"],
            source_hash=data["source_hash"],
            created_at=data["created_at"],
            updated_at=data["updated_at"],
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "recording_id": self.recording_id,
            "recording_name": self.recording_name,
            "recording_title": self.recording_title,
            "item_type": self.item_type,
            "text": self.text,
            "owner": self.owner,
            "due_date": self.due_date,
            "topics": self.topics,
            "confidence": self.confidence,
            "status": self.status,
            "source_excerpt": self.source_excerpt,
            "source_hash": self.source_hash,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

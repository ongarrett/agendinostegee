from __future__ import annotations

import hashlib
import json
import logging
import re

from google import genai
from google.genai import types
from json_repair import repair_json

from models.DBActionCenterItem import DBActionCenterItem
from repositories.SqliteDBRepository import SqliteDBRepository

logger = logging.getLogger(__name__)

MAX_OUTPUT_TOKENS = 8192
ACTION_ITEM_TYPES = {"action_item", "decision", "risk", "open_question"}

ACTION_INTELLIGENCE_PROMPT = """\
You extract grounded operational intelligence from one recording.

Rules:
1. Use only the supplied source text.
2. Do not invent owners, people, dates, risks, decisions, or topics.
3. If owner or due date is unclear, return an empty string for that field.
4. Keep item text concise and actionable.
5. Include a short source excerpt only when the source text supports it.
6. Return valid JSON only.

Return this exact shape:
{
  "action_items": [
    {
      "text": "Concise action",
      "owner": "",
      "due_date": "",
      "topics": ["topic"],
      "confidence": "high|medium|low",
      "source_excerpt": "short supporting excerpt"
    }
  ],
  "decisions": [],
  "risks": [],
  "open_questions": [],
  "people": [],
  "topics": []
}
"""


class GeminiActionExtractionService:
    def __init__(self, api_key: str, model: str):
        self._client = genai.Client(api_key=api_key)
        self._model = model

    def extract(self, source_text: str, recording_title: str = "") -> dict:
        logger.info("Extracting Action Center intelligence with Gemini")
        content = f"Recording title: {recording_title}\n\nSource text:\n{source_text}"
        response = self._client.models.generate_content(
            model=self._model,
            config=types.GenerateContentConfig(
                system_instruction=ACTION_INTELLIGENCE_PROMPT,
                response_mime_type="application/json",
                max_output_tokens=MAX_OUTPUT_TOKENS,
            ),
            contents=content,
        )
        return ActionIntelligenceService.parse_extraction_response(response.text or "")


class ActionIntelligenceService:
    def __init__(
        self,
        sqlite_db_repository: SqliteDBRepository,
        extraction_service: GeminiActionExtractionService | None = None,
    ):
        self._sqlite_db_repository = sqlite_db_repository
        self._extraction_service = extraction_service

    @staticmethod
    def parse_extraction_response(raw: str) -> dict:
        def _extract(data: dict) -> dict:
            return {
                "action_items": ActionIntelligenceService._normalize_items(data.get("action_items", [])),
                "decisions": ActionIntelligenceService._normalize_items(data.get("decisions", [])),
                "risks": ActionIntelligenceService._normalize_items(data.get("risks", [])),
                "open_questions": ActionIntelligenceService._normalize_items(data.get("open_questions", [])),
                "people": ActionIntelligenceService._normalize_string_list(data.get("people", [])),
                "topics": ActionIntelligenceService._normalize_string_list(data.get("topics", [])),
            }

        try:
            parsed = json.loads(raw)
            if isinstance(parsed, str):
                parsed = json.loads(parsed)
            if isinstance(parsed, dict):
                return _extract(parsed)
        except (json.JSONDecodeError, TypeError, AttributeError):
            pass

        try:
            repaired = repair_json(raw, return_objects=True)
            if isinstance(repaired, str):
                repaired = json.loads(repaired)
            if isinstance(repaired, dict):
                return _extract(repaired)
        except Exception as exc:
            logger.warning("Action intelligence JSON parsing failed: %s", exc)

        return ActionIntelligenceService.empty_extraction()

    @staticmethod
    def empty_extraction() -> dict:
        return {
            "action_items": [],
            "decisions": [],
            "risks": [],
            "open_questions": [],
            "people": [],
            "topics": [],
        }

    @staticmethod
    def _normalize_items(items) -> list[dict]:
        normalized = []
        for item in items or []:
            if isinstance(item, str):
                item = {"text": item}
            if not isinstance(item, dict):
                continue
            text = str(item.get("text", "")).strip()
            if not text:
                continue
            normalized.append(
                {
                    "text": text,
                    "owner": ActionIntelligenceService._blank_or_string(item.get("owner") or item.get("person")),
                    "due_date": ActionIntelligenceService._blank_or_string(item.get("due_date")),
                    "topics": ActionIntelligenceService._normalize_string_list(
                        item.get("topics") or item.get("project_tags") or item.get("tags")
                    ),
                    "confidence": ActionIntelligenceService._normalize_confidence(item.get("confidence")),
                    "source_excerpt": ActionIntelligenceService._blank_or_string(item.get("source_excerpt")),
                }
            )
        return normalized

    @staticmethod
    def _blank_or_string(value) -> str:
        return str(value).strip() if value is not None else ""

    @staticmethod
    def _normalize_confidence(value) -> str:
        confidence = str(value or "").strip().lower()
        return confidence if confidence in {"high", "medium", "low"} else "medium"

    @staticmethod
    def _normalize_string_list(value) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            parts = re.split(r"[,;\n]", value)
        elif isinstance(value, list):
            parts = value
        else:
            parts = []
        result = []
        seen = set()
        for part in parts:
            text = str(part).strip()
            key = text.lower()
            if text and key not in seen:
                seen.add(key)
                result.append(text)
        return result

    @staticmethod
    def fallback_extract(source_text: str) -> dict:
        result = ActionIntelligenceService.empty_extraction()
        patterns = {
            "action_items": re.compile(r"^\s*(?:[-*]\s*)?(?:action item|action|todo|to do)\s*[:\-]\s*(.+)$", re.I),
            "decisions": re.compile(r"^\s*(?:[-*]\s*)?(?:decision|decided)\s*[:\-]\s*(.+)$", re.I),
            "risks": re.compile(r"^\s*(?:[-*]\s*)?(?:risk|blocker|blocked by)\s*[:\-]\s*(.+)$", re.I),
            "open_questions": re.compile(r"^\s*(?:[-*]\s*)?(?:open question|question)\s*[:\-]\s*(.+)$", re.I),
        }
        for line in source_text.splitlines():
            for key, pattern in patterns.items():
                match = pattern.match(line)
                if match:
                    text = match.group(1).strip()
                    if text:
                        result[key].append(
                            {
                                "text": text,
                                "owner": "",
                                "due_date": "",
                                "topics": [],
                                "confidence": "low",
                                "source_excerpt": line.strip()[:500],
                            }
                        )
                    break
        return result

    def list_items(
        self,
        item_type: str | None = None,
        owner: str | None = None,
        topic: str | None = None,
        recording_name: str | None = None,
        date_filter: str | None = None,
        include_dismissed: bool = False,
    ) -> dict:
        items = self._sqlite_db_repository.list_action_center_items(
            item_type=item_type or None,
            owner=owner or None,
            topic=topic or None,
            recording_name=recording_name or None,
            date_filter=date_filter or None,
            include_dismissed=include_dismissed,
        )
        counts = {item_type: 0 for item_type in ACTION_ITEM_TYPES}
        for item in items:
            counts[item.item_type] = counts.get(item.item_type, 0) + 1
        return {
            "ok": True,
            "items": [item.to_dict() for item in items],
            "counts": counts,
            "filters": self._sqlite_db_repository.get_action_center_filter_options(),
        }

    def extract_selected(self, names: list[str], force: bool = False) -> dict:
        sources = self._sqlite_db_repository.get_action_center_sources(names=names)
        return self._extract_sources(sources, force=force)

    def extract_all_summarized(self, force: bool = False) -> dict:
        sources = self._sqlite_db_repository.get_action_center_sources(summarized_only=True)
        return self._extract_sources(sources, force=force)

    def extract_all_transcribed(self, force: bool = False) -> dict:
        sources = self._sqlite_db_repository.get_action_center_sources(transcribed_only=True)
        return self._extract_sources(sources, force=force)

    def extract_collection(self, collection_id: int, force: bool = False) -> dict:
        sources = self._sqlite_db_repository.get_action_center_sources(collection_id=collection_id)
        return self._extract_sources(sources, force=force)

    def regenerate_recording(self, name: str) -> dict:
        sources = self._sqlite_db_repository.get_action_center_sources(names=[name])
        return self._extract_sources(sources, force=True)

    def _extract_sources(self, sources: list[dict], force: bool = False) -> dict:
        results = []
        total_items = 0
        skipped = 0
        failed = 0
        for source in sources:
            if not force and self._sqlite_db_repository.has_action_center_items_for_recording(source["id"]):
                skipped += 1
                results.append({"recording_name": source["name"], "status": "skipped existing", "items": 0})
                continue
            if force:
                self._sqlite_db_repository.delete_open_action_center_items_for_recording(source["id"])

            extraction, error = self._extract_one(source)
            items = self._items_from_extraction(source, extraction)
            saved = self._sqlite_db_repository.save_action_center_items(items) if items else []
            total_items += len(saved)
            if error and not saved:
                failed += 1
                status = "failed"
            elif error:
                status = "fallback"
            else:
                status = "extracted"
            results.append(
                {
                    "recording_name": source["name"],
                    "status": status,
                    "items": len(saved),
                    **({"error": error} if error else {}),
                }
            )
        return {
            "ok": True,
            "counts": {
                "recordings": len(sources),
                "extracted": len([r for r in results if r["status"] in {"extracted", "fallback"}]),
                "skipped": skipped,
                "failed": failed,
                "items": total_items,
            },
            "results": results,
        }

    def _extract_one(self, source: dict) -> tuple[dict, str | None]:
        source_text = self._source_text(source)
        if not source_text.strip():
            return self.empty_extraction(), "No summary, transcript, or title available."
        if self._extraction_service:
            try:
                return self._extraction_service.extract(source_text, source.get("recording_title") or ""), None
            except Exception as exc:
                logger.warning("Gemini action extraction failed for %s: %s", source["name"], exc)
                return self.fallback_extract(source_text), str(exc)
        return self.fallback_extract(source_text), "Gemini extraction is unavailable."

    @staticmethod
    def _source_text(source: dict) -> str:
        if source.get("summary", "").strip():
            return source["summary"].strip()
        if source.get("transcript", "").strip():
            return source["transcript"].strip()
        title = source.get("recording_title") or source.get("label") or source.get("name") or ""
        tags = source.get("summary_tags") or ""
        return f"Title: {title}\nTags: {tags}".strip()

    def _items_from_extraction(self, source: dict, extraction: dict) -> list[DBActionCenterItem]:
        items = []
        global_topics = extraction.get("topics") or []
        source_text = self._source_text(source)
        source_hash = hashlib.sha256(source_text.encode("utf-8")).hexdigest()[:16]
        mapping = {
            "action_items": "action_item",
            "decisions": "decision",
            "risks": "risk",
            "open_questions": "open_question",
        }
        for key, item_type in mapping.items():
            for item in extraction.get(key, []) or []:
                topics = item.get("topics") or global_topics
                items.append(
                    DBActionCenterItem(
                        id=None,
                        recording_id=source["id"],
                        recording_name=source["name"],
                        recording_title=source.get("recording_title") or source.get("label") or source["name"],
                        item_type=item_type,
                        text=item["text"],
                        owner=item.get("owner") or None,
                        due_date=item.get("due_date") or None,
                        topics=topics,
                        confidence=item.get("confidence") or "medium",
                        status="open",
                        source_excerpt=item.get("source_excerpt") or "",
                        source_hash=source_hash,
                    )
                )
        return items

    def update_item_status(self, item_id: int, status: str) -> dict:
        if status not in {"open", "done", "resolved", "dismissed"}:
            return {"ok": False, "error": "Unsupported status"}
        item = self._sqlite_db_repository.update_action_center_item_status(item_id, status)
        if not item:
            return {"ok": False, "error": "Action Center item not found"}
        return {"ok": True, "item": item.to_dict()}

    def dismiss_item(self, item_id: int) -> dict:
        return self.update_item_status(item_id, "dismissed")

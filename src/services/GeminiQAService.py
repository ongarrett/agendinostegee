import json
import logging

from google import genai
from google.genai import types
from json_repair import repair_json

logger = logging.getLogger(__name__)

MAX_OUTPUT_TOKENS = 8192

QA_SYSTEM_PROMPT = """\
You answer questions about a small set of user-selected recordings.

Rules:
1. Use only the supplied recording sources.
2. Do not invent recordings, facts, dates, names, or decisions.
3. If the sources do not contain enough information, say that clearly.
4. Cite source recordings using the supplied source ids, such as [1] or [2].
5. Keep the answer concise but useful.

Return ONLY valid JSON with this exact shape:
{
  "answer": "Grounded answer with source ids like [1].",
  "citations": [
    {"source_id": 1, "recording_name": "recording-name", "title": "Recording title"}
  ]
}
"""


class GeminiQAService:
    def __init__(self, api_key: str, model: str):
        self._client = genai.Client(api_key=api_key)
        self._model = model

    def answer(self, question: str, context: str) -> dict:
        logger.info("Generating grounded recording Q&A answer with Gemini")
        response = self._client.models.generate_content(
            model=self._model,
            config=types.GenerateContentConfig(
                system_instruction=QA_SYSTEM_PROMPT,
                response_mime_type="application/json",
                max_output_tokens=MAX_OUTPUT_TOKENS,
            ),
            contents=f"Question:\n{question}\n\nRecording sources:\n{context}",
        )
        return self._parse_response(response.text or "")

    @staticmethod
    def _parse_response(raw: str) -> dict:
        def _extract(data: dict) -> dict:
            citations = []
            for item in data.get("citations", []) or []:
                if not isinstance(item, dict):
                    continue
                try:
                    source_id = int(item.get("source_id"))
                except (TypeError, ValueError):
                    continue
                recording_name = str(item.get("recording_name", "")).strip()
                title = str(item.get("title", "")).strip()
                citations.append(
                    {
                        "source_id": source_id,
                        "recording_name": recording_name,
                        "title": title,
                    }
                )
            return {
                "answer": str(data.get("answer", "")).strip(),
                "citations": citations,
            }

        try:
            data = json.loads(raw)
            if isinstance(data, str):
                data = json.loads(data)
            if isinstance(data, dict):
                return _extract(data)
        except (json.JSONDecodeError, AttributeError, TypeError):
            pass

        logger.warning("Strict JSON parse failed for Q&A response, attempting repair")
        try:
            repaired = repair_json(raw, return_objects=True)
            if isinstance(repaired, str):
                repaired = json.loads(repaired)
            if isinstance(repaired, dict):
                return _extract(repaired)
        except Exception as exc:
            logger.warning("JSON repair failed for Q&A response: %s", exc)

        return {"answer": raw.strip(), "citations": []}

import json
import logging
import urllib.error
import urllib.request

from services.SummarizationService import STRUCTURED_INSTRUCTIONS, SummarizationService

logger = logging.getLogger(__name__)

SUPPORTED_OLLAMA_SUMMARY_MODELS = {"llama3.1:8b", "qwen3:8b"}
OLLAMA_SUMMARY_MODEL_ALIASES = {
    "llama3.1": "llama3.1:8b",
    "qwen3": "qwen3:8b",
}


class OllamaSummarizationService:
    def __init__(self, base_url: str = "http://127.0.0.1:11434", model: str = "qwen3:8b", timeout_seconds: int = 180):
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout_seconds = timeout_seconds

    @staticmethod
    def normalize_model(model: str | None) -> str:
        selected = (model or "qwen3:8b").strip()
        return OLLAMA_SUMMARY_MODEL_ALIASES.get(selected, selected)

    @staticmethod
    def supported_models() -> set[str]:
        return set(SUPPORTED_OLLAMA_SUMMARY_MODELS)

    @staticmethod
    def is_supported_model(model: str) -> bool:
        return OllamaSummarizationService.normalize_model(model) in SUPPORTED_OLLAMA_SUMMARY_MODELS

    def summarize(
        self,
        transcript: str,
        system_prompt: str,
        recording_datetime: str | None = None,
        model: str | None = None,
    ) -> dict:
        selected_model = self.normalize_model(model or self._model)
        if not self.is_supported_model(selected_model):
            supported = ", ".join(sorted(SUPPORTED_OLLAMA_SUMMARY_MODELS))
            raise ValueError(f"Unsupported local summary model '{selected_model}'. Supported models: {supported}")

        prompt = self._build_prompt(transcript, system_prompt, recording_datetime)
        payload = {
            "model": selected_model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {
                "temperature": 0.2,
            },
        }
        request = urllib.request.Request(
            f"{self._base_url}/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        logger.info("Generating structured summary with local Ollama model '%s'", selected_model)
        try:
            with urllib.request.urlopen(request, timeout=self._timeout_seconds) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"Local AI summary failed. Is Ollama running at {self._base_url} with model '{selected_model}'?"
            ) from exc
        except json.JSONDecodeError as exc:
            raise RuntimeError("Local AI summary failed: Ollama returned invalid JSON") from exc

        raw = data.get("response", "")
        return SummarizationService._parse_response(raw)

    @staticmethod
    def _build_prompt(transcript: str, system_prompt: str, recording_datetime: str | None = None) -> str:
        user_content = ""
        if recording_datetime:
            user_content += f"Recording date/time: {recording_datetime}\n\n"
        user_content += transcript
        return (
            f"{system_prompt}{STRUCTURED_INSTRUCTIONS}\n\n"
            "Transcript to summarize:\n"
            f"{user_content}\n\n"
            "Return only the JSON object."
        )

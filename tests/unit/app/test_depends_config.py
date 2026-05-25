from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app import depends
from app.api.endpoints import dashboard


@pytest.fixture(autouse=True)
def reset_config(monkeypatch):
    depends.config.clear()
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    yield
    depends.config.clear()


def test_root_path_points_to_project_root():
    root = Path(depends.get_root_path())

    assert root.name == "agendinostegee"
    assert depends.DOTENV_PATH == root / ".env"


def test_get_config_uses_safe_defaults():
    config = depends.get_config()

    assert config["DATABASE_NAME"] == "agendino.db"
    assert config["GEMINI_MODEL"] == "gemini-2.5-flash"
    assert config["GEMINI_EMBEDDING_MODEL"] == "gemini-embedding-001"
    assert config["AUTH_ENABLED"] == "false"


@pytest.mark.parametrize(
    "api_key",
    [
        None,
        "",
        "   ",
        "AIzaS",
        "your-gemini-api-key",
        "your-real-gemini-api-key",
        "AIzaSy...",
        "not-a-google-api-key",
    ],
)
def test_get_gemini_api_key_rejects_missing_placeholder_and_malformed_values(monkeypatch, api_key):
    if api_key is not None:
        monkeypatch.setenv("GEMINI_API_KEY", api_key)

    with pytest.raises(HTTPException) as exc:
        depends.get_gemini_api_key()

    assert exc.value.status_code == 503
    assert "GEMINI_API_KEY is missing or invalid" in exc.value.detail
    assert str(depends.DOTENV_PATH) in exc.value.detail
    if api_key:
        assert api_key not in exc.value.detail


def test_get_gemini_api_key_accepts_well_formed_google_api_key(monkeypatch):
    expected = "AIza" + ("a" * 35)
    monkeypatch.setenv("GEMINI_API_KEY", f"  {expected}  ")

    assert depends.get_gemini_api_key() == expected


def test_semantic_search_service_rejects_missing_key_before_building_service():
    with pytest.raises(HTTPException) as exc:
        depends.get_semantic_search_service()

    assert exc.value.status_code == 503
    assert "GEMINI_API_KEY is missing or invalid" in exc.value.detail


def test_semantic_search_endpoint_returns_clear_missing_key_error():
    app = FastAPI()
    app.include_router(dashboard.router, prefix="/api/dashboard")
    client = TestClient(app)

    response = client.post("/api/dashboard/semantic-search", json={"query": "strategy"})

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert "GEMINI_API_KEY is missing or invalid" in detail
    assert "key value was not logged" in detail.lower()

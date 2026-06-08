"""
SPDX-License-Identifier: MIT

This file is part of the Syx project. See the LICENSE file in the project
root for full license information.
"""
"""
Tests for main FastAPI application.
"""

from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
import app.main as main
from app.main import app, _build_run_config, _collect_git_metadata

client = TestClient(app)


def _fake_settings():
    return SimpleNamespace(
        model_name="main-model",
        builder_model="builder-model",
        tagger_model="tagger-model",
        model_max_tokens=4096,
        base_top_k=8,
        retrieval_multiplier=3.0,
        embedding_model="embed-model",
        chunk_size=1000,
        chunk_overlap=100,
        enable_scheduler=True,
        sleep_cycle_hour=3,
        sleep_cycle_minute=30,
        verify_rag=True,
        force_rag_rebuild_on_startup=False,
        enable_dream=True,
        instrumentation_enabled=True,
        instrumentation_mode="full",
        instrumentation_run_id=None,
        instrumentation_runs_dir="/tmp/runs",
        instrumentation_prompt_tol_abs_tokens=50,
        instrumentation_prompt_tol_pct=0.1,
    )


def _fake_route_policy():
    return {
        "OTHER": SimpleNamespace(
            retrieval_multiplier=2.0,
            max_keep=5,
            min_score=0.4,
            expansion_max_before=1,
            expansion_max_after=2,
        )
    }


def test_root_endpoint():
    """Test root endpoint."""
    response = client.get("/")
    assert response.status_code == 200


def test_health_endpoint():
    """Test health check endpoint."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data and isinstance(data["status"], str)
    assert "service" in data and isinstance(data["service"], str)
    assert "version" in data and isinstance(data["version"], str)
    assert "dependencies" in data and isinstance(data["dependencies"], dict)


def test_api_docs():
    """Test API documentation endpoint."""
    response = client.get("/api/docs")
    assert response.status_code == 200


def test_redoc():
    """Test ReDoc documentation endpoint."""
    response = client.get("/api/redoc")
    assert response.status_code == 200


@patch("app.api.chat.get_llm_client")
def test_chat_stream_contract(mock_get_llm_client):
    """Streaming endpoint returns plain text tokens and completion marker."""
    class _FakeClient:
        @staticmethod
        def stream_chat(**_kwargs):
            yield "Hello", None
            yield " world", None

    mock_get_llm_client.return_value = _FakeClient()
    response = client.post("/chat/stream", json={"message": "hi"})
    assert response.status_code == 200
    assert response.headers.get("content-type", "").startswith("text/plain")
    body = response.text
    assert "Hello world" in body
    assert "::event: done" in body


# --- _build_run_config --------------------------------------------------------


def test_build_run_config_snapshot_shape():
    cfg = _build_run_config(_fake_settings(), _fake_route_policy(), "abc123", True)
    snap = cfg["config_snapshot"]
    assert snap["models_configured"] == {
        "main_model": "main-model",
        "builder_model": "builder-model",
        "tagger_model": "tagger-model",
    }
    assert snap["retrieval_static"]["base_top_k"] == 8
    assert snap["retrieval_static"]["embedding_model"] == "embed-model"
    assert snap["maintenance"]["sleep_cycle_hour"] == 3
    assert snap["maintenance"]["dream_enabled"] is True
    assert snap["instrumentation"]["mode"] == "full"
    assert snap["git_commit"] == "abc123"
    assert snap["git_dirty"] is True


def test_build_run_config_route_policy_snapshot():
    cfg = _build_run_config(_fake_settings(), _fake_route_policy(), "x", False)
    rp = cfg["config_snapshot"]["route_policy"]["OTHER"]
    assert rp["retrieval_multiplier"] == 2.0
    assert rp["max_keep"] == 5
    assert rp["min_score"] == 0.4
    assert rp["expansion"] == {"max_before": 1, "max_after": 2}


# --- _collect_git_metadata ----------------------------------------------------


def test_collect_git_metadata_success(monkeypatch):
    def _fake_run(cmd, **_kwargs):
        if "rev-parse" in cmd:
            return SimpleNamespace(returncode=0, stdout="deadbeef\n")
        return SimpleNamespace(returncode=0, stdout=" M file.py\n")

    monkeypatch.setattr(main.subprocess, "run", _fake_run)
    commit, dirty = _collect_git_metadata()
    assert commit == "deadbeef"
    assert dirty is True


def test_collect_git_metadata_clean_tree(monkeypatch):
    def _fake_run(cmd, **_kwargs):
        if "rev-parse" in cmd:
            return SimpleNamespace(returncode=0, stdout="cafe\n")
        return SimpleNamespace(returncode=0, stdout="")

    monkeypatch.setattr(main.subprocess, "run", _fake_run)
    commit, dirty = _collect_git_metadata()
    assert commit == "cafe"
    assert dirty is False


def test_collect_git_metadata_defaults_on_error(monkeypatch):
    def _boom(*_a, **_k):
        raise OSError("git not available")

    monkeypatch.setattr(main.subprocess, "run", _boom)
    commit, dirty = _collect_git_metadata()
    assert commit == "unknown"
    assert dirty is False

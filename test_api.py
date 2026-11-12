"""Integration tests using a temporary SQLite DB; production uses MySQL."""
import importlib
import os
from pathlib import Path

from fastapi.testclient import TestClient


def test_missing_then_cached(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///" + str(tmp_path / "test.db"))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    import main
    importlib.reload(main)
    with TestClient(main.app) as client:
        missing = client.post("/v1/nutrition/resolve", json={"label": "নেহারি"})
        assert missing.status_code == 404
        estimate_calls = []
        def fake_estimate(label, preparation):
            estimate_calls.append(label)
            return {"name": "Nihari (example)", "kcal": 120, "protein": 9,
                    "carbs": 3, "fat": 8, "fiber": 0.2,
                    "assumptions": "Fixture only; not verified food data"}
        monkeypatch.setattr(main, "estimate_per_100g", fake_estimate)
        first = client.post("/v1/nutrition/resolve", json={"label": "নেহারি"})
        assert first.status_code == 200
        assert first.json()["cached"] is False
        assert first.json()["food"]["source"] == "ai_estimate"
        second = client.post("/v1/nutrition/resolve", json={"label": "নেহারি"})
        assert second.status_code == 200
        assert second.json()["cached"] is True
        assert estimate_calls == ["নেহারি"]
        assert first.json()["food"]["kcal"] == second.json()["food"]["kcal"]

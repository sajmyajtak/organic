import pytest


@pytest.fixture(autouse=True)
def no_clip(monkeypatch):
    """Tests never download or run the CLIP model (igbot/relevance.py)."""
    monkeypatch.setenv("IGBOT_CLIP", "0")

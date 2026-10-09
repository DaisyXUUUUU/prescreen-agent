import pytest

from src import config


@pytest.fixture(autouse=True)
def no_bedrock(monkeypatch):
    """Unit tests never call a real model: an accidental agent call fails fast instead."""
    monkeypatch.setattr(config, "BEDROCK_MODEL_ID", "")

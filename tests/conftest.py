"""Test fixtures.

The NIM client is mocked so tests run without a real API key. Each test
gets a fresh in-memory SQLite + vector store via tmp paths injected into
settings before any backend module imports.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch, tmp_path):
    """Point all stateful paths at tmp_path before backend modules load."""
    monkeypatch.setenv("NVIDIA_API_KEY", "test-key")
    monkeypatch.setenv("MEMORY_DB_PATH", str(tmp_path / "memory.db"))
    monkeypatch.setenv("VECTOR_DB_PATH", str(tmp_path / "vectors.npz"))
    monkeypatch.setenv("UPGRADE_DIR", str(tmp_path / "versions"))
    monkeypatch.setenv("LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("CACHE_BACKEND", "memory")
    # Force reload of modules that read settings at import time
    for mod in list(sys.modules):
        if mod.startswith("backend"):
            sys.modules.pop(mod, None)
    yield


@pytest.fixture
def fake_chat_completion():
    """Build a ChatCompletion-like object that mocks NIM responses."""
    def _build(text: str = "ok", prompt_tokens: int = 10,
                completion_tokens: int = 5) -> MagicMock:
        msg = MagicMock(); msg.content = text
        choice = MagicMock(); choice.message = msg; choice.delta = msg
        usage = MagicMock(); usage.prompt_tokens = prompt_tokens
        usage.completion_tokens = completion_tokens; usage.total_tokens = 15
        resp = MagicMock(); resp.choices = [choice]; resp.usage = usage
        return resp
    return _build


@pytest.fixture
def patched_nim(monkeypatch, fake_chat_completion):
    """Replace the NIM client with deterministic mocks."""
    from backend.nvidia import client as nim_mod
    fake = MagicMock()
    fake.chat = AsyncMock(return_value=fake_chat_completion("synthetic answer"))

    async def _stream(model, messages, **_):
        for tok in ["syn", "the", "tic"]:
            yield tok

    fake.stream = _stream
    fake.list_models = AsyncMock(return_value=["nvidia/llama-3.3-nemotron-nano-8b"])
    fake.discover_and_register = AsyncMock(return_value=[])
    fake.stats = {}
    monkeypatch.setattr(nim_mod, "get_client", lambda: fake)

    # Embeddings
    import numpy as np
    from backend.nvidia import embeddings
    class _Emb:
        async def embed(self, texts):
            arr = np.random.default_rng(0).standard_normal(
                (1 if isinstance(texts, str) else len(list(texts)), 1024)
            ).astype(np.float32)
            arr /= np.linalg.norm(arr, axis=1, keepdims=True)
            return arr
    monkeypatch.setattr(embeddings, "get_embedder", lambda: _Emb())
    return fake

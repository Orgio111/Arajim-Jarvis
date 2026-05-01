"""NVIDIA NIM integration: the only LLM backend in the system."""
from backend.nvidia.client import NIMClient, get_client
from backend.nvidia.models import MODEL_REGISTRY, ModelTier, ModelInfo
from backend.nvidia.router import ModelRouter, router

__all__ = [
    "NIMClient",
    "get_client",
    "MODEL_REGISTRY",
    "ModelTier",
    "ModelInfo",
    "ModelRouter",
    "router",
]

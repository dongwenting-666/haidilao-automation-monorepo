"""Lightweight Ollama client wrapper for local LLM inference."""

from ollama_client.client import OllamaClient, OllamaConnectionError

__all__ = ["OllamaClient", "OllamaConnectionError"]

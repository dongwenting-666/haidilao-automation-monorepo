"""Thin wrapper around the official ollama Python package."""

from __future__ import annotations

import logging
import shutil
import subprocess
import time

import ollama as _ollama

log = logging.getLogger(__name__)

DEFAULT_MODEL = "qwen3:8b"


def ensure_running(host: str = "http://localhost:11434", timeout: int = 30) -> None:
    """Start Ollama server if it's not already running.

    Looks for ``ollama`` on PATH and runs ``ollama serve`` in the background.
    Waits up to *timeout* seconds for the server to become reachable.

    Raises:
        OllamaConnectionError: If ollama is not installed or server fails to start.
    """
    client = _ollama.Client(host=host, timeout=5)
    try:
        client.list()
        return  # Already running
    except Exception:
        pass

    ollama_path = shutil.which("ollama")
    if not ollama_path:
        raise OllamaConnectionError(
            "Ollama is not installed or not on PATH. "
            "Download from https://ollama.com"
        )

    log.info("Starting Ollama server...")
    subprocess.Popen(
        [ollama_path, "serve"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "DETACHED_PROCESS", 0),
    )

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            client.list()
            log.info("Ollama server is ready")
            return
        except Exception:
            time.sleep(1)

    raise OllamaConnectionError(
        f"Ollama server did not start within {timeout}s"
    )


class OllamaClient:
    """Client for local Ollama LLM inference.

    Wraps the official ``ollama`` package with a simplified interface
    and consistent error handling. Automatically starts the Ollama server
    if it's not running.
    """

    def __init__(
        self,
        host: str = "http://localhost:11434",
        model: str = DEFAULT_MODEL,
        timeout: float = 600,
    ) -> None:
        self.model = model
        self._host = host
        ensure_running(host)
        self._client = _ollama.Client(host=host, timeout=timeout)
        self._ensure_model(model)

    def generate(
        self,
        prompt: str,
        system: str | None = None,
        temperature: float = 0.3,
        model: str | None = None,
    ) -> str:
        """Send a generate request and return the response text.

        Raises:
            OllamaConnectionError: If Ollama is not reachable.
        """
        options = {"temperature": temperature}
        try:
            resp = self._client.generate(
                model=model or self.model,
                prompt=prompt,
                system=system or "",
                options=options,
            )
        except _ollama.ResponseError as e:
            raise OllamaConnectionError(str(e)) from e
        except Exception as e:
            raise OllamaConnectionError(f"Cannot connect to Ollama: {e}") from e

        return resp.get("response", "")

    def chat(
        self,
        messages: list[dict],
        temperature: float = 0.3,
        model: str | None = None,
    ) -> str:
        """Send a chat request and return the assistant's message text.

        Raises:
            OllamaConnectionError: If Ollama is not reachable.
        """
        options = {"temperature": temperature}
        try:
            resp = self._client.chat(
                model=model or self.model,
                messages=messages,
                options=options,
            )
        except _ollama.ResponseError as e:
            raise OllamaConnectionError(str(e)) from e
        except Exception as e:
            raise OllamaConnectionError(f"Cannot connect to Ollama: {e}") from e

        return resp.get("message", {}).get("content", "")

    def _ensure_model(self, model: str) -> None:
        """Pull the model if it's not already available locally."""
        try:
            self._client.show(model)
            return
        except _ollama.ResponseError:
            pass
        except Exception:
            return  # Can't check, will fail later with a clear error

        log.info("Pulling model %s (first time only)...", model)
        try:
            self._client.pull(model)
            log.info("Model %s ready", model)
        except Exception as e:
            raise OllamaConnectionError(f"Failed to pull model {model}: {e}") from e

    def list_models(self) -> list[str]:
        """Return list of available model names."""
        try:
            resp = self._client.list()
            return [m.get("name", "") for m in resp.get("models", [])]
        except Exception:
            return []

    def is_available(self) -> bool:
        """Check if Ollama is reachable."""
        try:
            self._client.list()
            return True
        except Exception:
            return False


class OllamaConnectionError(Exception):
    """Ollama server is not reachable."""

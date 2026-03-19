import logging
from pathlib import Path
from typing import List, Optional

import requests
from django.conf import settings
from langchain_ollama import OllamaEmbeddings, OllamaLLM
from functools import lru_cache

logger = logging.getLogger(__name__)


def _in_docker() -> bool:
    return Path("/.dockerenv").exists()


def _candidate_base_urls() -> List[str]:
    configured = getattr(settings, "OLLAMA_BASE_URL", "").strip()
    candidates: List[str] = []

    if configured:
        candidates.append(configured)

    if _in_docker():
        candidates.extend(
            [
                "http://host.docker.internal:11434",
                "http://172.17.0.1:11434",
            ]
        )

    candidates.append("http://localhost:11434")

    seen = set()
    deduped: List[str] = []
    for url in candidates:
        normalized = url.rstrip("/")
        if normalized and normalized not in seen:
            seen.add(normalized)
            deduped.append(normalized)
    return deduped


@lru_cache(maxsize=1)
def resolve_ollama_base_url(timeout_seconds: float = 1.5) -> Optional[str]:
    for base_url in _candidate_base_urls():
        try:
            response = requests.get(
                f"{base_url}/api/tags",
                timeout=timeout_seconds,
            )
            if response.status_code < 500:
                return base_url
        except requests.RequestException:
            continue

    candidates = ", ".join(_candidate_base_urls())
    logger.error(f"Ollama is unreachable. Tried: {candidates}")
    return _candidate_base_urls()[0] if _candidate_base_urls() else None


def _model_matches(name: str, requested: str) -> bool:
    normalized_name = (name or "").strip()
    normalized_requested = (requested or "").strip()
    if not normalized_name or not normalized_requested:
        return False
    if normalized_name == normalized_requested:
        return True
    return normalized_name.split(":")[0] == normalized_requested.split(":")[0]


@lru_cache(maxsize=16)
def ensure_model_available(model: str, pull_timeout_seconds: float = 900.0) -> Optional[str]:
    base_url = resolve_ollama_base_url()
    if not base_url:
        return None

    try:
        response = requests.get(f"{base_url}/api/tags", timeout=5)
        response.raise_for_status()
        payload = response.json() or {}
        for item in payload.get("models", []):
            if _model_matches(item.get("name", ""), model):
                return base_url
    except requests.RequestException as exc:
        logger.warning("Could not inspect Ollama models at %s: %s", base_url, exc)
        return base_url

    logger.warning("Ollama model '%s' is missing at %s. Pulling it now.", model, base_url)
    try:
        response = requests.post(
            f"{base_url}/api/pull",
            json={"name": model, "stream": False},
            timeout=pull_timeout_seconds,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise RuntimeError(
            f"Ollama model '{model}' is unavailable and automatic pull failed: {exc}"
        ) from exc

    return base_url


def create_embeddings(model: str = "nomic-embed-text") -> OllamaEmbeddings:
    base_url = ensure_model_available(model)
    kwargs = {"model": model}
    if base_url:
        kwargs["base_url"] = base_url
    return OllamaEmbeddings(**kwargs)


def create_llm(model: str = "mistral") -> OllamaLLM:
    base_url = ensure_model_available(model)
    kwargs = {
        "model": model,
        "temperature": getattr(settings, "RAG_LLM_TEMPERATURE", 0.2),
        "num_predict": getattr(settings, "RAG_LLM_NUM_PREDICT", 320),
        "num_ctx": getattr(settings, "RAG_LLM_NUM_CTX", 4096),
        "keep_alive": getattr(settings, "RAG_LLM_KEEP_ALIVE", "30m"),
    }
    if base_url:
        kwargs["base_url"] = base_url
    return OllamaLLM(**kwargs)

"""
Centralized AI Model and Embeddings Provider Manager.
Seamlessly routes inference and embeddings between Local AI (Ollama, LM Studio)
and Cloud AI (OpenAI) with automatic presence detection and zero downtime.
"""

from __future__ import annotations
import hashlib
import json
import logging
import math
import os
import re
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
try:
    from langchain_core.embeddings import Embeddings
except ImportError:
    class Embeddings:  # type: ignore
        """Fallback base class when langchain_core is not in environment."""
        pass

try:
    from langchain_openai import ChatOpenAI, OpenAIEmbeddings
except ImportError:
    ChatOpenAI = None  # type: ignore
    OpenAIEmbeddings = None  # type: ignore


from src.llms.model_discovery import (
    get_active_provider_configuration,
    discover_all_local_providers,
)

load_dotenv()
logger = logging.getLogger("src.llms.provider")

# Global active configuration cache
_active_provider_override: Optional[str] = None
_active_model_override: Optional[str] = None
_cached_llm: Optional[Any] = None
_cached_embeddings: Optional[Embeddings] = None


class LocalDeterministicEmbeddings(Embeddings):
    """
    High-speed, zero-dependency local embedding generator.
    Produces deterministic 1536-dimensional normalized vector representations
    from text tokens using hashed n-gram projections.
    Guarantees FAISS vector search works completely offline even without local embedding models.
    """

    def __init__(self, dimension: int = 1536):
        self.dimension = dimension

    def _hash_token(self, token: str) -> int:
        h = hashlib.sha256(token.encode("utf-8")).hexdigest()
        return int(h, 16) % self.dimension

    def _embed_text(self, text: str) -> List[float]:
        vector = [0.0] * self.dimension
        words = re.findall(r"\w+", text.lower())
        if not words:
            return vector

        # Term frequency + character n-grams + word bigrams
        for w in words:
            vector[self._hash_token(w)] += 2.0
            for n in (3, 4):
                if len(w) >= n:
                    for i in range(len(w) - n + 1):
                        vector[self._hash_token(w[i:i+n])] += 0.8

        for i in range(len(words) - 1):
            bigram = f"{words[i]}_{words[i+1]}"
            vector[self._hash_token(bigram)] += 2.0

        # L2 normalize
        norm = math.sqrt(sum(v * v for v in vector))
        if norm > 0:
            vector = [v / norm for v in vector]
        return vector

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return [self._embed_text(t) for t in texts]

    def embed_query(self, text: str) -> List[float]:
        return self._embed_text(text)


def get_llm(
    provider_override: Optional[str] = None,
    model_override: Optional[str] = None,
    force_refresh: bool = False
) -> Any:
    """
    Returns the appropriate LangChain chat model instance.
    Automatically binds to local AI models (Ollama, LM Studio) if present on the system,
    or falls back to OpenAI Cloud.
    """
    global _cached_llm, _active_provider_override, _active_model_override

    prov = provider_override or _active_provider_override
    mod = model_override or _active_model_override

    if _cached_llm is not None and not force_refresh and prov is None and mod is None:
        return _cached_llm

    cfg = get_active_provider_configuration(forced_provider=prov, forced_model=mod)
    logger.info("Initializing LLM with configuration: %s", cfg)

    # 1. Local AI Model (Ollama, LM Studio, Custom)
    if cfg.get("mode") == "local" or cfg.get("provider") in ["ollama", "lm_studio", "custom_local"]:
        base_url = cfg.get("openai_base_url", "http://localhost:11434/v1")
        model_name = cfg.get("selected_model", "llama3.2")
        logger.info("Configuring Local AI via %s (model: %s)", base_url, model_name)
        llm_instance = ChatOpenAI(
            base_url=base_url,
            api_key="local-ai",  # Ollama/LM Studio do not require a real key
            model=model_name,
            temperature=0.0,
            streaming=True,
        )
        _cached_llm = llm_instance
        return llm_instance

    # 2. OpenAI Cloud
    if cfg.get("provider") == "openai" or os.getenv("OPENAI_API_KEY"):
        api_key = os.getenv("OPENAI_API_KEY", "")
        model_name = cfg.get("selected_model", "gpt-4o")
        logger.info("Configuring OpenAI Cloud model: %s", model_name)
        llm_instance = ChatOpenAI(
            api_key=api_key,
            model=model_name,
            temperature=0.0,
            streaming=True,
        )
        _cached_llm = llm_instance
        return llm_instance

    # 3. Fallback when neither local server is running nor API key exists
    logger.warning("No running local model or OpenAI key found. Falling back to local Ollama localhost:11434/v1")
    llm_instance = ChatOpenAI(
        base_url="http://localhost:11434/v1",
        api_key="local-ai",
        model="llama3.2",
        temperature=0.0,
        streaming=True,
    )
    _cached_llm = llm_instance
    return llm_instance


def get_embeddings(provider_override: Optional[str] = None) -> Embeddings:
    """
    Returns an Embeddings provider for FAISS.
    - If local Ollama has an embedding model (e.g. nomic-embed-text), uses local embeddings.
    - If OPENAI_API_KEY is available, uses OpenAIEmbeddings.
    - Otherwise, provides high-speed LocalDeterministicEmbeddings so indexing never fails.
    """
    global _cached_embeddings
    if _cached_embeddings is not None and provider_override is None:
        return _cached_embeddings

    cfg = get_active_provider_configuration(forced_provider=provider_override)

    # If local provider with embedding model is available
    if cfg.get("selected_embed_model") and cfg.get("openai_base_url"):
        logger.info("Using local embedding model: %s from %s", cfg["selected_embed_model"], cfg["openai_base_url"])
        try:
            emb = OpenAIEmbeddings(
                base_url=cfg["openai_base_url"],
                api_key="local-ai",
                model=cfg["selected_embed_model"],
            )
            _cached_embeddings = emb
            return emb
        except Exception as e:
            logger.warning("Could not initialize local OpenAIEmbeddings: %s", e)

    # Cloud OpenAI embeddings
    if os.getenv("OPENAI_API_KEY"):
        try:
            emb = OpenAIEmbeddings()
            _cached_embeddings = emb
            return emb
        except Exception as e:
            logger.warning("Could not initialize OpenAIEmbeddings: %s", e)

    # Fully local deterministic fallback
    logger.info("Using LocalDeterministicEmbeddings for offline vector indexing.")
    emb = LocalDeterministicEmbeddings(dimension=1536)
    _cached_embeddings = emb
    return emb


def switch_provider(provider: str, model: Optional[str] = None) -> Dict[str, Any]:
    """Dynamically switches active model provider at runtime."""
    global _active_provider_override, _active_model_override, _cached_llm, _cached_embeddings
    _active_provider_override = provider
    _active_model_override = model
    _cached_llm = None
    _cached_embeddings = None
    return get_active_provider_status()


def get_active_provider_status() -> Dict[str, Any]:
    """Returns detailed status of active provider and all discovered local models."""
    cfg = get_active_provider_configuration(
        forced_provider=_active_provider_override,
        forced_model=_active_model_override
    )
    all_local = discover_all_local_providers()
    return {
        "active_configuration": cfg,
        "active_provider": cfg.get("provider"),
        "active_model": cfg.get("selected_model"),
        "is_local": cfg.get("mode") == "local",
        "has_cloud_key": bool(os.getenv("OPENAI_API_KEY")),
        "discovered_local_providers": all_local,
    }

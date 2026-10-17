"""
Local AI model discovery engine for Adaptive RAG.
Automatically probes for local LLM servers (Ollama, LM Studio, LocalAI, vLLM)
and discovers installed models.
"""

from __future__ import annotations
import json
import logging
import os
import urllib.request
from typing import Dict, List, Optional, Any

logger = logging.getLogger("src.llms.model_discovery")

# Default local server probe endpoints
DEFAULT_OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
DEFAULT_LM_STUDIO_HOST = os.getenv("LM_STUDIO_HOST", "http://localhost:1234")
DEFAULT_LOCAL_LLM_URL = os.getenv("LOCAL_LLM_URL", "")


def _probe_http_json(url: str, timeout: float = 1.0) -> Optional[Dict[str, Any]]:
    """Probes an HTTP endpoint and returns JSON if responsive."""
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "AdaptiveRAG-ModelDiscovery/1.0", "Accept": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                raw_data = resp.read().decode("utf-8")
                return json.loads(raw_data)
    except Exception as e:
        logger.debug("Probe to %s failed: %s", url, e)
    return None


def probe_ollama(host: str = DEFAULT_OLLAMA_HOST) -> Optional[Dict[str, Any]]:
    """
    Checks if Ollama is running and discovers all installed models.
    Endpoint: GET /api/tags
    """
    endpoint = f"{host.rstrip('/')}/api/tags"
    data = _probe_http_json(endpoint, timeout=1.2)
    if data and "models" in data:
        models = [m.get("name", "") for m in data.get("models", []) if m.get("name")]
        
        # Identify chat models vs embedding models
        chat_models = [m for m in models if "embed" not in m.lower()]
        embed_models = [m for m in models if "embed" in m.lower()]
        
        # Prefer llama3.2, llama3, mistral, qwen, deepseek, or first chat model
        preferred_model = None
        for candidate in ["llama3.2", "llama3", "mistral", "qwen2.5", "deepseek-r1", "phi3"]:
            for m in chat_models:
                if candidate in m.lower():
                    preferred_model = m
                    break
            if preferred_model:
                break
        
        if not preferred_model and chat_models:
            preferred_model = chat_models[0]
            
        return {
            "provider": "ollama",
            "name": "Ollama Local AI",
            "host": host,
            "openai_base_url": f"{host.rstrip('/')}/v1",
            "models": models,
            "chat_models": chat_models,
            "embed_models": embed_models,
            "selected_model": preferred_model or (models[0] if models else "llama3.2"),
            "selected_embed_model": embed_models[0] if embed_models else None,
            "is_running": True,
        }
    return None


def probe_lm_studio(host: str = DEFAULT_LM_STUDIO_HOST) -> Optional[Dict[str, Any]]:
    """
    Checks if LM Studio local server is running.
    Endpoint: GET /v1/models
    """
    endpoint = f"{host.rstrip('/')}/v1/models"
    data = _probe_http_json(endpoint, timeout=1.2)
    if data and "data" in data:
        models = [m.get("id", "") for m in data.get("data", []) if m.get("id")]
        return {
            "provider": "lm_studio",
            "name": "LM Studio Local AI",
            "host": host,
            "openai_base_url": f"{host.rstrip('/')}/v1",
            "models": models,
            "chat_models": models,
            "embed_models": [m for m in models if "embed" in m.lower()],
            "selected_model": models[0] if models else "local-model",
            "selected_embed_model": None,
            "is_running": True,
        }
    return None


def probe_custom_local(url: str = DEFAULT_LOCAL_LLM_URL) -> Optional[Dict[str, Any]]:
    """Checks custom local OpenAI-compatible endpoint (vLLM, LocalAI, Jan, etc.)."""
    if not url:
        return None
    endpoint = f"{url.rstrip('/')}/models"
    data = _probe_http_json(endpoint, timeout=1.5)
    if data and "data" in data:
        models = [m.get("id", "") for m in data.get("data", []) if m.get("id")]
        return {
            "provider": "custom_local",
            "name": "Custom Local Server",
            "host": url,
            "openai_base_url": url,
            "models": models,
            "chat_models": models,
            "embed_models": [],
            "selected_model": models[0] if models else "default",
            "selected_embed_model": None,
            "is_running": True,
        }
    return None


def discover_all_local_providers() -> List[Dict[str, Any]]:
    """Discovers all local AI model providers currently running on the system."""
    found: List[Dict[str, Any]] = []
    
    ollama_info = probe_ollama()
    if ollama_info:
        found.append(ollama_info)
        
    lm_studio_info = probe_lm_studio()
    if lm_studio_info:
        found.append(lm_studio_info)
        
    custom_info = probe_custom_local()
    if custom_info:
        found.append(custom_info)
        
    return found


def get_active_provider_configuration(
    forced_provider: Optional[str] = None,
    forced_model: Optional[str] = None
) -> Dict[str, Any]:
    """
    Determines the best AI provider to use based on system presence and user preferences.
    Strategy:
    1. If user/env forces a provider (e.g. 'ollama', 'lm_studio', 'openai', 'cloud'), adhere to it.
    2. If set to 'auto' (default):
       - If any local AI model server is running, USE LOCAL AI!
       - If no local AI is running but OPENAI_API_KEY is present, USE OPENAI.
       - If neither, return local fallback instructions.
    """
    mode = (forced_provider or os.getenv("LLM_PROVIDER", "auto")).lower()
    openai_key = os.getenv("OPENAI_API_KEY", "").strip()
    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    local_providers = discover_all_local_providers()

    # Mode: Force Local / Ollama
    if mode in ["ollama", "local", "lm_studio", "custom"]:
        matching = [p for p in local_providers if p["provider"] == mode or mode in ["local", "custom"]]
        if matching:
            cfg = matching[0].copy()
            if forced_model:
                cfg["selected_model"] = forced_model
            cfg["mode"] = "local"
            return cfg
        return {
            "provider": mode,
            "name": f"Local AI ({mode})",
            "is_running": False,
            "mode": "local",
            "openai_base_url": "http://localhost:11434/v1" if mode == "ollama" else "http://localhost:1234/v1",
            "selected_model": forced_model or "llama3.2",
            "warning": f"Local provider '{mode}' was requested but could not be reached. Ensure the service is running."
        }

    # Mode: Force Groq (Free Cloud Tier)
    if mode == "groq":
        return {
            "provider": "groq",
            "name": "Groq Cloud (Free Tier)",
            "is_running": bool(groq_key),
            "mode": "cloud",
            "selected_model": forced_model or os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
            "has_api_key": bool(groq_key),
        }

    # Mode: Force Cloud / OpenAI
    if mode in ["openai", "cloud"]:
        return {
            "provider": "openai",
            "name": "OpenAI Cloud",
            "is_running": bool(openai_key),
            "mode": "cloud",
            "selected_model": forced_model or os.getenv("OPENAI_MODEL", "gpt-4o"),
            "has_api_key": bool(openai_key),
        }

    # Mode: Auto (Default)
    # 1. Local AI First
    if local_providers:
        top_local = local_providers[0].copy()
        if forced_model:
            top_local["selected_model"] = forced_model
        top_local["mode"] = "local"
        top_local["auto_selected"] = True
        logger.info("Auto-detected local AI model provider: %s (%s)", top_local["name"], top_local["selected_model"])
        return top_local

    # 2. Groq Free Tier Fallback (if Groq key is set)
    if groq_key:
        return {
            "provider": "groq",
            "name": "Groq Cloud (Auto-Selected Free Tier)",
            "is_running": True,
            "mode": "cloud",
            "selected_model": forced_model or os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
            "has_api_key": True,
            "auto_selected": True,
        }

    # 3. OpenAI Cloud Fallback
    if openai_key:
        return {
            "provider": "openai",
            "name": "OpenAI Cloud (Auto-Selected)",
            "is_running": True,
            "mode": "cloud",
            "selected_model": forced_model or os.getenv("OPENAI_MODEL", "gpt-4o"),
            "has_api_key": True,
            "auto_selected": True,
        }

    # Neither local AI nor cloud key found
    return {
        "provider": "none",
        "name": "No Active Model Found",
        "is_running": False,
        "mode": "none",
        "selected_model": "none",
        "message": "Neither a running local model server (Ollama/LM Studio) nor an API key (Groq/OpenAI) was found.",
    }

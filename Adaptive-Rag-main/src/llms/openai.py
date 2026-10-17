"""
Model initialization interface with local AI discovery and backward compatibility.
Seamlessly routes to local models (Ollama, LM Studio) or OpenAI Cloud.
"""

from __future__ import annotations
import os
from dotenv import load_dotenv

from src.llms.provider import (
    get_llm,
    get_embeddings,
    get_active_provider_status,
    switch_provider,
)

load_dotenv()
os.environ["OPENAI_API_KEY"] = os.getenv("OPENAI_API_KEY", "")

# Dynamically initialized LLM instance (Auto-detects local Ollama/LM Studio or OpenAI)
llm = get_llm()

__all__ = ["llm", "get_llm", "get_embeddings", "get_active_provider_status", "switch_provider"]
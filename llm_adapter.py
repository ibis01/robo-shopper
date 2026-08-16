"""Robo-Shopper V4 - LLM-agnostic adapter (Sprint 6).
One interface, any brain. Configure via env:
  LLM_PROVIDER = ollama | groq | openai | openrouter | dashscope   (default: ollama)
  LLM_MODEL    = any model the provider serves (default per provider)
  API keys: GROQ_API_KEY / OPENAI_API_KEY / OPENROUTER_API_KEY / DASHSCOPE_API_KEY
Legacy compat: QWEN_MODE=local|cloud and OLLAMA_MODEL still respected.
"""
import os
from openai import OpenAI

PROVIDERS = {
    "ollama":     {"base_url": "http://localhost:11434/v1", "api_key": "ollama",
                   "default_model": "llama3.1:8b"},
    "groq":       {"base_url": "https://api.groq.com/openai/v1", "api_key_env": "GROQ_API_KEY",
                   "default_model": "llama-3.3-70b-versatile"},
    "openai":     {"base_url": None, "api_key_env": "OPENAI_API_KEY",
                   "default_model": "gpt-4o-mini"},
    "openrouter": {"base_url": "https://openrouter.ai/api/v1", "api_key_env": "OPENROUTER_API_KEY",
                   "default_model": "meta-llama/llama-3.3-70b-instruct"},
    "dashscope":  {"base_url": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
                   "api_key_env": "DASHSCOPE_API_KEY", "default_model": "qwen-max"},
}


def provider_name() -> str:
    p = os.getenv("LLM_PROVIDER")
    if p:
        return p.lower()
    # legacy fallback so old launch commands keep working
    return "ollama" if os.getenv("QWEN_MODE", "local") == "local" else "dashscope"


def make_client():
    """Returns (client, model, provider_name)."""
    name = provider_name()
    cfg = PROVIDERS.get(name, PROVIDERS["ollama"])
    api_key = cfg.get("api_key") or os.getenv(cfg.get("api_key_env", ""), "missing-key")
    model = (os.getenv("LLM_MODEL") or os.getenv("OLLAMA_MODEL") or cfg["default_model"])
    kwargs = {"api_key": api_key}
    if cfg["base_url"]:
        kwargs["base_url"] = cfg["base_url"]
    return OpenAI(**kwargs, timeout=120.0)  # 2 minutes for complex reasoning, model, name

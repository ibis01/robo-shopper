"""
Robo-Shopper V4 - LLM-agnostic adapter (Sprint 6).
One interface, any brain. Configure via env:
  LLM_PROVIDER = ollama | groq | openai | openrouter | dashscope | deepseek | mistral | together | fireworks | perplexity | cerebras | sambanova | novita | anyscale
  LLM_MODEL    = any model the provider serves (default per provider)
  API keys: GROQ_API_KEY, OPENAI_API_KEY, OPENROUTER_API_KEY, DASHSCOPE_API_KEY, etc.
Legacy compat: QWEN_MODE=local|cloud and OLLAMA_MODEL still respected.
"""
import os
from openai import OpenAI

# --- Dynamic base URL for Ollama (respects Docker host) ---
_OLLAMA_BASE = os.getenv("OLLAMA_HOST", "http://localhost:11434") + "/v1"

# --- Provider registry ---
PROVIDERS = {
    # === LOCAL / SELF-HOSTED ===
    "ollama": {
        "base_url": _OLLAMA_BASE,
        "api_key": "ollama",  # Ollama doesn't need a real key
        "default_model": "llama3.1:8b"
    },

    # === CLOUD PROVIDERS (OpenAI-compatible) ===
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "api_key_env": "GROQ_API_KEY",
        "default_model": "llama-3.3-70b-versatile"
    },
    "openai": {
        "base_url": None,  # uses default OpenAI endpoint
        "api_key_env": "OPENAI_API_KEY",
        "default_model": "gpt-4o-mini"
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "api_key_env": "OPENROUTER_API_KEY",
        "default_model": "meta-llama/llama-3.3-70b-instruct"
    },
    "dashscope": {
        "base_url": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        "api_key_env": "DASHSCOPE_API_KEY",
        "default_model": "qwen-max"
    },

    # === NEW: DeepSeek ===
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "api_key_env": "DEEPSEEK_API_KEY",
        "default_model": "deepseek-chat"
    },

    # === NEW: Mistral AI ===
    "mistral": {
        "base_url": "https://api.mistral.ai/v1",
        "api_key_env": "MISTRAL_API_KEY",
        "default_model": "mistral-large-latest"
    },

    # === NEW: Together AI ===
    "together": {
        "base_url": "https://api.together.xyz/v1",
        "api_key_env": "TOGETHER_API_KEY",
        "default_model": "meta-llama/Llama-3.3-70B-Instruct-Turbo"
    },

    # === NEW: Fireworks AI ===
    "fireworks": {
        "base_url": "https://api.fireworks.ai/inference/v1",
        "api_key_env": "FIREWORKS_API_KEY",
        "default_model": "accounts/fireworks/models/llama-v3p3-70b-instruct"
    },

    # === NEW: Perplexity AI ===
    "perplexity": {
        "base_url": "https://api.perplexity.ai",
        "api_key_env": "PERPLEXITY_API_KEY",
        "default_model": "llama-3.1-sonar-large-128k-online"
    },

    # === NEW: Cerebras ===
    "cerebras": {
        "base_url": "https://api.cerebras.ai/v1",
        "api_key_env": "CEREBRAS_API_KEY",
        "default_model": "llama-3.3-70b"
    },

    # === NEW: SambaNova ===
    "sambanova": {
        "base_url": "https://api.sambanova.ai/v1",
        "api_key_env": "SAMBANOVA_API_KEY",
        "default_model": "Meta-Llama-3.3-70B-Instruct"
    },

    # === NEW: Novita AI ===
    "novita": {
        "base_url": "https://api.novita.ai/v3/openai",
        "api_key_env": "NOVITA_API_KEY",
        "default_model": "meta-llama/llama-3.1-8b-instruct"
    },

    # === NEW: Anyscale ===
    "anyscale": {
        "base_url": "https://api.endpoints.anyscale.com/v1",
        "api_key_env": "ANYSCALE_API_KEY",
        "default_model": "meta-llama/Llama-3.3-70B-Instruct"
    },
}


def provider_name() -> str:
    """
    Resolve the provider name from environment variables.
    Priority: LLM_PROVIDER > legacy QWEN_MODE.
    """
    p = os.getenv("LLM_PROVIDER")
    if p:
        return p.lower()
    # Legacy fallback: "local" -> ollama, "cloud" -> dashscope
    qwen_mode = os.getenv("QWEN_MODE", "local")
    return "ollama" if qwen_mode == "local" else "dashscope"


def make_client():
    """
    Returns a tuple: (OpenAI client instance, model_name, provider_name).
    
    The client is configured with:
      - base_url (if applicable)
      - api_key (from hardcoded value or environment variable)
      - timeout = 120 seconds
    """
    name = provider_name()
    cfg = PROVIDERS.get(name, PROVIDERS["ollama"])  # fallback to ollama

    # Resolve API key
    if "api_key" in cfg:
        api_key = cfg["api_key"]
    else:
        env_key = cfg.get("api_key_env", "")
        api_key = os.getenv(env_key, "missing-key")
        if api_key == "missing-key":
            print(f"⚠️  WARNING: {env_key} not set. Requests may fail.")

    # Resolve model (explicit > provider default)
    model = (
        os.getenv("LLM_MODEL") or
        os.getenv("OLLAMA_MODEL") or  # legacy
        cfg["default_model"]
    )

    # Build client kwargs
    kwargs = {
        "api_key": api_key,
        "timeout": 120.0,
        "max_retries": 2,
    }
    if cfg["base_url"]:
        kwargs["base_url"] = cfg["base_url"]

    client = OpenAI(**kwargs)
    return client, model, name


# --- Optional: quick test when run directly ---
if __name__ == "__main__":
    client, model, provider = make_client()
    print(f"🧪 Provider: {provider}")
    print(f"🧪 Model: {model}")
    print(f"🧪 Client base_url: {client.base_url}")
    print("✅ llm_adapter loaded successfully.")
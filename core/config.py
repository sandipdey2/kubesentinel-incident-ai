"""LLM configuration. The key is read from Streamlit secrets or the environment, never from code."""
from __future__ import annotations

import os

DEFAULT_BASE_URL = "https://openai.vocareum.com/v1"
MODEL = "gpt-4o-mini"
TEMPERATURE = 0


def _from_streamlit(name: str) -> str | None:
    try:
        import streamlit as st
        return st.secrets.get(name)  # raises if no secrets file exists
    except Exception:
        return None


def get_credentials() -> tuple[str | None, str]:
    key = _from_streamlit("OPENAI_API_KEY") or os.environ.get("OPENAI_API_KEY")
    base = _from_streamlit("OPENAI_API_BASE") or os.environ.get("OPENAI_API_BASE") or DEFAULT_BASE_URL
    return key, base


def get_llm(http_async_client=None):
    """Build the chat model.

    Pass ``http_async_client`` (an ``httpx.AsyncClient`` created inside the running event loop) for async use.
    Without it, langchain-openai falls back to a process-wide cached async client whose pooled connections
    stay bound to the first event loop; reusing it from a later loop raises "Event loop is closed".
    """
    from langchain_openai import ChatOpenAI
    key, base = get_credentials()
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not set (use .streamlit/secrets.toml or an environment variable).")
    extra = {"http_async_client": http_async_client} if http_async_client is not None else {}
    return ChatOpenAI(model=MODEL, temperature=TEMPERATURE, api_key=key, base_url=base, timeout=60, max_retries=2,
                      **extra)

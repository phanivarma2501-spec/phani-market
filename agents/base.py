"""
agents/base.py
Shared DeepSeek client and base agent class.
All LLM agents inherit from this.
"""

import json
from typing import Optional
from openai import OpenAI
from loguru import logger
from config.settings import settings


def create_client() -> OpenAI:
    """Create a shared DeepSeek OpenAI-compatible client."""
    return OpenAI(
        api_key=settings.DEEPSEEK_API_KEY,
        base_url=settings.DEEPSEEK_BASE_URL,
    )


# Shared client singleton
_client: Optional[OpenAI] = None


def get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = create_client()
    return _client


def call_llm(
    model: str,
    prompt: str,
    max_tokens: int = 2000,
    temperature: float = 0.3,
) -> str:
    """Make a DeepSeek API call and return raw text response."""
    client = get_client()
    response = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
    )
    return response.choices[0].message.content


def call_llm_json(
    model: str,
    prompt: str,
    max_tokens: int = 2000,
    temperature: float = 0.3,
) -> dict:
    """Make a DeepSeek API call and parse JSON from response."""
    raw = call_llm(model, prompt, max_tokens, temperature)
    return parse_json_response(raw)


def parse_json_response(raw_text: str) -> dict:
    """Parse JSON from LLM response, handling markdown fences."""
    text = raw_text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    text = text.strip().rstrip("```").strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(text[start:end])
        raise ValueError(f"Could not parse JSON from LLM response: {text[:300]}")

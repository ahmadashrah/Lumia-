"""Anthropic API wrapper for Lio."""

import os
from anthropic import Anthropic

GENERATION_MODEL = "claude-opus-4-7"
ROUTING_MODEL = "claude-haiku-4-5-20251001"

_client = None


def _get_client() -> Anthropic:
    global _client
    if _client is None:
        key = os.getenv("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY not set. Export it in your shell before running Lio."
            )
        _client = Anthropic(api_key=key)
    return _client


def generate(
    system_prompt: str,
    user_prompt: str,
    model: str = GENERATION_MODEL,
    max_tokens: int = 2500,
) -> str:
    msg = _get_client().messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )
    return "".join(block.text for block in msg.content if hasattr(block, "text"))

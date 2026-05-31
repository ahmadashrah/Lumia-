"""Gemini wrapper for image generation and editing.

Uses gemini-2.5-flash-image (Nano Banana). Same model handles both modes —
prompt-only contents → generate; prompt + image bytes → edit.

Reads GEMINI_API_KEY (falls back to GOOGLE_API_KEY) from env.
"""

import os
from typing import List, Optional, Tuple

from google import genai
from google.genai import types

IMAGE_MODEL = "gemini-2.5-flash-image"

_client = None


def _get_client():
    global _client
    if _client is None:
        key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not key:
            raise RuntimeError(
                "GEMINI_API_KEY not set. Export it in your shell before running image features."
            )
        _client = genai.Client(api_key=key)
    return _client


def _extract_images(response) -> List[Tuple[bytes, str]]:
    """Return list of (bytes, mime_type) for every inline_data part in the response."""
    images = []
    for cand in getattr(response, "candidates", []) or []:
        content = getattr(cand, "content", None)
        if not content:
            continue
        for part in getattr(content, "parts", []) or []:
            inline = getattr(part, "inline_data", None)
            if inline and getattr(inline, "data", None):
                images.append((inline.data, getattr(inline, "mime_type", "image/png")))
    return images


def _extract_text(response) -> str:
    chunks = []
    for cand in getattr(response, "candidates", []) or []:
        content = getattr(cand, "content", None)
        if not content:
            continue
        for part in getattr(content, "parts", []) or []:
            text = getattr(part, "text", None)
            if text:
                chunks.append(text)
    return "\n".join(chunks).strip()


def generate_image(prompt: str) -> dict:
    response = _get_client().models.generate_content(
        model=IMAGE_MODEL,
        contents=[prompt],
    )
    return {
        "images": _extract_images(response),
        "text": _extract_text(response),
    }


def edit_image(prompt: str, image_bytes: bytes, mime_type: str = "image/png") -> dict:
    parts = [
        prompt,
        types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
    ]
    response = _get_client().models.generate_content(
        model=IMAGE_MODEL,
        contents=parts,
    )
    return {
        "images": _extract_images(response),
        "text": _extract_text(response),
    }

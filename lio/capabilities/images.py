"""Image generation + editing via Gemini."""

from datetime import datetime
from pathlib import Path
from typing import Optional

from ..core import gemini, logger

PROJECT_ROOT = Path(__file__).resolve().parents[2]
IMAGE_DIR = PROJECT_ROOT / "static" / "lio_images"

EXT_BY_MIME = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
}


def _save_outputs(images, kind: str) -> list[dict]:
    today = datetime.now().strftime("%Y-%m-%d")
    folder = IMAGE_DIR / today
    folder.mkdir(parents=True, exist_ok=True)

    saved = []
    for idx, (data, mime) in enumerate(images):
        ext = EXT_BY_MIME.get(mime, "png")
        ts = datetime.now().strftime("%H%M%S%f")
        fname = f"{kind}_{ts}_{idx}.{ext}"
        path = folder / fname
        path.write_bytes(data)
        rel = path.relative_to(PROJECT_ROOT)
        saved.append({
            "path": str(path),
            "url": "/" + str(rel).replace("\\", "/"),
            "mime": mime,
            "bytes": len(data),
        })
    return saved


def run_generate(prompt: str) -> dict:
    if not prompt or not prompt.strip():
        raise ValueError("prompt is required")

    result = gemini.generate_image(prompt)
    saved = _save_outputs(result["images"], kind="gen")

    record = {
        "capability": "images",
        "mode": "generate",
        "timestamp": datetime.now().isoformat(),
        "input": {"prompt": prompt},
        "model_text": result["text"],
        "images": saved,
    }
    log_path = logger.log_run("images_generate", record)
    record["log_path"] = str(log_path)
    return record


def run_edit(prompt: str, image_bytes: bytes, mime_type: str = "image/png", source_filename: Optional[str] = None) -> dict:
    if not prompt or not prompt.strip():
        raise ValueError("prompt is required")
    if not image_bytes:
        raise ValueError("source image is required")

    saved_source = _save_outputs([(image_bytes, mime_type)], kind="src")[0]

    result = gemini.edit_image(prompt, image_bytes, mime_type=mime_type)
    saved = _save_outputs(result["images"], kind="edit")

    record = {
        "capability": "images",
        "mode": "edit",
        "timestamp": datetime.now().isoformat(),
        "input": {
            "prompt": prompt,
            "source_filename": source_filename,
            "source_image": saved_source,
        },
        "model_text": result["text"],
        "images": saved,
    }
    log_path = logger.log_run("images_edit", record)
    record["log_path"] = str(log_path)
    return record

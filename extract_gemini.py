#!/usr/bin/env python3
"""Gemini-backed mirror of extract.py.

Same multi-pass pipeline (extract -> critic -> conditional recrop) and same
JSON output structure, but using Gemini 2.5 Pro via google-genai.
"""
import argparse
import json
import os
import pathlib
import re
import sys
import time

from dotenv import load_dotenv
from google import genai
from google.genai import types

import pdf_utils
from prompts import SYSTEM_PROMPT, CRITIC_INSTRUCTIONS, RECROP_INSTRUCTIONS, QUADRANT_INSTRUCTIONS, MERGE_INSTRUCTIONS

MODEL = "gemini-2.5-pro"
MAX_TOKENS = 64000


def build_image_part(img_bytes):
    return types.Part.from_bytes(data=img_bytes, mime_type="image/png")


def build_config(effort):
    thinking_budget = {
        "low": 1024,
        "medium": 4096,
        "high": 16384,
        "xhigh": 24576,
        "max": -1,
    }.get(effort, -1)
    return types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        max_output_tokens=MAX_TOKENS,
        thinking_config=types.ThinkingConfig(thinking_budget=thinking_budget),
    )


def call_gemini(client, parts, effort):
    resp = client.models.generate_content(
        model=MODEL,
        contents=parts,
        config=build_config(effort),
    )
    text = resp.text or ""
    usage = resp.usage_metadata
    return text, usage


def extract_json_and_summary(text):
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*", text)
    if fence:
        rest = text[fence.end():]
        close = rest.find("```")
        if close >= 0:
            candidate = rest[:close].strip()
            try:
                obj = json.loads(candidate)
                summary = rest[close + 3:].strip()
                return obj, summary
            except json.JSONDecodeError:
                pass

    start = text.find("{")
    if start < 0:
        return None, text
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        c = text[i]
        if esc:
            esc = False
            continue
        if c == "\\":
            esc = True
            continue
        if c == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                json_str = text[start:i + 1]
                summary = text[i + 1:].strip()
                try:
                    return json.loads(json_str), summary
                except json.JSONDecodeError:
                    return None, text
    return None, text


def needs_recrop(page_json):
    if not page_json:
        return True
    if page_json.get("unresolved"):
        return True
    for m in page_json.get("measurements", []) or []:
        if (m.get("confidence") or "").lower() == "low":
            return True
    return False


def context_header(file_name, page_num, dpi):
    return f"File: {file_name}\nPage: {page_num}\nRender DPI: {dpi}"


def _instructions_block(instructions):
    if not instructions or not instructions.strip():
        return ""
    return (
        "Special instructions from the user for this document (treat as authoritative "
        "context alongside the system prompt):\n---\n"
        f"{instructions.strip()}\n"
        "---\n\n"
    )


def run_first_pass(client, img_bytes, text_layer, file_name, page_num, dpi, effort, instructions=""):
    parts = [
        build_image_part(img_bytes),
        (
            f"{context_header(file_name, page_num, dpi)}\n\n"
            f"{_instructions_block(instructions)}"
            "Text layer extracted from the PDF (may be empty for scanned PDFs or images; "
            "reconcile against the image which is authoritative for drawings):\n"
            "---\n"
            f"{text_layer}\n"
            "---\n\n"
            "Perform your extraction per the system prompt. Think through the reasoning "
            "steps silently, then output the JSON, then the human-readable summary."
        ),
    ]
    return call_gemini(client, parts, effort)


def run_critic_pass(client, img_bytes, text_layer, first_pass_text, file_name, page_num, dpi, effort, instructions=""):
    parts = [
        build_image_part(img_bytes),
        (
            f"{context_header(file_name, page_num, dpi)}\n\n"
            f"{_instructions_block(instructions)}"
            f"{CRITIC_INSTRUCTIONS}\n\n"
            "Text layer:\n---\n"
            f"{text_layer}\n"
            "---\n\n"
            "First-pass output (JSON + summary):\n---\n"
            f"{first_pass_text}\n"
            "---"
        ),
    ]
    return call_gemini(client, parts, effort)


def run_quadrant_pass(client, quad_img_bytes, text_layer, file_name, page_num, quad_label, dpi, effort):
    parts = [
        build_image_part(quad_img_bytes),
        (
            f"{context_header(file_name, page_num, dpi)}\n"
            f"Quadrant: {quad_label}\n\n"
            f"{QUADRANT_INSTRUCTIONS.replace('{quadrant_label}', quad_label)}\n\n"
            "Text layer for the FULL page (use for cross-reference; values actually visible in this quadrant should still be verified against the crop):\n"
            "---\n"
            f"{text_layer}\n"
            "---\n\n"
            "Extract per the quadrant instructions above."
        ),
    ]
    return call_gemini(client, parts, effort)


def run_merge_pass(client, full_page_bytes, quadrant_outputs, text_layer, file_name, page_num, dpi, effort):
    parts = [build_image_part(full_page_bytes)]
    header_text = (
        f"{context_header(file_name, page_num, dpi)}\n\n"
        f"{MERGE_INSTRUCTIONS}\n\n"
        "Text layer (full page):\n---\n"
        f"{text_layer}\n"
        "---\n\n"
    )
    for label, out in quadrant_outputs.items():
        header_text += f"\n===== QUADRANT {label} OUTPUT =====\n{out}\n"
    parts.append(header_text)
    return call_gemini(client, parts, effort)


def run_recrop_pass(client, hi_img_bytes, prior_text, file_name, page_num, hi_dpi, effort, instructions=""):
    parts = [
        build_image_part(hi_img_bytes),
        (
            f"{context_header(file_name, page_num, hi_dpi)}\n\n"
            f"{_instructions_block(instructions)}"
            f"{RECROP_INSTRUCTIONS}\n\n"
            "Prior pass output (JSON + notes):\n---\n"
            f"{prior_text}\n"
            "---"
        ),
    ]
    return call_gemini(client, parts, effort)


def fmt_usage(u):
    if u is None:
        return ""
    parts = []
    if getattr(u, "prompt_token_count", None) is not None:
        parts.append(f"in={u.prompt_token_count}")
    if getattr(u, "candidates_token_count", None) is not None:
        parts.append(f"out={u.candidates_token_count}")
    if getattr(u, "thoughts_token_count", None):
        parts.append(f"think={u.thoughts_token_count}")
    if getattr(u, "cached_content_token_count", None):
        parts.append(f"cache_r={u.cached_content_token_count}")
    return " ".join(parts)


def process_page_grid(client, pdf_path, page_idx, file_name, cols, rows, region_dpi, full_dpi, effort):
    page_num = page_idx + 1
    n_regions = cols * rows
    print(f"\n=== Page {page_num} ({cols}x{rows} GRID, {n_regions} regions) ===", flush=True)
    t0 = time.time()

    regions = pdf_utils.render_page_grid_bytes(pdf_path, page_idx, region_dpi, cols=cols, rows=rows, overlap=0.10)
    text_layer = pdf_utils.get_text_layer(pdf_path, page_idx)
    for label, bytes_ in regions.items():
        print(f"  rendered region {label} @ {region_dpi} DPI ({len(bytes_) // 1024} KB)", flush=True)

    region_outputs = {}
    for label in regions.keys():
        print(f"  pass {label}: extracting...", flush=True)
        text, usage = run_quadrant_pass(
            client, regions[label], text_layer, file_name, page_num, label, region_dpi, effort,
        )
        print(f"    {fmt_usage(usage)}", flush=True)
        region_outputs[label] = text

    print(f"  merge pass: rendering full page @ {full_dpi} DPI and synthesizing...", flush=True)
    full_bytes = pdf_utils.render_page_png_bytes(pdf_path, page_idx, full_dpi)
    print(f"    full-page image {len(full_bytes) // 1024} KB", flush=True)

    merged_text, merged_usage = run_merge_pass(
        client, full_bytes, region_outputs, text_layer, file_name, page_num, full_dpi, effort,
    )
    print(f"    {fmt_usage(merged_usage)}", flush=True)

    merged_json, merged_summary = extract_json_and_summary(merged_text)
    elapsed = time.time() - t0
    print(f"  done in {elapsed:.1f}s ({n_regions} regions -> merge)", flush=True)

    if merged_json is None:
        print("  WARNING: could not parse merged JSON - storing raw text", flush=True)

    return {
        "page_number": page_num,
        "passes_run": [f"region_{l}" for l in region_outputs.keys()] + ["merge"],
        "grid_cols": cols,
        "grid_rows": rows,
        "render_dpi_region": region_dpi,
        "render_dpi_merge": full_dpi,
        "extraction": merged_json,
        "summary": merged_summary,
        "region_raw_outputs": region_outputs,
        "raw_output": merged_text if merged_json is None else None,
    }


def process_page(client, pdf_path, page_idx, file_name, dpi, hi_dpi, effort, do_critic, do_recrop, instructions=""):
    page_num = page_idx + 1
    print(f"\n=== Page {page_num} ===", flush=True)

    t0 = time.time()
    img_bytes = pdf_utils.render_page_png_bytes(pdf_path, page_idx, dpi)
    text_layer = pdf_utils.get_text_layer(pdf_path, page_idx)
    print(f"  rendered {dpi} DPI ({len(img_bytes) // 1024} KB), text layer {len(text_layer)} chars", flush=True)

    print("  pass 1: extracting...", flush=True)
    first_text, first_usage = run_first_pass(
        client, img_bytes, text_layer, file_name, page_num, dpi, effort, instructions=instructions
    )
    print(f"    {fmt_usage(first_usage)}", flush=True)

    current_text = first_text
    current_json, current_summary = extract_json_and_summary(current_text)
    passes = ["extract"]

    if do_critic:
        print("  pass 2: critic reviewing...", flush=True)
        critic_text, critic_usage = run_critic_pass(
            client, img_bytes, text_layer, current_text,
            file_name, page_num, dpi, effort, instructions=instructions,
        )
        print(f"    {fmt_usage(critic_usage)}", flush=True)
        current_text = critic_text
        current_json, current_summary = extract_json_and_summary(current_text)
        passes.append("critic")

    if do_recrop and needs_recrop(current_json):
        print(f"  pass 3: recrop @ {hi_dpi} DPI (unresolved or low-confidence present)...", flush=True)
        hi_bytes = pdf_utils.render_page_png_bytes(pdf_path, page_idx, hi_dpi)
        print(f"    rendered {hi_dpi} DPI ({len(hi_bytes) // 1024} KB)", flush=True)
        recrop_text, recrop_usage = run_recrop_pass(
            client, hi_bytes, current_text, file_name, page_num, hi_dpi, effort, instructions=instructions,
        )
        print(f"    {fmt_usage(recrop_usage)}", flush=True)
        current_text = recrop_text
        current_json, current_summary = extract_json_and_summary(current_text)
        passes.append("recrop")

    elapsed = time.time() - t0
    print(f"  done in {elapsed:.1f}s ({' -> '.join(passes)})", flush=True)

    if current_json is None:
        print("  WARNING: could not parse JSON from final output - storing raw text", flush=True)

    return {
        "page_number": page_num,
        "passes_run": passes,
        "render_dpi": dpi,
        "hi_render_dpi": hi_dpi if "recrop" in passes else None,
        "extraction": current_json,
        "summary": current_summary,
        "raw_output": current_text if current_json is None else None,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Gemini-backed dimensional extraction from a PDF drawing or datasheet."
    )
    parser.add_argument("pdf", help="Path to the PDF file")
    parser.add_argument("--dpi", type=int, default=200, help="Primary render DPI (default 200)")
    parser.add_argument("--hi-dpi", type=int, default=220, help="Recrop pass DPI (default 220)")
    parser.add_argument("--pages", default=None, help="Page spec, e.g. '1-3,5'. Default: all pages.")
    parser.add_argument("--effort", default="high", choices=["low", "medium", "high", "xhigh", "max"],
                        help="Thinking effort. 'max' = unlimited thinking budget, slowest, most expensive.")
    parser.add_argument("--no-critic", action="store_true", help="Skip the critic pass")
    parser.add_argument("--no-recrop", action="store_true", help="Skip the high-DPI recrop pass")
    parser.add_argument("--instructions", default="", help="Special instructions passed to the model alongside the system prompt")
    parser.add_argument("--quadrants", action="store_true", help="Shortcut for --grid 2x2.")
    parser.add_argument("--grid", default=None, help="Grid mode: split each page into COLSxROWS overlapping regions, extract each, then merge. Examples: 2x2 (4 regions, same as --quadrants), 3x2 (6 regions), 3x3 (9 regions).")
    parser.add_argument("--quad-dpi", type=int, default=400, help="DPI for region crops in grid mode (default 400)")
    parser.add_argument("--merge-dpi", type=int, default=180, help="Full-page DPI for the merge pass in grid mode (default 180)")
    parser.add_argument("--output", default=None, help="Output JSON path (default: <pdf>.gemini.json)")
    parser.add_argument("--summary", default=None, help="Markdown summary path (default: <pdf>.gemini.md)")
    args = parser.parse_args()

    load_dotenv()
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print("ERROR: GEMINI_API_KEY (or GOOGLE_API_KEY) is not set. Run set_gemini_key.py.", file=sys.stderr)
        sys.exit(1)

    pdf_path = pathlib.Path(args.pdf).expanduser().resolve()
    if not pdf_path.exists():
        print(f"ERROR: file not found: {pdf_path}", file=sys.stderr)
        sys.exit(1)

    output_path = pathlib.Path(args.output) if args.output else pdf_path.with_suffix(pdf_path.suffix + ".gemini.json")
    summary_path = pathlib.Path(args.summary) if args.summary else pdf_path.with_suffix(pdf_path.suffix + ".gemini.md")

    total_pages = pdf_utils.page_count(str(pdf_path))
    page_indices = pdf_utils.parse_page_spec(args.pages, total_pages)
    if not page_indices:
        print("ERROR: no pages selected", file=sys.stderr)
        sys.exit(1)

    print(f"PDF: {pdf_path}")
    print(f"Pages in file: {total_pages}")
    print(f"Processing: {len(page_indices)} page(s) -> {[i + 1 for i in page_indices]}")
    print(f"Model: {MODEL}   effort={args.effort}   DPI={args.dpi} (recrop {args.hi_dpi})")
    print(f"Passes: extract" + ("" if args.no_critic else " -> critic") + ("" if args.no_recrop else " -> recrop (conditional)"))

    client = genai.Client(api_key=api_key)

    pages_output = []
    total_measurements = 0
    total_unresolved = 0

    grid_spec = None
    if args.grid:
        try:
            cols_str, rows_str = args.grid.lower().split("x")
            grid_spec = (int(cols_str), int(rows_str))
        except ValueError:
            print(f"ERROR: --grid must be like '2x2' or '3x2', got '{args.grid}'", file=sys.stderr)
            sys.exit(1)
    elif args.quadrants:
        grid_spec = (2, 2)

    for idx in page_indices:
        if grid_spec:
            cols, rows = grid_spec
            result = process_page_grid(
                client,
                str(pdf_path),
                idx,
                pdf_path.name,
                cols,
                rows,
                args.quad_dpi,
                args.merge_dpi,
                args.effort,
            )
        else:
            result = process_page(
                client,
                str(pdf_path),
                idx,
                pdf_path.name,
                args.dpi,
                args.hi_dpi,
                args.effort,
                do_critic=not args.no_critic,
                do_recrop=not args.no_recrop,
                instructions=args.instructions,
            )
        pages_output.append(result)
        if result["extraction"]:
            total_measurements += len(result["extraction"].get("measurements") or [])
            total_unresolved += len(result["extraction"].get("unresolved") or [])

        intermediate = {
            "document_totals": {
                "file_name": pdf_path.name,
                "pages_processed": len(pages_output),
                "total_measurements": total_measurements,
                "total_unresolved": total_unresolved,
            },
            "pages": pages_output,
        }
        output_path.write_text(json.dumps(intermediate, indent=2), encoding="utf-8")

    document_totals = {
        "file_name": pdf_path.name,
        "pages_processed": len(pages_output),
        "total_measurements": total_measurements,
        "total_unresolved": total_unresolved,
    }

    final = {
        "document_totals": document_totals,
        "pages": pages_output,
    }

    output_path.write_text(json.dumps(final, indent=2), encoding="utf-8")
    print(f"\nJSON written: {output_path}")

    summary_lines = [f"# Measurement Extraction Summary (Gemini) - {pdf_path.name}\n"]
    summary_lines.append(f"- Pages processed: **{document_totals['pages_processed']}**")
    summary_lines.append(f"- Total measurements extracted: **{document_totals['total_measurements']}**")
    summary_lines.append(f"- Total unresolved entries: **{document_totals['total_unresolved']}**\n")
    for p in pages_output:
        summary_lines.append(f"## Page {p['page_number']}")
        summary_lines.append(f"*Passes: {' -> '.join(p['passes_run'])}*\n")
        if p["summary"]:
            summary_lines.append(p["summary"])
        else:
            summary_lines.append("_(no summary returned)_")
        summary_lines.append("")
    summary_path.write_text("\n".join(summary_lines), encoding="utf-8")
    print(f"Summary written: {summary_path}")


if __name__ == "__main__":
    main()

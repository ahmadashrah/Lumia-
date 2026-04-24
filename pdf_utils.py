import base64
import fitz

# Anthropic caps image input at 5 MB. Leave ~7% headroom for safety.
MAX_IMAGE_BYTES = int(5 * 1024 * 1024 * 0.93)
MIN_DPI_FLOOR = 120


def page_count(pdf_path):
    with fitz.open(pdf_path) as doc:
        return len(doc)


def _render_png_at_dpi(page, dpi):
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    return pix.tobytes("png")


def _render_bounded_png(page, dpi):
    """Render page at dpi; if the PNG exceeds MAX_IMAGE_BYTES, step DPI down and retry.
    Returns (png_bytes, effective_dpi).
    """
    cur = int(dpi)
    png_bytes = _render_png_at_dpi(page, cur)
    while len(png_bytes) > MAX_IMAGE_BYTES and cur > MIN_DPI_FLOOR:
        # Scale DPI by sqrt(target / actual) — area scales with DPI^2.
        ratio = (MAX_IMAGE_BYTES / len(png_bytes)) ** 0.5
        next_dpi = max(MIN_DPI_FLOOR, int(cur * ratio * 0.97))
        if next_dpi >= cur:
            next_dpi = cur - 25
        if next_dpi < MIN_DPI_FLOOR:
            break
        cur = next_dpi
        png_bytes = _render_png_at_dpi(page, cur)
    return png_bytes, cur


def render_page_png_b64(pdf_path, page_index, dpi):
    with fitz.open(pdf_path) as doc:
        page = doc[page_index]
        png_bytes, _eff_dpi = _render_bounded_png(page, dpi)
    return base64.standard_b64encode(png_bytes).decode("utf-8"), len(png_bytes)


def render_page_png_bytes(pdf_path, page_index, dpi):
    with fitz.open(pdf_path) as doc:
        page = doc[page_index]
        png_bytes, _eff_dpi = _render_bounded_png(page, dpi)
    return png_bytes


def render_page_quadrants_bytes(pdf_path, page_index, dpi, overlap=0.10):
    """Render a page as 4 overlapping quadrants. Returns dict {TL,TR,BL,BR: png_bytes}."""
    return render_page_grid_bytes(pdf_path, page_index, dpi, cols=2, rows=2, overlap=overlap)


_ROW_LABELS_BY_ROWS = {
    1: ["M"],
    2: ["T", "B"],
    3: ["T", "M", "B"],
}
_COL_LABELS_BY_COLS = {
    1: ["C"],
    2: ["L", "R"],
    3: ["L", "C", "R"],
}


def _grid_label(row, col, rows, cols):
    r = _ROW_LABELS_BY_ROWS.get(rows, [f"R{row}"])[row] if rows in _ROW_LABELS_BY_ROWS else f"R{row}"
    c = _COL_LABELS_BY_COLS.get(cols, [f"C{col}"])[col] if cols in _COL_LABELS_BY_COLS else f"C{col}"
    return f"{r}{c}"


def render_page_grid_bytes(pdf_path, page_index, dpi, cols, rows, overlap=0.10):
    """Render a page as a cols x rows grid with per-cell overlap. Returns ordered dict {label: png_bytes}."""
    with fitz.open(pdf_path) as doc:
        page = doc[page_index]
        w, h = page.rect.width, page.rect.height
        cell_w = w / cols
        cell_h = h / rows
        ox = cell_w * overlap / 2.0
        oy = cell_h * overlap / 2.0

        zoom = dpi / 72.0
        mat = fitz.Matrix(zoom, zoom)

        out = {}
        for row in range(rows):
            for col in range(cols):
                x0 = max(0, col * cell_w - ox)
                y0 = max(0, row * cell_h - oy)
                x1 = min(w, (col + 1) * cell_w + ox)
                y1 = min(h, (row + 1) * cell_h + oy)
                rect = fitz.Rect(x0, y0, x1, y1)
                label = _grid_label(row, col, rows, cols)
                pix = page.get_pixmap(matrix=mat, clip=rect, alpha=False)
                out[label] = pix.tobytes("png")
    return out


def get_text_layer(pdf_path, page_index):
    with fitz.open(pdf_path) as doc:
        return doc[page_index].get_text("text")


def parse_page_spec(spec, total):
    if not spec:
        return list(range(total))
    pages = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            pages.update(range(int(a) - 1, int(b)))
        else:
            pages.add(int(part) - 1)
    return sorted(p for p in pages if 0 <= p < total)

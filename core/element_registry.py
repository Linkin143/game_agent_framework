# core/element_registry.py
# =============================================================================
# Universal Element Proposer + Set-of-Mark (SoM) Annotation
#
# Builds a numbered registry of EVERY tappable element on screen by fusing
# four detection sources, then draws numbered markers on the screenshot so the
# VLM can SELECT an element by number instead of estimating raw pixels.
#
#   Sources:
#     1. XML clickable bounds          (native accessibility tree)
#     2. OCR word boxes                (text buttons / labels)
#     3. CV icon detection             (Canny contours + MSER) ← finds icons
#                                       with NO text, which OCR/XML both miss
#     4. Composite merge               (label + image artwork above it → ONE
#                                       element whose center is the IMAGE)
#
#   Why this matters (the two hard cases):
#     • Small icon, no OCR text  → CV icon detection registers it anyway.
#     • Label + image, image is the clickable part → composite merge makes the
#       IMAGE center the tap point; the label text is kept only as the
#       identifier so the step text ("Tap 'MONKEY MEADOW'") can match it.
#
#   The VLM then performs SELECTION ("which number is the gear icon?") rather
#   than ESTIMATION ("what pixel is the gear icon?") — Set-of-Mark prompting,
#   which dramatically improves grounding accuracy on small targets.
#
# Pure OpenCV + NumPy — no new dependencies, no ML model files.
# =============================================================================

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import cv2
import numpy as np


# ─── Registry Element ────────────────────────────────────────────────────────

@dataclass
class UIElement:
    """A single tappable element proposal with an exact center."""
    id:      int                       # ①②③ … the Set-of-Mark number
    bbox:    tuple                     # (x1, y1, x2, y2)
    center:  tuple                     # (cx, cy) — EXACT tap point
    kind:    str                       # "xml" | "text" | "icon" | "composite"
    text:    str   = ""                # OCR/XML text ("" for pure icons)
    source:  str   = ""                # provenance string
    score:   float = 0.0               # detection confidence 0–1

    def as_dict(self) -> dict:
        return {
            "id":     self.id,
            "bbox":   list(self.bbox),
            "center": list(self.center),
            "kind":   self.kind,
            "text":   self.text,
            "source": self.source,
            "score":  round(self.score, 3),
        }


# ─── Tuning Constants ────────────────────────────────────────────────────────

_ICON_MIN_PX        = 22       # smallest icon side accepted
_ICON_MAX_PX        = 240      # largest icon side accepted (bigger = not an icon)
_ICON_ASPECT_LO     = 0.35     # w/h ratio bounds (icons are roughly square-ish)
_ICON_ASPECT_HI     = 2.8
_ICON_MIN_AREA      = 500      # px² — reject specks
_EDGE_LOW           = 60       # Canny thresholds
_EDGE_HIGH          = 180
_IOU_DEDUP          = 0.55     # boxes overlapping more than this are merged
_COMPOSITE_STD      = 18.0     # pixel std-dev above a label that means "image"
_COMPOSITE_LOOK_UP  = 200      # max px to scan above a text label for artwork
_TOP_MARGIN_IGNORE  = 0        # ignore status-bar region (set >0 to skip top px)

# Detection-kind priority when two boxes overlap (richer wins)
_KIND_RANK = {"composite": 4, "xml": 3, "icon": 2, "text": 1}

# Annotation colours (BGR)
_COL_XML       = (0, 200, 0)       # green
_COL_TEXT      = (0, 200, 255)     # amber
_COL_ICON      = (255, 120, 0)     # blue
_COL_COMPOSITE = (0, 220, 255)     # cyan
_COL_NUM_BG    = (30, 30, 30)
_COL_NUM_FG    = (255, 255, 255)


def _kind_colour(kind: str) -> tuple:
    return {
        "xml":       _COL_XML,
        "text":      _COL_TEXT,
        "icon":      _COL_ICON,
        "composite": _COL_COMPOSITE,
    }.get(kind, _COL_ICON)


# ─── IoU Helper ──────────────────────────────────────────────────────────────

def _iou(a: tuple, b: tuple) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
    inter = iw * ih
    if inter == 0:
        return 0.0
    area_a = (ax2 - ax1) * (ay2 - ay1)
    area_b = (bx2 - bx1) * (by2 - by1)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def _center(bbox: tuple) -> tuple:
    x1, y1, x2, y2 = bbox
    return ((x1 + x2) // 2, (y1 + y2) // 2)


# ─── Source 1+2: XML and OCR proposals ───────────────────────────────────────

def _from_xml(selector_map: list[dict]) -> list[UIElement]:
    out = []
    for el in (selector_map or []):
        if not el.get("clickable"):
            continue
        b = el.get("bounds") or {}
        try:
            x1, y1 = int(b.get("x1", 0)), int(b.get("y1", 0))
            x2, y2 = int(b.get("x2", 0)), int(b.get("y2", 0))
        except (TypeError, ValueError):
            continue
        if x2 <= x1 or y2 <= y1:
            continue
        out.append(UIElement(
            id=0, bbox=(x1, y1, x2, y2), center=_center((x1, y1, x2, y2)),
            kind="xml", text=(el.get("text") or el.get("acc_id") or "").strip(),
            source="xml_clickable", score=0.95,
        ))
    return out


def _from_ocr(ocr_words: list) -> list[UIElement]:
    out = []
    for w in (ocr_words or []):
        try:
            conf = float(getattr(w, "confidence", 0.0))
        except (TypeError, ValueError):
            conf = 0.0
        if conf < 0.45:
            continue
        bbox = getattr(w, "bbox", None)
        if not bbox or len(bbox) < 4:
            continue
        x1, y1, x2, y2 = int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])
        if x2 <= x1 or y2 <= y1:
            continue
        out.append(UIElement(
            id=0, bbox=(x1, y1, x2, y2), center=_center((x1, y1, x2, y2)),
            kind="text", text=(getattr(w, "text", "") or "").strip(),
            source="ocr_word", score=conf,
        ))
    return out


# ─── Source 3: CV icon detection (NO text required) ──────────────────────────

def _from_cv_icons(image_np: np.ndarray) -> list[UIElement]:
    """
    Detect icon-shaped regions using Canny edge contours + MSER blobs.

    This finds tappable graphics that have no OCR text and no XML node —
    e.g. a settings gear, a play triangle, a back arrow, a coin icon.
    """
    if image_np is None or image_np.size == 0:
        return []
    h, w = image_np.shape[:2]
    gray = cv2.cvtColor(image_np, cv2.COLOR_BGR2GRAY) if image_np.ndim == 3 else image_np
    out: list[UIElement] = []

    # --- 3a: Canny edge contours -------------------------------------------
    edges = cv2.Canny(gray, _EDGE_LOW, _EDGE_HIGH)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for c in contours:
        x, y, bw, bh = cv2.boundingRect(c)
        if _accept_icon(x, y, bw, bh, w, h):
            bbox = (x, y, x + bw, y + bh)
            out.append(UIElement(
                id=0, bbox=bbox, center=_center(bbox),
                kind="icon", text="", source="cv_canny",
                score=0.55,
            ))

    # --- 3b: MSER (flat / solid-colour icons Canny may miss) ---------------
    try:
        mser = cv2.MSER_create()
        mser.setMinArea(_ICON_MIN_AREA)
        mser.setMaxArea(int(_ICON_MAX_PX * _ICON_MAX_PX))
        regions, _ = mser.detectRegions(gray)
        for pts in regions:
            x, y, bw, bh = cv2.boundingRect(pts.reshape(-1, 1, 2))
            if _accept_icon(x, y, bw, bh, w, h):
                bbox = (x, y, x + bw, y + bh)
                out.append(UIElement(
                    id=0, bbox=bbox, center=_center(bbox),
                    kind="icon", text="", source="cv_mser",
                    score=0.50,
                ))
    except Exception:
        pass  # MSER unavailable on some cv2 builds — Canny alone still works

    return out


def _accept_icon(x: int, y: int, bw: int, bh: int, img_w: int, img_h: int) -> bool:
    """Geometry gate for icon-like blobs."""
    if y < _TOP_MARGIN_IGNORE:
        return False
    if bw < _ICON_MIN_PX or bh < _ICON_MIN_PX:
        return False
    if bw > _ICON_MAX_PX or bh > _ICON_MAX_PX:
        return False
    if bw * bh < _ICON_MIN_AREA:
        return False
    # Reject full-width bars / dividers
    if bw > img_w * 0.85 or bh > img_h * 0.5:
        return False
    aspect = bw / float(bh) if bh else 99
    if aspect < _ICON_ASPECT_LO or aspect > _ICON_ASPECT_HI:
        return False
    return True


# ─── Source 4: Composite merge (label + image above it) ──────────────────────

def _merge_composites(
    image_np: np.ndarray,
    text_elems: list[UIElement],
) -> list[UIElement]:
    """
    For each OCR text label, look at the region ABOVE it. If that region has
    high pixel variance (real image artwork, not a flat background), fuse the
    label + image into ONE composite element whose center is the IMAGE center.

    This solves "label + image card" — we tap the image, not the text label.
    """
    if image_np is None or image_np.size == 0:
        return []
    h, w = image_np.shape[:2]
    out: list[UIElement] = []

    for t in text_elems:
        x1, y1, x2, y2 = t.bbox
        word_w = x2 - x1
        if word_w < 40:
            continue
        look_up = min(_COMPOSITE_LOOK_UP, y1)
        if look_up < 40:
            continue
        region = image_np[max(0, y1 - look_up): y1, x1: x2]
        if region.size == 0:
            continue
        if float(np.std(region.astype(np.float32))) < _COMPOSITE_STD:
            continue  # flat background above label → not a card

        card_x1 = max(0, x1 - 4)
        card_y1 = max(0, y1 - look_up)
        card_x2 = min(w, x2 + 4)
        card_y2 = min(h, y2)
        # Center on the IMAGE portion (between top of artwork and top of label)
        img_cx = (card_x1 + card_x2) // 2
        img_cy = (card_y1 + y1) // 2
        out.append(UIElement(
            id=0, bbox=(card_x1, card_y1, card_x2, card_y2),
            center=(img_cx, img_cy), kind="composite",
            text=t.text, source="label+image", score=0.80,
        ))
    return out


# ─── Deduplication ───────────────────────────────────────────────────────────

def _dedup(elems: list[UIElement]) -> list[UIElement]:
    """
    Merge overlapping boxes. When two overlap (IoU > threshold), keep the one
    with the richer kind (composite > xml > icon > text); carry over any text.
    """
    # Sort so richer kinds are considered first as "keepers"
    elems = sorted(elems, key=lambda e: (-_KIND_RANK.get(e.kind, 0), -e.score))
    kept: list[UIElement] = []
    for e in elems:
        merged = False
        for k in kept:
            if _iou(e.bbox, k.bbox) > _IOU_DEDUP:
                # e is overlapping an already-kept richer element.
                # Donate text to the keeper if it lacks one.
                if not k.text and e.text:
                    k.text = e.text
                merged = True
                break
        if not merged:
            kept.append(e)
    return kept


# ─── Public API ──────────────────────────────────────────────────────────────

def propose_elements(
    image_np:     np.ndarray,
    selector_map: list[dict],
    ocr_words:    list,
    max_elements: int = 60,
) -> list[UIElement]:
    """
    Build the numbered element registry from all four detection sources.

    Returns a deduplicated list of UIElement sorted top-to-bottom,
    left-to-right, with stable ids 1..N assigned.
    """
    xml_elems  = _from_xml(selector_map)
    text_elems = _from_ocr(ocr_words)
    icon_elems = _from_cv_icons(image_np)
    comp_elems = _merge_composites(image_np, text_elems)

    # Composites supersede the bare text labels they consumed; dedup handles it.
    all_elems = comp_elems + xml_elems + icon_elems + text_elems
    deduped   = _dedup(all_elems)

    # Reading order: top-to-bottom, then left-to-right (row-banded)
    deduped.sort(key=lambda e: (e.center[1] // 40, e.center[0]))

    # Cap and assign ids
    deduped = deduped[:max_elements]
    for i, e in enumerate(deduped, start=1):
        e.id = i
    return deduped


def annotate_registry(
    image_np: np.ndarray,
    elements: list[UIElement],
) -> np.ndarray:
    """
    Draw numbered Set-of-Mark markers on a copy of the screenshot.

    Each element gets a coloured box + a numbered tag at its top-left so the
    VLM can refer to elements by number. Colour encodes the detection kind.
    """
    if image_np is None or image_np.size == 0:
        return image_np
    img = image_np.copy()
    font = cv2.FONT_HERSHEY_SIMPLEX

    for e in elements:
        x1, y1, x2, y2 = e.bbox
        col = _kind_colour(e.kind)
        cv2.rectangle(img, (x1, y1), (x2, y2), col, 2)
        # crosshair at the exact tap center
        cx, cy = e.center
        cv2.drawMarker(img, (cx, cy), col, cv2.MARKER_CROSS, markerSize=12, thickness=1)

        # numbered tag (filled badge for readability)
        tag = str(e.id)
        (tw, th), _ = cv2.getTextSize(tag, font, 0.5, 1)
        bx1, by1 = x1, max(0, y1 - th - 6)
        bx2, by2 = x1 + tw + 8, y1
        cv2.rectangle(img, (bx1, by1), (bx2, by2), _COL_NUM_BG, -1)
        cv2.putText(img, tag, (bx1 + 4, by2 - 4), font, 0.5, _COL_NUM_FG, 1, cv2.LINE_AA)

    return img


def registry_as_text(elements: list[UIElement], limit: int = 60) -> str:
    """
    Render the registry as a compact text table for the VLM prompt, e.g.:
        [01] composite  text='MONKEY MEADOW'  center=(540,470)
        [07] icon       text=''               center=(120,1850)
    """
    lines = []
    for e in elements[:limit]:
        txt = f'"{e.text}"' if e.text else "(no text)"
        lines.append(
            f"  [{e.id:02d}] {e.kind:<9} {txt:<24} center=({e.center[0]},{e.center[1]})"
        )
    return "\n".join(lines) if lines else "  (no elements detected)"

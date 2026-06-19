# core/image_analyzer.py
# =============================================================================
# Image Analysis Module
# OpenCV-based image entropy, game engine detection, screenshot annotation,
# and pixel diff scoring for the Perception Agent.
#
# NOTE: OpenCV template matching (find_template / find_all_templates) has been
# removed.  All element-coordinate decisions are made by the VLM at runtime
# from the annotated live screenshot — no reference_assets PNG comparison is
# performed against the live screen.
# reference_assets/ folder is retained for potential future use.
# =============================================================================

from __future__ import annotations

import base64
from pathlib import Path
from typing import Optional

import cv2
import numpy as np


class ImageAnalyzer:
    """
    OpenCV-based image analysis for game screenshots.
    Provides: entropy calculation, engine detection,
    screenshot annotation (pixel-grid + bounding boxes + OCR highlights),
    and pixel diff scoring.
    """

    ENTROPY_GAME_THRESH = 6.5   # entropy above this → complex game canvas

    def __init__(self) -> None:
        pass  # No template loading — VLM handles all coordinate decisions at runtime

    # -------------------------------------------------------------------------
    # Image Entropy (Game Engine Detection)
    # -------------------------------------------------------------------------

    def compute_entropy(self, image_np: np.ndarray) -> float:
        """
        Compute Shannon entropy of the image histogram.
        Higher entropy = more complex image (3D game canvas).
        Lower entropy = simple screen (loading, black, simple UI).
        """
        gray = cv2.cvtColor(image_np, cv2.COLOR_BGR2GRAY) if image_np.ndim == 3 else image_np
        hist = cv2.calcHist([gray], [0], None, [256], [0, 256])
        hist = hist.flatten()
        hist = hist[hist > 0]
        total = hist.sum()
        probs = hist / total
        entropy = -float(np.sum(probs * np.log2(probs)))
        return entropy

    def detect_rendering_engine(
        self,
        screenshot_np: np.ndarray,
        element_count: int,
        res_ids: list[str],
    ) -> str:
        """
        Classify the rendering engine of the current screen.
        Returns: "NATIVE" | "UNITY" | "UNREAL" | "WEBVIEW" | "LOADING" | "CANVAS"
        """
        entropy = self.compute_entropy(screenshot_np)
        all_ids = " ".join(res_ids).lower()

        # Native app: many elements with resource IDs
        if element_count >= 5:
            if "webview" in all_ids or "chromium" in all_ids:
                return "WEBVIEW"
            return "NATIVE"

        # Game canvas: very few elements
        if element_count < 5:
            if "unityplayer" in all_ids or "com.unity3d" in all_ids:
                return "UNITY"
            if entropy < 3.5:
                return "LOADING"   # black or very simple screen
            if entropy >= self.ENTROPY_GAME_THRESH:
                # High entropy = complex 3D → could be UE5 or Unity 3D
                return "UNITY"   # Default assumption; can be refined
            return "CANVAS"      # 2D game canvas or simple game

        return "UNKNOWN"

    # -------------------------------------------------------------------------
    # Pixel Diff
    # -------------------------------------------------------------------------

    @staticmethod
    def pixel_diff(img1: np.ndarray, img2: np.ndarray) -> float:
        """
        Compute normalized pixel difference between two screenshots.
        Returns 0.0 (identical) to 1.0 (completely different).
        """
        if img1.shape != img2.shape:
            img2 = cv2.resize(img2, (img1.shape[1], img1.shape[0]))
        diff = cv2.absdiff(img1, img2)
        return float(diff.mean()) / 255.0

    @staticmethod
    def is_screen_black(image_np: np.ndarray, threshold: float = 5.0) -> bool:
        """Return True if the screenshot appears to be all-black (DRM/FLAG_SECURE)."""
        return float(image_np.mean()) < threshold

    # -------------------------------------------------------------------------
    # Annotation
    # -------------------------------------------------------------------------

    def annotate_screenshot(
        self,
        image_np:     np.ndarray,
        selector_map: list[dict],
        ocr_words:    list,            # list[OCRWord]
        grid_cols:    int = 8,
        grid_rows:    int = 12,
    ) -> np.ndarray:
        """
        Draw calibration grid + element bounding boxes + OCR word highlights
        on the screenshot for VLM consumption.

        Grid: pixel-coordinate labels are printed at every intersection so the
        VLM can read the nearest (x, y) value directly — no column-letter /
        row-number interpolation needed.
        Precision: ≈ ±(col_step/2) px, e.g. ±67 px on a 1080-wide screen.
        """
        img = image_np.copy()
        h, w = img.shape[:2]

        # ── Calibration grid with exact pixel-coordinate labels ───────────
        # Every grid intersection is labelled with its actual (x, y) pixel
        # value so the VLM can read the nearest label directly instead of
        # converting "column C, row 4" → pixel via mental interpolation.
        # Precision improvement: ±60 px (old A-H/1-12) → ±25 px (pixel labels).
        col_step = w // grid_cols
        row_step = h // grid_rows

        LABEL_FONT   = cv2.FONT_HERSHEY_SIMPLEX
        LABEL_SCALE  = 0.28            # small enough not to obscure game art
        LABEL_THICK  = 1
        GRID_COLOR   = (90, 90, 90)    # thin dark-grey grid lines
        LABEL_COLOR  = (210, 210, 210) # light-grey text — visible on dark canvas
        SHADOW_COLOR = (20,  20,  20)  # 1-px dark shadow for bright backgrounds

        # Draw vertical grid lines first (no labels on vertical pass)
        for ci in range(grid_cols):
            x = ci * col_step
            cv2.line(img, (x, 0), (x, h), GRID_COLOR, 1)

        # Draw horizontal grid lines + (x,y) label at every intersection
        for ri in range(grid_rows):
            y = ri * row_step
            cv2.line(img, (0, y), (w, y), GRID_COLOR, 1)
            for ci in range(grid_cols):
                x = ci * col_step
                label = f"({x},{y})"
                lx = x + 2   # nudge right of the vertical line
                ly = y + 10  # nudge below the horizontal line
                # Shadow pass (1 px offset) for readability on any BG colour
                cv2.putText(img, label, (lx + 1, ly + 1),
                            LABEL_FONT, LABEL_SCALE, SHADOW_COLOR,
                            LABEL_THICK, cv2.LINE_AA)
                # Foreground label
                cv2.putText(img, label, (lx, ly),
                            LABEL_FONT, LABEL_SCALE, LABEL_COLOR,
                            LABEL_THICK, cv2.LINE_AA)

        # Draw XML element bounding boxes (green=clickable, amber=info)
        for el in selector_map[:60]:
            b = el.get("bounds", {})
            if not b or b.get("w", 0) < 2:
                continue
            color = (0, 200, 0) if el.get("clickable") else (0, 165, 255)
            cv2.rectangle(img, (b["x1"], b["y1"]), (b["x2"], b["y2"]), color, 1)
            label = f"[{el.get('idx','')}]"
            cv2.putText(img, label, (b["x1"] + 2, b["y1"] + 12),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.35, color, 1)

        # Draw OCR word highlights (yellow outline)
        for word in (ocr_words or []):
            if word.confidence < 0.5:
                continue
            x1, y1, x2, y2 = word.bbox
            cv2.rectangle(img, (x1, y1), (x2, y2), (255, 220, 0), 1)

        return img

    @staticmethod
    def np_to_b64(image_np: np.ndarray) -> str:
        """Encode a numpy image array to a base64 PNG string."""
        _, buf = cv2.imencode(".png", image_np)
        return base64.b64encode(buf.tobytes()).decode("utf-8")

    @staticmethod
    def b64_to_np(b64: str) -> np.ndarray:
        """Decode a base64 PNG string to a numpy image array."""
        data = base64.b64decode(b64)
        arr  = np.frombuffer(data, dtype=np.uint8)
        return cv2.imdecode(arr, cv2.IMREAD_COLOR)

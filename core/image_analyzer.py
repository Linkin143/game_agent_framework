# core/image_analyzer.py
# =============================================================================
# Image Analysis Module
# OpenCV-based template matching, image entropy, game engine detection,
# and annotation utilities for the Perception Agent.
# =============================================================================

from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import cv2
import numpy as np


REFERENCE_ASSETS_DIR = Path(__file__).parent.parent / "reference_assets"


@dataclass
class TemplateMatch:
    """Result of a single template matching attempt."""
    template_name: str
    found:         bool
    confidence:    float
    bbox:          dict   # {x1, y1, x2, y2, cx, cy, w, h}
    method:        str    # "TM_CCOEFF_NORMED" | "multi_scale" | "not_found"


class ImageAnalyzer:
    """
    OpenCV-based image analysis for game screenshots.
    Provides: template matching, entropy calculation, engine detection,
    screenshot annotation, and pixel diff scoring.
    """

    DEFAULT_THRESHOLD   = 0.75
    ENTROPY_GAME_THRESH = 6.5   # entropy above this → complex game canvas
    SCALES              = [0.5, 0.65, 0.8, 1.0, 1.2, 1.4]  # for multi-scale

    def __init__(
        self,
        assets_dir:  Optional[Path] = None,
        threshold:   float          = DEFAULT_THRESHOLD,
    ) -> None:
        self._assets_dir = assets_dir or REFERENCE_ASSETS_DIR
        self._threshold  = threshold
        self._templates: dict[str, np.ndarray] = {}
        self._load_templates()

    # -------------------------------------------------------------------------
    # Template Matching
    # -------------------------------------------------------------------------

    def find_template(
        self,
        screenshot_np:  np.ndarray,
        template_name:  str,
        threshold:      Optional[float] = None,
    ) -> TemplateMatch:
        """
        Find a reference template in the screenshot using multi-scale matching.
        Template files live in reference_assets/<name>.png
        """
        th = threshold or self._threshold
        template = self._get_template(template_name)
        if template is None:
            return TemplateMatch(
                template_name=template_name,
                found=False, confidence=0.0,
                bbox={}, method="no_template_file",
            )

        best_conf   = 0.0
        best_loc    = None
        best_tw, best_th = 0, 0

        gray_screen = cv2.cvtColor(screenshot_np, cv2.COLOR_BGR2GRAY)
        gray_tmpl   = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY) if template.ndim == 3 else template

        for scale in self.SCALES:
            tw = max(1, int(gray_tmpl.shape[1] * scale))
            th_ = max(1, int(gray_tmpl.shape[0] * scale))
            resized = cv2.resize(gray_tmpl, (tw, th_))

            if resized.shape[0] > gray_screen.shape[0] or resized.shape[1] > gray_screen.shape[1]:
                continue

            result = cv2.matchTemplate(gray_screen, resized, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(result)

            if max_val > best_conf:
                best_conf = max_val
                best_loc  = max_loc
                best_tw, best_th_ = tw, th_

        if best_conf >= th and best_loc is not None:
            x1 = best_loc[0]
            y1 = best_loc[1]
            x2 = x1 + best_tw
            y2 = y1 + best_th_
            cx = (x1 + x2) // 2
            cy = (y1 + y2) // 2
            return TemplateMatch(
                template_name=template_name,
                found=True,
                confidence=round(best_conf, 4),
                bbox={"x1": x1, "y1": y1, "x2": x2, "y2": y2,
                      "cx": cx, "cy": cy, "w": best_tw, "h": best_th_},
                method="multi_scale",
            )
        return TemplateMatch(
            template_name=template_name,
            found=False,
            confidence=round(best_conf, 4),
            bbox={},
            method="multi_scale_no_match",
        )

    def find_all_templates(
        self,
        screenshot_np: np.ndarray,
        threshold: Optional[float] = None,
    ) -> list[TemplateMatch]:
        """Try all templates in reference_assets/ and return matches."""
        matches = []
        for name in self._templates:
            m = self.find_template(screenshot_np, name, threshold)
            if m.found:
                matches.append(m)
        return sorted(matches, key=lambda x: x.confidence, reverse=True)

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
        Returns: "NATIVE" | "UNITY" | "UNREAL" | "WEBVIEW" | "LOADING"
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
                # Try to distinguish via image analysis
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
        """
        img = image_np.copy()
        h, w = img.shape[:2]

        # Draw calibration grid
        col_step = w // grid_cols
        row_step = h // grid_rows
        COLS = "ABCDEFGH"
        for ci in range(grid_cols):
            x = ci * col_step
            cv2.line(img, (x, 0), (x, h), (80, 80, 80), 1)
            if ci < len(COLS):
                cv2.putText(img, COLS[ci], (x + 4, 18),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.4, (80, 80, 80), 1)
        for ri in range(grid_rows):
            y = ri * row_step
            cv2.line(img, (0, y), (w, y), (80, 80, 80), 1)
            cv2.putText(img, str(ri + 1), (4, y + 14),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.35, (80, 80, 80), 1)

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

        # Draw OCR word highlights (cyan outline)
        for word in (ocr_words or []):
            if word.confidence < 0.5:
                continue
            x1, y1, x2, y2 = word.bbox
            cv2.rectangle(img, (x1, y1), (x2, y2), (255, 220, 0), 1)

        return img

    @staticmethod
    def np_to_b64(image_np: np.ndarray) -> str:
        _, buf = cv2.imencode(".png", image_np)
        return base64.b64encode(buf.tobytes()).decode("utf-8")

    @staticmethod
    def b64_to_np(b64: str) -> np.ndarray:
        data = base64.b64decode(b64)
        arr  = np.frombuffer(data, dtype=np.uint8)
        return cv2.imdecode(arr, cv2.IMREAD_COLOR)

    # -------------------------------------------------------------------------
    # Private: Template Loading
    # -------------------------------------------------------------------------

    def _load_templates(self) -> None:
        """Pre-load all PNG templates from reference_assets/ directory."""
        self._templates.clear()
        if not self._assets_dir.exists():
            return
        for png in self._assets_dir.glob("*.png"):
            img = cv2.imread(str(png))
            if img is not None:
                self._templates[png.stem] = img
        if self._templates:
            print(f"[image_analyzer] Loaded {len(self._templates)} templates: "
                  f"{list(self._templates.keys())}")

    def _get_template(self, name: str) -> Optional[np.ndarray]:
        """Get a template by name, reloading from disk if needed."""
        if name in self._templates:
            return self._templates[name]
        # Try loading from disk
        path = self._assets_dir / f"{name}.png"
        if path.exists():
            img = cv2.imread(str(path))
            if img is not None:
                self._templates[name] = img
                return img
        return None

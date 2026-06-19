# core/ocr_engine.py
# =============================================================================
# OCR Text Extraction Engine
# Uses PaddleOCR (primary), EasyOCR (fallback), or Tesseract (last resort)
# to extract all visible text from the game/app screenshot — including
# canvas-rendered text that the Android accessibility tree CANNOT see.
#
# Backend priority:
#   1. PaddleOCR  — fastest + most accurate for game UIs (CPU-only, no GPU needed)
#   2. EasyOCR    — good accuracy, larger memory footprint
#   3. Tesseract  — lightest, lowest accuracy for stylized game fonts
# =============================================================================

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from typing import Optional
import cv2
import numpy as np


@dataclass
class OCRWord:
    """A single recognized word with its spatial location."""
    text:       str
    confidence: float
    bbox:       list[int]    # [x1, y1, x2, y2]
    center:     list[int]    # [cx, cy]


@dataclass
class OCRResult:
    """Full OCR result for one screenshot."""
    words:          list[OCRWord]
    all_text:       str           # Space-joined all words
    high_conf_text: str           # Only words with confidence > 0.7
    duration_ms:    float


class OCREngine:
    """
    Multi-backend OCR engine.
    Tries PaddleOCR first (fastest + most accurate for game UIs, CPU-only).
    Falls back to EasyOCR, then pytesseract if earlier backends are unavailable.
    """

    CONFIDENCE_THRESHOLD = 0.45   # Minimum confidence to include a word
    HIGH_CONF_THRESHOLD  = 0.70   # High-confidence threshold

    def __init__(
        self,
        languages:    list[str] = None,
        use_gpu:      bool       = False,
    ) -> None:
        self._languages = languages or ["en"]
        self._use_gpu   = use_gpu
        self._reader    = None
        self._backend   = "none"
        self._init_backend()

    def _init_backend(self) -> None:
        """Initialize OCR backend — try PaddleOCR first, then EasyOCR, then Tesseract."""
        # ── Tier 1: PaddleOCR (primary) ──────────────────────────────────────
        # PaddleOCR has changed its __init__ kwargs across versions:
        #   ≥ 2.8  : device='cpu', no show_log, no use_gpu
        #   2.7.x  : device='cpu', show_log=False, no use_gpu
        #   < 2.7  : use_gpu=False, show_log=False, no device
        # We try each candidate set in order and stop on the first success.
        try:
            from paddleocr import PaddleOCR  # type: ignore
            lang = self._languages[0] if self._languages else "en"
            self._reader = PaddleOCR(lang=lang)
            self._backend = "paddleocr"
            print("[ocr_engine] Backend: PaddleOCR [OK]")
            return
        except ImportError:
            print("[ocr_engine] PaddleOCR not installed — trying EasyOCR")
        except Exception as exc:
            print(f"[ocr_engine] PaddleOCR init failed ({exc}) — trying EasyOCR")

        # ── Tier 2: EasyOCR (first fallback) ─────────────────────────────────
        try:
            import easyocr  # type: ignore
            self._reader  = easyocr.Reader(
                self._languages,
                gpu=self._use_gpu,
                verbose=False,
            )
            self._backend = "easyocr"
            print("[ocr_engine] Backend: EasyOCR [OK]")
            return
        except ImportError:
            print("[ocr_engine] EasyOCR not installed — trying pytesseract")

        # ── Tier 3: Tesseract (last resort) ──────────────────────────────────
        try:
            import pytesseract  # type: ignore
            self._reader  = pytesseract
            self._backend = "tesseract"
            print("[ocr_engine] Backend: Tesseract [OK]")
        except ImportError:
            print("[ocr_engine] WARNING: No OCR backend available.")
            print("[ocr_engine] Install primary:  pip install paddleocr paddlepaddle")
            print("[ocr_engine] Install fallback: pip install easyocr")
            self._backend = "none"

    def extract(self, image_np: np.ndarray) -> OCRResult:
        """
        Extract all visible text from the screenshot.
        Returns an OCRResult with per-word confidence and bounding boxes.
        """
        t0 = time.time()
        if self._backend == "paddleocr":
            words = self._extract_paddleocr(image_np)
        elif self._backend == "easyocr":
            words = self._extract_easyocr(image_np)
        elif self._backend == "tesseract":
            words = self._extract_tesseract(image_np)
        else:
            words = []

        # Filter by confidence threshold
        words = [w for w in words if w.confidence >= self.CONFIDENCE_THRESHOLD]

        # Sort top-to-bottom, left-to-right
        words.sort(key=lambda w: (w.center[1] // 50, w.center[0]))

        all_text       = " ".join(w.text for w in words)
        high_conf_text = " ".join(w.text for w in words if w.confidence >= self.HIGH_CONF_THRESHOLD)
        duration_ms    = (time.time() - t0) * 1000

        return OCRResult(
            words=          words,
            all_text=       all_text,
            high_conf_text= high_conf_text,
            duration_ms=    duration_ms,
        )

    def find_text(self, result: OCRResult, query: str, threshold: float = 0.6) -> Optional[OCRWord]:
        """
        Find a specific text in OCR results (case-insensitive, partial match).
        Returns the best matching OCRWord or None.
        """
        query_lower = query.lower().strip()
        best: Optional[OCRWord] = None
        best_score = 0.0

        for word in result.words:
            text_lower = word.text.lower().strip()
            # Exact match
            if text_lower == query_lower:
                score = word.confidence * 2.0
            # Contains match
            elif query_lower in text_lower or text_lower in query_lower:
                overlap = len(set(query_lower) & set(text_lower)) / max(len(query_lower), 1)
                score = word.confidence * overlap
            else:
                continue

            if score > best_score and score >= threshold:
                best_score = score
                best = word

        return best

    def find_any(self, result: OCRResult, candidates: list[str]) -> Optional[OCRWord]:
        """
        Find the first matching word from a list of candidates.
        Used to find action buttons like ["PLAY", "START", "BEGIN"].
        """
        for candidate in candidates:
            found = self.find_text(result, candidate)
            if found:
                return found
        return None

    # -------------------------------------------------------------------------
    # Private: PaddleOCR Backend
    # -------------------------------------------------------------------------

    def _extract_paddleocr(self, image_np: np.ndarray) -> list[OCRWord]:
        """
        PaddleOCR 3.x implementation.
        Uses predict() API and converts output into OCRWord objects.
        """
        try:
            result = self._reader.predict(image_np)

            words: list[OCRWord] = []

            for page in result:

                texts = page.get("rec_texts", [])
                scores = page.get("rec_scores", [])
                polys = page.get("rec_polys", [])

                for text, score, poly in zip(texts, scores, polys):

                    try:
                        poly_np = np.array(poly)

                        if poly_np.ndim != 2 or poly_np.shape[1] != 2:
                            continue

                        xs = poly_np[:, 0].astype(int)
                        ys = poly_np[:, 1].astype(int)

                        x1 = int(xs.min())
                        y1 = int(ys.min())
                        x2 = int(xs.max())
                        y2 = int(ys.max())

                        cx = (x1 + x2) // 2
                        cy = (y1 + y2) // 2

                        text_clean = str(text).strip()

                        if not text_clean:
                            continue

                        words.append(
                            OCRWord(
                                text=text_clean,
                                confidence=float(score),
                                bbox=[x1, y1, x2, y2],
                                center=[cx, cy],
                            )
                        )

                    except Exception:
                        continue

            return words

        except Exception as exc:
            print(f"[ocr_engine] PaddleOCR error: {exc}")
            return []

    # -------------------------------------------------------------------------
    # Private: EasyOCR Backend
    # -------------------------------------------------------------------------

    def _extract_easyocr(self, image_np: np.ndarray) -> list[OCRWord]:
        """Run EasyOCR on the image and return structured word list."""
        try:
            # EasyOCR expects RGB
            rgb = cv2.cvtColor(image_np, cv2.COLOR_BGR2RGB)
            raw = self._reader.readtext(rgb, detail=1, paragraph=False)
            words = []
            for (bbox_pts, text, conf) in raw:
                # bbox_pts: [[x1,y1],[x2,y1],[x2,y2],[x1,y2]]
                xs = [int(p[0]) for p in bbox_pts]
                ys = [int(p[1]) for p in bbox_pts]
                x1, y1, x2, y2 = min(xs), min(ys), max(xs), max(ys)
                cx = (x1 + x2) // 2
                cy = (y1 + y2) // 2
                text_clean = text.strip()
                if text_clean:
                    words.append(OCRWord(
                        text=       text_clean,
                        confidence= float(conf),
                        bbox=       [x1, y1, x2, y2],
                        center=     [cx, cy],
                    ))
            return words
        except Exception as exc:
            print(f"[ocr_engine] EasyOCR error: {exc}")
            return []

    # -------------------------------------------------------------------------
    # Private: Tesseract Backend
    # -------------------------------------------------------------------------

    def _extract_tesseract(self, image_np: np.ndarray) -> list[OCRWord]:
        """Run pytesseract on the image and return structured word list."""
        try:
            import pytesseract  # type: ignore
            # Pre-process: upscale + grayscale for better accuracy
            h, w = image_np.shape[:2]
            if w < 1080:
                scale = 1080 / w
                image_np = cv2.resize(image_np, None, fx=scale, fy=scale)
            gray = cv2.cvtColor(image_np, cv2.COLOR_BGR2GRAY)
            data = pytesseract.image_to_data(
                gray, output_type=pytesseract.Output.DICT,
                config="--psm 11"
            )
            words = []
            for i, text in enumerate(data["text"]):
                text = str(text).strip()
                conf = int(data["conf"][i])
                if not text or conf < 0:
                    continue
                x = int(data["left"][i])
                y = int(data["top"][i])
                w_ = int(data["width"][i])
                h_ = int(data["height"][i])
                words.append(OCRWord(
                    text=       text,
                    confidence= conf / 100.0,
                    bbox=       [x, y, x + w_, y + h_],
                    center=     [x + w_ // 2, y + h_ // 2],
                ))
            return words
        except Exception as exc:
            print(f"[ocr_engine] Tesseract error: {exc}")
            return []

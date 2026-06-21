# agents/perception_agent.py
# =============================================================================
# Perception Agent — Tri-Modal Concurrent Screen Extraction
# SENSE phase: Screenshot + XML + OCR captured simultaneously using threads.
# Returns a unified PerceptionState for all downstream agents to use.
# =============================================================================

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from agents.base_agent import BaseAgent
from core.screen_capture import ScreenCapturer, ScreenCapture
from core.ocr_engine import OCREngine, OCRResult, OCRWord
from core.xml_extractor import XMLExtractor, XMLExtractionResult
from core.image_analyzer import ImageAnalyzer
from core.element_registry import (
    propose_elements, annotate_registry, registry_as_text, UIElement,
)


@dataclass
class PerceptionState:
    """
    Unified perception snapshot from all 3 modalities.
    This is the shared data structure passed to all downstream agents.
    """
    # Metadata
    timestamp:          float
    duration_ms:        float

    # Screenshot
    screenshot_b64:     str
    screenshot_np:      Optional[np.ndarray]
    screenshot_source:  str          # "appium" | "adb" | "scrcpy" | "none"
    annotated_b64:      str          # Screenshot with grid + bboxes + OCR
    is_black_screen:    bool
    screen_w:           int
    screen_h:           int

    # XML / Accessibility
    selector_map:       list[dict]
    element_count:      int
    has_native_tree:    bool
    context:            str          # "NATIVE_APP" | "WEBVIEW"
    current_url:        str

    # OCR
    ocr_result:         Optional[OCRResult]
    all_text:           str          # All OCR words joined
    high_conf_text:     str

    # Analysis
    rendering_engine:   str          # "NATIVE" | "UNITY" | "UNREAL" | "WEBVIEW" | "CANVAS"
    animation_score:    float        # Pixel diff 0-1 (higher = more animation)
    is_stable:          bool         # True if animation_score < 0.03

    # Set-of-Mark (SoM) Element Registry
    # Numbered, deduplicated tappable proposals fused from XML + OCR + CV + composite.
    # Lets the VLM SELECT a target by number instead of estimating raw pixels.
    element_registry:     list = field(default_factory=list)   # list[UIElement]
    registry_annotated_b64: str = ""                           # SoM numbered overlay (b64)
    registry_text:        str  = ""                            # compact text table for prompt

    def get_element(self, element_id: int):
        """Return the UIElement with the given SoM id, or None."""
        for e in (self.element_registry or []):
            if getattr(e, "id", None) == element_id:
                return e
        return None

    def find_element_by_text(self, text: str):
        """
        Return the best UIElement whose text matches `text` (exact, then
        case-insensitive substring). Used for step-anchored exact targeting.
        """
        if not text:
            return None
        want = text.strip().lower()
        # Pass 1: exact case-insensitive match
        for e in (self.element_registry or []):
            if (getattr(e, "text", "") or "").strip().lower() == want:
                return e
        # Pass 2: substring match, prefer richer kind + longer overlap
        best, best_rank = None, -1.0
        for e in (self.element_registry or []):
            etext = (getattr(e, "text", "") or "").strip().lower()
            if not etext:
                continue
            if want in etext or etext in want:
                kind_rank = {"composite": 4, "xml": 3, "icon": 2, "text": 1}.get(
                    getattr(e, "kind", ""), 0)
                rank = kind_rank + min(len(etext), len(want)) / 100.0
                if rank > best_rank:
                    best, best_rank = e, rank
        return best

    def to_context_dict(self) -> dict:

        """Return a dict suitable for LLM context (no numpy arrays)."""
        ocr_words = []
        if self.ocr_result:
            ocr_words = [
                {"text": w.text, "confidence": round(w.confidence, 2),
                 "center": w.center, "bbox": w.bbox}
                for w in self.ocr_result.words
            ]
        return {
            "timestamp":         self.timestamp,
            "screenshot_source": self.screenshot_source,
            "is_black_screen":   self.is_black_screen,
            "rendering_engine":  self.rendering_engine,
            "screen_w":          self.screen_w,
            "screen_h":          self.screen_h,
            "element_count":     self.element_count,
            "has_native_tree":   self.has_native_tree,
            "context":           self.context,
            "current_url":       self.current_url,
            "selector_map":      self.selector_map[:40],
            "ocr_words":         ocr_words[:30],
            "all_text":          self.all_text[:500],
            "animation_score":   round(self.animation_score, 3),
            "is_stable":         self.is_stable,
        }


class PerceptionAgent(BaseAgent):
    """
    Captures the current mobile screen state using 3 modalities simultaneously.
    
    Architecture:
        ThreadPoolExecutor runs 3 tasks in parallel:
        1. Screenshot capture (Appium + ADB + scrcpy fallback)
        2. XML tree extraction
        3. Waits for screenshot then runs OCR
        
    After all 3 complete, an animated stillness gate checks if the screen
    has settled before returning. If not stable after 5s, returns anyway.
    """

    SKILL_FILE        = "01_perception_skill.md"
    ANIMATION_GATE_S  = 5.0     # max seconds to wait for stillness
    ANIMATION_THRESH  = 0.03    # pixel diff below this = stable
    POLL_INTERVAL     = 0.3     # seconds between animation checks

    def __init__(
        self,
        capturer:      ScreenCapturer,
        ocr_engine:    OCREngine,
        xml_extractor: XMLExtractor,
        image_analyzer: ImageAnalyzer,
        llm,
    ) -> None:
        super().__init__(llm=llm, skill_file=self.SKILL_FILE)
        self._capturer       = capturer
        self._ocr            = ocr_engine
        self._xml            = xml_extractor
        self._analyzer       = image_analyzer

    def sense(self, wait_for_stable: bool = True) -> PerceptionState:
        """
        Main entry point: capture all 3 modalities concurrently.
        Returns a unified PerceptionState.
        """
        t0 = time.time()

        # Run screenshot + XML concurrently
        screenshot: Optional[ScreenCapture] = None
        xml_result: Optional[XMLExtractionResult] = None

        with ThreadPoolExecutor(max_workers=2) as pool:
            fut_screen = pool.submit(self._capturer.capture)
            fut_xml    = pool.submit(self._xml.extract)
            screenshot = fut_screen.result()
            xml_result = fut_xml.result()

        # Run OCR on the screenshot (sequential — needs screenshot first)
        ocr_result: Optional[OCRResult] = None
        if screenshot and not screenshot.is_black and screenshot.screenshot_np is not None:
            try:
                ocr_result = self._ocr.extract(screenshot.screenshot_np)
            except Exception as exc:
                print(f"[perception_agent] OCR error: {exc}")

        # Detect rendering engine
        res_ids = [e.get("res_id", "") or "" for e in (xml_result.selector_map if xml_result else [])]
        rendering_engine = self._analyzer.detect_rendering_engine(
            screenshot.screenshot_np if screenshot else np.zeros((10, 10, 3), dtype=np.uint8),
            xml_result.element_count if xml_result else 0,
            res_ids,
        )

        # Animation stillness gate
        animation_score = 0.0
        is_stable = True
        if wait_for_stable and screenshot and not screenshot.is_black:
            animation_score, is_stable = self._wait_for_stable(screenshot)

        # Annotate screenshot for VLM
        annotated_b64 = ""
        if screenshot and screenshot.screenshot_np is not None:
            try:
                ocr_words = ocr_result.words if ocr_result else []
                annotated = self._analyzer.annotate_screenshot(
                    screenshot.screenshot_np,
                    xml_result.selector_map if xml_result else [],
                    ocr_words,
                )
                annotated_b64 = self._analyzer.np_to_b64(annotated)
            except Exception as exc:
                print(f"[perception_agent] Annotation error: {exc}")
                annotated_b64 = screenshot.screenshot_b64

        # ── Set-of-Mark Element Registry ─────────────────────────────────
        # Fuse XML + OCR + CV icon + composite proposals into a numbered
        # registry, then render a numbered SoM overlay the VLM can SELECT from.
        element_registry: list = []
        registry_annotated_b64 = ""
        registry_text = ""
        if screenshot and screenshot.screenshot_np is not None:
            try:
                ocr_words = ocr_result.words if ocr_result else []
                element_registry = propose_elements(
                    screenshot.screenshot_np,
                    xml_result.selector_map if xml_result else [],
                    ocr_words,
                )
                som_img = annotate_registry(screenshot.screenshot_np, element_registry)
                registry_annotated_b64 = self._analyzer.np_to_b64(som_img)
                registry_text = registry_as_text(element_registry)
            except Exception as exc:
                print(f"[perception_agent] Registry error: {exc}")

        state = PerceptionState(
            timestamp=         t0,
            duration_ms=       (time.time() - t0) * 1000,
            screenshot_b64=    screenshot.screenshot_b64 if screenshot else "",
            screenshot_np=     screenshot.screenshot_np if screenshot else None,
            screenshot_source= screenshot.source if screenshot else "none",
            annotated_b64=     annotated_b64,
            is_black_screen=   screenshot.is_black if screenshot else True,
            screen_w=          screenshot.width if screenshot else 1080,
            screen_h=          screenshot.height if screenshot else 2400,
            selector_map=      xml_result.selector_map if xml_result else [],
            element_count=     xml_result.element_count if xml_result else 0,
            has_native_tree=   (xml_result.has_content if xml_result else False),
            context=           xml_result.context if xml_result else "NATIVE_APP",
            current_url=       xml_result.current_url if xml_result else "",
            ocr_result=        ocr_result,
            all_text=          (ocr_result.all_text if ocr_result else ""),
            high_conf_text=    (ocr_result.high_conf_text if ocr_result else ""),
            rendering_engine=  rendering_engine,
            animation_score=   animation_score,
            is_stable=         is_stable,
            element_registry=  element_registry,
            registry_annotated_b64= registry_annotated_b64,
            registry_text=     registry_text,
        )

        self._log_state(state)
        return state

    # -------------------------------------------------------------------------
    # Private: Animation Stillness Gate
    # -------------------------------------------------------------------------

    def _wait_for_stable(
        self,
        initial_capture: ScreenCapture,
    ) -> tuple[float, bool]:
        """
        Poll until the screen stops animating or timeout.
        Returns (animation_score, is_stable).
        """
        prev_np   = initial_capture.screenshot_np
        t_start   = time.time()
        last_diff = 1.0

        while (time.time() - t_start) < self.ANIMATION_GATE_S:
            time.sleep(self.POLL_INTERVAL)
            cap = self._capturer.capture()
            if cap and cap.screenshot_np is not None:
                diff = self._analyzer.pixel_diff(prev_np, cap.screenshot_np)
                last_diff = diff
                if diff < self.ANIMATION_THRESH:
                    return diff, True   # Screen stable
                prev_np = cap.screenshot_np

        return last_diff, False   # Timed out — screen still animating (game loop)

    @staticmethod
    def _log_state(state: PerceptionState) -> None:
        engine  = state.rendering_engine
        stable  = "STABLE" if state.is_stable else f"ANIMATING({state.animation_score:.2f})"
        print(
            f"[perception] {engine} | src={state.screenshot_source} | "
            f"elements={state.element_count} | ocr_words={len(state.ocr_result.words) if state.ocr_result else 0} | "
            f"som={len(state.element_registry)} | "
            f"{stable} | {state.duration_ms:.0f}ms"
        )
        if state.all_text:
            print(f"[perception] OCR: {state.all_text[:120]}")

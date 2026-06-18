# agents/action_agent.py
# =============================================================================
# Action Agent — 3-Tier Deterministic Repair Executor
# ACT phase: Execute the DecisionPlan using 3-tier progressive repair.
# =============================================================================

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from agents.base_agent import BaseAgent
from agents.decision_agent import DecisionPlan
from agents.perception_agent import PerceptionState
from core.action_executor import ActionExecutor, ActionResult
from core.image_analyzer import ImageAnalyzer


@dataclass
class ActionReport:
    """Result of the 3-tier action execution."""
    success:      bool
    tier_used:    int                 # 1, 2, or 3
    method:       str
    coordinates:  Optional[dict]
    action_type:  str
    attempt_logs: list[str] = field(default_factory=list)
    error:        Optional[str] = None


class ActionAgent(BaseAgent):
    """
    Executes actions through a 3-tier repair matrix.

    TIER 1: Semantic element targeting (acc_id, res_id, text, UiAutomator)
    TIER 2: OCR coordinates + OpenCV template matching + fuzzy text
    TIER 3: Raw hardware coordinate tap (never fails to execute)

    The optional `game_skill` string is passed from GameSkillLoader and
    contains game-specific action hints (e.g. exact sidebar coords for
    Bloons TD6 tower placement).  It is logged per-action so the ActionAgent
    can consult it when falling back to Tier 3 coordinate overrides.
    """

    SKILL_FILE = "03_action_skill.md"

    def __init__(
        self,
        executor:       ActionExecutor,
        image_analyzer: ImageAnalyzer,
        llm,
        game_skill:     str = "",
    ) -> None:
        super().__init__(llm=llm, skill_file=self.SKILL_FILE)
        self._executor   = executor
        self._analyzer   = image_analyzer
        self._game_skill = game_skill
        if game_skill:
            print(f"[action_agent] Game-specific skill available "
                  f"({len(game_skill)} chars) — Tier 3 coords may reference game HUD layout")

    def act(
        self,
        plan:       DecisionPlan,
        perception: PerceptionState,
    ) -> ActionReport:
        """Execute the DecisionPlan through the 3-tier repair matrix."""
        at  = (plan.action_type or "tap").lower().strip()
        log = []
        print(f"[action_agent] ACT: {at} → '{plan.target_description[:60]}' "
              f"(conf={plan.confidence:.2f})")

        # ── System actions: bypass element repair tiers ───────────────────
        if at in ("activate_app", "launch_app"):
            pkg = plan.locators[0]["value"] if plan.locators else ""
            r = self._executor.activate_app(pkg)
            return ActionReport(success=r.success, tier_used=0, method="activate_app",
                                coordinates=None, action_type=at, attempt_logs=[str(r)])

        if at in ("back", "navigate_back"):
            r = self._executor.press_back()
            return ActionReport(success=r.success, tier_used=0, method="back",
                                coordinates=None, action_type=at)

        if at in ("wait", "sleep", "pause"):
            try:
                dur = float(plan.type_payload or "2.0")
            except ValueError:
                dur = 2.0
            self._executor.wait(dur)
            return ActionReport(success=True, tier_used=0, method=f"wait({dur}s)",
                                coordinates=None, action_type=at)

        if at in ("swipe", "scroll"):
            direction = plan.target_description.lower()
            for d in ["up", "down", "left", "right"]:
                if d in direction:
                    r = self._executor.swipe(d, perception.screen_w, perception.screen_h)
                    return ActionReport(success=r.success, tier_used=0, method=f"swipe_{d}",
                                        coordinates=None, action_type=at)
            r = self._executor.swipe("up", perception.screen_w, perception.screen_h)
            return ActionReport(success=r.success, tier_used=0, method="swipe_up",
                                coordinates=None, action_type=at)

        # ── Long Press / Hold ─────────────────────────────────────────────
        # action_type: "long_press" | "hold" | "hold_press"
        # locators   : position (ocr_center or coords)
        # type_payload: duration in ms (default 1000)
        if at in ("long_press", "hold", "hold_press"):
            cx, cy = self._extract_primary_coords(plan, perception)
            try:
                dur_ms = int(float(plan.type_payload or "1000"))
            except ValueError:
                dur_ms = 1000
            r = self._executor.long_press_at(cx, cy, dur_ms)
            log.append(f"LONG_PRESS ({cx},{cy}) {dur_ms}ms → {'OK' if r.success else r.error}")
            return ActionReport(success=r.success, tier_used=2, method=r.method,
                                coordinates=r.coordinates, action_type=at, attempt_logs=log)

        # ── Double Tap ────────────────────────────────────────────────────
        # action_type: "double_tap" | "doubletap" | "double_click"
        # locators   : position (ocr_center or coords)
        if at in ("double_tap", "doubletap", "double_click"):
            cx, cy = self._extract_primary_coords(plan, perception)
            r = self._executor.double_tap_at(cx, cy)
            log.append(f"DOUBLE_TAP ({cx},{cy}) → {'OK' if r.success else r.error}")
            return ActionReport(success=r.success, tier_used=2, method=r.method,
                                coordinates=r.coordinates, action_type=at, attempt_logs=log)

        # ── Drag and Drop ─────────────────────────────────────────────────
        # action_type: "drag" | "drag_and_drop" | "drag_drop" | "tower_place" | "place"
        # start coords: from locators (ocr_center/coords) — the element to grab
        # end coords  : from type_payload "endX,endY" OR fallback_bounds center
        #
        # Bloons TD6 example:
        #   action_type: "drag_and_drop"
        #   locators: [{"type": "ocr_center", "value": "1015,420"}]  ← tower icon
        #   type_payload: "400,800"                                   ← map drop zone
        if at in ("drag", "drag_and_drop", "drag_drop", "tower_place", "place"):
            start_x, start_y = self._extract_primary_coords(plan, perception)
            end_x, end_y = self._extract_end_coords(plan, perception, start_x, start_y)
            try:
                dur_ms = int(float(plan.type_payload.split(",")[0])) if plan.type_payload and not "," in plan.type_payload else 1200
            except ValueError:
                dur_ms = 1200
            print(f"[action_agent] DRAG ({start_x},{start_y}) → ({end_x},{end_y}) dur={dur_ms}ms")
            r = self._executor.drag_and_drop(start_x, start_y, end_x, end_y, duration_ms=dur_ms)
            log.append(f"DRAG ({start_x},{start_y})→({end_x},{end_y}) → {'OK' if r.success else r.error}")
            return ActionReport(success=r.success, tier_used=2, method=r.method,
                                coordinates=r.coordinates, action_type=at, attempt_logs=log)

        # ── Swipe with explicit coordinates ───────────────────────────────
        # action_type: "swipe_coords" | "swipe_to" | "scroll_to" | "fling"
        # type_payload: "startX,startY,endX,endY"
        #
        # Bloons TD6 sidebar scroll example:
        #   action_type: "swipe_coords"
        #   type_payload: "1015,1800,1015,400"   ← scroll sidebar up
        if at in ("swipe_coords", "swipe_to", "scroll_to", "fling"):
            parts = [p.strip() for p in (plan.type_payload or "").split(",")]
            if len(parts) >= 4:
                try:
                    sx, sy, ex, ey = int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
                    r = self._executor.swipe_from_to(sx, sy, ex, ey)
                    log.append(f"SWIPE_COORDS ({sx},{sy})→({ex},{ey}) → {'OK' if r.success else r.error}")
                    return ActionReport(success=r.success, tier_used=2, method=r.method,
                                        coordinates=r.coordinates, action_type=at, attempt_logs=log)
                except ValueError:
                    pass
            # Fallback: directional swipe from target description
            direction = plan.target_description.lower()
            for d in ["up", "down", "left", "right"]:
                if d in direction:
                    r = self._executor.swipe(d, perception.screen_w, perception.screen_h)
                    return ActionReport(success=r.success, tier_used=2, method=f"swipe_{d}_fallback",
                                        coordinates=None, action_type=at, attempt_logs=log)
            r = self._executor.swipe("up", perception.screen_w, perception.screen_h)
            return ActionReport(success=r.success, tier_used=2, method="swipe_fallback",
                                coordinates=None, action_type=at, attempt_logs=log)

        # ── Pinch / Zoom ──────────────────────────────────────────────────
        # action_type: "pinch" | "pinch_zoom" | "zoom" | "zoom_in" | "zoom_out"
        # type_payload: scale factor  (0.5 = zoom out 50%, 2.0 = zoom in 200%)
        #               If not provided: zoom_in → 2.0, zoom_out/pinch → 0.5
        # fallback_bounds: zoom center (optional; defaults to screen center)
        if at in ("pinch", "pinch_zoom", "zoom", "zoom_in", "zoom_out"):
            fb = plan.fallback_bounds
            cx = (fb.get("cx") or perception.screen_w // 2) if fb else perception.screen_w // 2
            cy = (fb.get("cy") or perception.screen_h // 2) if fb else perception.screen_h // 2
            default_scale = 2.0 if "in" in at else 0.5
            try:
                scale = float(plan.type_payload or str(default_scale))
            except ValueError:
                scale = default_scale
            r = self._executor.pinch_zoom(cx, cy, scale)
            log.append(f"PINCH_ZOOM center=({cx},{cy}) scale={scale} → {'OK' if r.success else r.error}")
            return ActionReport(success=r.success, tier_used=2, method=r.method,
                                coordinates=r.coordinates, action_type=at, attempt_logs=log)

        # ── TIER 1: Semantic element locators ─────────────────────────────
        log.append("── TIER 1: Semantic Element Locators ──")
        tried = set()
        for loc in plan.locators:
            lt = (loc.get("type") or "").lower()
            lv = (loc.get("value") or "").strip()
            if not lv or lv in tried or lt in ("ocr_center", "coords", "template"):
                continue
            tried.add(lv)
            r = self._try_locator(lt, lv)
            log.append(f"T1 [{lt}] '{lv[:40]}' → {'OK' if r.success else r.error}")
            if r.success:
                return ActionReport(success=True, tier_used=1, method=r.method,
                                    coordinates=r.coordinates, action_type=at, attempt_logs=log)

        log.append("T1 exhausted → TIER 2")

        # ── TIER 2: OCR coords + template matching + fuzzy ────────────────
        log.append("── TIER 2: OCR Coords + Template + Fuzzy ──")

        # 2a: OCR center coordinates
        for loc in plan.locators:
            lt = (loc.get("type") or "").lower()
            lv = (loc.get("value") or "").strip()
            if lt == "ocr_center" and lv:
                parts = [p.strip() for p in lv.split(",")]
                if len(parts) >= 2:
                    try:
                        cx, cy = int(parts[0]), int(parts[1])
                        r = self._executor.tap_at(cx, cy)
                        log.append(f"T2 [ocr_center] ({cx},{cy}) → {'OK' if r.success else r.error}")
                        if r.success:
                            return ActionReport(success=True, tier_used=2, method="ocr_center",
                                                coordinates={"x": cx, "y": cy}, action_type=at,
                                                attempt_logs=log)
                    except ValueError:
                        pass

        # 2b: OpenCV template matching
        if plan.template_name and perception.screenshot_np is not None:
            match = self._analyzer.find_template(perception.screenshot_np, plan.template_name)
            if match.found:
                cx, cy = match.bbox["cx"], match.bbox["cy"]
                r = self._executor.tap_at(cx, cy)
                log.append(f"T2 [template:{plan.template_name}] conf={match.confidence:.2f} "
                            f"({cx},{cy}) → {'OK' if r.success else r.error}")
                if r.success:
                    return ActionReport(success=True, tier_used=2, method=f"template:{plan.template_name}",
                                        coordinates={"x": cx, "y": cy}, action_type=at, attempt_logs=log)

        # 2c: Try all templates automatically
        if perception.screenshot_np is not None:
            for tmatch in self._analyzer.find_all_templates(perception.screenshot_np):
                kw = plan.target_description.lower()
                if any(k in tmatch.template_name.lower() for k in kw.split()[:3]):
                    cx, cy = tmatch.bbox["cx"], tmatch.bbox["cy"]
                    r = self._executor.tap_at(cx, cy)
                    log.append(f"T2 [auto_template:{tmatch.template_name}] ({cx},{cy}) → OK")
                    if r.success:
                        return ActionReport(success=True, tier_used=2,
                                            method=f"auto_template:{tmatch.template_name}",
                                            coordinates={"x": cx, "y": cy}, action_type=at,
                                            attempt_logs=log)

        # 2d: Fuzzy text/desc match via UiAutomator
        hint = plan.target_description.split()[0][:20] if plan.target_description else ""
        if hint:
            r = self._executor.tap_text_contains(hint)
            log.append(f"T2 [textContains:{hint}] → {'OK' if r.success else r.error}")
            if r.success:
                return ActionReport(success=True, tier_used=2, method="textContains",
                                    coordinates=None, action_type=at, attempt_logs=log)

        log.append("T2 exhausted → TIER 3")

        # ── TIER 3: Raw hardware coordinate tap ───────────────────────────
        log.append("── TIER 3: Hardware Coordinate Override ──")

        coord_sources = []
        fb = plan.fallback_bounds
        if fb:
            cx = fb.get("cx") or (fb.get("x1", 0) + (fb.get("x2", 0) - fb.get("x1", 0)) // 2)
            cy = fb.get("cy") or (fb.get("y1", 0) + (fb.get("y2", 0) - fb.get("y1", 0)) // 2)
            coord_sources.append((cx, cy, "fallback_bounds"))

        for loc in plan.locators:
            lt = (loc.get("type") or "").lower()
            lv = (loc.get("value") or "").strip()
            if lt == "coords" and lv:
                parts = [p.strip() for p in lv.split(",")]
                if len(parts) >= 2:
                    try:
                        coord_sources.append((int(parts[0]), int(parts[1]), "coords_locator"))
                    except ValueError:
                        pass

        # Screen center as last resort
        coord_sources.append((perception.screen_w // 2, perception.screen_h // 2, "screen_center"))

        tried_coords: set = set()
        for cx, cy, label in coord_sources:
            if (cx, cy) in tried_coords or cx <= 0 or cy <= 0:
                continue
            tried_coords.add((cx, cy))
            r = self._executor.tap_at(cx, cy)
            log.append(f"T3 [{label}] ({cx},{cy}) → {'OK' if r.success else r.error}")
            if r.success:
                return ActionReport(success=True, tier_used=3, method=f"T3:{label}",
                                    coordinates={"x": cx, "y": cy}, action_type=at, attempt_logs=log)

        # This should NEVER happen — tap_at always executes
        log.append("T3 coordinate tap failed (unexpected)")
        return ActionReport(success=False, tier_used=3, method="all_failed",
                            coordinates=None, action_type=at, attempt_logs=log,
                            error="All 3 tiers exhausted")

    # -------------------------------------------------------------------------
    # Private: Locator Router
    # -------------------------------------------------------------------------

    def _try_locator(self, lt: str, lv: str) -> ActionResult:
        if lt == "accessibility_id":
            return self._executor.tap_by_accessibility_id(lv)
        if lt == "resource_id":
            return self._executor.tap_by_id(lv)
        if lt == "text":
            return self._executor.tap_by_text(lv)
        if lt == "xpath":
            return self._executor.tap_by_xpath(lv)
        if lt == "uiautomator":
            return self._executor.tap_by_uiautomator(lv)
        return ActionResult(success=False, method=lt, error=f"Unknown locator type: {lt}")

    # -------------------------------------------------------------------------
    # Private: Coordinate Extraction Helpers
    # -------------------------------------------------------------------------

    @staticmethod
    def _extract_primary_coords(
        plan:       DecisionPlan,
        perception: PerceptionState,
    ) -> tuple[int, int]:
        """
        Extract primary (start / target) coordinates from plan.
        Priority: ocr_center locator → coords locator → fallback_bounds center → screen center.
        Used by long_press, double_tap, and drag_and_drop (start position).
        """
        for loc in plan.locators:
            lt = (loc.get("type") or "").lower()
            lv = (loc.get("value") or "").strip()
            if lt in ("ocr_center", "coords") and lv:
                parts = [p.strip() for p in lv.split(",")]
                if len(parts) >= 2:
                    try:
                        return int(parts[0]), int(parts[1])
                    except ValueError:
                        pass

        fb = plan.fallback_bounds
        if fb:
            cx = fb.get("cx") or (fb.get("x1", 0) + (fb.get("x2", 0) - fb.get("x1", 0)) // 2)
            cy = fb.get("cy") or (fb.get("y1", 0) + (fb.get("y2", 0) - fb.get("y1", 0)) // 2)
            if cx and cy:
                return int(cx), int(cy)

        return perception.screen_w // 2, perception.screen_h // 2

    @staticmethod
    def _extract_end_coords(
        plan:       DecisionPlan,
        perception: PerceptionState,
        default_x:  int,
        default_y:  int,
    ) -> tuple[int, int]:
        """
        Extract end (drop target) coordinates for drag_and_drop.
        Priority: type_payload "endX,endY" → fallback_bounds center (if different from start).

        Convention: VLM sets type_payload="endX,endY" for drag target,
        and locators contain the START element (tower icon, slider handle, etc.)
        """
        # type_payload = "endX,endY"
        if plan.type_payload:
            parts = [p.strip() for p in plan.type_payload.split(",")]
            if len(parts) >= 2:
                try:
                    ex, ey = int(parts[0]), int(parts[1])
                    if ex > 0 and ey > 0:
                        return ex, ey
                except ValueError:
                    pass

        # fallback_bounds as drop target (only if meaningfully different from start)
        fb = plan.fallback_bounds
        if fb:
            cx = fb.get("cx") or (fb.get("x1", 0) + (fb.get("x2", 0) - fb.get("x1", 0)) // 2)
            cy = fb.get("cy") or (fb.get("y1", 0) + (fb.get("y2", 0) - fb.get("y1", 0)) // 2)
            if cx and cy and (abs(int(cx) - default_x) > 20 or abs(int(cy) - default_y) > 20):
                return int(cx), int(cy)

        # Nudge default downward as last resort (prevents zero-distance drag)
        return default_x, min(default_y + 400, perception.screen_h - 50)

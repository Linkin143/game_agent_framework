# agents/action_agent.py
# =============================================================================
# Action Agent — VLM-First 3-Tier Repair Executor
# ACT phase: Execute the DecisionPlan using 3-tier progressive repair.
#
# DESIGN PRINCIPLE — All coordinates come from the VLM:
# ──────────────────────────────────────────────────────
# Every coordinate that reaches the device hardware originates from the VLM's
# DecisionPlan (plan.locators, plan.fallback_bounds, plan.type_payload) or
# from a targeted VLM re-ask call made when all plan coordinates are exhausted.
#
# Removed intentionally:
#   • Tier 2c (auto-template scan) — OpenCV picked coords without VLM visual
#     confirmation; coordinates came from filename keyword matching, not from
#     the VLM seeing where the element actually is on the live screen.
#   • Screen-center last resort — tapping (screen_w/2, screen_h/2) blindly is
#     actively harmful on game canvases (Unity/Unreal) where it may accidentally
#     select a tower, open an upgrade panel, or do nothing useful.
#   • Drag-end +400 nudge — silently dragged to a wrong location when VLM
#     provided no drop target.
#
# Instead, when all VLM-provided coordinates are exhausted:
#   → Make one targeted VLM re-ask (fresh screenshot + target description)
#   → If VLM still cannot locate the element → return success=False
#   → Caller (GameplayAgent / orchestrator) re-senses on the next tick
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
    tier_used:    int                 # 0=system, 1=semantic, 2=ocr/template, 3=coords/reask
    method:       str
    coordinates:  Optional[dict]
    action_type:  str
    attempt_logs: list[str] = field(default_factory=list)
    error:        Optional[str] = None


class ActionAgent(BaseAgent):
    """
    Executes VLM DecisionPlans through a 3-tier repair matrix.

    TIER 1: Semantic element targeting (acc_id, res_id, text, UiAutomator)
            → uses VLM's plan.locators (non-coordinate types)

    TIER 2: OCR coordinates + named OpenCV template + fuzzy text
            → uses VLM's plan.locators[ocr_center], plan.template_name,
              plan.target_description

    TIER 3: VLM-provided bounding box / coords → VLM re-ask (fresh screenshot)
            → uses plan.fallback_bounds, plan.locators[coords]
            → if all empty: targeted VLM re-ask for coordinates
            → if re-ask fails: return success=False (caller retries next tick)

    All coordinates that reach the device originate from VLM decisions.
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
            print(f"[action_agent] Game-specific skill loaded ({len(game_skill)} chars)")

    # =========================================================================
    # Public — act()
    # =========================================================================

    def act(
        self,
        plan:       DecisionPlan,
        perception: PerceptionState,
    ) -> ActionReport:
        """Execute the DecisionPlan through the 3-tier VLM-driven repair matrix."""
        at  = (plan.action_type or "tap").lower().strip()
        log = []
        print(f"[action_agent] ACT: {at} → '{plan.target_description[:60]}' "
              f"(conf={plan.confidence:.2f})")

        # ── System actions: no element repair needed ──────────────────────
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
            # Dynamic duration: VLM extracts from step text (e.g. "wait for 40 seconds")
            # or from OCR loading detection (default 3.0s).
            # type_payload is a plain string number set by the decision agent.
            try:
                dur = float(plan.type_payload or "2.0")
            except ValueError:
                dur = 2.0
            # Clamp to safe bounds: 0.5 s minimum, 120 s maximum
            dur = max(0.5, min(dur, 120.0))
            reason = plan.target_description or plan.reasoning or "loading/wait"
            print(f"[action_agent] ⏳ WAIT {dur}s — {reason[:80]}")
            self._executor.wait(dur)
            return ActionReport(
                success=True, tier_used=0, method=f"wait({dur}s)",
                coordinates=None, action_type=at,
                attempt_logs=[f"Waited {dur}s — {reason[:80]}"],
            )

        # ── Verify / Confirm ─────────────────────────────────────────────
        # VLM chose to visually verify the current screen state — no hardware
        # action is needed.  Return success=True so VerificationAgent knows
        # the VLM examined the screen and confirmed the stated condition.
        # VerificationAgent._verify_step() checks action_type=="verify" first
        # and accepts this as proof — no OCR token matching required.
        if at in ("verify", "confirm", "assert", "check_state", "check"):
            print(f"[action_agent] VLM visual verify: "
                  f"'{plan.target_description[:60]}' conf={plan.confidence:.2f}")
            return ActionReport(success=True, tier_used=0, method="vlm_verify",
                                coordinates=None, action_type=at)

        if at in ("swipe", "scroll"):
            direction = plan.target_description.lower()
            for d in ["up", "down", "left", "right"]:
                if d in direction:
                    r = self._executor.swipe(d, perception.screen_w, perception.screen_h)
                    return ActionReport(success=r.success, tier_used=0, method=f"swipe_{d}",
                                        coordinates=None, action_type=at)
            # Direction not found in VLM's description — log and fail cleanly
            log.append("swipe: no direction found in VLM target_description")
            print(f"[action_agent] swipe: cannot determine direction from "
                  f"'{plan.target_description[:40]}' — returning failure")
            return ActionReport(success=False, tier_used=0, method="swipe_no_direction",
                                coordinates=None, action_type=at, attempt_logs=log,
                                error="No direction in VLM target_description")

        # ── Long Press / Hold ─────────────────────────────────────────────
        # action_type: "long_press" | "hold" | "hold_press"
        # locators   : position (ocr_center or coords)
        # type_payload: duration in ms (default 1000)
        if at in ("long_press", "hold", "hold_press"):
            cx, cy = self._extract_primary_coords(plan)
            if cx == 0 and cy == 0:
                log.append("long_press: no VLM coordinates — returning failure")
                return ActionReport(success=False, tier_used=0, method="long_press_no_coords",
                                    coordinates=None, action_type=at, attempt_logs=log,
                                    error="VLM provided no coordinates for long_press")
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
            cx, cy = self._extract_primary_coords(plan)
            if cx == 0 and cy == 0:
                log.append("double_tap: no VLM coordinates — returning failure")
                return ActionReport(success=False, tier_used=0, method="double_tap_no_coords",
                                    coordinates=None, action_type=at, attempt_logs=log,
                                    error="VLM provided no coordinates for double_tap")
            r = self._executor.double_tap_at(cx, cy)
            log.append(f"DOUBLE_TAP ({cx},{cy}) → {'OK' if r.success else r.error}")
            return ActionReport(success=r.success, tier_used=2, method=r.method,
                                coordinates=r.coordinates, action_type=at, attempt_logs=log)

        # ── Drag and Drop ─────────────────────────────────────────────────
        # action_type: "drag" | "drag_and_drop" | "drag_drop" | "tower_place" | "place"
        #
        # Convention (from gameplay guide + VLM):
        #   locators    → [{"type": "ocr_center", "value": "X,Y"}]  ← DRAG START (tower icon)
        #   type_payload → "endX,endY"                               ← DRAG END (drop target)
        #   fallback_bounds → {"cx": endX, "cy": endY}              ← backup drop target
        #
        # All coordinates must come from VLM's plan.
        # If VLM provided no end coordinates → return failure (VLM re-ask via next tick).
        if at in ("drag", "drag_and_drop", "drag_drop", "tower_place", "place"):
            start_x, start_y = self._extract_primary_coords(plan)
            end_x, end_y     = self._extract_end_coords(plan, start_x, start_y)

            # Guard: no valid start coordinates
            if start_x == 0 and start_y == 0:
                log.append("drag_and_drop: no VLM start coordinates — aborted")
                print("[action_agent] drag_and_drop aborted: no start coords from VLM")
                return ActionReport(success=False, tier_used=0, method="drag_aborted_no_start",
                                    coordinates=None, action_type=at, attempt_logs=log,
                                    error="VLM provided no drag start coordinates")

            # Guard: no valid end coordinates (0,0 sentinel from _extract_end_coords)
            if end_x == 0 and end_y == 0:
                log.append("drag_and_drop: no VLM end coordinates — aborted")
                print("[action_agent] drag_and_drop aborted: no end coords from VLM "
                      f"(type_payload='{plan.type_payload}' "
                      f"fallback_bounds={plan.fallback_bounds})")
                return ActionReport(success=False, tier_used=0, method="drag_aborted_no_end",
                                    coordinates=None, action_type=at, attempt_logs=log,
                                    error="VLM provided no drag end coordinates. "
                                          "Set type_payload='endX,endY' in the action plan.")

            # Fixed duration — always 1200ms for reliable drag gestures
            dur_ms = 1200
            print(f"[action_agent] DRAG ({start_x},{start_y}) → ({end_x},{end_y}) dur={dur_ms}ms")
            r = self._executor.drag_and_drop(start_x, start_y, end_x, end_y, duration_ms=dur_ms)
            log.append(f"DRAG ({start_x},{start_y})→({end_x},{end_y}) → {'OK' if r.success else r.error}")
            return ActionReport(success=r.success, tier_used=2, method=r.method,
                                coordinates=r.coordinates, action_type=at, attempt_logs=log)

        # ── Swipe with explicit coordinates ───────────────────────────────
        # action_type: "swipe_coords" | "swipe_to" | "scroll_to" | "fling"
        # type_payload: "startX,startY,endX,endY"  ← all 4 from VLM
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
            # Fallback: directional swipe from VLM's target_description
            direction = plan.target_description.lower()
            for d in ["up", "down", "left", "right"]:
                if d in direction:
                    r = self._executor.swipe(d, perception.screen_w, perception.screen_h)
                    return ActionReport(success=r.success, tier_used=2, method=f"swipe_{d}_fallback",
                                        coordinates=None, action_type=at, attempt_logs=log)
            # VLM gave neither valid type_payload nor direction — fail cleanly
            log.append("swipe_coords: no valid coords in type_payload and no direction in description")
            return ActionReport(success=False, tier_used=0, method="swipe_coords_no_data",
                                coordinates=None, action_type=at, attempt_logs=log,
                                error="VLM provided no valid swipe coordinates")

        # ── Pinch / Zoom ──────────────────────────────────────────────────
        # action_type: "pinch" | "pinch_zoom" | "zoom" | "zoom_in" | "zoom_out"
        # type_payload: scale factor (0.5 = zoom out, 2.0 = zoom in)
        # fallback_bounds: zoom center (optional)
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

        # ── TIER 1: Semantic element locators (VLM-provided) ─────────────
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

        # ── TIER 2: OCR coords + named template + fuzzy text ─────────────
        log.append("── TIER 2: OCR Coords + Named Template + Fuzzy ──")

        # 2a: OCR center coordinates from VLM's locators
        #
        # ── OFFSET FIX: ocr_center = text label center ≠ element visual center ──
        # EasyOCR returns the bounding box of the TEXT (e.g., "Monkey Meadow" label
        # at the bottom of a map thumbnail). For image thumbnails and icon tiles,
        # the text label sits 40-80px BELOW the actual visual element center.
        # Tapping the OCR label center lands on the label row, not the tile image.
        #
        # Rule:
        #   • fallback_bounds height > 50px AND width > 50px
        #     → element is an image thumbnail / large icon
        #     → use fallback_bounds cx/cy (covers full element) NOT raw ocr text center
        #   • fallback_bounds absent or tiny (text-only button like "PLAY")
        #     → use ocr_center as-is (correct for pure text buttons)
        for loc in plan.locators:
            lt = (loc.get("type") or "").lower()
            lv = (loc.get("value") or "").strip()
            if lt == "ocr_center" and lv:
                parts = [p.strip() for p in lv.split(",")]
                if len(parts) >= 2:
                    try:
                        ocr_cx, ocr_cy = int(parts[0]), int(parts[1])

                        # Check if fallback_bounds covers a large visual element
                        fb   = plan.fallback_bounds
                        cx, cy = ocr_cx, ocr_cy   # default: use raw OCR position
                        if fb:
                            fb_w = (fb.get("x2", 0) or 0) - (fb.get("x1", 0) or 0)
                            fb_h = (fb.get("y2", 0) or 0) - (fb.get("y1", 0) or 0)
                            if fb_w > 50 and fb_h > 50:
                                # Large element: bounds center is the visual tile center
                                cx = int(fb.get("cx") or (fb.get("x1", 0) + fb_w // 2))
                                cy = int(fb.get("cy") or (fb.get("y1", 0) + fb_h // 2))
                                log.append(
                                    f"T2 [ocr_center→bounds_center] "
                                    f"element {fb_w}×{fb_h}px → bounds center ({cx},{cy}) "
                                    f"overrides OCR label ({ocr_cx},{ocr_cy})"
                                )
                            else:
                                log.append(
                                    f"T2 [ocr_center] text-only element "
                                    f"({fb_w}×{fb_h}px) → using OCR label ({cx},{cy})"
                                )
                        else:
                            log.append(f"T2 [ocr_center] no fallback_bounds → using ({cx},{cy})")

                        r = self._executor.tap_at(cx, cy)
                        log.append(f"T2 [ocr_center] tap ({cx},{cy}) → {'OK' if r.success else r.error}")
                        if r.success:
                            return ActionReport(success=True, tier_used=2, method="ocr_center",
                                                coordinates={"x": cx, "y": cy}, action_type=at,
                                                attempt_logs=log)
                    except ValueError:
                        pass

        # ── Tier 2b: Card Bounds Sanity Check + VLM Card Re-Query ────────────
        # Cards are IMAGE ARTWORK (large) + TEXT LABEL (small) stacked vertically.
        # Tier 2a may have tapped the text label center (40-80px below image center).
        # If the VLM flagged element_type='card', OR target description contains
        # card-like keywords, AND the fallback_bounds height is suspiciously small
        # (< 60px = text-only bounding box), fire a targeted VLM re-query that
        # explicitly asks for the IMAGE CENTER, not the label center.
        _CARD_KEYWORDS = {
            "map", "level", "tile", "card", "select", "chapter",
            "stage", "character", "hero", "item", "mode", "world",
        }
        is_card_target = (
            getattr(plan, "element_type", None) == "card"
            or any(kw in plan.target_description.lower() for kw in _CARD_KEYWORDS)
        )
        if is_card_target:
            fb    = plan.fallback_bounds or {}
            fb_h  = (fb.get("y2", 0) or 0) - (fb.get("y1", 0) or 0)
            if fb_h < 60:
                log.append(
                    f"T2b [card_sanity] element_type={getattr(plan,'element_type',None)} "
                    f"bounds_h={fb_h}px < 60px — looks text-only; firing card re-query"
                )
                card_coords = self._vlm_card_bounds_requery(perception, plan)
                if card_coords:
                    cx2b, cy2b = card_coords
                    r = self._executor.tap_at(cx2b, cy2b)
                    log.append(
                        f"T2b [card_requery] ({cx2b},{cy2b}) → "
                        f"{'OK' if r.success else r.error}"
                    )
                    if r.success:
                        return ActionReport(
                            success=True, tier_used=2, method="T2b:card_requery",
                            coordinates={"x": cx2b, "y": cy2b},
                            action_type=at, attempt_logs=log,
                        )
            else:
                log.append(
                    f"T2b [card_sanity] bounds_h={fb_h}px >= 60px — "
                    f"bounds look correct, skipping re-query"
                )

        # 2d: Fuzzy UiAutomator text match — from VLM's target_description
        hint = plan.target_description.split()[0][:20] if plan.target_description else ""
        if hint:
            r = self._executor.tap_text_contains(hint)
            log.append(f"T2 [textContains:{hint}] → {'OK' if r.success else r.error}")
            if r.success:
                return ActionReport(success=True, tier_used=2, method="textContains",
                                    coordinates=None, action_type=at, attempt_logs=log)

        log.append("T2 exhausted → TIER 3")

        # ── TIER 3: VLM-provided bounding box coordinates ─────────────────
        # Uses plan.fallback_bounds and plan.locators[coords] — both from VLM.
        # If all VLM-provided coordinates are empty: targeted VLM re-ask.
        # Screen-center fallback removed — blindly harmful on game canvases.
        log.append("── TIER 3: VLM-Provided Coords + VLM Re-Ask ──")

        coord_sources = []
        fb = plan.fallback_bounds
        if fb:
            cx = fb.get("cx") or (fb.get("x1", 0) + (fb.get("x2", 0) - fb.get("x1", 0)) // 2)
            cy = fb.get("cy") or (fb.get("y1", 0) + (fb.get("y2", 0) - fb.get("y1", 0)) // 2)
            if cx and cy:
                coord_sources.append((int(cx), int(cy), "fallback_bounds"))

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

        tried_coords: set = set()
        for cx, cy, label in coord_sources:
            if (cx, cy) in tried_coords or cx <= 0 or cy <= 0:
                continue
            tried_coords.add((cx, cy))
            r = self._executor.tap_at(cx, cy)
            log.append(f"T3 [{label}] ({cx},{cy}) → {'OK' if r.success else r.error}")
            if r.success:
                return ActionReport(success=True, tier_used=3, method=f"T3:{label}",
                                    coordinates={"x": cx, "y": cy}, action_type=at,
                                    attempt_logs=log)

        # ── T3 LAST RESORT: VLM Re-Ask for Coordinates ────────────────────
        # All VLM-provided coordinates from the original plan are exhausted.
        # Make ONE targeted VLM call with a fresh screenshot asking specifically
        # for the pixel coordinates of the target element.
        #
        # This is more expensive (extra API call) but fully VLM-driven and
        # handles edge cases where the VLM omitted coordinates in its first plan.
        #
        # If VLM re-ask also fails → return success=False so the caller
        # (GameplayAgent / orchestrator) re-senses on the next tick.
        log.append("T3: VLM-provided coords exhausted → VLM coordinate re-ask")
        print(f"[action_agent] T3: No usable coords in plan — VLM re-ask for "
              f"'{plan.target_description[:50]}'")

        reask_coords = self._vlm_reask_coordinates(perception, plan)
        if reask_coords:
            rx, ry = reask_coords
            r = self._executor.tap_at(rx, ry)
            log.append(f"T3 [vlm_reask] ({rx},{ry}) → {'OK' if r.success else r.error}")
            if r.success:
                return ActionReport(success=True, tier_used=3, method="T3:vlm_reask",
                                    coordinates={"x": rx, "y": ry}, action_type=at,
                                    attempt_logs=log)

        # All tiers + VLM re-ask exhausted.
        # Return failure — caller will re-sense + re-ask VLM on the next tick.
        log.append("T3 VLM re-ask failed — returning success=False for caller to retry")
        print(f"[action_agent] ⚠ All tiers + VLM re-ask exhausted for: "
              f"'{plan.target_description[:50]}'")
        return ActionReport(
            success=     False,
            tier_used=   3,
            method=      "all_tiers_exhausted",
            coordinates= None,
            action_type= at,
            attempt_logs=log,
            error=(
                "All 3 tiers + VLM re-ask exhausted. "
                "Caller should re-sense and re-plan on the next tick."
            ),
        )

    # =========================================================================
    # Private: VLM Re-Ask for Coordinates
    # =========================================================================

    def _vlm_reask_coordinates(
        self,
        perception: PerceptionState,
        plan:       DecisionPlan,
    ) -> Optional[tuple[int, int]]:
        """
        Targeted VLM re-ask: send a fresh screenshot asking for the pixel
        center of the target element by description.

        Called only when all 3 tiers exhausted their VLM-provided coordinates.

        Returns (x, y) if VLM can locate the element, or None if:
          • Element not visible on current screen
          • VLM API call fails
          • VLM returns (0, 0)

        Prompt is intentionally lightweight — asks ONLY for coordinates,
        not a full DecisionPlan. This keeps the extra call fast and cheap.
        """
        screenshot_b64 = perception.annotated_b64 or perception.screenshot_b64
        if not screenshot_b64:
            print("[action_agent] VLM re-ask: no screenshot available — skipping")
            return None

        prompt = (
            f"COORDINATE LOOKUP — TARGETED RE-ASK\n"
            f"{'─'*50}\n"
            f"A previous action attempt exhausted all locator strategies.\n"
            f"I need the exact pixel center of this element:\n\n"
            f"  TARGET  : {plan.target_description}\n"
            f"  CONTEXT : {plan.reasoning[:200]}\n"
            f"  SCREEN  : {perception.screen_w}×{perception.screen_h} px\n\n"
            f"Instructions:\n"
            f"  1. Look at the screenshot carefully\n"
            f"  2. Find the element described above (button, icon, or UI widget)\n"
            f"  3. Return its pixel center coordinates\n\n"
            f"Return ONLY raw JSON (no markdown, no extra text):\n"
            f'  {{"x": <integer>, "y": <integer>, "found": true, '
            f'"reason": "<brief description of where you found it>"}}\n\n'
            f"If the element is NOT visible on the screen, return:\n"
            f'  {{"x": 0, "y": 0, "found": false, "reason": "<why not visible>"}}'
        )

        lean_prompt = (
            f"TARGET: {plan.target_description[:80]}\n"
            f"SCREEN: {perception.screen_w}×{perception.screen_h}\n"
            f"Return JSON only: {{\"x\": int, \"y\": int, \"found\": bool, \"reason\": str}}"
        )

        content = self.build_image_message(screenshot_b64, prompt)
        result  = self.call_llm(user_content=content, lean_content=lean_prompt)

        if result.get("llm_failed"):
            print(f"[action_agent] VLM re-ask: LLM call failed — {result.get('error','?')}")
            return None

        if not result.get("found", False):
            print(f"[action_agent] VLM re-ask: element not found — "
                  f"{result.get('reason','no reason given')[:60]}")
            return None

        try:
            x = int(result.get("x", 0))
            y = int(result.get("y", 0))
        except (TypeError, ValueError):
            print(f"[action_agent] VLM re-ask: invalid coordinates in response: {result}")
            return None

        if x > 0 and y > 0:
            print(f"[action_agent] VLM re-ask: ✅ found at ({x},{y}) — "
                  f"{result.get('reason','')[:60]}")
            return (x, y)

        print("[action_agent] VLM re-ask: returned (0,0) — element not found on screen")
        return None

    def _vlm_card_bounds_requery(
        self,
        perception: PerceptionState,
        plan:       DecisionPlan,
    ) -> Optional[tuple[int, int]]:
        """
        Targeted VLM re-query for CARD/TILE elements.

        Called by Tier 2b when the fallback_bounds look text-only (height < 60px)
        but the target is a card (image artwork + text label composite element).

        Sends the annotated screenshot with an explicit prompt asking for the
        IMAGE CENTER of the card — NOT the text label center.  The prompt also
        tells the VLM to look for the cyan CARD(cx,cy) annotations drawn by
        image_analyzer.py so it can read off the pre-computed image center directly.

        Returns (x, y) image center coordinates, or None on failure.
        """
        screenshot_b64 = perception.annotated_b64 or perception.screenshot_b64
        if not screenshot_b64:
            print("[action_agent] T2b card_requery: no screenshot — skipping")
            return None

        prompt = (
            f"CARD BOUNDS RE-QUERY\n"
            f"{'─'*50}\n"
            f"I need to tap the IMAGE CENTER of this card/tile element:\n\n"
            f"  TARGET : {plan.target_description}\n"
            f"  SCREEN : {perception.screen_w}×{perception.screen_h} px\n\n"
            f"CARD STRUCTURE: image artwork (large area, ~120-160px tall) ABOVE\n"
            f"                text label (small, ~20-25px) below it.\n\n"
            f"Your task:\n"
            f"  1. Look for CYAN boxes labelled 'CARD(cx,cy)' on the screenshot.\n"
            f"     If present → that IS the image center — use it directly.\n"
            f"  2. If no cyan annotation → visually locate the card artwork area\n"
            f"     (the large image/thumbnail portion) and return its center.\n"
            f"  3. Do NOT return the text label center — that is 40-80px too low.\n\n"
            f"Return ONLY raw JSON:\n"
            f'  {{"x": <image_center_x>, "y": <image_center_y>, "found": true,\n'
            f'   "card_x1": <int>, "card_y1": <int>, "card_x2": <int>, "card_y2": <int>,\n'
            f'   "reason": "<brief description>"}}\n\n'
            f"If the card is NOT visible:\n"
            f'  {{"x": 0, "y": 0, "found": false, "reason": "<why not visible>"}}'
        )

        lean_prompt = (
            f"CARD TARGET: {plan.target_description[:80]}\n"
            f"SCREEN: {perception.screen_w}×{perception.screen_h}\n"
            f"Find the IMAGE CENTER of this card (not text label).\n"
            f"Look for cyan CARD(cx,cy) annotation if present.\n"
            f"Return JSON: {{\"x\": int, \"y\": int, \"found\": bool, \"reason\": str}}"
        )

        content = self.build_image_message(screenshot_b64, prompt)
        result  = self.call_llm(user_content=content, lean_content=lean_prompt)

        if result.get("llm_failed"):
            print(f"[action_agent] T2b card_requery: LLM failed — "
                  f"{result.get('error', '?')}")
            return None

        if not result.get("found", False):
            print(f"[action_agent] T2b card_requery: card not found — "
                  f"{result.get('reason', 'no reason')[:60]}")
            return None

        try:
            x = int(result.get("x", 0))
            y = int(result.get("y", 0))
        except (TypeError, ValueError):
            print(f"[action_agent] T2b card_requery: invalid coords in response: {result}")
            return None

        if x > 0 and y > 0:
            print(f"[action_agent] T2b card_requery: ✅ image center ({x},{y}) — "
                  f"{result.get('reason', '')[:60]}")
            return (x, y)

        print("[action_agent] T2b card_requery: returned (0,0) — card not found")
        return None

    # =========================================================================
    # Private: Locator Router
    # =========================================================================

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

    # =========================================================================
    # Private: Coordinate Extraction Helpers
    # =========================================================================

    @staticmethod
    def _extract_primary_coords(plan: DecisionPlan) -> tuple[int, int]:
        """
        Extract primary (start / target) coordinates from the VLM's plan.

        Priority order:
          1. locators[type=ocr_center]  — VLM gave pixel center from OCR
          2. locators[type=coords]      — VLM gave raw pixel coordinates
          3. fallback_bounds center     — VLM gave bounding box

        Returns (0, 0) if VLM provided no usable coordinates.
        Callers MUST guard against (0, 0) before executing hardware actions.
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

        # VLM provided no coordinates — return (0,0) sentinel
        return 0, 0

    @staticmethod
    def _extract_end_coords(
        plan:      DecisionPlan,
        default_x: int,
        default_y: int,
    ) -> tuple[int, int]:
        """
        Extract end (drop target) coordinates for drag_and_drop.

        Convention: VLM sets type_payload="endX,endY" for drag end point.
        If type_payload is empty, fallback_bounds is used as the drop target
        (only when meaningfully different from start position).

        Returns (0, 0) if VLM provided no valid end coordinates.
        Callers MUST guard against (0, 0) before executing drag actions.

        NOTE: The old '+400 nudge' fallback has been removed — it silently
        produced wrong drags when VLM gave no target. Now we fail cleanly
        and let the caller retry on the next tick with fresh VLM guidance.
        """
        # type_payload = "endX,endY"  (as specified in gameplay guide)
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

        # VLM provided no valid drag end coordinates — return (0,0) sentinel
        return 0, 0

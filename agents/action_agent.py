# agents/action_agent.py
# =============================================================================
# Action Agent - 3-Tier Execution Repair
# ACT phase: execute the current DecisionPlan without making a second decision.
#
# DESIGN PRINCIPLE - stay inside the current plan target:
# The action agent may repair execution on the SAME target using existing
# locators, OCR/text hints, and plan-provided coordinates only.
# If those paths are exhausted:
#   -> return success=False
#   -> caller re-senses and asks DecisionAgent for a fresh plan next tick
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
    tier_used:    int                 # 0=system, 1=semantic, 2=ocr/text, 3=plan coords
    method:       str
    coordinates:  Optional[dict]
    action_type:  str
    attempt_logs: list[str] = field(default_factory=list)
    error:        Optional[str] = None


class ActionAgent(BaseAgent):
    """
    Executes DecisionPlans through a 3-tier repair matrix.

    TIER 1: Semantic element targeting (acc_id, res_id, text, UiAutomator)
            -> uses plan.locators (non-coordinate types)

    TIER 2: OCR coordinates + fuzzy text
            -> uses plan.locators[ocr_center], plan.target_description

    TIER 3: Plan-provided bounding box / coords
            -> uses plan.fallback_bounds, plan.locators[coords]
            -> if exhausted: return success=False so caller re-senses and re-plans

    Execution may self-heal only within the same target already chosen by DecisionAgent.
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
        """Execute the DecisionPlan using same-target repair only."""
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

        if at in ("type", "enter_text", "input_text"):
            text = (plan.type_payload or "").strip()
            if not text:
                return ActionReport(
                    success=False,
                    tier_used=0,
                    method="type_no_payload",
                    coordinates=None,
                    action_type=at,
                    attempt_logs=["type: missing text payload"],
                    error="No text payload provided for type action",
                )
            return self._type_into_field(plan, perception, at, text)

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
            print(f"[action_agent] Plan-only visual verify: "
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
            # Direction not found in the current plan description — fail cleanly
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
            cx, cy = self._extract_primary_coords(plan, perception)
            if cx == 0 and cy == 0:
                log.append("long_press: no plan coordinates — returning failure")
                return ActionReport(success=False, tier_used=0, method="long_press_no_coords",
                                    coordinates=None, action_type=at, attempt_logs=log,
                                    error="Plan provided no coordinates for long_press")
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
            if cx == 0 and cy == 0:
                log.append("double_tap: no plan coordinates — returning failure")
                return ActionReport(success=False, tier_used=0, method="double_tap_no_coords",
                                    coordinates=None, action_type=at, attempt_logs=log,
                                    error="Plan provided no coordinates for double_tap")
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
        # All coordinates must come from the current plan.
        # If the plan provides no end coordinates → return failure so caller re-plans.
        if at in ("drag", "drag_and_drop", "drag_drop", "tower_place", "place"):
            start_x, start_y = self._extract_primary_coords(plan, perception)
            end_x, end_y     = self._extract_end_coords(plan, start_x, start_y)

            # Guard: no valid start coordinates
            if start_x == 0 and start_y == 0:
                log.append("drag_and_drop: no plan start coordinates — aborted")
                print("[action_agent] drag_and_drop aborted: no start coords in plan")
                return ActionReport(success=False, tier_used=0, method="drag_aborted_no_start",
                                    coordinates=None, action_type=at, attempt_logs=log,
                                    error="Plan provided no drag start coordinates")

            # Guard: no valid end coordinates (0,0 sentinel from _extract_end_coords)
            if end_x == 0 and end_y == 0:
                log.append("drag_and_drop: no plan end coordinates — aborted")
                print("[action_agent] drag_and_drop aborted: no end coords in plan "
                      f"(type_payload='{plan.type_payload}' "
                      f"fallback_bounds={plan.fallback_bounds})")
                return ActionReport(success=False, tier_used=0, method="drag_aborted_no_end",
                                    coordinates=None, action_type=at, attempt_logs=log,
                                    error="Plan provided no drag end coordinates. "
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
        # type_payload: "startX,startY,endX,endY"  ← all 4 from the current plan
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
            # Fallback: directional swipe from the current plan description
            direction = plan.target_description.lower()
            for d in ["up", "down", "left", "right"]:
                if d in direction:
                    r = self._executor.swipe(d, perception.screen_w, perception.screen_h)
                    return ActionReport(success=r.success, tier_used=2, method=f"swipe_{d}_fallback",
                                        coordinates=None, action_type=at, attempt_logs=log)
            # Plan gave neither valid type_payload nor direction — fail cleanly
            log.append("swipe_coords: no valid coords in type_payload and no direction in description")
            return ActionReport(success=False, tier_used=0, method="swipe_coords_no_data",
                                coordinates=None, action_type=at, attempt_logs=log,
                                error="Plan provided no valid swipe coordinates")

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

        # ── TIER SoM: Step/registry-anchored exact tap ───────────────────
        # When the decision came from a step-text anchor or a VLM Set-of-Mark
        # selection (plan.element_id set, OR a coords locator derived from the
        # registry), we already have the EXACT element center. Tap it directly,
        # honour repeat/interval, and self-heal by re-tapping the registry
        # neighbour if the screen did not change.
        som_report = self._try_som_tap(plan, perception, at, log)
        if som_report is not None:
            return som_report

        # ── TIER 1: Semantic element locators from the current plan ───────
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

        # ── TIER 2: OCR coords + fuzzy text from the current plan ─────────
        log.append("── TIER 2: OCR Coords + Fuzzy Text ──")

        # 2a: OCR center coordinates from the current plan
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

        # 2d: Fuzzy UiAutomator text match — from the current plan target description
        hint = plan.target_description.split()[0][:20] if plan.target_description else ""
        if hint:
            r = self._executor.tap_text_contains(hint)
            log.append(f"T2 [textContains:{hint}] → {'OK' if r.success else r.error}")
            if r.success:
                return ActionReport(success=True, tier_used=2, method="textContains",
                                    coordinates=None, action_type=at, attempt_logs=log)

        log.append("T2 exhausted → TIER 3")

        # ── TIER 3: Plan-provided bounding box coordinates ────────────────
        # Uses plan.fallback_bounds and plan.locators[coords] only.
        log.append("── TIER 3: Plan-Provided Coords ──")

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

        # Plan-provided coordinates are exhausted at this point.
        # Return failure so the caller re-senses and asks DecisionAgent for a
        # fresh plan instead of doing a second decision inside ActionAgent.
        return ActionReport(
            success=     False,
            tier_used=   3,
            method=      "all_tiers_exhausted",
            coordinates= None,
            action_type= at,
            attempt_logs=log,
            error=(
                "All 3 tiers from the current plan were exhausted. "
                "Caller should re-sense and re-plan on the next tick."
            ),
        )


    # =========================================================================
    # Private: Set-of-Mark Exact Tap (+ repeat/interval + self-heal)
    # =========================================================================

    def _try_som_tap(
        self,
        plan:       DecisionPlan,
        perception: PerceptionState,
        at:         str,
        log:        list,
    ) -> Optional[ActionReport]:
        """
        Pixel-accurate tap using a Set-of-Mark / step-anchored target.

        Fires ONLY for tap-like actions when the plan carries an exact center,
        which happens when:
          • plan.element_id is set (DecisionAgent selected a numbered SoM element), OR
          • the step-text anchor produced a coords locator from the registry.

        In both cases the center already IS the element's true tap point
        (composite center = IMAGE center for label+image cards; geometric
        center for icons/buttons). No estimation, no OCR-label offset.

        Extra robustness:
          • repeat / interval  — taps N times with a gap (e.g. "tap 4 times,
            1s apart"). All repeats use the SAME exact coordinate.
          • tap-verify-correct — for a SINGLE tap, frame-diff before/after; if
            the screen did not change, retry once at the same exact center
            (covers a stale-coordinate race). Repeat taps skip this so
            we never double the requested count.

        Returns an ActionReport when it handled the action, or None to let the
        normal tier cascade run (no exact anchor available).
        """
        if at not in ("tap", "click", "press", "select", "touch"):
            return None

        # Resolve the exact center: prefer the registry element, else the
        # first coords locator, else fallback_bounds center.
        cx = cy = 0
        source = ""

        el = None
        if getattr(plan, "element_id", None) is not None:
            el = perception.get_element(plan.element_id)
        if el is not None:
            cx, cy = el.center
            source = f"registry#{el.id}({el.kind})"
        else:
            for loc in plan.locators:
                if (loc.get("type") or "").lower() == "coords":
                    parts = [s.strip() for s in str(loc.get("value", "")).split(",")]
                    if len(parts) >= 2:
                        try:
                            cx, cy = int(parts[0]), int(parts[1])
                            source = "coords_anchor"
                            break
                        except ValueError:
                            pass

        # Only engage when this looks like an anchored decision. A plain VLM
        # plan with no element_id and an OCR/semantic intent should fall through.
        anchored = (
            el is not None
            or getattr(plan, "element_id", None) is not None
            or "anchor" in (plan.reasoning or "").lower()
            or "registry" in (plan.screen_assessment or "").lower()
        )
        if not anchored or cx <= 0 or cy <= 0:
            return None

        repeat   = max(1, int(getattr(plan, "repeat", 1) or 1))
        interval = max(0.0, float(getattr(plan, "interval_s", 0.0) or 0.0))

        log.append(f"── TIER SoM: exact tap ({cx},{cy}) src={source} "
                   f"repeat={repeat} interval={interval}s ──")
        print(f"[action_agent] 🎯 SoM exact tap ({cx},{cy}) src={source} "
              f"repeat={repeat} interval={interval}s")

        # ── Repeated taps (e.g. "four times, one second apart") ──────────
        if repeat > 1:
            ok_any = False
            for i in range(repeat):
                r = self._executor.tap_at(cx, cy)
                ok_any = ok_any or r.success
                log.append(f"SoM tap {i+1}/{repeat} ({cx},{cy}) → "
                           f"{'OK' if r.success else r.error}")
                if i < repeat - 1 and interval > 0:
                    self._executor.wait(interval)
            return ActionReport(
                success=ok_any, tier_used=1,
                method=f"som_repeat_tap_x{repeat}",
                coordinates={"x": cx, "y": cy}, action_type=at, attempt_logs=log,
            )

        # ── Single tap with tap-verify-correct self-heal ─────────────────
        pre_np = perception.screenshot_np
        r = self._executor.tap_at(cx, cy)
        log.append(f"SoM tap ({cx},{cy}) → {'OK' if r.success else r.error}")
        if not r.success:
            log.append("SoM tap reported failure — falling through to tier cascade")
            return None

        # Verify the tap actually changed the screen.
        if pre_np is not None:
            try:
                self._executor.wait(0.4)
                post = self._capture_np()
                if post is not None:
                    diff = self._analyzer.pixel_diff(pre_np, post)
                    log.append(f"SoM verify pixel_diff={diff:.3f}")
                    if diff < 0.01:
                        # No change — re-tap once at the same exact center.
                        log.append("SoM self-heal: no screen change → re-tap once")
                        print(f"[action_agent] SoM self-heal re-tap ({cx},{cy}) "
                              f"(diff={diff:.3f})")
                        r2 = self._executor.tap_at(cx, cy)
                        log.append(f"SoM re-tap ({cx},{cy}) → "
                                   f"{'OK' if r2.success else r2.error}")
            except Exception as exc:
                log.append(f"SoM verify skipped ({exc})")

        return ActionReport(
            success=True, tier_used=1, method=f"som_exact_tap:{source}",
            coordinates={"x": cx, "y": cy}, action_type=at, attempt_logs=log,
        )

    def _type_into_field(
        self,
        plan: DecisionPlan,
        perception: PerceptionState,
        at: str,
        text: str,
    ) -> ActionReport:
        """
        Type text into a target input field or the currently focused field.
        """
        log: list[str] = []
        target_upper = (plan.target_description or "").upper()
        wants_submit = "SEARCH" in target_upper

        if self._looks_like_non_input_target(target_upper):
            log.append(f"TYPE guard blocked non-input target '{plan.target_description[:60]}'")
            return ActionReport(
                success=False,
                tier_used=0,
                method="type_guard_non_input_target",
                coordinates=None,
                action_type=at,
                attempt_logs=log,
                error="Type action points to a navigation/icon/menu target instead of an input field",
            )

        for loc in plan.locators:
            lt = (loc.get("type") or "").lower()
            lv = (loc.get("value") or "").strip()
            if not lv or lt not in {"accessibility_id", "resource_id", "xpath", "text", "uiautomator"}:
                continue
            r = self._executor.type_text(lt, lv, text, clear_first=True)
            log.append(f"TYPE [{lt}] '{lv[:40]}' -> {'OK' if r.success else r.error}")
            if r.success:
                if wants_submit:
                    submit = self._executor.press_enter()
                    log.append(f"TYPE submit enter -> {'OK' if submit.success else submit.error}")
                return ActionReport(
                    success=True,
                    tier_used=1,
                    method=f"type:{lt}",
                    coordinates=None,
                    action_type=at,
                    attempt_logs=log,
                )

        cx, cy = self._extract_primary_coords(plan, perception)
        if cx > 0 and cy > 0:
            tap = self._executor.tap_at(cx, cy)
            log.append(f"TYPE focus tap ({cx},{cy}) -> {'OK' if tap.success else tap.error}")
            if tap.success:
                self._executor.wait(0.3)
                focused = self._executor.type_text_focused(text, clear_first=True)
                log.append(f"TYPE focused after tap -> {'OK' if focused.success else focused.error}")
                if focused.success:
                    if wants_submit:
                        submit = self._executor.press_enter()
                        log.append(f"TYPE submit enter -> {'OK' if submit.success else submit.error}")
                    return ActionReport(
                        success=True,
                        tier_used=2,
                        method="type:tap_then_focused",
                        coordinates={"x": cx, "y": cy},
                        action_type=at,
                        attempt_logs=log,
                    )

        focused = self._executor.type_text_focused(text, clear_first=True)
        log.append(f"TYPE focused fallback -> {'OK' if focused.success else focused.error}")
        if focused.success:
            if wants_submit:
                submit = self._executor.press_enter()
                log.append(f"TYPE submit enter -> {'OK' if submit.success else submit.error}")
            return ActionReport(
                success=True,
                tier_used=2,
                method="type:focused",
                coordinates=None,
                action_type=at,
                attempt_logs=log,
            )

        return ActionReport(
            success=False,
            tier_used=2,
            method="type_failed",
            coordinates=None,
            action_type=at,
            attempt_logs=log,
            error=f"Unable to type '{text[:40]}' into the target input field",
        )

    @staticmethod
    def _looks_like_non_input_target(target_upper: str) -> bool:
        """Reject obvious nav/icon/menu/tab targets for type actions."""
        if not target_upper:
            return False
        has_nav_terms = any(term in target_upper for term in (
            " ICON", "ICON ", " MENU", "MENU ", " NAV", "NAVIGATION",
            " TAB", "TAB ", " BUTTON", "BOTTOM BAR", "BOTTOM NAV",
        ))
        has_input_terms = any(term in target_upper for term in (
            "INPUT", "FIELD", "SEARCH BAR", "SEARCH BOX", "TEXT BOX",
            "TEXTBOX", "EDITTEXT", "EDIT TEXT", "USERNAME", "EMAIL", "PASSWORD",
            "FOCUSED INPUT",
        ))
        return has_nav_terms and not has_input_terms

    def _capture_np(self):
        """Best-effort fresh screenshot as numpy for self-heal verification."""
        try:
            cap = self._executor.screenshot()
            return getattr(cap, "screenshot_np", None)
        except Exception:
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

    def _extract_primary_coords(
        self,
        plan: DecisionPlan,
        perception: Optional[PerceptionState] = None,
    ) -> tuple[int, int]:
        """
        Extract primary (start / target) coordinates from the current plan.

        Priority order:
          1. SoM / registry anchor via plan.element_id
          2. locators[type=coords]
          3. fallback_bounds center
          4. locators[type=ocr_center]

        Returns (0, 0) if the plan provided no usable coordinates.
        Callers MUST guard against (0, 0) before executing hardware actions.
        """
        if perception is not None and getattr(plan, "element_id", None) is not None:
            el = perception.get_element(plan.element_id)
            if el is not None:
                return int(el.center[0]), int(el.center[1])

        for loc in plan.locators:
            lt = (loc.get("type") or "").lower()
            lv = (loc.get("value") or "").strip()
            if lt == "coords" and lv:
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

        for loc in plan.locators:
            lt = (loc.get("type") or "").lower()
            lv = (loc.get("value") or "").strip()
            if lt == "ocr_center" and lv:
                parts = [p.strip() for p in lv.split(",")]
                if len(parts) >= 2:
                    try:
                        return int(parts[0]), int(parts[1])
                    except ValueError:
                        pass

        # Plan provided no coordinates — return (0,0) sentinel
        return 0, 0

    @staticmethod
    def _extract_end_coords(
        plan:      DecisionPlan,
        default_x: int,
        default_y: int,
    ) -> tuple[int, int]:
        """
        Extract end (drop target) coordinates for drag_and_drop.

        Convention: the current plan sets type_payload="endX,endY" for drag end point.
        If type_payload is empty, fallback_bounds is used as the drop target
        (only when meaningfully different from start position).

        Returns (0, 0) if the plan provided no valid end coordinates.
        Callers MUST guard against (0, 0) before executing drag actions.

        NOTE: The old '+400 nudge' fallback has been removed — it silently
        produced wrong drags when the plan gave no target. Now we fail cleanly
        and let the caller retry on the next tick with fresh planning.
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

        # Plan provided no valid drag end coordinates — return (0,0) sentinel
        return 0, 0

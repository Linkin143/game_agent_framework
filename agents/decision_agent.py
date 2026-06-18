# agents/decision_agent.py
# =============================================================================
# Decision Agent — Goal-Driven VLM Reasoning
# TEST phase: Analyzes PerceptionState + current subgoal → decides next action.
# Reads 02_decision_skill.md + 06_game_navigation_skill.md as system prompts.
# =============================================================================

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from agents.base_agent import BaseAgent
from agents.perception_agent import PerceptionState

SKILLS_DIR = Path(__file__).parent.parent / "skills"


@dataclass
class DecisionPlan:
    """The complete action plan produced by the Decision Agent."""
    # Screen analysis
    screen_assessment:   str
    subgoal_progress:    str
    rendering_engine:    str

    # Blocking element (handle first if not None)
    blocking_element:    Optional[str]   # "ad", "permission", "dialog", "tutorial"

    # Action to execute
    action_type:         str             # tap | wait | back | swipe | type | activate_app
    target_description:  str
    locators:            list[dict]      # [{"type": ..., "value": ...}]
    fallback_bounds:     dict            # {x1, y1, x2, y2}
    type_payload:        str             # text to type (for type action)
    template_name:       str            # reference_assets template name

    # Confidence
    confidence:          float           # 0.0–1.0
    reasoning:           str

    # Subgoal update
    subgoal_complete:    bool
    suggested_next_subgoal: Optional[str]


class DecisionAgent(BaseAgent):
    """
    Goal-driven decision maker.
    Receives PerceptionState + current subgoal → returns DecisionPlan.

    Process:
    1. Build context: annotated screenshot + OCR table + XML summary + subgoal
    2. Include game navigation skill + game-specific skill as additional context
    3. Call VLM to analyze and plan
    4. Parse JSON response into DecisionPlan
    5. Fallback to heuristics if LLM fails
    """

    SKILL_FILE = "02_decision_skill.md"

    def __init__(self, llm, game_skill: str = "") -> None:
        super().__init__(llm=llm, skill_file=self.SKILL_FILE)
        # Load generic engine/navigation skills
        self._nav_skill   = self._load_skill("06_game_navigation_skill.md")
        self._ue5_skill   = self._load_skill("07_unreal_engine_skill.md")
        self._unity_skill = self._load_skill("08_unity_skill.md")
        # Game-specific skill: loaded by GameSkillLoader and injected at init
        # This text is ONLY for the currently launched game package — never mixed
        self._game_skill  = game_skill
        if game_skill:
            print(f"[decision_agent] Game-specific skill loaded "
                  f"({len(game_skill)} chars) — will inject into every VLM call")
        else:
            print("[decision_agent] No game-specific skill — using generic skills only")

    def decide(
        self,
        perception:      PerceptionState,
        current_subgoal: str,
        goal:            str,
        stuck_count:     int = 0,
    ) -> DecisionPlan:
        """
        Main decision method: analyze screen + subgoal → produce action plan.

        DESIGN PRINCIPLE — Live Screenshot is ALWAYS sent to Claude Vision:
        ─────────────────────────────────────────────────────────────────────
        Every single decision goes through the LLM with the annotated live
        screenshot + XML tree + OCR together.  The heuristic runs ONLY to
        generate a pre-computed "suggested action" hint which is injected
        into the LLM prompt — giving Claude Vision an efficient starting
        point while still seeing the real pixel truth of the current screen.

        The LLM can confirm, modify, or override the heuristic suggestion.
        Heuristic is NEVER used to bypass the LLM call.
        ─────────────────────────────────────────────────────────────────────
        """
        print(f"[decision_agent] DECIDE | subgoal='{current_subgoal}' "
              f"engine='{perception.rendering_engine}' stuck={stuck_count}")

        # Step 1: Run heuristic to generate a HINT (not a bypass)
        heuristic_hint: Optional[DecisionPlan] = self._fast_heuristic(perception, current_subgoal)
        if heuristic_hint:
            print(f"[decision_agent] Heuristic hint: '{heuristic_hint.target_description[:50]}' "
                  f"(conf={heuristic_hint.confidence:.2f}) → sending to VLM for visual confirmation")

        # Step 2: ALWAYS call the LLM with live screenshot + XML + OCR
        # The heuristic hint is embedded in the prompt so the VLM can confirm/override it
        user_content = self._build_user_content(
            perception, current_subgoal, goal, stuck_count, heuristic_hint
        )

        # Engine-specific skill context
        extra_system = ""
        eng = perception.rendering_engine
        if eng in ("UNITY", "CANVAS"):
            extra_system = f"\n\n## Engine-Specific Context\n{self._unity_skill[:1200]}"
        elif eng == "UNREAL":
            extra_system = f"\n\n## Engine-Specific Context\n{self._ue5_skill[:1200]}"
        extra_system += f"\n\n## Game Navigation Reference\n{self._nav_skill[:800]}"

        # ── GAME-SPECIFIC SKILL: Injected ONLY for the launched game's package ──
        # This provides precise gameplay instructions (HUD layout, button coords,
        # OCR keywords, navigation flow) specific to the current game.
        # It is loaded once at startup by GameSkillLoader and NEVER mixed with
        # skills from other games.
        if self._game_skill:
            extra_system += (
                f"\n\n{'═'*60}\n"
                f"## GAME-SPECIFIC GAMEPLAY INSTRUCTIONS (HIGH PRIORITY)\n"
                f"The following instructions are specific to THIS game's package.\n"
                f"They override generic navigation rules when there is a conflict.\n"
                f"Use the HUD keywords, coordinates, and navigation sequence below\n"
                f"to make precise decisions for the current subgoal.\n"
                f"{'═'*60}\n"
                f"{self._game_skill[:3000]}\n"
                f"{'═'*60}\n"
            )

        # Step 3: LLM call — receives screenshot + XML + OCR + hint
        result = self.call_llm(
            user_content=user_content,
            extra_system=extra_system,
            lean_content=self._build_lean_content(perception, current_subgoal),
        )

        # Step 4: Parse LLM result — if LLM completely fails, fall back to heuristic
        if result.get("llm_failed"):
            if heuristic_hint:
                print(f"[decision_agent] LLM failed — using heuristic hint as fallback")
                return heuristic_hint
            return self._fallback_plan(perception, current_subgoal)

        plan = self._parse_plan(result, perception)
        print(f"[decision_agent] VLM decision: action={plan.action_type} "
              f"target='{plan.target_description[:40]}' conf={plan.confidence:.2f}")
        return plan

    # -------------------------------------------------------------------------
    # Private: Fast Heuristics (no LLM call)
    # -------------------------------------------------------------------------

    def _fast_heuristic(
        self,
        p: PerceptionState,
        subgoal: str,
    ) -> Optional[DecisionPlan]:
        """
        Fast deterministic path — no LLM call needed.

        Priority order (matches perception priority):
          1. XML accessibility tree  → highest confidence, direct element targeting
          2. OCR canvas text         → fallback for game canvas (Unity/Unreal, no XML)
        """
        text = p.all_text.upper()
        ocr  = p.ocr_result
        play_words = ["PLAY", "START", "BEGIN", "ENTER", "GO", "CONTINUE"]
        dismiss_words = ["NOT NOW", "LATER", "NO THANKS", "SKIP"]
        allow_words = ["ALLOW", "ACCEPT", "AGREE", "OK", "PERMIT"]

        # ── PRIORITY 1: XML accessibility tree ───────────────────────────
        # Check XML for clickable blocking elements first
        for el in p.selector_map:
            t = (el.get("text") or "").upper().strip()
            acc = (el.get("acc_id") or "").upper()
            clickable = el.get("clickable", False)

            # Permission / dialog dismissal
            if any(kw in t or kw in acc for kw in allow_words) and clickable:
                b = el.get("bounds", {})
                return DecisionPlan(
                    screen_assessment=   f"XML: Permission element '{t}'",
                    subgoal_progress=    "handling blocking element",
                    rendering_engine=    p.rendering_engine,
                    blocking_element=    "permission",
                    action_type=         "tap",
                    target_description=  f"'{t}' button from XML",
                    locators=            [{"type": "text", "value": el.get("text","")},
                                          {"type": "accessibility_id", "value": el.get("acc_id","")}],
                    fallback_bounds=     b,
                    type_payload=        "",
                    template_name=       "",
                    confidence=          0.97,
                    reasoning=           f"XML clickable element with allow/accept text: '{t}'",
                    subgoal_complete=    False,
                    suggested_next_subgoal=None,
                )

        # Main navigation: look for PLAY/START in XML first
        if subgoal in ("NAVIGATE_TO_MAIN_MENU", "NAVIGATE_TO_LEVEL_SELECT", "START_GAMEPLAY"):
            for el in p.selector_map:
                t = (el.get("text") or "").upper().strip()
                if any(pw == t for pw in play_words) and el.get("clickable"):
                    b = el.get("bounds", {})
                    return DecisionPlan(
                        screen_assessment=   f"XML: Found '{t}' button",
                        subgoal_progress=    subgoal,
                        rendering_engine=    p.rendering_engine,
                        blocking_element=    None,
                        action_type=         "tap",
                        target_description=  f"'{t}' button from XML tree",
                        locators=            [{"type": "text", "value": el.get("text","")},
                                              {"type": "accessibility_id", "value": el.get("acc_id","")}],
                        fallback_bounds=     b,
                        type_payload=        "",
                        template_name=       "",
                        confidence=          0.92,
                        reasoning=           f"XML element text='{t}' — direct element tap",
                        subgoal_complete=    False,
                        suggested_next_subgoal=None,
                    )

        # ── PRIORITY 2: OCR canvas text (game canvas, Unity, Unreal) ──────
        # Only used when XML has no matching element (game canvas mode)
        if ocr:
            # Blocking: Permission dialog via OCR
            for allow_word in allow_words:
                w = next((wd for wd in p.ocr_result.words
                           if allow_word.lower() in wd.text.lower() and wd.confidence > 0.65), None)
                if w:
                    return self._make_ocr_tap_plan(w, "permission_allow", 0.90,
                                                    f"OCR: Permission dialog — tapping '{w.text}'")

            # Blocking: Dismiss words via OCR
            for dismiss in dismiss_words:
                if dismiss in text:
                    w = next((wd for wd in p.ocr_result.words
                               if dismiss.lower() in wd.text.lower()), None)
                    if w:
                        return self._make_ocr_tap_plan(w, f"dismiss_{dismiss.lower()}", 0.85,
                                                        f"OCR: Dismissing '{dismiss}'")

            # Navigation: play/start via OCR (game canvas only)
            if subgoal in ("NAVIGATE_TO_MAIN_MENU", "NAVIGATE_TO_LEVEL_SELECT", "START_GAMEPLAY"):
                for pw in play_words:
                    w = next((wd for wd in p.ocr_result.words
                               if wd.text.upper() == pw and wd.confidence > 0.70), None)
                    if w:
                        return self._make_ocr_tap_plan(w, pw.lower(), 0.82,
                                                        f"OCR canvas: tapping '{pw}' button")

        return None

    @staticmethod
    def _make_ocr_tap_plan(
        word,
        label: str,
        conf:  float,
        reason: str,
    ) -> DecisionPlan:
        return DecisionPlan(
            screen_assessment=   reason,
            subgoal_progress=    "handling blocking element",
            rendering_engine=    "CANVAS",
            blocking_element=    label,
            action_type=         "tap",
            target_description=  f"OCR: '{word.text}' at {word.center}",
            locators=            [{"type": "ocr_center", "value": f"{word.center[0]},{word.center[1]}"}],
            fallback_bounds=     {"x1": word.bbox[0], "y1": word.bbox[1],
                                   "x2": word.bbox[2], "y2": word.bbox[3],
                                   "cx": word.center[0], "cy": word.center[1]},
            type_payload=        "",
            template_name=       "",
            confidence=          conf,
            reasoning=           reason,
            subgoal_complete=    False,
            suggested_next_subgoal=None,
        )

    # -------------------------------------------------------------------------
    # Private: LLM Message Building
    # -------------------------------------------------------------------------

    def _build_user_content(
        self,
        p:              PerceptionState,
        subgoal:        str,
        goal:           str,
        stuck:          int,
        hint:           Optional["DecisionPlan"] = None,
    ) -> list:
        """
        Build the multimodal LLM payload.

        The live screenshot (base64) is ALWAYS the first element sent to Claude Vision.
        It is followed by the full XML accessibility tree and OCR text so the LLM
        can cross-reference what it sees visually against the structured element data.

        Layout:
          [IMAGE]  ← annotated live screenshot (PRIMARY — visual truth)
          [TEXT]   ← XML tree + OCR + heuristic hint + decision rules
        """
        # ── PRIMARY: XML accessibility tree ──────────────────────────────
        xml_lines = []
        for i, e in enumerate(p.selector_map[:40]):
            row = f"[{i:02d}]"
            row += " [TAP]" if e.get("clickable") else "      "
            if e.get("text"):    row += f' text="{e["text"][:30]}"'
            if e.get("acc_id"): row += f' acc="{e["acc_id"][:30]}"'
            if e.get("res_id"): row += f' id="{e["res_id"][:30]}"'
            if e.get("class"):  row += f' cls="{e["class"].split(".")[-1]}"'
            if e.get("bounds"): row += f' bounds={e["bounds"]}'
            if e.get("center"): row += f' center={e.get("center","")}'
            xml_lines.append(row)

        xml_summary = "\n".join(xml_lines) if xml_lines else (
            "⚠ NO XML ELEMENTS — Pure game canvas (Unity/Unreal/SurfaceView).\n"
            "  Action MUST use screenshot visual + OCR coordinates (Tier 2/3 only)."
        )

        # ── SUPPLEMENTARY: OCR canvas text ───────────────────────────────
        ocr_lines = []
        if p.ocr_result:
            for w in p.ocr_result.words[:30]:
                if w.confidence > 0.50:
                    ocr_lines.append(f'  "{w.text}" @ center={w.center}  conf={w.confidence:.2f}')
        ocr_block = ("\n".join(ocr_lines)
                     if ocr_lines else
                     "  (none — use screenshot pixel coordinates)")

        # ── HEURISTIC HINT (pre-computed suggestion for VLM to confirm) ──
        hint_block = ""
        if hint:
            hint_block = (
                f"\n▶ PRE-COMPUTED HINT (from XML/OCR analysis — confirm visually):\n"
                f"  action     : {hint.action_type}\n"
                f"  target     : {hint.target_description}\n"
                f"  locators   : {hint.locators[:2]}\n"
                f"  bounds     : {hint.fallback_bounds}\n"
                f"  confidence : {hint.confidence:.2f}\n"
                f"  reasoning  : {hint.reasoning}\n"
                f"  ▸ Look at the SCREENSHOT above to visually CONFIRM this element is\n"
                f"    actually present and correctly identified. Override if wrong.\n"
            )

        text_ctx = (
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"OVERALL GOAL    : \"{goal}\"\n"
            f"CURRENT SUBGOAL : {subgoal}\n"
            f"RENDERING ENGINE: {p.rendering_engine}  |  STUCK: {stuck}\n"
            f"SCREEN SIZE     : {p.screen_w}×{p.screen_h}  |  source={p.screenshot_source}\n"
            f"ANIMATION SCORE : {p.animation_score:.3f}  |  stable={p.is_stable}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

            f"▶ PRIMARY INPUT 1 — LIVE SCREENSHOT (image attached above):\n"
            f"  This is the REAL current screen captured this instant from the device.\n"
            f"  Grid coordinates and XML bounding boxes are overlaid on it.\n"
            f"  The screenshot is the single source of visual truth — trust it above all.\n\n"

            f"▶ PRIMARY INPUT 2 — XML ACCESSIBILITY TREE ({p.element_count} elements):\n"
            f"{xml_summary}\n\n"

            f"▶ SUPPLEMENTARY — OCR TEXT (game canvas text visible on screen):\n"
            f"{ocr_block}\n"
            f"{hint_block}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"YOUR TASK — Cross-reference screenshot + XML + OCR then decide:\n"
            f"  1. If XML has a visible [TAP] element → use accessibility_id or text locator\n"
            f"  2. If game canvas (no XML) → use pixel coordinates from the screenshot grid\n"
            f"  3. Always set fallback_bounds from the screenshot bounding box\n"
            f"  4. Confidence ≥ 0.85 to act; if unsure set confidence=0.5\n\n"
            f"Return ONLY raw JSON — no markdown, no explanation."
        )

        return self.build_image_message(p.annotated_b64 or p.screenshot_b64, text_ctx)

    def _build_lean_content(self, p: PerceptionState, subgoal: str) -> str:
        """Minimal text prompt for LLM retry."""
        return (
            f"SUBGOAL: {subgoal}\n"
            f"ENGINE: {p.rendering_engine}\n"
            f"OCR: {p.all_text[:200]}\n"
            "Return JSON with action_type, locators, confidence, reasoning."
        )

    def _parse_plan(self, raw: dict, p: PerceptionState) -> DecisionPlan:
        """Parse LLM response dict into DecisionPlan."""
        return DecisionPlan(
            screen_assessment=      raw.get("screen_assessment", ""),
            subgoal_progress=       raw.get("subgoal_progress", ""),
            rendering_engine=       raw.get("rendering_engine", p.rendering_engine),
            blocking_element=       raw.get("blocking_element"),
            action_type=            raw.get("action_type", "tap"),
            target_description=     raw.get("target_description", ""),
            locators=               raw.get("locators", []),
            fallback_bounds=        raw.get("fallback_bounds", {}),
            type_payload=           raw.get("type_payload", ""),
            template_name=          raw.get("template_name", ""),
            confidence=             float(raw.get("confidence", 0.5)),
            reasoning=              raw.get("reasoning", ""),
            subgoal_complete=       bool(raw.get("subgoal_complete", False)),
            suggested_next_subgoal= raw.get("suggested_next_subgoal"),
        )

    def _fallback_plan(self, p: PerceptionState, subgoal: str) -> DecisionPlan:
        """Deterministic fallback when LLM fails completely."""
        # Try to find any clickable element
        for el in p.selector_map:
            if el.get("clickable"):
                b = el.get("bounds", {})
                return DecisionPlan(
                    screen_assessment=   "LLM fallback: using first clickable element",
                    subgoal_progress=    subgoal,
                    rendering_engine=    p.rendering_engine,
                    blocking_element=    None,
                    action_type=         "tap",
                    target_description=  el.get("text") or el.get("acc_id") or "clickable element",
                    locators=            [{"type": "coords", "value": el.get("center", "")}],
                    fallback_bounds=     b,
                    type_payload=        "",
                    template_name=       "",
                    confidence=          0.3,
                    reasoning=           "LLM unavailable; using first clickable element",
                    subgoal_complete=    False,
                    suggested_next_subgoal=None,
                )
        # No clickable element: tap screen center
        cx, cy = p.screen_w // 2, p.screen_h // 2
        return DecisionPlan(
            screen_assessment=   "LLM fallback: tap screen center",
            subgoal_progress=    subgoal,
            rendering_engine=    p.rendering_engine,
            blocking_element=    None,
            action_type=         "tap",
            target_description=  "screen center (last resort)",
            locators=            [{"type": "coords", "value": f"{cx},{cy}"}],
            fallback_bounds=     {"x1": 0, "y1": 0, "x2": p.screen_w, "y2": p.screen_h, "cx": cx, "cy": cy},
            type_payload=        "",
            template_name=       "",
            confidence=          0.2,
            reasoning=           "LLM failed and no clickable elements found",
            subgoal_complete=    False,
            suggested_next_subgoal=None,
        )

# agents/decision_agent.py
# =============================================================================
# Decision Agent — Goal-Driven VLM Reasoning
# TEST phase: Analyzes PerceptionState + current subgoal → decides next action.
# Reads 02_decision_skill.md + 06_game_navigation_skill.md as system prompts.
# =============================================================================

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from agents.base_agent import BaseAgent
from agents.perception_agent import PerceptionState

SKILLS_DIR = Path(__file__).parent.parent / "skills"

# ─── Dynamic-Wait Detection Constants ────────────────────────────────────────
# Regex: matches "wait for 40 seconds", "wait 15s", "wait 3.5 sec", etc.
_WAIT_DUR_RE = re.compile(
    r'\bwait\s+(?:for\s+)?(\d+(?:\.\d+)?)\s*(?:seconds?|secs?|s\b)',
    re.IGNORECASE,
)

# OCR keywords that indicate a loading / connecting / pending screen state
_LOADING_KEYWORDS: frozenset[str] = frozenset({
    "loading", "downloading", "connecting", "reconnecting",
    "processing", "pending", "syncing", "please wait",
    "initializing", "preparing", "server connection",
    "connecting to server", "waiting for server",
})


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

    # Card/tile element flag (set by VLM when target is an image+label card)
    element_type:        Optional[str] = None   # "card" | None

    # ── Set-of-Mark (SoM) targeting ──────────────────────────────────────────
    # When the VLM SELECTS a numbered element instead of estimating pixels, it
    # returns element_id. The action agent looks up the exact center from the
    # perception.element_registry — guaranteeing pixel-accurate taps on small
    # icons and label+image composites.
    element_id:          Optional[int] = None    # SoM registry id (1..N)

    # ── Step-anchored repeat / interval (from StepIntent) ───────────────────
    # "Tap the white triangle button four times in interval of one second gap"
    #   → repeat=4, interval_s=1.0
    repeat:              int   = 1               # number of times to tap
    interval_s:          float = 0.0             # seconds to wait between taps

    # Step-anchored verification hint: tap is confirmed once this text appears.
    wait_after_text:     Optional[str] = None



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
        step_intent:     Optional[object] = None,
    ) -> DecisionPlan:
        """
        Main decision method: analyze screen + subgoal → produce action plan.

        step_intent (StepIntent, optional)
        ──────────────────────────────────
        In steps mode the orchestrator parses the current step string into a
        structured StepIntent (action, target_text, repeat, interval_s,
        wait_after, wait_seconds). When present it enables two deterministic
        fast paths BEFORE the VLM call:
          • Explicit wait     → return a wait plan with the parsed duration.
          • Exact-text anchor  → if the quoted step text matches a registry
            element exactly, return a SoM tap plan with the element's exact
            center (no pixel guessing). Solves the label+image + small-icon
            accuracy cases when the step names the target.


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

        # ── Step 0: Step-anchored deterministic fast paths (steps mode) ──────
        # When a StepIntent is available, two zero-LLM paths can resolve the
        # action with guaranteed pixel accuracy. Only used while not stuck so
        # repeated failures still fall through to the VLM for re-grounding.
        if step_intent is not None and stuck_count == 0:
            anchored = self._step_anchored_plan(perception, current_subgoal, step_intent)
            if anchored is not None:
                print(f"[decision_agent] ⚓ Step-anchored plan: "
                      f"action={anchored.action_type} "
                      f"target='{anchored.target_description[:40]}' "
                      f"conf={anchored.confidence:.2f}")
                return anchored

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

        # ── Phase-Aware Skill Injection ───────────────────────────────────────
        # NAVIGATION PHASE (launch → gameplay): inject NOTHING.
        #   VLM navigates by VISION only — annotated screenshot + pixel grid
        #   + OCR + XML accessibility tree.
        #
        # WHY: Injecting navigation .md text causes text-instruction bias:
        #   • VLM reads "tap Monkey Meadow" → uses ocr_center (text label center)
        #     instead of visually locating the image tile center.
        #   • 8000+ chars of mixed nav+gameplay text triggers hallucination.
        #   • Multiple .md files with conflicting coordinate rules cause the VLM
        #     to pick a wrong compromise instead of trusting the screenshot.
        #
        # GAMEPLAY PHASE (ACTIVE_GAMEPLAY / VERIFY_GAMEPLAY): inject gameplay
        #   tactics only. Navigation text is still excluded even in this phase.
        #   The game_skill loaded via load_gameplay_skill() contains only
        #   02_mechanics + 03_guide — no 01_navigation files.
        # ─────────────────────────────────────────────────────────────────────
        _GAMEPLAY_SUBGOALS = {
            "ACTIVE_GAMEPLAY", "VERIFY_GAMEPLAY",
            "START_GAMEPLAY",  "VERIFY_PLAYBACK",
        }
        is_gameplay_phase = (
            current_subgoal.upper().strip() in _GAMEPLAY_SUBGOALS
            or "ACTIVE_GAMEPLAY" in current_subgoal.upper()
        )

        extra_system = ""   # default: NOTHING injected during navigation

        if is_gameplay_phase and self._game_skill:
            # Gameplay phase only: inject engine hint + game-specific tactics
            eng = perception.rendering_engine
            if eng in ("UNITY", "CANVAS"):
                extra_system = f"\n\n## Engine Context\n{self._unity_skill[:600]}"
            elif eng == "UNREAL":
                extra_system = f"\n\n## Engine Context\n{self._ue5_skill[:600]}"
            extra_system += (
                f"\n\n{'═'*60}\n"
                f"## IN-GAME TACTICS (HIGH PRIORITY — active gameplay only)\n"
                f"These instructions apply while you are INSIDE the game.\n"
                f"{'═'*60}\n"
                f"{self._game_skill[:2000]}\n"
                f"{'═'*60}\n"
            )
            print(f"[decision_agent] GAMEPLAY phase — injecting game skill "
                  f"({min(len(self._game_skill), 2000)} chars)")
        elif self._game_skill:
            # Navigation phase: skill text withheld — VLM navigates by vision
            print(f"[decision_agent] NAVIGATION phase — game skill withheld "
                  f"(VLM navigates by screenshot vision only)")

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
    # Private: Step-Anchored Deterministic Planning (steps mode, no LLM)
    # -------------------------------------------------------------------------

    def _step_anchored_plan(
        self,
        p:           PerceptionState,
        subgoal:     str,
        step_intent: object,
    ) -> Optional[DecisionPlan]:
        """
        Build a pixel-accurate DecisionPlan directly from the parsed StepIntent,
        with NO LLM call, when the step gives us a deterministic anchor.

        Two anchors, in priority order:

          A. Explicit wait
             StepIntent.action == "wait" OR StepIntent.wait_seconds set.
             → return a wait plan with the parsed duration.

          B. Exact-text element anchor
             StepIntent.target_text (the quoted text in the step, e.g.
             'MONKEY MEADOW') matches a UIElement in the registry.
             → return a SoM tap plan whose coordinates ARE the element's exact
               center (composite center = IMAGE center, solving label+image;
               XML/OCR center for plain buttons). repeat / interval / wait_after
               are carried through from the StepIntent.

        Returns None when no deterministic anchor applies — the caller then
        proceeds to the normal heuristic-hint + VLM path (which now also gets
        the SoM registry overlay and can SELECT element_id by number).
        """
        action       = getattr(step_intent, "action", "tap")
        target_text  = getattr(step_intent, "target_text", None)
        repeat       = int(getattr(step_intent, "repeat", 1) or 1)
        interval_s   = float(getattr(step_intent, "interval_s", 0.0) or 0.0)
        wait_after   = getattr(step_intent, "wait_after", None)
        wait_seconds = getattr(step_intent, "wait_seconds", None)
        wait_after_text = (wait_after or {}).get("expect_text") if wait_after else None

        # ── Anchor A: explicit wait ──────────────────────────────────────
        if action == "wait" or wait_seconds is not None:
            dur = float(wait_seconds if wait_seconds is not None else 3.0)
            return DecisionPlan(
                screen_assessment=      f"Step-anchored wait {dur}s",
                subgoal_progress=       subgoal,
                rendering_engine=       p.rendering_engine,
                blocking_element=       None,
                action_type=            "wait",
                target_description=     f"wait {dur}s (from step)",
                locators=               [],
                fallback_bounds=        {},
                type_payload=           str(dur),
                template_name=          "",
                confidence=             0.96,
                reasoning=              f"StepIntent parsed explicit wait of {dur}s",
                subgoal_complete=       False,
                suggested_next_subgoal= None,
                repeat=                 1,
                interval_s=             0.0,
                wait_after_text=        wait_after_text,
            )

        # ── Anchor B: exact-text element anchor (the heart of accuracy) ──
        if not target_text:
            return None

        el = p.find_element_by_text(target_text)
        if el is None:
            # No registry match — let the SoM-augmented VLM path handle it.
            return None

        cx, cy = el.center
        x1, y1, x2, y2 = el.bbox
        return DecisionPlan(
            screen_assessment=      f"Step anchor '{target_text}' → registry element #{el.id} ({el.kind})",
            subgoal_progress=       subgoal,
            rendering_engine=       p.rendering_engine,
            blocking_element=       None,
            action_type=            "tap",
            target_description=     f"'{target_text}' ({el.kind} #{el.id}) at ({cx},{cy})",
            locators=               [{"type": "coords", "value": f"{cx},{cy}"}],
            fallback_bounds=        {"x1": x1, "y1": y1, "x2": x2, "y2": y2,
                                     "cx": cx, "cy": cy},
            type_payload=           "",
            template_name=          "",
            confidence=             0.93,
            reasoning=(
                f"Exact step-text anchor '{target_text}' matched registry "
                f"element #{el.id} (kind={el.kind}, source={el.source}). "
                f"Using its exact center ({cx},{cy}) — no pixel estimation."
            ),
            subgoal_complete=       False,
            suggested_next_subgoal= None,
            element_type=           "card" if el.kind == "composite" else None,
            element_id=             el.id,
            repeat=                 repeat,
            interval_s=             interval_s,
            wait_after_text=        wait_after_text,
        )

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

        # ── PRIORITY 0: Dynamic Wait Detection ───────────────────────────
        # Checks step text for an explicit duration AND OCR for loading
        # keywords.  Returns a wait hint BEFORE any tap logic so a step
        # like "wait for 40 seconds to load" is never converted to a tap.
        should_wait, wait_dur, wait_reason = self._detect_wait_condition(
            subgoal, p.all_text
        )
        if should_wait:
            # High confidence when the step text explicitly names a duration;
            # slightly lower when we infer from OCR loading keywords only.
            conf = 0.95 if "specifies" in wait_reason else 0.80
            print(f"[decision_agent] Dynamic wait hint: {wait_reason} "
                  f"({wait_dur}s, conf={conf:.2f})")
            return DecisionPlan(
                screen_assessment=      wait_reason,
                subgoal_progress=       subgoal,
                rendering_engine=       p.rendering_engine,
                blocking_element=       None,
                action_type=            "wait",
                target_description=     wait_reason,
                locators=               [],
                fallback_bounds=        {},
                type_payload=           str(wait_dur),
                template_name=          "",
                confidence=             conf,
                reasoning=              wait_reason,
                subgoal_complete=       False,
                suggested_next_subgoal= None,
            )

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
    def _detect_wait_condition(
        subgoal:  str,
        all_text: str,
    ) -> tuple[bool, float, str]:
        """
        Pure-Python wait detector — no LLM call.

        Returns (should_wait, duration_seconds, reason_string).

        Three sources checked in priority order:
          1. Explicit duration in step/subgoal text
             e.g. "wait for 40 seconds to load" → (True, 40.0, "Step specifies wait 40s")
          2. Step says "wait" (no duration) + OCR shows loading keyword
             e.g. "wait for Play screen" + OCR "Loading…" → (True, 3.0, "…")
          3. OCR shows clear loading keyword only (no wait in step)
             e.g. OCR "Connecting to server" → (True, 3.0, "…") (lower-conf hint)
        """
        # Source 1: explicit numeric duration in the step text
        m = _WAIT_DUR_RE.search(subgoal)
        if m:
            dur = float(m.group(1))
            return True, dur, f"Step specifies wait {dur}s"

        # Source 2 + 3: step says "wait" AND/OR OCR loading keyword
        step_says_wait = bool(re.search(r'\bwait\b', subgoal, re.IGNORECASE))
        ocr_lower      = all_text.lower()
        loading_hit    = next(
            (kw for kw in _LOADING_KEYWORDS if kw in ocr_lower), None
        )

        if step_says_wait and loading_hit:
            return True, 3.0, (
                f"Step says 'wait' + OCR loading keyword: '{loading_hit}'"
            )

        if loading_hit:
            # Screen is loading even without an explicit wait in the step
            return True, 3.0, f"OCR loading keyword detected: '{loading_hit}'"

        return False, 0.0, ""

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

        # ── SET-OF-MARK registry (numbered tappable proposals) ───────────
        # The annotated image sent to the VLM has numbered coloured boxes.
        # The VLM should SELECT a target by its number (element_id) instead of
        # estimating pixels — this is far more accurate on small icons and
        # label+image composites.
        registry = getattr(p, "element_registry", None) or []
        if registry:
            som_block = (
                f"\n▶ SET-OF-MARK ELEMENTS ({len(registry)} numbered, shown on image):\n"
                f"{getattr(p, 'registry_text', '')}\n"
                f"  ▸ Each [NN] is a numbered box drawn on the screenshot at its EXACT\n"
                f"    tap center (crosshair). 'composite' = image+label card (center is\n"
                f"    the IMAGE, not the text). 'icon' = graphic with no text.\n"
                f"  ▸ STRONGLY PREFER selecting one of these by number: set\n"
                f"    \"element_id\": NN in your JSON. The framework converts NN into the\n"
                f"    element's exact pixel center automatically — you do NOT need to\n"
                f"    output x,y for it. Only fall back to raw coordinates if the target\n"
                f"    is genuinely not in the numbered list.\n"
            )
        else:
            som_block = ""

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
            f"{som_block}\n"
            f"{hint_block}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"YOUR TASK — Cross-reference screenshot + XML + OCR then decide:\n"
            f"  1. If XML has a visible [TAP] element → use accessibility_id or text locator\n"
            f"  2. If game canvas (no XML) → use pixel coordinates from the screenshot grid\n"
            f"  3. CARD/TILE ELEMENTS — Look for CYAN-outlined boxes labelled 'CARD(cx,cy)'\n"
            f"     on the screenshot. These are auto-detected card elements (image + label).\n"
            f"     → The CARD(cx,cy) value shown IS the image center — use it directly.\n"
            f"     → Set fallback_bounds to the full cyan box bounds.\n"
            f"     → Set element_type='card' in your JSON response.\n"
            f"     → Do NOT use the text label's ocr_center for cards.\n"
            f"  4. MANUAL CARD DETECTION (if no cyan annotation present):\n"
            f"     fallback_bounds MUST cover the FULL visual element (image area + label).\n"
            f"     Set cx/cy to the CENTER of the IMAGE/ICON area, NOT the text label below it.\n"
            f"     Example: map thumbnail 200×140px image at y=400, label at y=545–570.\n"
            f"     → fallback_bounds: {{x1, y1=400, x2, y2=570, cx, cy=470}} (image center)\n"
            f"     → element_type='card'\n"
            f"  5. ocr_center locator: ONLY use for pure text buttons (e.g. 'PLAY', 'EASY').\n"
            f"     Do NOT use ocr_center for image thumbnails, map tiles, or icon buttons.\n"
            f"  6. Confidence >= 0.85 to act; if unsure set confidence=0.5\n\n"
            f"WAIT ACTION — CHECK FIRST (before planning any tap):\n"
            f"  W1. If the subgoal text says 'wait for X seconds' / 'wait X seconds' /\n"
            f"      'wait X sec' / 'wait X s':\n"
            f"      → action_type='wait',  type_payload='X'   (X as a plain number string)\n"
            f"      Examples: 'wait for 40 seconds' → type_payload='40.0'\n"
            f"                'wait 15 seconds'     → type_payload='15.0'\n"
            f"  W2. If OCR shows ANY of: Loading / Downloading / Connecting / Processing /\n"
            f"      Pending / Please wait / Reconnecting / Initializing / Server connection:\n"
            f"      → action_type='wait',  type_payload='3.0'\n"
            f"  W3. If subgoal says 'wait' (no explicit duration) AND OCR shows loading:\n"
            f"      → action_type='wait',  type_payload='3.0'\n"
            f"  W4. type_payload for wait MUST be a plain string number, e.g. '40.0', '3.0'\n\n"
            f"Return ONLY raw JSON — no markdown, no explanation."
        )

        # Prefer the SoM (numbered) overlay so the VLM can SELECT by number.
        primary_image = (
            getattr(p, "registry_annotated_b64", "")
            or p.annotated_b64
            or p.screenshot_b64
        )
        return self.build_image_message(primary_image, text_ctx)

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

        print("\n========== RAW GPT JSON ==========")
        print(json.dumps(raw, indent=2))
        print("==================================\n")

        locators        = raw.get("locators", []) or []
        fallback_bounds = raw.get("fallback_bounds", {}) or {}

        # ── Set-of-Mark resolution ───────────────────────────────────────
        # If the VLM SELECTED a numbered element (element_id), look up its
        # EXACT center in the registry and inject that as a coords locator +
        # fallback_bounds. This converts a "pick a number" answer into a
        # pixel-perfect tap target — no estimation involved.
        element_id = raw.get("element_id")
        try:
            element_id = int(element_id) if element_id is not None else None
        except (TypeError, ValueError):
            element_id = None

        if element_id is not None:
            el = p.get_element(element_id)
            if el is not None:
                cx, cy = el.center
                x1, y1, x2, y2 = el.bbox
                # Prepend the exact center so action_agent uses it first.
                locators        = [{"type": "coords", "value": f"{cx},{cy}"}] + locators
                fallback_bounds = {"x1": x1, "y1": y1, "x2": x2, "y2": y2,
                                   "cx": cx, "cy": cy}
                print(f"[decision_agent] SoM: VLM selected element #{element_id} "
                      f"({el.kind}, text='{el.text}') → exact center ({cx},{cy})")
            else:
                print(f"[decision_agent] SoM: VLM selected element #{element_id} "
                      f"but it is not in the registry — ignoring")
                element_id = None

        plan = DecisionPlan(
            screen_assessment=      raw.get("screen_assessment", ""),
            subgoal_progress=       raw.get("subgoal_progress", ""),
            rendering_engine=       raw.get("rendering_engine", p.rendering_engine),
            blocking_element=       raw.get("blocking_element"),
            action_type=            raw.get("action_type", "tap"),
            target_description=     raw.get("target_description", ""),
            locators=               locators,
            fallback_bounds=        fallback_bounds,
            type_payload=           raw.get("type_payload", ""),
            template_name=          raw.get("template_name", ""),
            confidence=             float(raw.get("confidence", 0.5)),
            reasoning=              raw.get("reasoning", ""),
            subgoal_complete=       bool(raw.get("subgoal_complete", False)),
            suggested_next_subgoal= raw.get("suggested_next_subgoal"),
            element_type=           raw.get("element_type"),
            element_id=             element_id,
        )

        # Carry through repeat / interval if the VLM echoed them.
        try:
            plan.repeat = max(1, int(raw.get("repeat", 1) or 1))
        except (TypeError, ValueError):
            plan.repeat = 1
        try:
            plan.interval_s = float(raw.get("interval_s", 0.0) or 0.0)
        except (TypeError, ValueError):
            plan.interval_s = 0.0
        return plan


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

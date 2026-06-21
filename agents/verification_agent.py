# agents/verification_agent.py
# =============================================================================
# Verification Agent — Post-Action State Verifier
# VERIFY phase: Did the action succeed? Is the subgoal complete?
#
# Three verification strategies, applied in order:
#   Stage 1 — Pixel diff (fast, engine-agnostic)
#   Stage 2 — SubGoal deterministic rules:
#               (a) Per-game subgoal_config.json  (require_any + exclude_if)
#               (b) Steps-mode NLP step completion
#               (c) Generic hardcoded fallback rules
#   Stage 3 — Blocking-element / large-change pass-through
#
# Key fixes vs previous version:
#   FIX-1  Per-game subgoal order loaded from subgoal_config.json
#          (8 stages for Bloons TD6, 5 for Subway Surfers, etc.)
#   FIX-2  Exclusion keyword guard in every gameplay-detection block:
#          if pre-game menu words are still visible → NOT yet in gameplay.
#   FIX-3  Steps mode: each NLP step string is treated as its own mini-subgoal;
#          GOAL_ACHIEVED only fires when the LAST step completes.
# =============================================================================
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Optional

from agents.base_agent import BaseAgent
from agents.perception_agent import PerceptionState
from agents.action_agent import ActionReport
from core.image_analyzer import ImageAnalyzer

# ─── Default (generic) subgoal order used when no per-game config is loaded ──
# Games with a subgoal_config.json override this list entirely.
SUBGOAL_ORDER = [
    "APP_LAUNCH",
    "NAVIGATE_TO_MAIN_MENU",
    "NAVIGATE_TO_LEVEL_SELECT",
    "START_GAMEPLAY",
    "VERIFY_GAMEPLAY",
]

# ─── Generic pre-game exclusion keywords ─────────────────────────────────────
# If ANY of these appear in OCR while we are in a "gameplay" subgoal, we know
# we are still on a configuration/menu screen and must NOT fire GOAL_ACHIEVED.
GENERIC_PREGAME_EXCLUSIONS = [
    "EASY", "MEDIUM", "HARD", "IMPOPPABLE",
    "SELECT", "DIFFICULTY", "STANDARD", "DEFLATION", "APOPALYPSE",
    "BEGINNER", "ADVANCED", "EXPERT",
    "HERO", "SHOP", "KNOWLEDGE",
    "SIGN IN", "LOG IN",
]


@dataclass
class VerificationResult:
    verdict:           str    # GOAL_ACHIEVED|SUBGOAL_COMPLETE|ACTION_SUCCESS|ACTION_FAILED|WRONG_NAVIGATION|BLOCKING_ELEMENT
    subgoal_complete:  bool
    goal_achieved:     bool
    pixel_diff_score:  float
    evidence:          list[str]
    next_subgoal:      Optional[str]
    reasoning:         str


class VerificationAgent(BaseAgent):
    SKILL_FILE = "04_verification_skill.md"

    def __init__(
        self,
        image_analyzer: ImageAnalyzer,
        llm,
        game_skill:      str  = "",
        subgoal_config:  dict = {},
    ) -> None:
        super().__init__(llm=llm, skill_file=self.SKILL_FILE)
        self._analyzer       = image_analyzer
        self._game_skill     = game_skill
        self._subgoal_config = subgoal_config  # loaded from subgoal_config.json

        # ── Per-game subgoal order (Suggestion 1) ────────────────────────────
        # If the game provides a subgoal_config.json we use that ordered list;
        # otherwise we fall back to the hardcoded generic SUBGOAL_ORDER.
        if subgoal_config and subgoal_config.get("subgoal_order"):
            self._subgoal_order: list[str] = subgoal_config["subgoal_order"]
            print(f"[verification_agent] Per-game subgoal order: {self._subgoal_order}")
        else:
            self._subgoal_order = list(SUBGOAL_ORDER)

        # ── Per-subgoal confirmation rules ───────────────────────────────────
        # Dict[str, {"require_any": [...], "exclude_if": [...]}]
        self._confirmations: dict = (
            subgoal_config.get("subgoal_confirmations", {})
            if subgoal_config else {}
        )

        # ── Game-specific HUD keywords extracted from the skill .md ──────────
        self._game_hud_keywords: list[str] = self._extract_hud_keywords(game_skill)
        if self._game_hud_keywords:
            print(f"[verification_agent] Game HUD keywords loaded: "
                  f"{self._game_hud_keywords[:10]}")

    # ─────────────────────────────────────────────────────────────────────────
    # Public — verify()
    # ─────────────────────────────────────────────────────────────────────────

    def verify(
        self,
        pre:              PerceptionState,
        post:             PerceptionState,
        action_report:    ActionReport,
        current_subgoal:  str,
        goal:             str,
        # Steps-mode context (Suggestion 3)
        mode:             str = "oneliner",
        current_step_index: int = 0,
        total_steps:      int = 0,
        # Step-anchored verification (Phase 1): expected next-screen text
        wait_after_text:  Optional[str] = None,
    ) -> VerificationResult:
        """
        Verify whether the last action advanced the app toward the current
        subgoal/step.

        Args:
            mode:               "oneliner" or "steps"
            current_step_index: zero-based index of the current step (steps mode)
            total_steps:        total number of steps in the recipe (steps mode)
            wait_after_text:    when set (from the StepIntent's wait directive),
                                the step only completes once this text is visible
                                in post-action OCR. Gates premature advancement.
        """

        evidence: list[str] = []

        # ── Stage 1: Pixel diff ───────────────────────────────────────────
        diff = 0.0
        if pre.screenshot_np is not None and post.screenshot_np is not None:
            diff = self._analyzer.pixel_diff(pre.screenshot_np, post.screenshot_np)
        evidence.append(f"pixel_diff={diff:.3f}")

        print("\n========== VERIFY ==========")
        print("SUBGOAL:", current_subgoal)
        print("ACTION :", action_report.action_type)
        print("SUCCESS:", action_report.success)
        print("DIFF   :", f"{diff:.3f}")
        print("OCR    :", post.all_text[:150])
        print("============================\n")

        # ── Detect if this is a steps-mode subgoal ────────────────────────
        # A steps-mode subgoal is a free-form NLP sentence (contains spaces).
        # Named subgoals like "APP_LAUNCH" or "VERIFY_GAMEPLAY" never have spaces.
        is_steps_mode = (
            mode == "steps"
            or (current_subgoal and " " in current_subgoal.strip())
        )

        # ── STEPS MODE (Suggestion 3) ─────────────────────────────────────
        if is_steps_mode:
            return self._verify_step(
                step_text=          current_subgoal,
                step_index=         current_step_index,
                total_steps=        total_steps,
                pre=                pre,
                post=               post,
                action_report=      action_report,
                diff=               diff,
                evidence=           evidence,
                wait_after_text=    wait_after_text,
            )


        # ── ONELINER MODE — use per-game config rules first ───────────────
        post_text = post.all_text.upper()

        # ── FIX-B: Gameplay subgoal fast path (replaces old FIX-B) ───────
        # Determine the final subgoal (the one that means GOAL_ACHIEVED).
        final_subgoal = self._subgoal_order[-1] if self._subgoal_order else "VERIFY_GAMEPLAY"
        gameplay_subgoals = {final_subgoal, "VERIFY_GAMEPLAY", "START_GAMEPLAY", "VERIFY_PLAYBACK"}

        if current_subgoal in gameplay_subgoals:
            return self._check_gameplay_subgoal(
                current_subgoal=current_subgoal,
                post=post,
                post_text=post_text,
                diff=diff,
                evidence=evidence,
            )

        # ── Stage 2 (a): Per-game confirmation rules ──────────────────────
        if current_subgoal in self._confirmations:
            result = self._apply_confirmation_rules(
                current_subgoal=current_subgoal,
                post_text=post_text,
                diff=diff,
                evidence=evidence,
            )
            if result is not None:
                return result

        # ── Stage 2 (b): Generic hardcoded rules (backward compat) ───────
        generic_result = self._check_generic_subgoal(
            current_subgoal=current_subgoal,
            post_text=post_text,
            post=post,
            diff=diff,
            evidence=evidence,
            action_report=action_report,
        )
        if generic_result is not None:
            return generic_result

        # ── Standard pixel diff short-circuit ────────────────────────────
        if diff < 0.01 and action_report.action_type not in ("wait", "sleep"):
            return VerificationResult(
                verdict="ACTION_FAILED", subgoal_complete=False, goal_achieved=False,
                pixel_diff_score=diff, evidence=evidence,
                next_subgoal=current_subgoal,
                reasoning="No pixel change detected — action had no visual effect",
            )

        # ── Stage 3: Large change → re-sense ─────────────────────────────
        if diff > 0.08:
            return VerificationResult(
                verdict="ACTION_SUCCESS", subgoal_complete=False, goal_achieved=False,
                pixel_diff_score=diff, evidence=evidence,
                next_subgoal=current_subgoal,
                reasoning=f"Action caused screen change (diff={diff:.2f}); re-sense to evaluate",
            )

        # Check for new blocking element
        block_kws = ["ALLOW", "DENY", "ACCEPT", "AGREE", "SKIP", "CLAIM",
                     "COLLECT", "OK", "CLOSE"]
        for bk in block_kws:
            if bk in post_text:
                evidence.append(f"blocking={bk}")
                return VerificationResult(
                    verdict="BLOCKING_ELEMENT", subgoal_complete=False, goal_achieved=False,
                    pixel_diff_score=diff, evidence=evidence, next_subgoal=current_subgoal,
                    reasoning=f"Blocking element detected: '{bk}'",
                )

        return VerificationResult(
            verdict="ACTION_SUCCESS", subgoal_complete=False, goal_achieved=False,
            pixel_diff_score=diff, evidence=evidence, next_subgoal=current_subgoal,
            reasoning="Small change detected; continuing toward subgoal",
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Steps Mode (Suggestion 3)
    # ─────────────────────────────────────────────────────────────────────────

    def _verify_step(
        self,
        step_text:     str,
        step_index:    int,
        total_steps:   int,
        pre:           PerceptionState,
        post:          PerceptionState,
        action_report: ActionReport,
        diff:          float,
        evidence:      list[str],
        wait_after_text: Optional[str] = None,
    ) -> VerificationResult:
        """
        Verify completion of a single NLP step (steps mode).


        A step is considered complete when:
          • The action itself succeeded (tier reported success) AND
          • The screen changed (diff > 0.015) OR it was a wait/verify action.

        Special case — "verify" steps:
          If the step text contains "verify", "check", "confirm", or "ensure",
          we extract key nouns from the step and look for them in OCR.  The step
          only completes when those nouns are found.

        Last step:
          When the last step completes → GOAL_ACHIEVED.
        """
        evidence.append(f"step={step_index}/{max(total_steps-1,0)}")
        step_upper  = step_text.upper()
        post_text   = post.all_text.upper()

        is_verify_step = any(v in step_upper for v in
                             ["VERIFY", "CHECK", "CONFIRM", "ENSURE", "ASSERT"])
        is_last_step   = (total_steps > 0 and step_index >= total_steps - 1)
        is_wait_action = action_report.action_type in ("wait", "sleep", "verify")

        evidence.append(f"is_verify_step={is_verify_step} is_last_step={is_last_step}")

        # ── Step-anchored WAIT gate (Phase 1) ────────────────────────────
        # If the StepIntent declared an expected next-screen text (e.g.
        # "...then wait for the 'EASY' screen"), the step must NOT complete
        # until that text is visible in post-action OCR. This prevents the
        # orchestrator from racing ahead through a loading transition.
        if wait_after_text:
            expect_up = wait_after_text.strip().upper()
            gate_ok   = expect_up in post_text
            evidence.append(f"wait_after='{expect_up}' satisfied={gate_ok}")
            if not gate_ok:
                return VerificationResult(
                    verdict="ACTION_SUCCESS", subgoal_complete=False, goal_achieved=False,
                    pixel_diff_score=diff, evidence=evidence, next_subgoal=step_text,
                    reasoning=(
                        f"Step waiting for expected screen text '{expect_up}' "
                        f"to appear before completing: {step_text[:40]}"
                    ),
                )

        # ── Verify-type step: trust VLM verdict first, OCR as fallback ───

        if is_verify_step:
            # PRIORITY 1: Trust VLM's explicit visual verify verdict.
            # If ActionAgent handled the step as action_type="verify" and
            # reported success=True, the VLM has already visually confirmed
            # the state — no OCR token matching needed.
            vlm_verified = (
                action_report.action_type in ("verify", "confirm", "assert", "check_state", "check")
                and action_report.success
            )
            if vlm_verified:
                step_complete = True
                reason = (
                    f"VLM visually confirmed step: '{step_text[:50]}' "
                    f"(action_type={action_report.action_type}, success=True)"
                )
            else:
                # PRIORITY 2: Fallback — OCR token matching (useful for steps like
                # "Verify PLAY button visible" where a specific label appears on screen)
                keywords = self._extract_step_keywords(step_text)
                found    = [kw for kw in keywords if kw in post_text]
                evidence.append(f"verify_kws_found={found}")
                if found:
                    step_complete = True
                    reason = f"Step '{step_text[:50]}' confirmed via OCR: {found}"
                else:
                    # Not confirmed yet — wait one more iteration
                    return VerificationResult(
                        verdict="ACTION_SUCCESS", subgoal_complete=False, goal_achieved=False,
                        pixel_diff_score=diff, evidence=evidence, next_subgoal=step_text,
                        reasoning=f"Verify step: waiting for OCR tokens {keywords[:5]}",
                    )
        else:
            # Action step: complete when action succeeded + screen changed
            screen_changed = (
                diff > 0.015
                or is_wait_action
                or action_report.success
            )
            evidence.append(f"screen_changed={screen_changed} diff={diff:.3f}")
            if screen_changed and action_report.success:
                step_complete = True
                reason = f"Step '{step_text[:50]}' complete (success, diff={diff:.3f})"
            elif not action_report.success:
                return VerificationResult(
                    verdict="ACTION_FAILED", subgoal_complete=False, goal_achieved=False,
                    pixel_diff_score=diff, evidence=evidence, next_subgoal=step_text,
                    reasoning=f"Step action failed — retrying: {step_text[:50]}",
                )
            else:
                # Action succeeded but no visible change yet (loading screen, etc.)
                return VerificationResult(
                    verdict="ACTION_SUCCESS", subgoal_complete=False, goal_achieved=False,
                    pixel_diff_score=diff, evidence=evidence, next_subgoal=step_text,
                    reasoning=f"Waiting for screen to reflect step: {step_text[:50]}",
                )

        # ── Step complete → decide if this was the last step ─────────────
        if is_last_step:
            print(f"[verification] ✅ LAST STEP COMPLETE → GOAL_ACHIEVED: {step_text[:60]}")
            return VerificationResult(
                verdict="GOAL_ACHIEVED", subgoal_complete=True, goal_achieved=True,
                pixel_diff_score=diff, evidence=evidence, next_subgoal=None,
                reasoning=reason,
            )

        # Advance to next step (orchestrator reads next_subgoal=None and
        # increments step_index itself — see orchestrator/graph.py).
        print(f"[verification] ✅ Step {step_index} complete → advance")
        return VerificationResult(
            verdict="SUBGOAL_COMPLETE", subgoal_complete=True, goal_achieved=False,
            pixel_diff_score=diff, evidence=evidence, next_subgoal=None,
            reasoning=reason,
        )

    @staticmethod
    def _extract_step_keywords(step_text: str) -> list[str]:
        """
        Extract meaningful nouns/proper nouns from a verify-step sentence.

        Strategy: take words > 3 chars, strip common English stop words,
        uppercase them for OCR comparison.
        """
        stop = {
            "THE", "AND", "FOR", "THAT", "WITH", "FROM", "ARE", "WAS",
            "HAS", "HAVE", "BEEN", "WILL", "THIS", "THEN", "INTO",
            "ANY", "WHEN", "OVER", "ALSO", "SHOULD", "APPEAR", "VISIBLE",
            "VERIFY", "CHECK", "CONFIRM", "ENSURE", "ASSERT",
        }
        words = re.findall(r"[A-Za-z]+", step_text.upper())
        return [w for w in words if len(w) > 3 and w not in stop]

    # ─────────────────────────────────────────────────────────────────────────
    # Gameplay Subgoal Check — FIX-B rewrite (Suggestion 2)
    # ─────────────────────────────────────────────────────────────────────────

    def _check_gameplay_subgoal(
        self,
        current_subgoal: str,
        post:            PerceptionState,
        post_text:       str,
        diff:            float,
        evidence:        list[str],
    ) -> VerificationResult:
        """
        FIX-B (rewritten):
        Confirm active gameplay using per-game require_any + HARD exclusion guard.

        Old FIX-B fired GOAL_ACHIEVED on `has_any_change = diff > 0.005` which
        was too loose — ANY pixel change on ANY screen triggered it.

        New logic:
          1. EXCLUSION GUARD — if pre-game menu keywords are visible → NOT gameplay.
          2. REQUIRE_ANY     — at least one real HUD token must appear in OCR.
          3. ANIMATION CHECK — canvas animation OR meaningful diff (> 0.02).
        """
        # ── 1. Exclusion guard (FIX-2 / Suggestion 2) ────────────────────
        # Pull game-specific exclusions first, fall back to generic list.
        config_excl: list[str] = []
        if current_subgoal in self._confirmations:
            config_excl = [w.upper() for w in
                           self._confirmations[current_subgoal].get("exclude_if", [])]
        excl_list = config_excl or [w.upper() for w in GENERIC_PREGAME_EXCLUSIONS]

        found_excl = [kw for kw in excl_list if kw in post_text]
        if found_excl:
            evidence.append(f"excluded_by={found_excl[:3]}")
            print(f"[verification] ⛔ FIX-B BLOCKED by exclusion: {found_excl[:3]} "
                  f"— still on pre-game screen")
            return VerificationResult(
                verdict="ACTION_SUCCESS", subgoal_complete=False, goal_achieved=False,
                pixel_diff_score=diff, evidence=evidence,
                next_subgoal=current_subgoal,
                reasoning=(
                    f"Exclusion guard triggered ({found_excl[:3]}) — "
                    "pre-game menu still visible, not in active gameplay yet"
                ),
            )

        # ── 2. Require at least one HUD keyword ──────────────────────────
        # Build HUD keyword list: game-specific (from skill md) + generic
        generic_hud = [
            "ROUND", "LIVES", "CASH", "SCORE", "HEALTH", "HP", "COINS",
            "TIME", "WAVE", "BLOONS", "TOWER", "GOLD", "MANA", "ENERGY",
            "UPGRADes", "TACK", "SHOOTER", "MONKEY", "DART", "SNIPER",
            "PAUSE", "SKIP INTRO", "MULTIPLIER", "KEYS",
        ]
        config_require: list[str] = []
        if current_subgoal in self._confirmations:
            config_require = [w.upper() for w in
                              self._confirmations[current_subgoal].get("require_any", [])]
        hud_list  = config_require or (self._game_hud_keywords + generic_hud)
        hud_found = [kw for kw in hud_list if kw in post_text]

        is_animating    = post.animation_score > 0.02
        meaningful_diff = diff > 0.02   # raised from 0.005 — FIX-2

        evidence.append(f"hud_found={hud_found[:5]}")
        evidence.append(f"animating={is_animating} anim_score={post.animation_score:.3f}")
        evidence.append(f"meaningful_diff={meaningful_diff}")

        # ── 3. Confirm: HUD found OR canvas is animating ─────────────────
        if hud_found or is_animating:
            reason = (
                f"FIX-B ({current_subgoal}): Gameplay confirmed — "
                f"hud={hud_found[:4]} anim={post.animation_score:.3f} diff={diff:.3f}"
            )
            print(f"[verification] ✅ {reason}")
            return VerificationResult(
                verdict="GOAL_ACHIEVED", subgoal_complete=True, goal_achieved=True,
                pixel_diff_score=diff, evidence=evidence, next_subgoal=None,
                reasoning=reason,
            )

        # Nothing conclusive yet — wait another loop
        return VerificationResult(
            verdict="ACTION_SUCCESS", subgoal_complete=False, goal_achieved=False,
            pixel_diff_score=diff, evidence=evidence,
            next_subgoal=current_subgoal,
            reasoning=f"{current_subgoal}: no gameplay signal yet — waiting for game loop",
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Per-game confirmation rules (Suggestion 1)
    # ─────────────────────────────────────────────────────────────────────────

    def _apply_confirmation_rules(
        self,
        current_subgoal: str,
        post_text:       str,
        diff:            float,
        evidence:        list[str],
    ) -> Optional[VerificationResult]:
        """
        Apply the require_any / exclude_if rules from subgoal_config.json.

        Returns a VerificationResult when a definitive verdict can be reached,
        or None to let Stage 2(b) generic rules run.
        """
        rules      = self._confirmations[current_subgoal]
        require    = [w.upper() for w in rules.get("require_any", [])]
        exclude    = [w.upper() for w in rules.get("exclude_if",  [])]

        found_excl = [kw for kw in exclude  if kw in post_text]
        found_req  = [kw for kw in require  if kw in post_text]

        evidence.append(f"config_require_found={found_req}")
        evidence.append(f"config_exclude_found={found_excl}")

        # Exclusion takes priority — if a pre-state keyword is present we
        # are still on the wrong screen even if some required words appear.
        if found_excl:
            return VerificationResult(
                verdict="ACTION_SUCCESS", subgoal_complete=False, goal_achieved=False,
                pixel_diff_score=diff, evidence=evidence,
                next_subgoal=current_subgoal,
                reasoning=(
                    f"Config exclude guard: {found_excl[:3]} visible — "
                    f"subgoal '{current_subgoal}' not yet complete"
                ),
            )

        if require and found_req:
            return self._make_subgoal_complete(
                current_subgoal, diff, evidence,
                f"Config rule match: {found_req[:4]} visible for '{current_subgoal}'"
            )

        if not require:
            # No require_any constraint — pixel diff alone is enough
            if diff > 0.02:
                return self._make_subgoal_complete(
                    current_subgoal, diff, evidence,
                    f"No OCR requirement for '{current_subgoal}'; screen changed (diff={diff:.3f})"
                )

        return None  # Inconclusive — fall through to generic rules

    # ─────────────────────────────────────────────────────────────────────────
    # Generic subgoal rules (backward compatibility / games without config)
    # ─────────────────────────────────────────────────────────────────────────

    def _check_generic_subgoal(
        self,
        current_subgoal: str,
        post_text:       str,
        post:            PerceptionState,
        diff:            float,
        evidence:        list[str],
        action_report:   ActionReport,
    ) -> Optional[VerificationResult]:
        """
        Original hardcoded subgoal rules kept for backward compatibility with
        games that have no subgoal_config.json.
        """
        if current_subgoal == "APP_LAUNCH":
            complete = bool(post.element_count > 0 or len(post_text) > 5)
            evidence.append(f"has_content={complete}")
            if complete:
                return self._make_subgoal_complete(
                    current_subgoal, diff, evidence, "App launched — content visible"
                )

        elif current_subgoal == "NAVIGATE_TO_MAIN_MENU":
            keywords = ["PLAY", "START", "BEGIN", "HOME", "MAIN"]
            found    = [kw for kw in keywords if kw in post_text]
            evidence.append(f"menu_keywords={found}")
            if found:
                return self._make_subgoal_complete(
                    current_subgoal, diff, evidence,
                    f"Main menu detected: {found}"
                )

        elif current_subgoal in ("NAVIGATE_TO_LEVEL_SELECT", "SELECT_MAP"):
            keywords = ["LEVEL", "STAGE", "MAP", "WORLD", "EASY", "HARD", "SELECT",
                        "BEGINNER", "ADVANCED"]
            found    = [kw for kw in keywords if kw in post_text]
            evidence.append(f"level_keywords={found}")
            if found or diff > 0.20:
                return self._make_subgoal_complete(
                    current_subgoal, diff, evidence,
                    f"Level/map select detected: {found or 'large screen change'}"
                )

        elif current_subgoal == "START_GAMEPLAY":
            # Legacy generic check — only fires on real animation, NOT on any change.
            evidence.append(f"stable={post.is_stable}")
            if not post.is_stable and post.animation_score > 0.05:
                return self._make_subgoal_complete(
                    current_subgoal, diff, evidence,
                    "Game loop active (animation detected)"
                )

        elif current_subgoal == "DISMISS_POPUPS":
            # Confirmed when typical main-menu words appear
            keywords = ["PLAY", "START", "HOME", "MAIN", "CONTINUE"]
            found    = [kw for kw in keywords if kw in post_text]
            if found:
                return self._make_subgoal_complete(
                    current_subgoal, diff, evidence,
                    f"Popup dismissed — main screen visible: {found}"
                )

        elif current_subgoal in ("SELECT_DIFFICULTY", "DISMISS_TUTORIAL",
                                  "SELECT_GAME_MODE"):
            # Generic: any significant screen change advances these
            if diff > 0.15:
                return self._make_subgoal_complete(
                    current_subgoal, diff, evidence,
                    f"Significant screen change (diff={diff:.2f}) — {current_subgoal} assumed complete"
                )

        return None  # Not handled → caller continues to Stage 3

    # ─────────────────────────────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _make_subgoal_complete(
        self,
        subgoal:  str,
        diff:     float,
        evidence: list[str],
        reason:   str,
    ) -> VerificationResult:
        """
        Advance to the next subgoal in the per-game (or generic) order.
        Returns next_subgoal=None only when this is the last subgoal
        (which makes the orchestrator fire GOAL_ACHIEVED).
        """
        order = self._subgoal_order
        try:
            idx = order.index(subgoal)
        except ValueError:
            idx = -1

        if idx == -1:
            # Subgoal not in list — treat as intermediate, no advancement
            next_sg = None
        elif idx + 1 >= len(order):
            # This IS the last subgoal → GOAL_ACHIEVED
            return VerificationResult(
                verdict="GOAL_ACHIEVED", subgoal_complete=True, goal_achieved=True,
                pixel_diff_score=diff, evidence=evidence, next_subgoal=None,
                reasoning=reason,
            )
        else:
            next_sg = order[idx + 1]

        return VerificationResult(
            verdict="SUBGOAL_COMPLETE", subgoal_complete=True, goal_achieved=False,
            pixel_diff_score=diff, evidence=evidence, next_subgoal=next_sg,
            reasoning=reason,
        )

    @staticmethod
    def _extract_hud_keywords(game_skill: str) -> list[str]:
        """
        Parse game-specific HUD keywords out of the loaded skill text.
        Looks for lines inside "## Detecting Active Gameplay" sections.
        Falls back to empty list if nothing found (generic keywords still apply).
        """
        if not game_skill:
            return []
        keywords:       list[str] = []
        inside_section: bool      = False
        for line in game_skill.splitlines():
            line_upper = line.strip().upper()
            if "DETECTING ACTIVE GAMEPLAY" in line_upper or "OCR KEYWORDS" in line_upper:
                inside_section = True
                continue
            if inside_section and line.startswith("##"):
                inside_section = False
            if inside_section:
                for word in line.replace(",", " ").split():
                    w = word.strip("`\"'#-*[]() ").upper()
                    if len(w) >= 2 and w.isalpha():
                        keywords.append(w)
        # Deduplicate, preserve order
        seen:   set      = set()
        result: list[str] = []
        for k in keywords:
            if k not in seen:
                seen.add(k)
                result.append(k)
        return result

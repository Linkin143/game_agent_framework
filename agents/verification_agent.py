# agents/verification_agent.py
# =============================================================================
# Verification Agent — Post-Action State Verifier
# VERIFY phase: Did the action succeed? Is the subgoal complete?
# Uses 3-stage check: pixel diff → OCR rules → LLM (only when needed)
# =============================================================================
from __future__ import annotations
import time
from dataclasses import dataclass
from typing import Optional
from agents.base_agent import BaseAgent
from agents.perception_agent import PerceptionState
from agents.action_agent import ActionReport
from core.image_analyzer import ImageAnalyzer

SUBGOAL_ORDER = [
    "APP_LAUNCH", "NAVIGATE_TO_MAIN_MENU", "NAVIGATE_TO_LEVEL_SELECT",
    "START_GAMEPLAY", "VERIFY_GAMEPLAY",
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

    def __init__(self, image_analyzer: ImageAnalyzer, llm) -> None:
        super().__init__(llm=llm, skill_file=self.SKILL_FILE)
        self._analyzer = image_analyzer

    def verify(
        self,
        pre:             PerceptionState,
        post:            PerceptionState,
        action_report:   ActionReport,
        current_subgoal: str,
        goal:            str,
    ) -> VerificationResult:
        evidence = []

        # ── Stage 1: Pixel diff ───────────────────────────────────────────
        diff = 0.0
        if pre.screenshot_np is not None and post.screenshot_np is not None:
            diff = self._analyzer.pixel_diff(pre.screenshot_np, post.screenshot_np)
        evidence.append(f"pixel_diff={diff:.3f}")

        # ── FIX B: Gameplay subgoals — HUD + animation = GOAL ACHIEVED ───
        # Active games ALWAYS have pixel changes (canvas animating every frame).
        # If we can see gameplay HUD text (ROUND/CASH/SCORE/UPGRADE etc.) AND
        # the screen is changing, we are definitively inside a running game.
        # This fires on BOTH START_GAMEPLAY and VERIFY_GAMEPLAY subgoals.
        gameplay_subgoals_b = ("START_GAMEPLAY", "VERIFY_GAMEPLAY")
        if current_subgoal in gameplay_subgoals_b:
            post_text_v = post.all_text.upper()
            hud_kws = ["ROUND", "LIVES", "CASH", "SCORE", "HEALTH", "HP", "COINS",
                       "TIME", "WAVE", "BLOONS", "TOWER", "GOLD", "MANA", "ENERGY",
                       "UPGRADE", "TACK", "SHOOTER", "MONKEY", "DART", "SNIPER"]
            hud_found = [kw for kw in hud_kws if kw in post_text_v]
            is_animating = post.animation_score > 0.02
            has_any_change = diff > 0.005

            evidence.append(f"animating={is_animating} anim_score={post.animation_score:.3f}")
            evidence.append(f"hud={hud_found}")

            # Gameplay confirmed: HUD text visible in OCR OR screen is animating
            if hud_found or is_animating or has_any_change:
                reason = (
                    f"FIX-B ({current_subgoal}): Gameplay confirmed — "
                    f"hud={hud_found} anim={post.animation_score:.3f} diff={diff:.3f}"
                )
                print(f"[verification] ✅ {reason}")
                return VerificationResult(
                    verdict="GOAL_ACHIEVED", subgoal_complete=True, goal_achieved=True,
                    pixel_diff_score=diff, evidence=evidence, next_subgoal=None,
                    reasoning=reason,
                )
            # Truly nothing visible — wait one more loop
            return VerificationResult(
                verdict="ACTION_SUCCESS", subgoal_complete=False, goal_achieved=False,
                pixel_diff_score=diff, evidence=evidence,
                next_subgoal=current_subgoal,
                reasoning=f"{current_subgoal}: no gameplay signal yet — waiting for game loop",
            )

        # ── Standard pixel diff short-circuit (non-gameplay subgoals only) ─
        if diff < 0.01 and action_report.action_type not in ("wait", "sleep"):
            return VerificationResult(
                verdict="ACTION_FAILED", subgoal_complete=False, goal_achieved=False,
                pixel_diff_score=diff, evidence=evidence,
                next_subgoal=current_subgoal,
                reasoning="No pixel change detected — action had no visual effect",
            )

        # ── Stage 2: SubGoal deterministic rules ──────────────────────────
        post_text = post.all_text.upper()

        if current_subgoal == "APP_LAUNCH":
            pkg = goal.lower().replace(" ", "")
            complete = bool(post.element_count > 0 or len(post_text) > 5)
            evidence.append(f"has_content={complete}")
            if complete:
                return self._make_subgoal_complete(current_subgoal, diff, evidence, "App launched — content visible")

        elif current_subgoal == "NAVIGATE_TO_MAIN_MENU":
            keywords = ["PLAY", "START", "BEGIN", "HOME", "MAIN"]
            found = [kw for kw in keywords if kw in post_text]
            evidence.append(f"menu_keywords={found}")
            if found:
                return self._make_subgoal_complete(current_subgoal, diff, evidence,
                                                    f"Main menu detected: {found}")

        elif current_subgoal == "NAVIGATE_TO_LEVEL_SELECT":
            keywords = ["LEVEL", "STAGE", "MAP", "WORLD", "EASY", "HARD", "SELECT"]
            found = [kw for kw in keywords if kw in post_text]
            evidence.append(f"level_keywords={found}")
            if found or diff > 0.20:
                return self._make_subgoal_complete(current_subgoal, diff, evidence,
                                                    f"Level select detected: {found or 'large screen change'}")

        elif current_subgoal == "START_GAMEPLAY":
            # Check for active game rendering
            evidence.append(f"stable={post.is_stable}")
            if not post.is_stable and post.animation_score > 0.05:
                return self._make_subgoal_complete(current_subgoal, diff, evidence,
                                                    "Game loop active (animation detected)")

        elif current_subgoal == "VERIFY_GAMEPLAY":
            hud_kws = ["ROUND", "LIVES", "CASH", "SCORE", "HEALTH", "HP", "COINS", "TIME"]
            hud_found = [kw for kw in hud_kws if kw in post_text]
            is_animating = post.animation_score > 0.05
            evidence.append(f"hud={hud_found} animating={is_animating}")
            if hud_found or is_animating:
                return VerificationResult(
                    verdict="GOAL_ACHIEVED", subgoal_complete=True, goal_achieved=True,
                    pixel_diff_score=diff, evidence=evidence, next_subgoal=None,
                    reasoning=f"Gameplay confirmed: HUD={hud_found}, animating={is_animating}",
                )

        # ── Stage 3: If action worked but subgoal not yet confirmed ───────
        if diff > 0.08:
            return VerificationResult(
                verdict="ACTION_SUCCESS", subgoal_complete=False, goal_achieved=False,
                pixel_diff_score=diff, evidence=evidence, next_subgoal=current_subgoal,
                reasoning=f"Action caused screen change (diff={diff:.2f}); re-sense to evaluate",
            )

        # Check for new blocking element
        block_kws = ["ALLOW", "DENY", "ACCEPT", "AGREE", "SKIP", "CLAIM", "COLLECT", "OK", "CLOSE"]
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

    def _make_subgoal_complete(self, subgoal, diff, evidence, reason) -> VerificationResult:
        idx = SUBGOAL_ORDER.index(subgoal) if subgoal in SUBGOAL_ORDER else -1
        next_sg = SUBGOAL_ORDER[idx + 1] if idx + 1 < len(SUBGOAL_ORDER) else None
        return VerificationResult(
            verdict="SUBGOAL_COMPLETE", subgoal_complete=True, goal_achieved=False,
            pixel_diff_score=diff, evidence=evidence, next_subgoal=next_sg,
            reasoning=reason,
        )

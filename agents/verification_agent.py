from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from agents.action_agent import ActionReport
from agents.base_agent import BaseAgent
from agents.decision_agent import DecisionPlan
from agents.perception_agent import PerceptionState
from core.image_analyzer import ImageAnalyzer
from core.screen_semantics import (
    screen_matches,
    summarize_perception,
)


@dataclass
class VerificationResult:
    verdict: str
    subgoal_complete: bool
    goal_achieved: bool
    pixel_diff_score: float
    evidence: list[str]
    next_subgoal: Optional[str]
    reasoning: str


class VerificationAgent(BaseAgent):
    """
    Verification has two modes:
      oneliner: verify goal progress from live screen truth + shared contract
      steps:    verify each explicit step as its own checkpoint
    """

    SKILL_FILE = "04_verification_skill.md"

    def __init__(
        self,
        image_analyzer: ImageAnalyzer,
        llm,
        game_skill: str = "",
    ) -> None:
        super().__init__(llm=llm, skill_file=self.SKILL_FILE)
        self._analyzer = image_analyzer
        self._game_skill = game_skill
        self._game_hud_keywords = self._extract_hud_keywords(game_skill)
        if self._game_hud_keywords:
            print(f"[verification_agent] Game HUD markers loaded: {self._game_hud_keywords[:10]}")

    def verify(
        self,
        pre: PerceptionState,
        post: PerceptionState,
        action_report: ActionReport,
        decision_plan: Optional[DecisionPlan],
        current_subgoal: str,
        goal: str,
        mode: str = "oneliner",
        current_step_index: int = 0,
        total_steps: int = 0,
        wait_after_text: Optional[str] = None,
    ) -> VerificationResult:
        evidence: list[str] = []
        pre_summary = summarize_perception(pre)
        post_summary = summarize_perception(post)

        diff = 0.0
        if pre.screenshot_np is not None and post.screenshot_np is not None:
            diff = self._analyzer.pixel_diff(pre.screenshot_np, post.screenshot_np)
        evidence.append(f"pixel_diff={diff:.3f}")
        evidence.append(f"pre_screen={pre_summary.label}")
        evidence.append(f"post_screen={post_summary.label}")

        print("\n========== VERIFY ==========")
        print("TASK  :", current_subgoal[:120])
        print("ACTION:", action_report.action_type)
        print("OK    :", action_report.success)
        print("DIFF  :", f"{diff:.3f}")
        print("OCR   :", post.all_text[:150])
        print("============================\n")

        if mode == "steps":
            return self._verify_step(
                step_text=current_subgoal,
                step_index=current_step_index,
                total_steps=total_steps,
                pre=pre,
                post=post,
                action_report=action_report,
                diff=diff,
                evidence=evidence,
                wait_after_text=wait_after_text,
            )

        return self._verify_goal_mode(
            pre=pre,
            post=post,
            pre_summary=pre_summary,
            post_summary=post_summary,
            action_report=action_report,
            decision_plan=decision_plan,
            goal=goal,
            diff=diff,
            evidence=evidence,
        )

    def _verify_goal_mode(
        self,
        pre: PerceptionState,
        post: PerceptionState,
        pre_summary,
        post_summary,
        action_report: ActionReport,
        decision_plan: Optional[DecisionPlan],
        goal: str,
        diff: float,
        evidence: list[str],
    ) -> VerificationResult:
        post_text = post.all_text.upper()

        if decision_plan is not None:
            contract = self._verify_plan_contract(
                pre_summary=pre_summary,
                post_summary=post_summary,
                action_report=action_report,
                decision_plan=decision_plan,
                diff=diff,
                evidence=evidence,
            )
            if contract is not None:
                return contract

        gameplay_words = self._game_hud_keywords or [
            "ROUND", "LIVES", "CASH", "SCORE", "COINS", "HP", "HEALTH",
            "WAVE", "PAUSE", "UPGRADE", "TOWER", "HERO", "ENERGY",
        ]
        gameplay_hits = [kw for kw in gameplay_words if kw in post_text]
        evidence.append(f"gameplay_hits={gameplay_hits[:6]}")

        if (
            post_summary.kind == "ACTIVE_GAMEPLAY"
            and (gameplay_hits or post.animation_score > 0.02)
            and any(token in (goal or "").upper() for token in ("GAMEPLAY", "PLAY", "WATCH", "RUN"))
        ):
            return VerificationResult(
                verdict="GOAL_ACHIEVED",
                subgoal_complete=True,
                goal_achieved=True,
                pixel_diff_score=diff,
                evidence=evidence,
                next_subgoal=None,
                reasoning=f"Goal achieved on active gameplay screen: {post_summary.label}",
            )

        block_kws = ["ALLOW", "DENY", "ACCEPT", "AGREE", "SKIP", "CLAIM", "COLLECT", "OK", "CLOSE"]
        blocking = [bk for bk in block_kws if bk in post_text]
        if blocking:
            evidence.append(f"blocking={blocking[:3]}")
            return VerificationResult(
                verdict="BLOCKING_ELEMENT",
                subgoal_complete=False,
                goal_achieved=False,
                pixel_diff_score=diff,
                evidence=evidence,
                next_subgoal=goal,
                reasoning=f"Blocking element detected: {blocking[:3]}",
            )

        if not action_report.success and action_report.action_type not in ("wait", "sleep", "verify", "confirm", "check"):
            return VerificationResult(
                verdict="ACTION_FAILED",
                subgoal_complete=False,
                goal_achieved=False,
                pixel_diff_score=diff,
                evidence=evidence,
                next_subgoal=goal,
                reasoning="Action executor reported failure before meaningful goal progress",
            )

        if diff < 0.01 and action_report.action_type not in ("wait", "sleep", "verify", "confirm", "check"):
            return VerificationResult(
                verdict="ACTION_FAILED",
                subgoal_complete=False,
                goal_achieved=False,
                pixel_diff_score=diff,
                evidence=evidence,
                next_subgoal=goal,
                reasoning="No visible screen change detected after action",
            )

        return VerificationResult(
            verdict="ACTION_SUCCESS",
            subgoal_complete=False,
            goal_achieved=False,
            pixel_diff_score=diff,
            evidence=evidence,
            next_subgoal=goal,
            reasoning=f"Goal not achieved yet; continue from current screen '{post_summary.label}'",
        )

    def _verify_plan_contract(
        self,
        pre_summary,
        post_summary,
        action_report: ActionReport,
        decision_plan: DecisionPlan,
        diff: float,
        evidence: list[str],
    ) -> Optional[VerificationResult]:
        expected_screen_match = screen_matches(post_summary, decision_plan.expected_next_screen)
        expected_type_match = screen_matches(post_summary, decision_plan.expected_screen_type)
        forbidden_hits = self._forbidden_outcome_hits(post_summary, decision_plan.forbidden_outcomes)
        same_screen = pre_summary.signature == post_summary.signature
        meaningful_change = diff > 0.02 or not same_screen
        progress_improved = bool(expected_screen_match or expected_type_match or meaningful_change)
        likely_goal_reached = bool(
            expected_screen_match
            or expected_type_match
            or (
                post_summary.kind == "ACTIVE_GAMEPLAY"
                and (decision_plan.goal_status in {"at_goal", "ahead"} or "GAMEPLAY" in decision_plan.expected_screen_type.upper())
            )
        )

        evidence.append(f"plan_observed={decision_plan.observed_screen}")
        evidence.append(f"plan_expected_screen={decision_plan.expected_next_screen}")
        evidence.append(f"plan_expected_screen_type={decision_plan.expected_screen_type}")
        evidence.append(f"plan_success_condition={decision_plan.success_condition}")
        evidence.append(f"plan_goal_progress_hint={decision_plan.goal_progress_hint}")
        evidence.append(f"plan_forbidden={decision_plan.forbidden_outcomes}")
        evidence.append(f"plan_goal_status={decision_plan.goal_status}")
        evidence.append(f"plan_expected_screen_match={expected_screen_match}")
        evidence.append(f"plan_expected_type_match={expected_type_match}")
        evidence.append(f"plan_forbidden_hits={forbidden_hits}")

        if decision_plan.goal_status == "blocked":
            return VerificationResult(
                verdict="ACTION_FAILED",
                subgoal_complete=False,
                goal_achieved=False,
                pixel_diff_score=diff,
                evidence=evidence,
                next_subgoal=decision_plan.goal_progress_hint or decision_plan.expected_next_screen or None,
                reasoning="Decision plan marked this path as blocked; re-plan instead of repeating the same action.",
            )

        if forbidden_hits and not progress_improved:
            return VerificationResult(
                verdict="ACTION_FAILED",
                subgoal_complete=False,
                goal_achieved=False,
                pixel_diff_score=diff,
                evidence=evidence,
                next_subgoal=decision_plan.goal_progress_hint or decision_plan.expected_next_screen or None,
                reasoning=(
                    "Post-action screen shows forbidden outcome evidence "
                    f"{forbidden_hits[:4]} instead of the expected progress."
                ),
            )

        if decision_plan.goal_status == "at_goal" or likely_goal_reached:
            return VerificationResult(
                verdict="GOAL_ACHIEVED",
                subgoal_complete=True,
                goal_achieved=True,
                pixel_diff_score=diff,
                evidence=evidence,
                next_subgoal=None,
                reasoning=(
                    f"Goal reached on '{post_summary.label}' via contract "
                    f"'{decision_plan.success_condition or decision_plan.expected_outcome}'."
                ),
            )

        if decision_plan.goal_status == "ahead" and (
            post_summary.kind == "ACTIVE_GAMEPLAY" or expected_screen_match or expected_type_match
        ):
            return VerificationResult(
                verdict="GOAL_ACHIEVED",
                subgoal_complete=True,
                goal_achieved=True,
                pixel_diff_score=diff,
                evidence=evidence,
                next_subgoal=None,
                reasoning=f"Screen truth is ahead of the previous plan: {post_summary.label}",
            )

        if action_report.success and (progress_improved or (meaningful_change and expected_screen_match)):
            reason = (
                f"Action advanced the shared contract: '{pre_summary.label}' -> '{post_summary.label}'"
            )
            return VerificationResult(
                verdict="ACTION_SUCCESS",
                subgoal_complete=False,
                goal_achieved=False,
                pixel_diff_score=diff,
                evidence=evidence,
                next_subgoal=decision_plan.goal_progress_hint or decision_plan.expected_next_screen or None,
                reasoning=reason,
            )

        if (
            action_report.action_type not in ("wait", "sleep", "verify", "confirm", "check")
            and action_report.success
            and not progress_improved
            and same_screen
            and diff < 0.01
        ):
            return VerificationResult(
                verdict="ACTION_FAILED",
                subgoal_complete=False,
                goal_achieved=False,
                pixel_diff_score=diff,
                evidence=evidence,
                next_subgoal=decision_plan.goal_progress_hint or decision_plan.expected_next_screen or None,
                reasoning=(
                    "Action reported success, but the shared screen contract did not change: "
                    f"still '{post_summary.label}' with no new expected evidence."
                ),
            )

        return None

    def _verify_step(
        self,
        step_text: str,
        step_index: int,
        total_steps: int,
        pre: PerceptionState,
        post: PerceptionState,
        action_report: ActionReport,
        diff: float,
        evidence: list[str],
        wait_after_text: Optional[str] = None,
    ) -> VerificationResult:
        evidence.append(f"step={step_index}/{max(total_steps - 1, 0)}")
        step_upper = step_text.upper()
        post_text = post.all_text.upper()
        post_summary = summarize_perception(post)

        is_verify_step = any(v in step_upper for v in ["VERIFY", "CHECK", "CONFIRM", "ENSURE", "ASSERT"])
        is_last_step = (total_steps > 0 and step_index >= total_steps - 1)
        is_wait_action = action_report.action_type in ("wait", "sleep", "verify")
        evidence.append(f"is_verify_step={is_verify_step} is_last_step={is_last_step}")

        if wait_after_text:
            expect_up = wait_after_text.strip().upper()
            gate_ok = expect_up in post_text
            evidence.append(f"wait_after='{expect_up}' satisfied={gate_ok}")
            if not gate_ok:
                return VerificationResult(
                    verdict="ACTION_SUCCESS",
                    subgoal_complete=False,
                    goal_achieved=False,
                    pixel_diff_score=diff,
                    evidence=evidence,
                    next_subgoal=step_text,
                    reasoning=f"Step waiting for expected screen text '{expect_up}'",
                )

        if is_verify_step:
            if self._is_gameplay_verify_step(step_upper):
                gameplay_hits = self._gameplay_verify_hits(post_text)
                evidence.append(f"gameplay_verify_hits={gameplay_hits}")
                if post_summary.kind == "ACTIVE_GAMEPLAY" and gameplay_hits:
                    step_complete = True
                    reason = (
                        "Gameplay verification passed from screen truth: "
                        f"{post_summary.label} with HUD evidence {gameplay_hits[:4]}"
                    )
                else:
                    step_complete = False

                if step_complete:
                    if is_last_step:
                        return VerificationResult(
                            verdict="GOAL_ACHIEVED",
                            subgoal_complete=True,
                            goal_achieved=True,
                            pixel_diff_score=diff,
                            evidence=evidence,
                            next_subgoal=None,
                            reasoning=reason,
                        )
                    return VerificationResult(
                        verdict="SUBGOAL_COMPLETE",
                        subgoal_complete=True,
                        goal_achieved=False,
                        pixel_diff_score=diff,
                        evidence=evidence,
                        next_subgoal=None,
                        reasoning=reason,
                    )

            vlm_verified = (
                action_report.action_type in ("verify", "confirm", "assert", "check_state", "check")
                and action_report.success
            )
            if vlm_verified:
                step_complete = True
                reason = f"VLM visually confirmed step: '{step_text[:50]}'"
            else:
                state_verified, reason = self._verify_step_by_screen_state(step_upper, post_summary, post_text)
                evidence.append(f"screen_state_verified={state_verified}")
                if state_verified:
                    step_complete = True
                else:
                    return VerificationResult(
                        verdict="ACTION_SUCCESS",
                        subgoal_complete=False,
                        goal_achieved=False,
                        pixel_diff_score=diff,
                        evidence=evidence,
                        next_subgoal=step_text,
                        reasoning="Verify step waiting for screen-state confirmation",
                    )
        else:
            screen_changed = diff > 0.015 or is_wait_action or action_report.success
            evidence.append(f"screen_changed={screen_changed} diff={diff:.3f}")
            if screen_changed and action_report.success:
                step_complete = True
                reason = f"Step '{step_text[:50]}' complete (success, diff={diff:.3f})"
            elif not action_report.success:
                return VerificationResult(
                    verdict="ACTION_FAILED",
                    subgoal_complete=False,
                    goal_achieved=False,
                    pixel_diff_score=diff,
                    evidence=evidence,
                    next_subgoal=step_text,
                    reasoning=f"Step action failed — retrying: {step_text[:50]}",
                )
            else:
                return VerificationResult(
                    verdict="ACTION_SUCCESS",
                    subgoal_complete=False,
                    goal_achieved=False,
                    pixel_diff_score=diff,
                    evidence=evidence,
                    next_subgoal=step_text,
                    reasoning=f"Waiting for screen to reflect step: {step_text[:50]}",
                )

        if is_last_step:
            return VerificationResult(
                verdict="GOAL_ACHIEVED",
                subgoal_complete=True,
                goal_achieved=True,
                pixel_diff_score=diff,
                evidence=evidence,
                next_subgoal=None,
                reasoning=reason,
            )

        return VerificationResult(
            verdict="SUBGOAL_COMPLETE",
            subgoal_complete=True,
            goal_achieved=False,
            pixel_diff_score=diff,
            evidence=evidence,
            next_subgoal=None,
            reasoning=reason,
        )

    def _gameplay_verify_hits(self, post_text: str) -> list[str]:
        hits: list[str] = []
        gameplay_words = self._game_hud_keywords or [
            "ROUND", "LIVES", "CASH", "UPGRADES", "WAVE", "HERO", "TOWER",
        ]
        for kw in gameplay_words:
            if kw in post_text:
                hits.append(kw)
        if "$" in post_text:
            hits.append("$")
        if re.search(r"\b\d+/\d+\b", post_text):
            hits.append("ROUND_FRACTION")
        return hits

    @staticmethod
    def _is_gameplay_verify_step(step_upper: str) -> bool:
        if not step_upper:
            return False
        wants_verify = any(v in step_upper for v in ("VERIFY", "CHECK", "CONFIRM", "ENSURE", "ASSERT"))
        gameplay_terms = any(term in step_upper for term in ("GAMEPLAY", "ROUND", "LIVES", "CASH"))
        return wants_verify and gameplay_terms

    def _verify_step_by_screen_state(self, step_upper: str, post_summary, post_text: str) -> tuple[bool, str]:
        if any(term in step_upper for term in ("LOADING", "CONNECTING", "WAITING")):
            if post_summary.kind == "LOADING":
                return True, f"Step confirmed on loading screen '{post_summary.label}'"

        if any(term in step_upper for term in ("DIALOG", "POPUP", "PERMISSION")):
            if post_summary.kind == "DIALOG":
                return True, f"Step confirmed on dialog screen '{post_summary.label}'"

        if any(term in step_upper for term in ("MAP", "LEVEL", "MODE", "DIFFICULTY", "SELECT")):
            if post_summary.kind == "SELECTION":
                return True, f"Step confirmed on selection screen '{post_summary.label}'"

        if any(term in step_upper for term in ("MENU", "HOME")):
            if post_summary.kind in {"MENU", "UI_SCREEN"}:
                return True, f"Step confirmed on menu-like screen '{post_summary.label}'"

        if any(term in step_upper for term in ("SEARCH", "RESULT", "JOIN", "ROOM", "LOBBY")):
            if post_summary.kind in {"UI_SCREEN", "MENU", "SELECTION"} and post_summary.label:
                return True, f"Step confirmed on UI screen '{post_summary.label}'"

        return False, ""

    @staticmethod
    def _forbidden_outcome_hits(post_summary, forbidden_outcomes: list[str]) -> list[str]:
        if not forbidden_outcomes:
            return []
        label_upper = (post_summary.label or "").upper()
        keyword_set = set(post_summary.keywords or [])
        hits: list[str] = []
        for item in forbidden_outcomes:
            value = str(item or "").strip().upper()
            if not value:
                continue
            if value in label_upper or value in keyword_set:
                hits.append(value)
        return hits

    @staticmethod
    def _extract_hud_keywords(game_skill: str) -> list[str]:
        if not game_skill:
            return []
        keywords: list[str] = []
        inside_section = False
        for line in game_skill.splitlines():
            line_upper = line.strip().upper()
            if any(
                marker in line_upper
                for marker in (
                    "DETECTING ACTIVE GAMEPLAY",
                    "HUD MARKERS",
                    "GAMEPLAY MARKERS",
                    "OCR KEYWORDS",  # legacy skill text support
                )
            ):
                inside_section = True
                continue
            if inside_section and line.startswith("##"):
                inside_section = False
            if inside_section:
                for word in line.replace(",", " ").split():
                    w = word.strip("`\"'#-*[]() ").upper()
                    if len(w) >= 2 and w.isalpha():
                        keywords.append(w)
        seen: set[str] = set()
        result: list[str] = []
        for k in keywords:
            if k not in seen:
                seen.add(k)
                result.append(k)
        return result

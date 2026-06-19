# agents/gameplay_agent.py
# =============================================================================
# Autonomous Gameplay Agent — Pure VLM-Driven Post-Navigation Loop
#
# Architecture: VLM + OCR + XML (no hardcoded tactic cards, no pixel tables)
#
# After the orchestrator confirms GOAL_ACHIEVED (gameplay screen reached),
# this agent takes over and plays the game for ``duration_s`` seconds using
# the full multimodal reasoning stack on every single tick:
#
# Execution flow per tick:
#   1. SENSE   : Fresh screenshot + OCR + XML tree via PerceptionAgent
#   2. DECIDE  : DecisionAgent (VLM) receives:
#                  • Live annotated screenshot (image)
#                  • OCR text extracted from the screen
#                  • XML accessibility tree (if available)
#                  • Game-specific gameplay guide (injected at agent init)
#                  • Current subgoal: "ACTIVE_GAMEPLAY — Xs remaining"
#                The VLM analyses all of this together and decides:
#                  • action_type (tap / drag_and_drop / swipe / wait)
#                  • target_description (natural-language description of target)
#                  • locators (visual/OCR coordinates it found from the screenshot)
#                  • fallback_bounds (bounding box of the target)
#   3. ACT     : ActionAgent executes the plan through the 3-tier repair matrix:
#                  Tier 1 → Semantic element (accessibility_id / text / res_id)
#                  Tier 2 → OCR center / OpenCV template / fuzzy text
#                  Tier 3 → Raw hardware coordinate tap (never skipped)
#   4. LOG     : Record tick, action, source, success, elapsed time
#   5. LOOP    : Repeat until duration_s expires
#
# Why no hardcoded coordinates?
#   The VLM (Claude Vision) sees the ACTUAL screenshot and picks coordinates
#   dynamically — this works on any device resolution, any screen state, and
#   any novel situation without requiring manual pixel tables.
#
# The gameplay guide (game_skills/<package>/03_gameplay_guide.md) is loaded
# once by GameSkillLoader and injected into DecisionAgent at framework init
# time — it automatically appears in every VLM call made during gameplay.
# =============================================================================
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from agents.perception_agent import PerceptionAgent
from agents.decision_agent   import DecisionAgent
from agents.action_agent     import ActionAgent


# ─── Action Log Entry ────────────────────────────────────────────────────────

@dataclass
class GameplayLogEntry:
    tick:        int
    elapsed:     float
    action_type: str
    target:      str
    reasoning:   str
    success:     bool
    tier_used:   int


# ─── Gameplay Agent ───────────────────────────────────────────────────────────

class GameplayAgent:
    """
    Autonomous post-navigation gameplay loop.

    After the orchestrator confirms GOAL_ACHIEVED (gameplay screen reached),
    this agent takes over and plays the game for ``duration_s`` seconds using
    pure VLM reasoning on every tick (screenshot + OCR + XML + gameplay guide).

    The game-specific gameplay guide (03_gameplay_guide.md) is already
    embedded inside DecisionAgent's system prompt via the ``game_skill``
    parameter — so every ``da.decide()`` call automatically includes the
    full strategic context for the current game without any extra wiring here.

    Usage
    ─────
        agent = GameplayAgent(pa, da, aa, game_skill="...")
        summary = agent.play(duration_s=300, action_interval_s=4.0)

    Returns
    ───────
        Summary dict:
            ticks         : int   — total ticks executed
            duration_s    : float — actual elapsed seconds
            total_actions : int   — actions where action_type != wait
            action_log    : list  — full per-tick log
    """

    def __init__(
        self,
        perception_agent: PerceptionAgent,
        decision_agent:   DecisionAgent,
        action_agent:     ActionAgent,
        game_skill:       str = "",
    ) -> None:
        """
        Args:
            perception_agent : SENSE layer — captures screenshot + OCR + XML.
            decision_agent   : VLM reasoning layer — already has game_skill
                               embedded in its system prompt via __init__.
            action_agent     : 3-tier execution layer.
            game_skill       : Raw gameplay guide text (used only for logging
                               here — DecisionAgent already holds it internally).
        """
        self._pa         = perception_agent
        self._da         = decision_agent
        self._aa         = action_agent
        self._game_skill = game_skill

        self._action_log: list[GameplayLogEntry] = []

        skill_chars = len(game_skill)
        print(f"[gameplay_agent] Initialised — VLM-only mode")
        print(f"[gameplay_agent] Game skill: {skill_chars} chars "
              f"({'embedded in VLM' if skill_chars else 'none — VLM uses generic reasoning'})")

    # ─────────────────────────────────────────────────────────────────────────
    # Public — play()
    # ─────────────────────────────────────────────────────────────────────────

    def play(
        self,
        duration_s:        int   = 300,
        action_interval_s: float = 4.0,
    ) -> dict:
        """
        Run the autonomous VLM gameplay loop for ``duration_s`` seconds.

        Every tick the agent:
          1. Captures a fresh screenshot + OCR + XML (SENSE)
          2. Sends everything to the VLM with the gameplay subgoal (DECIDE)
          3. Executes the VLM's chosen action through the 3-tier matrix (ACT)
          4. Waits ``action_interval_s`` before the next tick

        Args:
            duration_s:        Total gameplay duration in seconds (default 300 = 5 min).
            action_interval_s: Pause between ticks in seconds.
                               Increase this to reduce VLM API call frequency.
                               Minimum effective value: ~3.0s

        Returns:
            Summary dict with: ticks, duration_s, total_actions, action_log
        """
        start_time = time.time()
        tick        = 0
        self._action_log.clear()

        print(f"\n{'═'*62}")
        print(f"[gameplay] 🎮 GAMEPLAY LOOP START")
        print(f"[gameplay]    Duration  : {duration_s}s "
              f"({duration_s // 60}m {duration_s % 60}s)")
        print(f"[gameplay]    Tick gap  : {action_interval_s:.1f}s between actions")
        print(f"[gameplay]    Mode      : VLM + OCR + XML (pure visual reasoning)")
        print(f"{'═'*62}\n")

        while True:
            elapsed   = time.time() - start_time
            remaining = duration_s - elapsed
            if remaining <= 0:
                break

            tick += 1
            print(f"\n[gameplay] ── Tick {tick:03d} | "
                  f"{elapsed:.0f}s elapsed | {remaining:.0f}s remaining ──")

            # ── 1. SENSE ──────────────────────────────────────────────────
            perception = self._sense(tick)
            if perception is None:
                # sense failed — wait and retry next tick
                time.sleep(2.0)
                continue

            # Brief OCR preview for logging
            ocr_preview = perception.all_text[:80].replace("\n", " ")
            print(f"[gameplay]    OCR preview : {ocr_preview!r}")
            print(f"[gameplay]    Engine      : {perception.rendering_engine}")
            print(f"[gameplay]    Elements    : {perception.element_count}")

            # ── 2. DECIDE (VLM) ───────────────────────────────────────────
            plan = self._decide(perception, remaining, duration_s)
            if plan is None:
                print(f"[gameplay]    VLM decision failed — skipping tick")
                time.sleep(action_interval_s)
                continue

            print(f"[gameplay]    VLM action  : {plan.action_type}")
            print(f"[gameplay]    VLM target  : {plan.target_description[:70]}")
            print(f"[gameplay]    VLM conf    : {plan.confidence:.2f}")
            print(f"[gameplay]    VLM reason  : {plan.reasoning[:80]}")

            # ── 3. ACT ────────────────────────────────────────────────────
            if plan.action_type.lower() in ("wait", "sleep", "none", "observe"):
                # VLM decided nothing actionable — log and wait
                print(f"[gameplay]    → VLM chose to wait/observe this tick")
                self._log_entry(
                    tick=        tick,
                    elapsed=     elapsed,
                    action_type= "wait",
                    target=      plan.reasoning[:60],
                    reasoning=   plan.reasoning,
                    success=     True,
                    tier_used=   0,
                )
                time.sleep(action_interval_s)
                continue

            report = self._act(plan, perception, tick)

            # Log the result
            self._log_entry(
                tick=        tick,
                elapsed=     elapsed,
                action_type= plan.action_type,
                target=      plan.target_description[:60],
                reasoning=   plan.reasoning[:80],
                success=     report.success if report else False,
                tier_used=   report.tier_used if report else -1,
            )

            icon = "✅" if (report and report.success) else "❌"
            tier = report.tier_used if report else "?"
            print(f"[gameplay]    → {icon} Executed via Tier {tier}")

            # ── 4. WAIT ───────────────────────────────────────────────────
            # Always pause between ticks regardless of success/failure.
            # This gives the game time to render the result of the action.
            time.sleep(action_interval_s)

        # ── Loop finished ─────────────────────────────────────────────────
        total_elapsed = time.time() - start_time
        action_count  = sum(1 for e in self._action_log if e.action_type != "wait")
        wait_count    = sum(1 for e in self._action_log if e.action_type == "wait")
        success_count = sum(1 for e in self._action_log if e.success and e.action_type != "wait")

        print(f"\n{'═'*62}")
        print(f"[gameplay] ✅ LOOP ENDED — {total_elapsed:.1f}s elapsed")
        print(f"[gameplay]    Ticks          : {tick}")
        print(f"[gameplay]    Actions taken  : {action_count}")
        print(f"[gameplay]    Actions success: {success_count} / {action_count}")
        print(f"[gameplay]    Wait ticks     : {wait_count}")
        print(f"{'═'*62}\n")

        return {
            "ticks":         tick,
            "duration_s":    total_elapsed,
            "total_actions": action_count,
            "action_log":    [vars(e) for e in self._action_log],
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Private — SENSE
    # ─────────────────────────────────────────────────────────────────────────

    def _sense(self, tick: int):
        """
        Capture a fresh PerceptionState.
        Returns None on error so the caller can skip the tick gracefully.
        """
        try:
            perception = self._pa.sense(wait_for_stable=False)
            return perception
        except Exception as exc:
            print(f"[gameplay]    SENSE error (tick {tick}): {exc}")
            return None

    # ─────────────────────────────────────────────────────────────────────────
    # Private — DECIDE
    # ─────────────────────────────────────────────────────────────────────────

    def _decide(self, perception, remaining_s: float, total_s: int):
        """
        Call the VLM (DecisionAgent) with a gameplay-focused subgoal.

        The subgoal text tells the VLM:
          • It is in the active gameplay phase (not navigation)
          • How much time remains
          • What its strategic objective is

        The game-specific gameplay guide (03_gameplay_guide.md) is already
        embedded inside DecisionAgent's system prompt — the VLM reads it
        automatically on every call without any extra effort here.

        Returns None on error.
        """
        # Build a clear, gameplay-specific subgoal description.
        # The word "ACTIVE_GAMEPLAY" distinguishes this from navigation subgoals
        # in the DecisionAgent's heuristic path (which ignores it correctly).
        subgoal = (
            f"ACTIVE_GAMEPLAY — {remaining_s:.0f}s remaining out of {total_s}s total. "
            "You are IN the game. The navigation phase is complete. "
            "Your only job now is to play the game well. "
            "Follow the gameplay guide's decision loop: "
            "handle defeat/victory screens first, dismiss any popups, "
            "then place towers, use hero ability when ready, start rounds, "
            "and upgrade towers when affordable."
        )

        overall_goal = (
            f"Autonomously play the game for {remaining_s:.0f} more seconds. "
            "Keep the game alive, place towers strategically, and make "
            "progress through as many rounds as possible."
        )

        try:
            plan = self._da.decide(
                perception=      perception,
                current_subgoal= subgoal,
                goal=            overall_goal,
                stuck_count=     0,
            )
            return plan
        except Exception as exc:
            print(f"[gameplay]    DECIDE error: {exc}")
            return None

    # ─────────────────────────────────────────────────────────────────────────
    # Private — ACT
    # ─────────────────────────────────────────────────────────────────────────

    def _act(self, plan, perception, tick: int):
        """
        Execute the VLM's plan through ActionAgent's 3-tier repair matrix.
        Returns None on unexpected error.
        """
        try:
            report = self._aa.act(plan, perception)
            return report
        except Exception as exc:
            print(f"[gameplay]    ACT error (tick {tick}): {exc}")
            return None

    # ─────────────────────────────────────────────────────────────────────────
    # Private — Log
    # ─────────────────────────────────────────────────────────────────────────

    def _log_entry(
        self,
        tick:        int,
        elapsed:     float,
        action_type: str,
        target:      str,
        reasoning:   str,
        success:     bool,
        tier_used:   int,
    ) -> None:
        self._action_log.append(GameplayLogEntry(
            tick=        tick,
            elapsed=     round(elapsed, 1),
            action_type= action_type,
            target=      target,
            reasoning=   reasoning,
            success=     success,
            tier_used=   tier_used,
        ))

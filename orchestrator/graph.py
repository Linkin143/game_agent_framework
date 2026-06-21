# orchestrator/graph.py
# =============================================================================
# LangGraph Orchestration — SENSE → TEST → ACT → VERIFY Loop
# The central state machine that coordinates all 5 specialist agents.
#
# Supports two execution modes:
#   oneliner  — AI decomposes a single goal into per-game subgoals defined in
#               subgoal_config.json (8 stages for Bloons TD6, etc.)
#   steps     — Caller supplies an ordered list of NLP step strings; each step
#               is treated as its own mini-subgoal. GOAL_ACHIEVED fires only
#               when the LAST step completes. (FIX-3)
# =============================================================================
from __future__ import annotations

import time
from typing import Annotated, Any, Optional
from typing_extensions import TypedDict

from langgraph.graph import StateGraph, END

from agents.perception_agent import PerceptionAgent, PerceptionState
from agents.decision_agent import DecisionAgent
from agents.action_agent import ActionAgent
from agents.verification_agent import VerificationAgent, SUBGOAL_ORDER
from agents.memory_agent import MemoryAgent
from core.action_executor import ActionExecutor
from core.step_parser import parse_step, StepIntent

# ─── LangGraph Shared State ───────────────────────────────────────────────────

class GameAgentState(TypedDict):
    # Goal
    goal:              str
    app_package:       str

    # Mode + Steps (FIX-3: steps-as-subgoals)
    mode:              str          # "oneliner" | "steps"
    steps:             list         # NLP step strings (steps mode only)
    current_step_index: int         # zero-based index into steps[]

    # SubGoal tracking (oneliner mode OR step text in steps mode)
    current_subgoal:   str
    subgoal_index:     int
    stuck_count:       int
    retry_count:       int
    fallback_level:    int

    # Perception
    perception:        Optional[Any]   # PerceptionState
    pre_perception:    Optional[Any]   # Pre-action PerceptionState

    # Decision
    decision_plan:     Optional[Any]   # DecisionPlan

    # Action
    action_report:     Optional[Any]   # ActionReport

    # Verification
    verification:      Optional[Any]   # VerificationResult

    # Session
    iteration:         int
    max_iterations:    int
    action_log:        list[dict]
    start_time:        float
    goal_achieved:     bool
    error_message:     str

    # Memory
    use_replay:        bool
    replay_path:       Optional[Any]


# ─── Orchestrator ─────────────────────────────────────────────────────────────

class GameOrchestrator:
    """
    LangGraph-powered orchestrator that runs the SENSE→TEST→ACT→VERIFY loop.

    Two execution modes
    ───────────────────
    oneliner
        Pass only ``goal`` and ``app_package``.  The AI decomposes the goal
        into ordered subgoals driven by the per-game subgoal_config.json.

    steps
        Pass ``goal``, ``app_package``, AND a non-empty ``steps`` list.
        Each element of ``steps`` is a plain-English instruction
        (e.g. "Tap the PLAY button on the main menu").
        GOAL_ACHIEVED fires ONLY when the last step completes.

    Usage
    ─────
        orch = GameOrchestrator(...)
        # oneliner:
        result = orch.run(goal="Launch Bloons TD6", app_package="com...")
        # steps:
        result = orch.run(goal="...", app_package="com...", steps=[...])
    """

    MAX_ITERATIONS = 60   # raised from 40 — steps mode can have many steps
    MAX_STUCK      = 3
    MAX_FALLBACK   = 5

    def __init__(
        self,
        perception_agent:    PerceptionAgent,
        decision_agent:      DecisionAgent,
        action_agent:        ActionAgent,
        verification_agent:  VerificationAgent,
        memory_agent:        MemoryAgent,
        executor:            ActionExecutor,
    ) -> None:
        self._pa  = perception_agent
        self._da  = decision_agent
        self._aa  = action_agent
        self._va  = verification_agent
        self._ma  = memory_agent
        self._exe = executor
        self._graph = self._build_graph()

    # ─── Graph Construction ───────────────────────────────────────────────────

    def _build_graph(self) -> Any:
        g = StateGraph(GameAgentState)

        g.add_node("memory_check",  self._node_memory_check)
        g.add_node("sense",         self._node_sense)
        g.add_node("test",          self._node_test)
        g.add_node("act",           self._node_act)
        g.add_node("verify",        self._node_verify)
        g.add_node("fallback",      self._node_fallback)
        g.add_node("done",          self._node_done)

        g.set_entry_point("memory_check")

        # Memory check: use replay or go to live sensing
        g.add_conditional_edges("memory_check", self._route_memory, {
            "replay": "act",
            "live":   "sense",
        })

        g.add_edge("sense", "test")
        g.add_edge("test",  "act")
        g.add_edge("act",   "verify")

        g.add_conditional_edges("verify", self._route_verify, {
            "done":     "done",
            "next":     "sense",
            "fallback": "fallback",
        })

        g.add_edge("fallback", "sense")
        g.add_edge("done", END)

        return g.compile()

    # ─── Node Implementations ─────────────────────────────────────────────────

    def _node_memory_check(self, state: GameAgentState) -> GameAgentState:
        """Check replay buffer before doing any live sensing."""
        p = self._pa.sense(wait_for_stable=False)
        replay = self._ma.get_replay_path(p, state["goal"])
        state["perception"] = p
        if replay:
            state["use_replay"]  = True
            state["replay_path"] = replay
            print(f"[orchestrator] ✓ Replay path found — skipping live reasoning")
        else:
            state["use_replay"]  = False
            state["replay_path"] = None
        return state

    def _node_sense(self, state: GameAgentState) -> GameAgentState:
        """SENSE: Capture fresh tri-modal perception state."""
        mode_tag = (
            f"step {state.get('current_step_index', 0)+1}/"
            f"{len(state.get('steps', []))}"
            if state.get("mode") == "steps" else
            f"subgoal={state['current_subgoal']}"
        )
        print(f"\n{'─'*60}")
        print(f"[orchestrator] SENSE | iter={state['iteration']} | "
              f"{mode_tag} | stuck={state['stuck_count']}")
        perception = self._pa.sense(wait_for_stable=True)
        state["perception"]     = perception
        state["pre_perception"] = perception
        state["iteration"]      = state.get("iteration", 0) + 1
        return state

    def _node_test(self, state: GameAgentState) -> GameAgentState:
        """TEST: Decision agent analyzes screen and plans action."""
        perception = state["perception"]

        # ── STEPS MODE: parse the current step string into a StepIntent ────
        # The StepIntent provides a deterministic, regex-derived anchor
        # (quoted target text, repeat count, interval, wait directives) that
        # the DecisionAgent uses for step-anchored SoM targeting.
        step_intent: Optional[StepIntent] = None
        if state.get("mode") == "steps":
            step_intent = parse_step(state["current_subgoal"])
            print(f"[orchestrator] STEP INTENT → {step_intent.summary()}")
        # Stash for the VERIFY node (used for the wait_after_text gate).
        state["step_intent"] = step_intent

        plan = self._da.decide(

            perception=      perception,
            current_subgoal= state["current_subgoal"],
            goal=            state["goal"],
            stuck_count=     state.get("stuck_count", 0),
            step_intent=     step_intent,
        )
        state["decision_plan"] = plan
        print(f"[orchestrator] TEST → action={plan.action_type} "
              f"target='{plan.target_description[:40]}' conf={plan.confidence:.2f}")
        return state


    def _node_act(self, state: GameAgentState) -> GameAgentState:
        """ACT: Execute the planned action through 3-tier repair."""
        plan       = state["decision_plan"]
        perception = state["perception"]

        # ── APP_LAUNCH detection ──────────────────────────────────────────
        # Fires on iteration 1 when:
        #   • oneliner mode: current_subgoal == "APP_LAUNCH"
        #   • steps mode:    first step mentions "launch" (step_index==0, iter<=1)
        is_launch_step = self._is_app_launch_step(state)
        if is_launch_step:
            print(f"[orchestrator] APP_LAUNCH: activating {state['app_package']}")
            r = self._exe.activate_app(state["app_package"])
            from agents.action_agent import ActionReport
            report = ActionReport(
                success=r.success, tier_used=0, method="activate_app",
                coordinates=None, action_type="activate_app",
            )

        elif state.get("use_replay") and state.get("replay_path"):
            report = self._execute_replay_step(state)

        elif plan is not None:
            report = self._aa.act(plan, perception)

        else:
            from agents.action_agent import ActionReport
            report = ActionReport(
                success=False, tier_used=0, method="no_plan",
                coordinates=None, action_type="tap", error="No plan available",
            )

        state["action_report"] = report

        # Log action
        log_entry = {
            "iter":     state.get("iteration", 0),
            "subgoal":  state["current_subgoal"],
            "action":   plan.action_type if plan else "unknown",
            "target":   (plan.target_description[:40] if plan else ""),
            "tier":     report.tier_used,
            "success":  report.success,
        }
        state["action_log"] = state.get("action_log", []) + [log_entry]
        print(f"[orchestrator] ACT result: tier={report.tier_used} "
              f"method={report.method} success={report.success}")

        # ── FIX-A (unchanged): VLM says "wait/gameplay active" at high conf ─
        # Only applies in oneliner mode — steps mode uses explicit step tracking.
        if state.get("mode") != "steps":
            self._check_fixA_gameplay(state, plan, report)

        return state

    def _node_verify(self, state: GameAgentState) -> GameAgentState:
        """VERIFY: Capture post-action state and verify outcome."""
        pre    = state.get("pre_perception")
        report = state["action_report"]

        post = self._pa.sense(wait_for_stable=True)
        state["perception"] = post

        # ── Build steps-mode context for VerificationAgent ───────────────
        mode          = state.get("mode", "oneliner")
        step_index    = state.get("current_step_index", 0)
        steps         = state.get("steps", [])
        total_steps   = len(steps)

        # Step-anchored wait gate: pull expected next-screen text (if any)
        # from the StepIntent stashed by the TEST node.
        wait_after_text = None
        si = state.get("step_intent")
        if si is not None and getattr(si, "wait_after", None):
            wait_after_text = si.wait_after.get("expect_text")

        result = self._va.verify(
            pre=               pre or post,
            post=              post,
            action_report=     report,
            current_subgoal=   state["current_subgoal"],
            goal=              state["goal"],
            mode=              mode,
            current_step_index=step_index,
            total_steps=       total_steps,
            wait_after_text=   wait_after_text,
        )

        state["verification"] = result

        print(f"[orchestrator] VERIFY: {result.verdict} | "
              f"diff={result.pixel_diff_score:.3f} | {result.reasoning[:60]}")

        # ── Handle result ────────────────────────────────────────────────
        if result.goal_achieved:
            state["goal_achieved"] = True
            return state

        if result.subgoal_complete:
            if mode == "steps":
                # STEPS MODE (FIX-3): advance step index, not SUBGOAL_ORDER
                new_index = step_index + 1
                if new_index >= total_steps:
                    # All steps done → GOAL_ACHIEVED
                    print(f"[orchestrator] ✅ All {total_steps} steps complete → GOAL_ACHIEVED")
                    state["goal_achieved"] = True
                else:
                    next_step = steps[new_index]
                    print(f"[orchestrator] ✓ Step {step_index+1}/{total_steps} done → "
                          f"step {new_index+1}: '{next_step[:50]}'")
                    state["current_step_index"] = new_index
                    state["current_subgoal"]    = next_step
                    state["subgoal_index"]       = new_index
                    state["stuck_count"]         = 0
                    state["retry_count"]         = 0
                    self._record_action(state, report)
            else:
                # ONELINER MODE: advance via per-game subgoal list
                if result.next_subgoal:
                    print(f"[orchestrator] ✓ SubGoal '{state['current_subgoal']}' COMPLETE → "
                          f"next: '{result.next_subgoal}'")
                    state["current_subgoal"] = result.next_subgoal
                    state["subgoal_index"]   = (
                        SUBGOAL_ORDER.index(result.next_subgoal)
                        if result.next_subgoal in SUBGOAL_ORDER else 0
                    )
                    state["stuck_count"]  = 0
                    state["retry_count"]  = 0
                    self._record_action(state, report)
                else:
                    # next_subgoal=None in oneliner means it was the last one
                    # (VerificationAgent already fires GOAL_ACHIEVED in that case,
                    # but guard here just in case)
                    state["goal_achieved"] = True

        elif result.verdict == "ACTION_FAILED":
            state["stuck_count"] = state.get("stuck_count", 0) + 1
            state["retry_count"] = state.get("retry_count", 0) + 1
            print(f"[orchestrator] Action failed (stuck={state['stuck_count']})")

        else:
            state["stuck_count"] = 0
            state["retry_count"] = 0

        return state

    def _node_fallback(self, state: GameAgentState) -> GameAgentState:
        """FALLBACK: Progressive recovery when stuck."""
        level = state.get("fallback_level", 0) + 1
        state["fallback_level"] = level
        state["stuck_count"]    = 0
        print(f"[orchestrator] ⚠ FALLBACK level {level}")

        if level == 1:
            print("  FALLBACK_1: Force fresh perception (2s wait)")
            time.sleep(2.0)

        elif level == 2:
            print("  FALLBACK_2: Press BACK")
            self._exe.press_back()
            time.sleep(1.0)

        elif level == 3:
            print("  FALLBACK_3: Dismiss any dialog")
            p = self._pa.sense(wait_for_stable=False)
            for dismiss in ["OK", "Close", "X", "Cancel", "No thanks", "Dismiss"]:
                word = next(
                    (w for w in (p.ocr_result.words if p.ocr_result else [])
                     if dismiss.lower() in w.text.lower()), None
                )
                if word:
                    self._exe.tap_at(word.center[0], word.center[1])
                    print(f"  Dismissed: '{dismiss}'")
                    break

        elif level == 4:
            print("  FALLBACK_4: Force-stop and restart app")
            self._exe.force_stop_app(state["app_package"])
            time.sleep(2.0)
            self._exe.activate_app(state["app_package"])
            time.sleep(3.0)
            # Reset back to first subgoal / first step
            if state.get("mode") == "steps" and state.get("steps"):
                state["current_step_index"] = 0
                state["current_subgoal"]    = state["steps"][0]
            else:
                state["current_subgoal"]  = "APP_LAUNCH"
                state["subgoal_index"]    = 0
            state["use_replay"] = False

        else:
            print("  FALLBACK_5: Grid exploration tap")
            p = self._pa.sense(wait_for_stable=False)
            sw, sh = p.screen_w, p.screen_h
            zones = [
                (sw//6, sh//8), (sw//2, sh//8),
                (sw//6, sh//2), (sw//2, sh//2), (sw*5//6, sh//2),
                (sw//6, sh*7//8), (sw//2, sh*7//8), (sw*5//6, sh*7//8),
            ]
            for cx, cy in zones:
                self._exe.tap_at(cx, cy)
                time.sleep(0.5)

        return state

    def _node_done(self, state: GameAgentState) -> GameAgentState:
        """Final node: log completion."""
        elapsed = time.time() - state.get("start_time", time.time())
        mode    = state.get("mode", "oneliner")
        steps   = state.get("steps", [])
        print(f"\n{'═'*60}")
        if state.get("goal_achieved"):
            print(f"[orchestrator] ✅ GOAL ACHIEVED in {elapsed:.1f}s | "
                  f"{state.get('iteration',0)} iterations")
        else:
            print(f"[orchestrator] ⛔ Goal NOT achieved after {elapsed:.1f}s | "
                  f"max_iterations reached")
        print(f"  Goal: {state['goal']}")
        print(f"  Mode: {mode}")
        if mode == "steps":
            si = state.get("current_step_index", 0)
            print(f"  Steps completed: {si}/{len(steps)}")
            print(f"  Last step: {steps[si][:60] if si < len(steps) else '(all done)'}")
        else:
            print(f"  Last subgoal: {state.get('current_subgoal','?')}")
        print(f"  Actions taken: {len(state.get('action_log',[]))}")
        print(f"{'═'*60}\n")
        return state

    # ─── Edge Routing ─────────────────────────────────────────────────────────

    def _route_memory(self, state: GameAgentState) -> str:
        return "replay" if state.get("use_replay") else "live"

    def _route_verify(self, state: GameAgentState) -> str:
        if state.get("goal_achieved"):
            return "done"
        if state.get("iteration", 0) >= state.get("max_iterations", self.MAX_ITERATIONS):
            return "done"
        if state.get("stuck_count", 0) >= self.MAX_STUCK:
            if state.get("fallback_level", 0) >= self.MAX_FALLBACK:
                return "done"
            return "fallback"
        return "next"

    # ─── Public Run Method ────────────────────────────────────────────────────

    def run(self, goal: str, app_package: str, steps: list = None) -> dict:
        """
        Run the full SENSE→TEST→ACT→VERIFY loop until goal is achieved.

        Args:
            goal:        High-level goal: "Launch Bloons TD6 and go to gameplay"
            app_package: Android package: "com.netflix.NGP.BloonsTDSix"
            steps:       Optional ordered NLP steps list (activates steps mode).

        Returns:
            Final state dict with goal_achieved, action_log, and timing info.
        """
        steps = steps or []
        mode  = "steps" if steps else "oneliner"

        # Starting subgoal: first step text (steps mode) or "APP_LAUNCH" (oneliner)
        initial_subgoal     = steps[0] if steps else "APP_LAUNCH"
        initial_step_index  = 0

        initial_state: GameAgentState = {
            "goal":              goal,
            "app_package":       app_package,
            # Mode + steps
            "mode":              mode,
            "steps":             steps,
            "current_step_index": initial_step_index,
            # SubGoal
            "current_subgoal":   initial_subgoal,
            "subgoal_index":     0,
            "stuck_count":       0,
            "retry_count":       0,
            "fallback_level":    0,
            # Perception / plan / action / verification
            "perception":        None,
            "pre_perception":    None,
            "decision_plan":     None,
            "action_report":     None,
            "verification":      None,
            # Session
            "iteration":         0,
            "max_iterations":    self.MAX_ITERATIONS,
            "action_log":        [],
            "start_time":        time.time(),
            "goal_achieved":     False,
            "error_message":     "",
            # Memory
            "use_replay":        False,
            "replay_path":       None,
        }

        print(f"\n{'═'*60}")
        print(f"[orchestrator] 🎮 GOAL: {goal}")
        print(f"[orchestrator]    APP:  {app_package}")
        print(f"[orchestrator]    MODE: {mode.upper()}"
              + (f" ({len(steps)} steps)" if steps else ""))
        print(f"{'═'*60}\n")

        return self._graph.invoke(initial_state)

    # ─── Internal Helpers ─────────────────────────────────────────────────────

    def _is_app_launch_step(self, state: GameAgentState) -> bool:
        """
        Detect whether the current execution context is an app-launch action.

        Fires when:
          • oneliner mode AND current_subgoal == "APP_LAUNCH"  AND iteration <= 1
          • steps mode  AND step_index == 0                    AND step text
            contains "launch" (case-insensitive)               AND iteration <= 1
        """
        if state.get("iteration", 0) > 1:
            return False
        subgoal = state.get("current_subgoal", "")
        mode    = state.get("mode", "oneliner")
        if mode == "steps":
            return (
                state.get("current_step_index", 0) == 0
                and "launch" in subgoal.lower()
            )
        return subgoal == "APP_LAUNCH"

    def _check_fixA_gameplay(self, state: GameAgentState, plan, report) -> None:
        """
        FIX-A: VLM says 'wait' at high confidence AND description mentions gameplay
        → mark GOAL_ACHIEVED without waiting for verification.
        Only runs in oneliner mode.
        """
        gameplay_keywords = ("gameplay", "active", "already", "playing", "running",
                              "game is", "in-game", "round", "level started")
        if not (
            plan is not None
            and (plan.action_type or "").lower() in ("wait", "sleep", "pause", "verify")
            and report.success
            and plan.confidence >= 0.85
        ):
            return

        desc_lower       = (plan.target_description or "").lower()
        vlm_says_gameplay = any(kw in desc_lower for kw in gameplay_keywords)

        perception = state.get("perception")
        hud_keywords = ["round", "lives", "cash", "score", "upgrade", "tower",
                         "bloons", "wave", "health", "hp", "coins"]
        ocr_text_lower = (perception.all_text.lower() if perception else "")
        ocr_has_hud    = any(kw in ocr_text_lower for kw in hud_keywords)

        gameplay_subgoals = ("START_GAMEPLAY", "VERIFY_GAMEPLAY", "NAVIGATE_TO_LEVEL_SELECT",
                              "VERIFY_PLAYBACK")
        if vlm_says_gameplay or (ocr_has_hud and state.get("current_subgoal") in gameplay_subgoals):
            print(f"[orchestrator] ✅ FIX-A: VLM confirmed gameplay "
                  f"(vlm={vlm_says_gameplay} hud={ocr_has_hud}) → GOAL ACHIEVED")
            state["goal_achieved"] = True

    def _execute_replay_step(self, state: GameAgentState):
        """Execute one step from the replay buffer."""
        from agents.action_agent import ActionReport
        path   = state["replay_path"]
        iter_  = state.get("iteration", 0)
        if iter_ <= len(path.actions):
            action = path.actions[iter_ - 1]
            loc    = action.get("locator", {})
            lt, lv = loc.get("type", "coords"), str(loc.get("value", "540,1200"))
            if lt == "ocr_center" and "," in lv:
                cx, cy = [int(x) for x in lv.split(",")[:2]]
                r = self._exe.tap_at(cx, cy)
                return ActionReport(
                    success=r.success, tier_used=2, method="replay",
                    coordinates={"x": cx, "y": cy}, action_type="tap",
                )
        return ActionReport(
            success=False, tier_used=0, method="replay_oob",
            coordinates=None, action_type="tap", error="Replay out of bounds",
        )

    def _record_action(self, state: GameAgentState, report) -> None:
        """Record a completed action for replay buffer learning."""
        plan = state.get("decision_plan")
        if plan and report.success and report.coordinates:
            locs = plan.locators or []
            entry = {
                "step":        len(state.get("action_log", [])),
                "subgoal":     state["current_subgoal"],
                "action_type": plan.action_type,
                "locator":     locs[0] if locs else {
                    "type":  "coords",
                    "value": f"{report.coordinates['x']},{report.coordinates['y']}",
                },
                "label":   plan.target_description[:40],
                "success": True,
            }
            state["action_log"] = state.get("action_log", []) + [entry]

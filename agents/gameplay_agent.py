# agents/gameplay_agent.py
# =============================================================================
# Autonomous Gameplay Agent — Post-Navigation Timed Gameplay Loop
#
# Architecture: Option D+C (VLM-driven with deterministic tactic-card fallback)
#
# Execution flow per tick:
#   1. SENSE  : Fresh screenshot + OCR via PerceptionAgent
#   2. TACTIC : Scan parsed tactic cards (priority-sorted, cooldown-gated)
#               → If a card matches → execute deterministically (no VLM call)
#               → Handles defeat/victory/popup/tower-placement/upgrades/speed
#   3. VLM    : If no tactic matched → ask DecisionAgent what to do
#               → DecisionAgent receives live screen + game_skill tactical context
#   4. ACT    : Execute via ActionAgent (existing 3-tier repair matrix)
#   5. LOG    : Record tick, source, action, success, elapsed time
#   6. LOOP   : Repeat until duration_s expires
#
# Tactic Card Format (in *tactics*.md files):
#   ## TACTIC: NAME
#   priority: critical|high|normal|low
#   require_any: TOKEN1, TOKEN2   ← at least one must be in OCR
#   require_all: TOKEN1, TOKEN2   ← all must be in OCR
#   exclude_if:  TOKEN1, TOKEN2   ← any present → skip tactic
#   action_type: tap|drag_and_drop|swipe|wait
#   action_desc: plain English description
#   ocr_target:  OCR word to find and tap (beats coords)
#   coords:      x,y  (tap point or drag START — 1080×2340 reference)
#   end_coords:  x,y  (drag END for drag_and_drop)
#   fallback_end_coords: x,y  (alternate drop zone)
#   wait_after:  1.5  (seconds to sleep after tactic fires)
#   cooldown:    20.0 (min seconds between re-fires)
#
# All coordinates are at 1080×2340 reference — auto-scaled by screen_w.
# =============================================================================
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Optional, Tuple

from agents.perception_agent import PerceptionAgent
from agents.decision_agent import DecisionAgent
from agents.action_agent import ActionAgent
from core.action_executor import ActionExecutor


# ─── Tactic Card Dataclass ────────────────────────────────────────────────────

@dataclass
class TacticCard:
    """
    A single deterministic condition → action rule loaded from a
    game-specific *tactics*.md file.
    """
    name:                str
    priority:            str            = "normal"   # critical|high|normal|low
    require_any:         list[str]      = field(default_factory=list)
    require_all:         list[str]      = field(default_factory=list)
    exclude_if:          list[str]      = field(default_factory=list)
    action_type:         str            = "tap"      # tap|drag_and_drop|swipe|wait
    action_desc:         str            = ""
    ocr_target:          str            = ""         # OCR word to find + tap
    coords:              Optional[Tuple[int,int]] = None  # tap or drag START
    end_coords:          Optional[Tuple[int,int]] = None  # drag END
    fallback_end_coords: Optional[Tuple[int,int]] = None  # alternate drop
    wait_after:          float          = 1.0
    cooldown_s:          float          = 10.0


@dataclass
class TacticResult:
    matched:          bool
    tactic:           Optional[TacticCard] = None
    action_executed:  bool                 = False
    reason:           str                  = ""


# ─── Gameplay Agent ───────────────────────────────────────────────────────────

class GameplayAgent:
    """
    Autonomous post-navigation gameplay loop.

    After the orchestrator confirms GOAL_ACHIEVED (gameplay reached),
    this agent takes over and plays the game for ``duration_s`` seconds using:
      •  Deterministic tactic cards   (fast, zero VLM cost)
      •  VLM fallback via DecisionAgent (handles novel / unanticipated states)

    Usage
    ─────
        agent = GameplayAgent(pa, da, aa, executor, game_skill, tactics_text)
        summary = agent.play(duration_s=300)
    """

    PRIORITY_ORDER: dict[str, int] = {
        "critical": 0,
        "high":     1,
        "normal":   2,
        "low":      3,
    }
    DEFAULT_TICK_INTERVAL: float = 4.0  # seconds between VLM ticks

    def __init__(
        self,
        perception_agent: PerceptionAgent,
        decision_agent:   DecisionAgent,
        action_agent:     ActionAgent,
        executor:         ActionExecutor,
        game_skill:       str  = "",
        tactics_text:     str  = "",
    ) -> None:
        self._pa          = perception_agent
        self._da          = decision_agent
        self._aa          = action_agent
        self._exe         = executor
        self._game_skill  = game_skill

        # Parse tactic cards from the raw markdown text
        self._tactics: list[TacticCard] = self.parse_tactics(tactics_text)
        print(f"[gameplay_agent] Loaded {len(self._tactics)} tactic cards")
        if self._tactics:
            names = [t.name for t in self._tactics]
            print(f"[gameplay_agent] Tactics: {names}")

        # Per-tactic cooldown tracking: tactic_name → elapsed seconds at last fire
        self._last_fired: dict[str, float] = {}

        # Full action log for post-run reporting
        self._action_log: list[dict] = []

    # ─────────────────────────────────────────────────────────────────────────
    # Public — play()
    # ─────────────────────────────────────────────────────────────────────────

    def play(
        self,
        duration_s:       int   = 300,
        action_interval_s: float = 4.0,
    ) -> dict:
        """
        Run the autonomous gameplay loop for ``duration_s`` seconds.

        Args:
            duration_s:        How long to play in seconds (default 300 = 5 min).
            action_interval_s: Pause between ticks when VLM fallback fires
                               (tactic-matched ticks use wait_after instead).

        Returns:
            Summary dict: {ticks, duration_s, total_actions, action_log}
        """
        start_time = time.time()
        tick        = 0
        self._action_log.clear()
        self._last_fired.clear()

        print(f"\n{'═'*60}")
        print(f"[gameplay] 🎮 GAMEPLAY LOOP START — {duration_s}s ({duration_s//60}m {duration_s%60}s)")
        print(f"[gameplay] Tactic cards: {len(self._tactics)}")
        print(f"[gameplay] VLM fallback: enabled")
        print(f"{'═'*60}\n")

        while True:
            elapsed   = time.time() - start_time
            remaining = duration_s - elapsed
            if remaining <= 0:
                break

            tick += 1
            print(f"\n[gameplay] ⏱ Tick {tick} | {elapsed:.0f}s elapsed | {remaining:.0f}s remaining")

            # ── 1. SENSE ─────────────────────────────────────────────────
            try:
                perception = self._pa.sense(wait_for_stable=False)
            except Exception as exc:
                print(f"[gameplay] SENSE error: {exc} — skipping tick")
                time.sleep(2.0)
                continue

            ocr_text = perception.all_text.upper()
            print(f"[gameplay] OCR: {ocr_text[:100]}")

            # ── 2. TACTIC CHECK (deterministic, no VLM) ──────────────────
            result = self._try_tactics(ocr_text, perception, elapsed)

            if result.matched and result.action_executed:
                wait = result.tactic.wait_after if result.tactic else 1.0
                self._log(tick, elapsed, "tactic",
                          result.tactic.name if result.tactic else "?",
                          result.reason, True)
                time.sleep(wait)
                continue

            if result.matched and not result.action_executed:
                # Tactic fired but action failed — let VLM handle
                print(f"[gameplay] Tactic '{result.tactic.name if result.tactic else '?'}' "
                      f"matched but action failed → VLM fallback")

            # ── 3. VLM FALLBACK ───────────────────────────────────────────
            try:
                plan = self._da.decide(
                    perception=      perception,
                    current_subgoal= (
                        f"ACTIVE_GAMEPLAY — {remaining:.0f}s remaining. "
                        "Choose the single most useful game action right now. "
                        "Use HUD coordinates and game knowledge from skills."
                    ),
                    goal=(
                        f"Play the game autonomously for {remaining:.0f} more seconds. "
                        "Place towers, start rounds, upgrade, use abilities. "
                        "Handle defeat or victory states immediately."
                    ),
                    stuck_count=0,
                )
                if plan and plan.action_type not in ("wait", "sleep", "none"):
                    report = self._aa.act(plan, perception)
                    self._log(tick, elapsed, "vlm",
                              plan.action_type,
                              plan.target_description[:60],
                              report.success)
                    # Brief sleep before next tick
                    time.sleep(action_interval_s * 0.5)
                else:
                    print(f"[gameplay] VLM chose wait/none — sleeping {action_interval_s:.1f}s")
                    time.sleep(action_interval_s)

            except Exception as exc:
                print(f"[gameplay] VLM error: {exc}")
                time.sleep(action_interval_s)

        # ── Loop finished ─────────────────────────────────────────────────
        total_elapsed = time.time() - start_time
        tactic_count = sum(1 for e in self._action_log if e["source"] == "tactic")
        vlm_count    = sum(1 for e in self._action_log if e["source"] == "vlm")

        print(f"\n{'═'*60}")
        print(f"[gameplay] ✅ LOOP ENDED after {total_elapsed:.1f}s")
        print(f"[gameplay]   Ticks:          {tick}")
        print(f"[gameplay]   Tactic actions: {tactic_count}")
        print(f"[gameplay]   VLM actions:    {vlm_count}")
        print(f"[gameplay]   Total actions:  {len(self._action_log)}")
        print(f"{'═'*60}\n")

        return {
            "ticks":          tick,
            "duration_s":     total_elapsed,
            "tactic_actions": tactic_count,
            "vlm_actions":    vlm_count,
            "total_actions":  len(self._action_log),
            "action_log":     self._action_log,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Tactic Evaluation
    # ─────────────────────────────────────────────────────────────────────────

    def _try_tactics(
        self,
        ocr_text:   str,
        perception,
        elapsed:    float,
    ) -> TacticResult:
        """
        Scan all tactic cards in priority order (CRITICAL first).
        For each card: check cooldown → check conditions → execute if met.
        Returns on the FIRST matching card.
        """
        sorted_tactics = sorted(
            self._tactics,
            key=lambda t: self.PRIORITY_ORDER.get(t.priority, 2),
        )

        for tactic in sorted_tactics:
            # ── Cooldown gate ─────────────────────────────────────────
            last_fire = self._last_fired.get(tactic.name, -9999.0)
            if elapsed - last_fire < tactic.cooldown_s:
                continue

            # ── Condition gate ────────────────────────────────────────
            if not self._condition_met(tactic, ocr_text):
                continue

            # ── Execute ───────────────────────────────────────────────
            print(f"[gameplay] 🃏 Tactic '{tactic.name}' matched — executing")
            success = self._execute_tactic(tactic, perception)
            self._last_fired[tactic.name] = elapsed

            return TacticResult(
                matched=         True,
                tactic=          tactic,
                action_executed= success,
                reason=          f"{tactic.name}: {tactic.action_desc[:50]}",
            )

        return TacticResult(matched=False)

    def _condition_met(self, tactic: TacticCard, ocr_text: str) -> bool:
        """Return True when all conditions are satisfied."""
        # exclude_if: ANY matching token → skip
        for ex in tactic.exclude_if:
            if ex.upper() in ocr_text:
                return False
        # require_any: at least ONE must match
        if tactic.require_any:
            if not any(r.upper() in ocr_text for r in tactic.require_any):
                return False
        # require_all: ALL must match
        if tactic.require_all:
            if not all(r.upper() in ocr_text for r in tactic.require_all):
                return False
        return True

    # ─────────────────────────────────────────────────────────────────────────
    # Tactic Execution
    # ─────────────────────────────────────────────────────────────────────────

    def _execute_tactic(self, tactic: TacticCard, perception) -> bool:
        """
        Execute a matched tactic card.

        Coordinate scaling:
            All tactic coords are at 1080×2340 reference.
            We scale by perception.screen_w / 1080 to fit the actual device.
        """
        scale = perception.screen_w / 1080
        print(f"[gameplay]   action_type={tactic.action_type} "
              f"desc='{tactic.action_desc[:40]}'")

        try:
            if tactic.action_type == "tap":
                return self._exec_tap(tactic, perception, scale)

            elif tactic.action_type == "drag_and_drop":
                return self._exec_drag(tactic, perception, scale)

            elif tactic.action_type == "swipe":
                return self._exec_swipe(tactic, perception, scale)

            elif tactic.action_type == "wait":
                time.sleep(tactic.wait_after)
                return True

            else:
                print(f"[gameplay]   Unknown action_type '{tactic.action_type}' — skip")
                return False

        except Exception as exc:
            print(f"[gameplay]   Tactic execution error: {exc}")
            return False

    def _exec_tap(self, tactic: TacticCard, perception, scale: float) -> bool:
        """Tap: try OCR word center first, fall back to coords."""
        # Try OCR target (more accurate than static coords)
        if tactic.ocr_target and perception.ocr_result:
            target_upper = tactic.ocr_target.upper()
            word = next(
                (w for w in (perception.ocr_result.words or [])
                 if target_upper in w.text.upper()),
                None,
            )
            if word:
                cx, cy = word.center
                r = self._exe.tap_at(cx, cy)
                print(f"[gameplay]   OCR-tap '{tactic.ocr_target}' at ({cx},{cy})"
                      f" → success={r.success}")
                return r.success

        # Fallback to fixed coords
        if tactic.coords:
            x = int(tactic.coords[0] * scale)
            y = int(tactic.coords[1] * scale)
            r = self._exe.tap_at(x, y)
            print(f"[gameplay]   Coord-tap ({x},{y}) → success={r.success}")
            return r.success

        print(f"[gameplay]   No tap target for tactic '{tactic.name}'")
        return False

    def _exec_drag(self, tactic: TacticCard, perception, scale: float) -> bool:
        """Drag from coords → end_coords; retry with fallback_end_coords."""
        if not tactic.coords or not tactic.end_coords:
            print(f"[gameplay]   drag_and_drop missing coords for '{tactic.name}'")
            return False

        sx = int(tactic.coords[0] * scale)
        sy = int(tactic.coords[1] * scale)
        ex = int(tactic.end_coords[0] * scale)
        ey = int(tactic.end_coords[1] * scale)

        r = self._exe.drag_and_drop(sx, sy, ex, ey)
        print(f"[gameplay]   drag ({sx},{sy})→({ex},{ey}) → success={r.success}")

        if not r.success and tactic.fallback_end_coords:
            fx = int(tactic.fallback_end_coords[0] * scale)
            fy = int(tactic.fallback_end_coords[1] * scale)
            r = self._exe.drag_and_drop(sx, sy, fx, fy)
            print(f"[gameplay]   drag fallback ({sx},{sy})→({fx},{fy})"
                  f" → success={r.success}")

        return r.success

    def _exec_swipe(self, tactic: TacticCard, perception, scale: float) -> bool:
        """Swipe from coords to end_coords."""
        if not tactic.coords or not tactic.end_coords:
            print(f"[gameplay]   swipe missing coords for '{tactic.name}'")
            return False

        sx = int(tactic.coords[0] * scale)
        sy = int(tactic.coords[1] * scale)
        ex = int(tactic.end_coords[0] * scale)
        ey = int(tactic.end_coords[1] * scale)

        r = self._exe.swipe_from_to(sx, sy, ex, ey)
        print(f"[gameplay]   swipe ({sx},{sy})→({ex},{ey}) → success={r.success}")
        return r.success

    # ─────────────────────────────────────────────────────────────────────────
    # Logging
    # ─────────────────────────────────────────────────────────────────────────

    def _log(
        self,
        tick:    int,
        elapsed: float,
        source:  str,
        name:    str,
        reason:  str,
        success: bool,
    ) -> None:
        icon = "✅" if success else "❌"
        print(f"[gameplay] {icon} [{source.upper()}] {name}: {reason[:60]}")
        self._action_log.append({
            "tick":    tick,
            "elapsed": round(elapsed, 1),
            "source":  source,   # "tactic" | "vlm"
            "name":    name,
            "reason":  reason[:80],
            "success": success,
        })

    # ─────────────────────────────────────────────────────────────────────────
    # Static — Tactic Card Parser
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def parse_tactics(tactics_text: str) -> list[TacticCard]:
        """
        Parse one or more tactic cards from a raw markdown string.

        Each card starts with a line matching:
            ## TACTIC: <NAME>
        Followed by ``key: value`` pairs (one per line).

        Lines starting with "#" (comments) are ignored outside card sections.
        Returns a list of TacticCard instances sorted CRITICAL-first.
        """
        if not tactics_text:
            return []

        cards:        list[TacticCard] = []
        current_data: dict             = {}

        for raw_line in tactics_text.splitlines():
            line = raw_line.strip()

            # New tactic card header
            if line.startswith("## TACTIC:"):
                if current_data.get("name"):
                    card = GameplayAgent._build_card(current_data)
                    if card:
                        cards.append(card)
                tactic_name = line.split(":", 1)[1].strip()
                current_data = {"name": tactic_name}
                continue

            # Skip lines outside of a card section
            if not current_data.get("name"):
                continue

            # Skip pure comment lines and blank lines
            if not line or line.startswith("#"):
                continue

            # Parse key: value
            if ":" in line:
                # Strip markdown decoration (-, *, spaces, bold markers)
                clean = re.sub(r"^[\-\*\s]+", "", line)
                clean = clean.replace("**", "")
                key, _, value = clean.partition(":")
                key   = key.strip().lower().replace(" ", "_")
                value = value.strip()
                if key and value:
                    current_data[key] = value

        # Don't forget the last card
        if current_data.get("name"):
            card = GameplayAgent._build_card(current_data)
            if card:
                cards.append(card)

        # Sort: CRITICAL first
        priority_order = {"critical": 0, "high": 1, "normal": 2, "low": 3}
        cards.sort(key=lambda c: priority_order.get(c.priority, 2))

        return cards

    @staticmethod
    def _build_card(data: dict) -> Optional[TacticCard]:
        """
        Convert a raw key-value dict into a TacticCard instance.
        Returns None if parsing fails (e.g., malformed coords).
        """
        def parse_list(s: str) -> list[str]:
            """Parse comma-separated token list, uppercase."""
            if not s:
                return []
            return [x.strip().upper() for x in s.split(",") if x.strip()]

        def parse_coords(s: str) -> Optional[Tuple[int, int]]:
            """Parse 'x,y' → (int, int) or None."""
            if not s:
                return None
            parts = [p.strip() for p in s.split(",")]
            if len(parts) >= 2:
                try:
                    return (int(parts[0]), int(parts[1]))
                except ValueError:
                    pass
            return None

        try:
            return TacticCard(
                name=                data["name"],
                priority=            data.get("priority", "normal").strip().lower(),
                require_any=         parse_list(data.get("require_any", "")),
                require_all=         parse_list(data.get("require_all", "")),
                exclude_if=          parse_list(data.get("exclude_if", "")),
                action_type=         data.get("action_type", "tap").strip().lower(),
                action_desc=         data.get("action_desc", ""),
                ocr_target=          data.get("ocr_target", "").strip(),
                coords=              parse_coords(data.get("coords", "")),
                end_coords=          parse_coords(data.get("end_coords", "")),
                fallback_end_coords= parse_coords(data.get("fallback_end_coords", "")),
                wait_after=          float(data.get("wait_after", "1.0")),
                cooldown_s=          float(data.get("cooldown",   "10.0")),
            )
        except Exception as exc:
            print(f"[gameplay_agent] ⚠ Failed to build tactic "
                  f"'{data.get('name','?')}': {exc}")
            return None

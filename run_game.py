# run_game.py
# =============================================================================
# Master Entry Point — Goal-Driven Multi-Agentic Game Framework
#
# Usage:
#   python run_game.py "Launch Bloons TD6 and go to gameplay"
#   python run_game.py "Play Subway Surfers" --package com.kiloo.subwaysurf
#   python run_game.py "Open Netflix and watch a movie"
#
# Environment:
#   Copy example.env to .env and configure APPIUM_SERVER_URL, ANTHROPIC_API_KEY
# =============================================================================
from __future__ import annotations

import argparse
import os
import sys
import time
import warnings
from pathlib import Path

# ── Suppress PyTorch/EasyOCR non-critical warnings ────────────────────────────
# "pin_memory is set as true but no accelerator is found" — safe to ignore on CPU
warnings.filterwarnings("ignore", message=".*pin_memory.*")
os.environ.setdefault("PYTORCH_NO_CUDA_MEMORY_CACHING", "1")
# Suppress EasyOCR/torch deprecation noise
warnings.filterwarnings("ignore", category=UserWarning, module="torch")
warnings.filterwarnings("ignore", category=FutureWarning, module="torch")

# Load .env file if present
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent / ".env"
    if not env_path.exists():
        env_path = Path(__file__).parent / "example.env"
    load_dotenv(env_path)
    print(f"[run_game] Loaded env: {env_path}")
except ImportError:
    pass

from langchain_anthropic import ChatAnthropic

from config.capabilities import get_driver
from core.screen_capture     import ScreenCapturer
from core.ocr_engine         import OCREngine
from core.xml_extractor      import XMLExtractor
from core.image_analyzer     import ImageAnalyzer
from core.action_executor    import ActionExecutor
from core.game_skill_loader  import GameSkillLoader
from agents.perception_agent    import PerceptionAgent
from agents.decision_agent      import DecisionAgent
from agents.action_agent        import ActionAgent
from agents.verification_agent  import VerificationAgent
from agents.memory_agent        import MemoryAgent
from agents.gameplay_agent      import GameplayAgent        # NEW: 5-min gameplay loop
from orchestrator.graph         import GameOrchestrator

# ─── Known App Packages ───────────────────────────────────────────────────────
KNOWN_PACKAGES = {
    "bloons td6":     "com.netflix.NGP.BloonsTDSix",
    "netflix":        "com.netflix.mediaclient",
}


def detect_package(goal: str, explicit_package: str = "") -> str:
    """Auto-detect app package from goal text or use explicit override."""
    if explicit_package:
        return explicit_package
    goal_lower = goal.lower()
    for name, pkg in KNOWN_PACKAGES.items():
        if name in goal_lower:
            return pkg
    # Default fallback
    return os.getenv("DEFAULT_APP_PACKAGE", "com.netflix.mediaclient")


def build_framework(driver, app_package: str = "") -> dict:
    """
    Construct all agents, the orchestrator, and the gameplay agent.

    Returns a dict with keys:
        "orchestrator"    → GameOrchestrator  (navigation loop)
        "gameplay_agent"  → GameplayAgent     (post-navigation gameplay loop)

    ``app_package`` is the Android package name of the game/app being tested.
    GameSkillLoader loads ONLY the skill folder matching ``app_package`` exactly
    — zero cross-game leakage.
    """
    # ── LLM (shared across all agents) ───────────────────────────────────
    llm = ChatAnthropic(
        model=        os.getenv("LLM_MODEL", "claude-sonnet-4-6"),
        api_key=      os.getenv("ANTHROPIC_API_KEY", ""),
        max_tokens=   int(os.getenv("LLM_MAX_TOKENS", "1024")),
        temperature=  float(os.getenv("LLM_TEMPERATURE", "0.1")),
    )

    device_serial = os.getenv("DEVICE_UDID", "93b3d10f71da")

    # ── Load game-specific skill + subgoal config ─────────────────────────
    # GameSkillLoader.load()              → concatenated .md skill text
    # GameSkillLoader.load_subgoal_config → per-game subgoal order + rules
    # Both are loaded once here and threaded into the relevant agents.
    # If no skill / config exists, agents degrade gracefully to generic logic.
    game_skill     = GameSkillLoader.load(app_package)
    subgoal_config = GameSkillLoader.load_subgoal_config(app_package)
    skill_info     = GameSkillLoader.get_info(app_package)
    print(f"[run_game] Game skill: found={skill_info['skill_found']} "
          f"files={skill_info['skill_files']} "
          f"subgoal_config={skill_info.get('subgoal_config', False)} "
          f"package={app_package}")

    # ── Core modules ─────────────────────────────────────────────────────
    capturer       = ScreenCapturer(driver, device_serial=device_serial)
    ocr_engine     = OCREngine(languages=["en"], use_gpu=False)
    xml_extractor  = XMLExtractor(driver)
    image_analyzer = ImageAnalyzer()
    executor       = ActionExecutor(
        driver,
        device_serial=    device_serial,
        post_action_wait= float(os.getenv("POST_ACTION_WAIT", "0.8")),
    )

    # ── Specialist agents ─────────────────────────────────────────────────
    # DecisionAgent (TEST):     game_skill  → injected into every VLM call
    # ActionAgent   (ACT):      game_skill  → Tier 3 coordinate hints
    # VerificationAgent (VERIFY):
    #   game_skill      → parses game-specific HUD keywords from .md
    #   subgoal_config  → per-game subgoal order + require_any/exclude_if rules
    #                     (FIX-1/FIX-2: prevents premature GOAL_ACHIEVED)
    perception_agent   = PerceptionAgent(capturer, ocr_engine, xml_extractor, image_analyzer, llm)
    decision_agent     = DecisionAgent(llm, game_skill=game_skill)
    action_agent       = ActionAgent(executor, image_analyzer, llm, game_skill=game_skill)
    verification_agent = VerificationAgent(
        image_analyzer,
        llm,
        game_skill=     game_skill,
        subgoal_config= subgoal_config,   # ← NEW: per-game subgoal rules
    )
    memory_agent       = MemoryAgent(llm)

    # ── Orchestrator (navigation) ─────────────────────────────────────────
    orchestrator = GameOrchestrator(
        perception_agent=   perception_agent,
        decision_agent=     decision_agent,
        action_agent=       action_agent,
        verification_agent= verification_agent,
        memory_agent=       memory_agent,
        executor=           executor,
    )

    # ── Gameplay Agent (post-navigation autonomous loop) ─────────────────
    # Loads tactic cards from *tactics*.md files in the game skill folder.
    # If no tactics file exists, GameplayAgent falls back to VLM-only mode.
    tactics_text = GameSkillLoader.load_tactics(app_package)
    gameplay_agent = GameplayAgent(
        perception_agent= perception_agent,
        decision_agent=   decision_agent,
        action_agent=     action_agent,
        executor=         executor,
        game_skill=       game_skill,
        tactics_text=     tactics_text,
    )

    return {
        "orchestrator":    orchestrator,
        "gameplay_agent":  gameplay_agent,
    }


def load_goal_file(path: str) -> tuple[str, str, list, dict]:
    """
    Load goal + optional steps + gameplay_phase from a goals/*.json file.
    Returns (goal, app_package, steps_list, gameplay_phase_dict).
    steps_list is [] for oneliner mode; gameplay_phase is {} if not defined.
    """
    import json
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    goal           = data.get("goal", "")
    package        = data.get("app_package", "")
    mode           = data.get("mode", "oneliner")
    steps          = data.get("steps", []) if mode == "steps" else []
    gameplay_phase = data.get("gameplay_phase", {})
    if not goal:
        raise ValueError(f"Goal file '{path}' has no 'goal' field.")
    print(f"[run_game] Loaded goal file: {path}")
    print(f"[run_game] Mode: {mode} | Steps: {len(steps)} | "
          f"Gameplay phase: {gameplay_phase.get('enabled', False)} "
          f"({gameplay_phase.get('duration_seconds', 0)}s)")
    return goal, package, steps, gameplay_phase


def main():
    parser = argparse.ArgumentParser(
        description="🎮 Goal-Driven Multi-Agentic Game Automation Framework",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
USAGE EXAMPLES:
  # One-liner goal (AI decomposes automatically):
  python run_game.py "Launch Bloons TD6 and go to gameplay"
  python run_game.py "Play Subway Surfers"
  python run_game.py "Open Clash of Clans"

  # Explicit package:
  python run_game.py "Go to gameplay" --package com.ninjakiwi.bloonstd6

  # Load from a goals/*.json file (supports both oneliner + steps modes):
  python run_game.py --file goals/bloons_td6.json
  python run_game.py --file goals/netflix.json
  python run_game.py --file goals/any_game_template.json
        """
    )
    parser.add_argument(
        "goal",
        type=str,
        nargs="?",
        default="",
        help='High-level goal in plain English. Example: "Launch Bloons TD6 and go to gameplay"',
    )
    parser.add_argument(
        "--file", "-f",
        type=str,
        default="",
        help="Path to a goals/*.json file. Supports oneliner and steps modes.",
    )
    parser.add_argument(
        "--package", "-p",
        type=str,
        default="",
        help="Android app package name (auto-detected from goal if not specified)",
    )
    parser.add_argument(
        "--max-iterations", "-m",
        type=int,
        default=40,
        help="Maximum SENSE→TEST→ACT→VERIFY iterations (default: 40)",
    )
    args = parser.parse_args()

    # ── Resolve goal + package ──────────────────────────────────────────
    steps          = []
    gameplay_phase = {}
    if args.file:
        # Load from JSON file (includes gameplay_phase if defined)
        goal, pkg_from_file, steps, gameplay_phase = load_goal_file(args.file)
        package = detect_package(goal, args.package or pkg_from_file)
    elif args.goal:
        goal    = args.goal
        package = detect_package(goal, args.package)
    else:
        parser.print_help()
        print("\n❌ ERROR: Provide a goal string OR --file path.\n")
        sys.exit(1)

    print(f"\n{'═'*60}")
    print(f"  🎮 Game Agent Framework — Multi-Agentic Mode")
    print(f"  Goal:    {goal}")
    print(f"  Package: {package}")
    print(f"{'═'*60}\n")

    # Connect to Appium
    driver = None
    try:
        print("[run_game] Connecting to Appium...")
        driver = get_driver()

        # Build all agents — returns dict with orchestrator + gameplay_agent
        print("[run_game] Initializing agents...")
        framework       = build_framework(driver, app_package=package)
        orchestrator    = framework["orchestrator"]
        gameplay_agent  = framework["gameplay_agent"]

        # ── Phase 1: Navigation loop ────────────────────────────────────
        # SENSE→TEST→ACT→VERIFY until gameplay is reached (GOAL_ACHIEVED).
        t0 = time.time()
        final_state = orchestrator.run(goal=goal, app_package=package, steps=steps)
        nav_elapsed = time.time() - t0

        if not final_state.get("goal_achieved"):
            print(f"\n⛔ FAILED: Navigation goal not achieved after {nav_elapsed:.1f}s")
            print(f"   Last subgoal: {final_state.get('current_subgoal','?')}")
            sys.exit(1)

        print(f"\n✅ NAVIGATION COMPLETE in {nav_elapsed:.1f}s")
        print(f"   Iterations: {final_state.get('iteration', 0)}")
        print(f"   Actions:    {len(final_state.get('action_log', []))}")

        # ── Phase 2: Gameplay loop (optional) ───────────────────────────
        # Runs only if goals/*.json defines gameplay_phase.enabled = true.
        gp_enabled  = gameplay_phase.get("enabled", False)
        gp_duration = int(gameplay_phase.get("duration_seconds", 300))
        gp_interval = float(gameplay_phase.get("action_interval_seconds", 4.0))

        if gp_enabled:
            print(f"\n[run_game] 🎮 Starting gameplay phase ({gp_duration}s)...")
            gp_summary = gameplay_agent.play(
                duration_s=        gp_duration,
                action_interval_s= gp_interval,
            )
            elapsed_total = time.time() - t0
            print(f"\n✅ SUCCESS: Navigation + Gameplay complete in {elapsed_total:.1f}s")
            print(f"   Nav iterations:  {final_state.get('iteration', 0)}")
            print(f"   Gameplay ticks:  {gp_summary.get('ticks', 0)}")
            print(f"   Tactic actions:  {gp_summary.get('tactic_actions', 0)}")
            print(f"   VLM actions:     {gp_summary.get('vlm_actions', 0)}")
        else:
            elapsed_total = nav_elapsed
            print(f"\n✅ SUCCESS: Goal achieved in {elapsed_total:.1f}s (no gameplay phase)")

        sys.exit(0)

    except KeyboardInterrupt:
        print("\n[run_game] Interrupted by user")
        sys.exit(130)
    except Exception as exc:
        print(f"\n[run_game] Fatal error: {exc}")
        import traceback; traceback.print_exc()
        sys.exit(2)
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


if __name__ == "__main__":
    main()

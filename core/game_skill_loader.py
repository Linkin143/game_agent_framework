# core/game_skill_loader.py
# =============================================================================
# Game-Specific Skill Loader
# Loads gameplay instructions keyed by the app's Android package name.
#
# Directory layout:
#   game_skills/
#     <app_package>/            ← folder name MUST match Android package ID
#       01_navigation.md        ← how to navigate from launch → gameplay
#       02_gameplay_mechanics.md← game rules, HUD keywords, tower/unit names
#       03_hud_reference.md     ← exact coordinates, button labels, OCR hints
#       subgoal_config.json     ← per-game subgoal order + confirm/exclude rules
#       ...                     ← any additional .md files in sort order
#
# Usage:
#   from core.game_skill_loader import GameSkillLoader
#   skill_text    = GameSkillLoader.load("com.netflix.NGP.BloonsTDSix")
#   subgoal_cfg   = GameSkillLoader.load_subgoal_config("com.netflix.NGP.BloonsTDSix")
#   metadata      = GameSkillLoader.get_info("com.netflix.NGP.BloonsTDSix")
# =============================================================================

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

# Root of the game_skills directory — sits alongside core/ at repo root
GAME_SKILLS_DIR = Path(__file__).parent.parent / "game_skills"


class GameSkillLoader:
    """
    Static utility that loads game-specific skill documents for a given
    Android package.  Only the skill folder whose name matches the
    `app_package` is loaded — all other games are ignored.

    Returns a single concatenated markdown string ready to be injected
    into an agent's `extra_system` prompt as:
        ## Game-Specific Gameplay Instructions
        <content>

    If no skill folder exists for the package, returns "" (empty string)
    and logs a warning — the agents degrade gracefully to generic skills.
    """

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    @classmethod
    def load(cls, app_package: str) -> str:
        """
        Load and return all game skill .md files for `app_package`,
        concatenated in filename sort order.

        Returns "" if no skill folder exists for this package.
        """
        if not app_package:
            return ""

        skill_dir = cls._find_skill_dir(app_package)
        if skill_dir is None:
            print(f"[game_skill_loader] No game skill found for: {app_package}")
            print(f"[game_skill_loader] Expected path: {GAME_SKILLS_DIR / app_package}/")
            return ""

        md_files = sorted(skill_dir.glob("*.md"))
        if not md_files:
            print(f"[game_skill_loader] Skill folder exists but contains no .md files: {skill_dir}")
            return ""

        parts: list[str] = []
        for md in md_files:
            content = md.read_text(encoding="utf-8").strip()
            if content:
                parts.append(f"### [{md.stem}]\n{content}")

        combined = "\n\n---\n\n".join(parts)
        total_chars = len(combined)
        print(
            f"[game_skill_loader] ✅ Loaded game skill for '{app_package}' "
            f"— {len(md_files)} files, {total_chars} chars"
        )
        return combined

    @classmethod
    def load_subgoal_config(cls, app_package: str) -> dict:
        """
        Load the per-game ``subgoal_config.json`` for ``app_package``.

        Returns a dict with keys:
            subgoal_order         : list[str]  — ordered subgoal names
            subgoal_confirmations : dict       — per-subgoal require_any/exclude_if

        Returns an empty dict ``{}`` if no config file exists, so callers can
        always fall back to the hardcoded generic subgoal list gracefully.
        """
        if not app_package:
            return {}

        skill_dir = cls._find_skill_dir(app_package)
        if skill_dir is None:
            return {}

        config_path = skill_dir / "subgoal_config.json"
        if not config_path.exists():
            print(f"[game_skill_loader] No subgoal_config.json for: {app_package}")
            return {}

        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
            order = data.get("subgoal_order", [])
            confirmations = data.get("subgoal_confirmations", {})
            print(
                f"[game_skill_loader] ✅ Loaded subgoal config for '{app_package}' "
                f"— {len(order)} subgoals: {order}"
            )
            return {"subgoal_order": order, "subgoal_confirmations": confirmations}
        except Exception as exc:
            print(f"[game_skill_loader] ⚠ Failed to parse subgoal_config.json: {exc}")
            return {}

    @classmethod
    def get_info(cls, app_package: str) -> dict:
        """
        Return metadata about the available game skill for `app_package`.
        Useful for logging and debugging.
        """
        skill_dir = cls._find_skill_dir(app_package)
        if skill_dir is None:
            return {
                "app_package":      app_package,
                "skill_found":      False,
                "skill_dir":        str(GAME_SKILLS_DIR / app_package),
                "skill_files":      [],
                "subgoal_config":   False,
            }
        files = sorted(skill_dir.glob("*.md"))
        has_config = (skill_dir / "subgoal_config.json").exists()
        return {
            "app_package":      app_package,
            "skill_found":      True,
            "skill_dir":        str(skill_dir),
            "skill_files":      [f.name for f in files],
            "subgoal_config":   has_config,
        }

    @classmethod
    def load_tactics(cls, app_package: str) -> str:
        """
        Load raw tactic-card markdown text from all ``*tactics*.md`` files
        in the game skill folder for ``app_package``.

        Returns a single concatenated string (blank lines between files) ready
        to be passed to ``GameplayAgent.parse_tactics()``.
        Returns "" if no tactics files exist — GameplayAgent degrades to
        VLM-only mode gracefully.
        """
        if not app_package:
            return ""

        skill_dir = cls._find_skill_dir(app_package)
        if skill_dir is None:
            return ""

        # Match any .md file whose name contains "tactics" (case-insensitive)
        tactic_files = sorted(
            f for f in skill_dir.glob("*.md")
            if "tactic" in f.name.lower()
        )
        if not tactic_files:
            print(f"[game_skill_loader] No tactics .md found for: {app_package}")
            return ""

        parts: list[str] = []
        for md in tactic_files:
            content = md.read_text(encoding="utf-8").strip()
            if content:
                parts.append(content)

        combined = "\n\n".join(parts)
        print(
            f"[game_skill_loader] ✅ Loaded tactics for '{app_package}' "
            f"— {len(tactic_files)} file(s), {len(combined)} chars"
        )
        return combined

    @classmethod
    def list_available(cls) -> list[str]:
        """Return all package names that have a game skill folder."""
        if not GAME_SKILLS_DIR.exists():
            return []
        return [
            d.name for d in sorted(GAME_SKILLS_DIR.iterdir())
            if d.is_dir() and not d.name.startswith(".")
            and any(d.glob("*.md"))
        ]

    # -------------------------------------------------------------------------
    # Private
    # -------------------------------------------------------------------------

    @classmethod
    def _find_skill_dir(cls, app_package: str) -> Optional[Path]:
        """
        Find the skill directory for `app_package`.
        Supports both exact match and case-insensitive fallback.
        """
        if not GAME_SKILLS_DIR.exists():
            return None

        # Exact match first (preferred — package names are case-sensitive)
        exact = GAME_SKILLS_DIR / app_package
        if exact.is_dir():
            return exact

        # Case-insensitive fallback
        pkg_lower = app_package.lower()
        for d in GAME_SKILLS_DIR.iterdir():
            if d.is_dir() and d.name.lower() == pkg_lower:
                return d

        return None

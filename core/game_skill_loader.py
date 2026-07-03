# core/game_skill_loader.py
# =============================================================================
# Game-Specific Skill Loader
# Loads gameplay instructions keyed by the app's Android package name.
#
# Directory layout:
#   game_skills/
#     <app_package>/            ← folder name MUST match Android package ID
#       01_navigation.md        ← how to navigate from launch → gameplay
#       02_gameplay_mechanics.md← game rules, HUD markers, tower/unit names
#       03_gameplay_guide.md    ← VLM gameplay guide: strategy, visuals, decisions
#       ...                     ← any additional .md files in sort order
#
# Usage:
#   from core.game_skill_loader import GameSkillLoader
#   skill_text    = GameSkillLoader.load("com.netflix.NGP.BloonsTDSix")
#   metadata      = GameSkillLoader.get_info("com.netflix.NGP.BloonsTDSix")
# =============================================================================

from __future__ import annotations

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
        Load ALL game skill .md files for `app_package`, concatenated in
        filename sort order (including navigation files).

        Prefer `load_gameplay_skill()` for agent injection — it skips
        navigation files and prevents LLM text-instruction bias.

        Returns "" if no skill folder exists for this package.
        """
        return cls._load_md_files(app_package, skip_navigation=False)

    @classmethod
    def load_gameplay_skill(cls, app_package: str) -> str:
        """
        Load ONLY in-gameplay strategy .md files for `app_package`.

        Skips any file whose name starts with "01_navigation" — navigation
        from launch → gameplay is handled by the generic VLM framework using
        the annotated screenshot + pixel grid + OCR + XML accessibility tree.

        Injecting navigation scripts into the LLM context causes text-instruction
        bias: the VLM pattern-matches the text ("tap Monkey Meadow") and uses
        ocr_center of the text label instead of visually locating the image center
        in the screenshot.  Removing nav text forces the VLM to rely on vision.

        Returns "" if no skill folder or no non-navigation .md files exist.
        """
        return cls._load_md_files(app_package, skip_navigation=True)

    
    @classmethod
    def _load_md_files(cls, app_package: str, skip_navigation: bool) -> str:
        """Internal helper: load .md files with optional navigation filtering."""
        if not app_package:
            return ""

        skill_dir = cls._find_skill_dir(app_package)
        if skill_dir is None:
            print(f"[game_skill_loader] No game skill found for: {app_package}")
            print(f"[game_skill_loader] Expected path: {GAME_SKILLS_DIR / app_package}/")
            return ""

        all_md = sorted(skill_dir.glob("*.md"))
        if skip_navigation:
            md_files = [
                f for f in all_md
                if not f.stem.lower().startswith("01_navigation")
            ]
            skipped = [f.name for f in all_md if f not in md_files]
            if skipped:
                print(f"[game_skill_loader] Skipped navigation files: {skipped}")
        else:
            md_files = all_md

        mode = "gameplay-only" if skip_navigation else "all"
        return cls._combine_md_files(md_files, mode, app_package)

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
            }
        files = sorted(skill_dir.glob("*.md"))
        return {
            "app_package":      app_package,
            "skill_found":      True,
            "skill_dir":        str(skill_dir),
            "skill_files":      [f.name for f in files],
        }

    

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
    def _load_md_files_from_dir(cls, skill_dir: Path, mode_label: str, app_package: str) -> str:
        md_files = sorted(skill_dir.glob("*.md"))
        return cls._combine_md_files(md_files, mode_label, app_package)

    @classmethod
    def _combine_md_files(cls, md_files: list[Path], mode_label: str, app_package: str) -> str:
        if not md_files:
            print(f"[game_skill_loader] No .md files to load for: {app_package}")
            return ""

        parts: list[str] = []
        for md in md_files:
            content = md.read_text(encoding="utf-8").strip()
            if content:
                parts.append(f"### [{md.stem}]\n{content}")

        combined = "\n\n---\n\n".join(parts)
        print(
            f"[game_skill_loader] Loaded {mode_label} skill for '{app_package}' "
            f"- {len(md_files)} files [{', '.join(f.name for f in md_files)}], "
            f"{len(combined)} chars"
        )
        return combined

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

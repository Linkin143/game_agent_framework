# agents/base_agent.py
# =============================================================================
# Base Agent — Skill Loader + LLM Wrapper
# All specialist agents inherit from BaseAgent.
# The key innovation: each agent's system prompt is loaded from a .md skill file.
# Editing the skill file = changing agent behavior (no code changes needed).
# =============================================================================

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from typing import Any

SKILLS_DIR = Path(__file__).parent.parent / "skills"


class BaseAgent:
    """
    Base class for all specialist agents.
    - Loads its skill from skills/<skill_file>.md at initialization
    - Provides a structured LLM call wrapper with retry + lean fallback
    - All agents share the same LLM instance (passed in)
    """

    # Subclasses override this with their skill filename
    SKILL_FILE: str = ""

    def __init__(
        self,
        llm: Any,
        skill_file: Optional[str] = None,
    ) -> None:
        self._llm   = llm
        self._skill = self._load_skill(skill_file or self.SKILL_FILE)

    # -------------------------------------------------------------------------
    # Skill Loading
    # -------------------------------------------------------------------------

    @classmethod
    def _load_skill(cls, skill_filename: str) -> str:
        """
        Load the agent's skill from its .md file in the skills/ directory.
        If the file doesn't exist, returns a basic fallback prompt.
        """
        if not skill_filename:
            return "You are a mobile automation agent. Follow instructions carefully."
        path = SKILLS_DIR / skill_filename
        if path.exists():
            content = path.read_text(encoding="utf-8")
            print(f"[{cls.__name__}] Loaded skill: {skill_filename} ({len(content)} chars)")
            return content
        print(f"[{cls.__name__}] WARNING: Skill file not found: {path}")
        return f"You are a specialist mobile automation agent. Skill file: {skill_filename}"

    @classmethod
    def reload_skill(cls) -> str:
        """Reload skill from disk (hot-reload without restart)."""
        return cls._load_skill(cls.SKILL_FILE)

    # -------------------------------------------------------------------------
    # LLM Call Wrapper
    # -------------------------------------------------------------------------

    def call_llm(
        self,
        user_content: Any,           # str or list (multimodal: text + images)
        extra_system: str = "",      # Additional system context appended to skill
        max_retries:  int = 3,
        lean_content: Optional[Any] = None,  # Smaller payload for retry attempt 3
    ) -> dict:
        """
        Call the LLM with the agent's skill as system prompt.
        3-attempt retry with exponential backoff:
          Attempt 1: Full prompt (image + full context)
          Attempt 2: Same content, no image (text-only)
          Attempt 3: Lean prompt (minimal context)

        Returns parsed JSON dict from LLM response.
        """
        system = self._skill
        if extra_system:
            system = f"{system}\n\n---\n{extra_system}"

        last_error = None
        for attempt in range(max_retries):
            try:
                if attempt == 0:
                    content = user_content
                elif attempt == 1:
                    # Text-only fallback: strip image parts
                    content = self._strip_images(user_content)
                    print(f"[{self.__class__.__name__}] LLM retry {attempt+1}: text-only payload")
                else:
                    # Lean fallback
                    content = lean_content or self._strip_images(user_content)
                    print(f"[{self.__class__.__name__}] LLM retry {attempt+1}: lean payload")

                messages = [
                    SystemMessage(content=system),
                    HumanMessage(content=content),
                ]
                response = self._llm.invoke(messages)
                raw      = response.content.strip()

                if not raw:
                    raise ValueError("LLM returned empty response")

                # Strip markdown code fences if present
                if raw.startswith("```"):
                    raw = raw.split("```")[1]
                    if raw.startswith("json"):
                        raw = raw[4:].strip()
                    raw = raw.rsplit("```", 1)[0].strip()

                return json.loads(raw)

            except Exception as exc:
                last_error = exc
                wait = 2 ** attempt
                if attempt < max_retries - 1:
                    print(f"[{self.__class__.__name__}] LLM attempt {attempt+1} failed: {exc} → retry in {wait}s")
                    time.sleep(wait)
                else:
                    print(f"[{self.__class__.__name__}] LLM ALL attempts failed: {exc}")

        return {"error": str(last_error), "llm_failed": True}

    @staticmethod
    def _strip_images(content: Any) -> Any:
        """Remove image parts from multimodal content, keeping only text."""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "\n".join(
                part["text"] for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            )
        return str(content)

    # -------------------------------------------------------------------------
    # Image Building Helper
    # -------------------------------------------------------------------------

    @staticmethod
    def build_image_message(
        screenshot_b64: str,
        text:           str,
    ) -> list:
        """Build a multimodal message with image + text."""
        parts: list = []
        if screenshot_b64:
            parts.append({
                "type":   "image",
                "source": {
                    "type":       "base64",
                    "media_type": "image/png",
                    "data":       screenshot_b64,
                },
            })
        parts.append({"type": "text", "text": text})
        return parts

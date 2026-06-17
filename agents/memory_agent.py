# agents/memory_agent.py
# =============================================================================
# Memory Agent — Replay Buffer: Store & Replay Successful Navigation Paths
# =============================================================================
from __future__ import annotations
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import numpy as np
from agents.base_agent import BaseAgent
from agents.perception_agent import PerceptionState

MEMORY_FILE = Path(__file__).parent.parent / "memory" / "replay_buffer.json"


@dataclass
class ReplayAction:
    step:       int
    subgoal:    str
    action_type: str
    locator:    dict
    label:      str
    post_screen_hash: str = ""
    success:    bool = True


@dataclass
class ReplayPath:
    path_id:      str
    app_package:  str
    goal:         str
    starting_screen_hash: str
    actions:      list[dict]
    success_count: int = 0
    last_used:    str = ""
    avg_duration_s: float = 0.0


class MemoryAgent(BaseAgent):
    SKILL_FILE = "05_memory_skill.md"
    HASH_DISTANCE_THRESHOLD = 12

    def __init__(self, llm) -> None:
        super().__init__(llm=llm, skill_file=self.SKILL_FILE)
        self._buffer: list[dict] = []
        self._load_buffer()

    def get_replay_path(self, perception: PerceptionState, goal: str) -> Optional[ReplayPath]:
        """Check if a successful path exists for the current screen + goal."""
        screen_hash = self._compute_hash(perception)
        for entry in self._buffer:
            if entry.get("goal", "").lower() == goal.lower():
                if self._hash_matches(entry.get("starting_screen_hash",""), screen_hash):
                    if entry.get("success_count", 0) >= 2:
                        print(f"[memory_agent] Replay match found: {entry['path_id']} "
                              f"(success_count={entry['success_count']})")
                        return ReplayPath(**{k: entry[k] for k in ReplayPath.__dataclass_fields__ if k in entry})
        return None

    def store_path(
        self,
        app_package:   str,
        goal:          str,
        start_perception: PerceptionState,
        action_sequence: list[dict],
        duration_s:    float,
    ) -> None:
        """Store a successful navigation path to the replay buffer."""
        screen_hash = self._compute_hash(start_perception)
        path_id = f"{app_package}_{goal.replace(' ', '_')[:20]}_{int(time.time())}"

        # Check if similar path exists → increment success_count
        for entry in self._buffer:
            if (entry.get("goal","").lower() == goal.lower() and
                    self._hash_matches(entry.get("starting_screen_hash",""), screen_hash)):
                entry["success_count"] = entry.get("success_count", 0) + 1
                entry["last_used"] = time.strftime("%Y-%m-%dT%H:%M:%SZ")
                entry["avg_duration_s"] = (entry.get("avg_duration_s", duration_s) + duration_s) / 2
                self._save_buffer()
                print(f"[memory_agent] Updated existing path (success_count={entry['success_count']})")
                return

        new_path = {
            "path_id":            path_id,
            "app_package":        app_package,
            "goal":               goal,
            "starting_screen_hash": screen_hash,
            "actions":            action_sequence,
            "success_count":      1,
            "last_used":          time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "avg_duration_s":     duration_s,
        }
        self._buffer.append(new_path)
        # Keep buffer bounded
        if len(self._buffer) > 100:
            self._buffer = sorted(self._buffer, key=lambda x: x.get("success_count", 0), reverse=True)[:100]
        self._save_buffer()
        print(f"[memory_agent] Stored new path: {path_id}")

    def _compute_hash(self, p: PerceptionState) -> str:
        """Compute a perceptual hash for the current screen state."""
        try:
            from PIL import Image
            import imagehash
            if p.screenshot_np is not None:
                import cv2
                rgb = cv2.cvtColor(p.screenshot_np, cv2.COLOR_BGR2RGB)
                pil = Image.fromarray(rgb)
                ph = str(imagehash.phash(pil))
            else:
                ph = "0000000000000000"
        except Exception:
            ph = "0000000000000000"

        words = frozenset(p.all_text.lower().split()[:20]) if p.all_text else frozenset()
        text_h = str(hash(words) & 0xFFFFFFFF)
        return f"{ph}:{text_h}"

    def _hash_matches(self, stored: str, current: str) -> bool:
        if not stored or not current:
            return False
        try:
            from imagehash import hex_to_hash
            s_ph = stored.split(":")[0]
            c_ph = current.split(":")[0]
            diff = hex_to_hash(s_ph) - hex_to_hash(c_ph)
            return diff <= self.HASH_DISTANCE_THRESHOLD
        except Exception:
            return stored.split(":")[1:] == current.split(":")[1:]

    def _load_buffer(self) -> None:
        MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        if MEMORY_FILE.exists():
            try:
                self._buffer = json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
            except Exception:
                self._buffer = []
        else:
            self._buffer = []
            self._save_buffer()

    def _save_buffer(self) -> None:
        MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        MEMORY_FILE.write_text(json.dumps(self._buffer, indent=2), encoding="utf-8")

# core/step_parser.py
# =============================================================================
# Step Intent Parser — Pure-Python NLP step → structured intent (no LLM)
#
# In "steps" mode each step string from goals/<game>.json IS the subgoal.
# This parser extracts the machine-readable intent embedded in the step text so
# the rest of the pipeline can target elements precisely instead of guessing:
#
#   "Tap the 'MONKEY MEADOW' and wait for next 'EASY' screen"
#       → action="tap", target_text="MONKEY MEADOW",
#         wait_after={"expect_text": "EASY"}
#
#   "Tap the white triangle button four times in interval of one second gap"
#       → action="tap", target_text=None,
#         target_desc="white triangle button", repeat=4, interval_s=1.0
#
#   "Launch the game and wait for 40 seconds to welcome screen"
#       → action="launch", wait_seconds=40.0
#
# The parser is deterministic (regex + small word maps) and never calls the LLM.
# =============================================================================

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


# ─── Structured Step Intent ──────────────────────────────────────────────────

@dataclass
class StepIntent:
    """Structured intent extracted from a single NLP step string."""
    raw:          str                       # original step text
    action:       str                       # tap|wait|swipe|drag|verify|launch|back|exit|type
    target_text:  Optional[str] = None      # quoted exact text anchor ("MONKEY MEADOW")
    target_desc:  str           = ""        # visual description for SoM / VLM matching
    repeat:       int           = 1         # "four times" → 4
    interval_s:   float         = 0.0       # "one second gap" → 1.0
    wait_after:   Optional[dict] = None     # {"expect_text": "EASY"} from "wait for 'EASY' screen"
    wait_seconds: Optional[float] = None    # explicit "wait for 40 seconds"
    swipe_dir:    Optional[str]  = None     # up|down|left|right
    type_text:    Optional[str]  = None     # text payload for type actions

    def summary(self) -> str:
        bits = [f"action={self.action}"]
        if self.target_text:  bits.append(f"text='{self.target_text}'")
        if self.target_desc:  bits.append(f"desc='{self.target_desc[:40]}'")
        if self.type_text:    bits.append(f"type='{self.type_text[:40]}'")
        if self.repeat != 1:  bits.append(f"repeat={self.repeat}")
        if self.interval_s:   bits.append(f"interval={self.interval_s}s")
        if self.wait_seconds: bits.append(f"wait={self.wait_seconds}s")
        if self.wait_after:   bits.append(f"wait_after={self.wait_after}")
        return " ".join(bits)


# ─── Lookup Tables ───────────────────────────────────────────────────────────

# Number words → integer (for "tap four times")
_NUMBER_WORDS = {
    "once": 1, "twice": 2, "thrice": 3,
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}

# Action verbs → canonical action.  Order matters (checked first-match).
_ACTION_VERBS = [
    (("launch", "open", "start the game", "start app"), "launch"),
    (("exit", "close the game", "quit"),                "exit"),
    (("verify", "confirm", "check", "ensure", "assert"), "verify"),
    (("wait", "pause", "sleep"),                          "wait"),
    (("swipe", "scroll", "drag the screen"),             "swipe"),
    (("drag", "place", "drop"),                          "drag"),
    (("type", "enter text", "input text", "fill", "search for"), "type"),
    (("back", "go back", "press back"),                  "back"),
    (("dismiss", "skip", "cancel"),                      "tap"),   # dismiss = tap a close button
    (("tap", "click", "press", "select", "choose", "hit", "touch"), "tap"),
]

# Quoted text:  '...'  or  "..."  or  ‘...’ / “...”
_QUOTE_RE = re.compile(r"['\"\u2018\u2019\u201c\u201d]([^'\"\u2018\u2019\u201c\u201d]{1,60})['\"\u2018\u2019\u201c\u201d]")

# "wait for 40 seconds" / "wait 15 s" / "for 3.5 sec"
_WAIT_SECONDS_RE = re.compile(
    r'\bwait\s+(?:for\s+)?(\d+(?:\.\d+)?)\s*(?:seconds?|secs?|s\b)',
    re.IGNORECASE,
)

# Repeat count:  "four times" / "4 times" / "tap twice"
_REPEAT_DIGIT_RE = re.compile(r'\b(\d+)\s*times?\b', re.IGNORECASE)
_REPEAT_WORD_RE  = re.compile(
    r'\b(' + '|'.join(_NUMBER_WORDS.keys()) + r')\s*times?\b', re.IGNORECASE
)
_TWICE_THRICE_RE = re.compile(r'\b(twice|thrice)\b', re.IGNORECASE)

# Interval:  "interval of one second" / "1 second gap" / "every 2 seconds"
_INTERVAL_DIGIT_RE = re.compile(
    r'(?:interval\s+of\s+|gap\s+of\s+|every\s+)?(\d+(?:\.\d+)?)\s*(?:seconds?|secs?|s)\s*(?:gap|interval|apart)?',
    re.IGNORECASE,
)
_INTERVAL_WORD_RE = re.compile(
    r'(?:interval\s+of\s+|gap\s+of\s+|every\s+)(' + '|'.join(_NUMBER_WORDS.keys()) +
    r')\s*(?:seconds?|secs?)',
    re.IGNORECASE,
)

# "wait for the 'EASY' screen" / "wait for next 'STANDARD' screen"
_WAIT_FOR_SCREEN_RE = re.compile(
    r'wait\s+for\s+(?:the\s+|next\s+)*'
    r"['\"\u2018\u2019\u201c\u201d]([^'\"\u2018\u2019\u201c\u201d]{1,40})['\"\u2018\u2019\u201c\u201d]"
    r'\s*screen',
    re.IGNORECASE,
)

# Swipe direction
_DIRECTIONS = ("up", "down", "left", "right")


# ─── Parser ──────────────────────────────────────────────────────────────────

def parse_step(step: str) -> StepIntent:
    """
    Parse one NLP step string into a structured StepIntent.

    Fully deterministic — regex + small word maps, never calls the LLM.
    Robust to messy text: unknown verbs default to action='tap'.
    """
    raw   = (step or "").strip()
    lower = raw.lower()

    # ── action verb ────────────────────────────────────────────────────────
    action = "tap"  # safe default — most steps are taps
    for verbs, canon in _ACTION_VERBS:
        if any(v in lower for v in verbs):
            action = canon
            break

    # ── explicit wait seconds (overrides action to wait if it leads) ────────
    wait_seconds: Optional[float] = None
    m = _WAIT_SECONDS_RE.search(raw)
    if m:
        wait_seconds = float(m.group(1))
        # If the step is *primarily* a wait (starts with wait), make it a wait.
        if lower.lstrip().startswith(("wait", "pause", "sleep")):
            action = "wait"

    # ── quoted exact-text anchor (first quote that is NOT a screen-wait) ─────
    target_text: Optional[str] = None
    wait_after: Optional[dict] = None

    screen_m = _WAIT_FOR_SCREEN_RE.search(raw)
    screen_text = screen_m.group(1).strip() if screen_m else None
    if screen_text:
        wait_after = {"expect_text": screen_text}

    for qm in _QUOTE_RE.finditer(raw):
        candidate = qm.group(1).strip()
        # Skip the quote that belongs to the "wait for 'X' screen" clause
        if screen_text and candidate.lower() == screen_text.lower():
            continue
        target_text = candidate
        break

    # Generic text-entry detection:
    #   Type 'Foo' in the search field
    #   Enter 'Foo' in the search input field
    #   Input 'Foo' into username
    if _looks_like_type_step(lower, bool(target_text)):
        action = "type"

    # ── repeat count ───────────────────────────────────────────────────────
    repeat = 1
    rm = _REPEAT_DIGIT_RE.search(raw)
    if rm:
        repeat = max(1, int(rm.group(1)))
    else:
        rwm = _REPEAT_WORD_RE.search(raw)
        if rwm:
            repeat = _NUMBER_WORDS.get(rwm.group(1).lower(), 1)
        else:
            ttm = _TWICE_THRICE_RE.search(raw)
            if ttm:
                repeat = _NUMBER_WORDS.get(ttm.group(1).lower(), 1)

    # ── interval seconds ───────────────────────────────────────────────────
    interval_s = 0.0
    # Word form first ("interval of one second") to avoid digit regex grabbing
    # an unrelated number elsewhere in the sentence.
    iwm = _INTERVAL_WORD_RE.search(raw)
    if iwm:
        interval_s = float(_NUMBER_WORDS.get(iwm.group(1).lower(), 0))
    elif ("interval" in lower or "gap" in lower or "every" in lower):
        idm = _INTERVAL_DIGIT_RE.search(raw)
        if idm:
            interval_s = float(idm.group(1))

    # ── swipe direction ────────────────────────────────────────────────────
    swipe_dir: Optional[str] = None
    if action in ("swipe", "drag"):
        for d in _DIRECTIONS:
            if re.search(rf'\b{d}\b', lower):
                swipe_dir = d
                break

    # ── type payload (quoted text after a type verb) ───────────────────────
    type_text: Optional[str] = None
    if action == "type" and target_text:
        type_text = target_text

    # ── target description (cleaned full text, used for SoM / VLM matching) ─
    if action == "type":
        target_desc = _build_input_target_desc(raw, target_text)
    else:
        target_desc = _build_target_desc(raw, target_text)

    return StepIntent(
        raw=          raw,
        action=       action,
        target_text=  target_text,
        target_desc=  target_desc,
        repeat=       repeat,
        interval_s=   interval_s,
        wait_after=   wait_after,
        wait_seconds= wait_seconds,
        swipe_dir=    swipe_dir,
        type_text=    type_text,
    )


def _build_target_desc(raw: str, target_text: Optional[str]) -> str:
    """
    Produce a concise visual description of the target for SoM/VLM matching.

    Strips leading action verbs and trailing "and wait for ... screen" clauses
    so the description focuses on WHAT to tap, not the surrounding instruction.
    """
    desc = raw

    # Drop the trailing "and wait for ... screen" / "to reach ... screen" clause
    desc = re.split(
        r'\band\s+wait\b|\bthen\s+wait\b|\bto\s+reach\b|\bwhich\s+led\b|\bwait\s+for\b',
        desc, maxsplit=1, flags=re.IGNORECASE,
    )[0]

    # Strip a leading action verb ("Tap the", "Select", "Click on", ...)
    desc = re.sub(
        r'^\s*(tap|click|press|select|choose|hit|touch|launch|open|dismiss|'
        r'skip|cancel|swipe|scroll|drag|verify|confirm|check|wait|exit|close)'
        r'\s+(on\s+|the\s+|a\s+|an\s+)?',
        '', desc, flags=re.IGNORECASE,
    )

    # Drop repeat/interval phrasing from the description
    desc = re.sub(r'\b\d+\s*times?\b', '', desc, flags=re.IGNORECASE)
    desc = re.sub(r'\b(once|twice|thrice|one|two|three|four|five|six|seven|eight|nine|ten)\s*times?\b',
                  '', desc, flags=re.IGNORECASE)
    desc = re.sub(r'(interval\s+of\s+|gap\s+of\s+|in\s+interval\s+of\s+).*$', '', desc, flags=re.IGNORECASE)

    desc = desc.strip(" .,'\"")
    # If we still have the quoted text, prefer a clean "<text>" form
    if not desc and target_text:
        desc = target_text
    return desc


def _looks_like_type_step(lower: str, has_quote: bool) -> bool:
    """Return True when the step is clearly asking for text entry."""
    if not has_quote:
        return False
    text_verbs = ("type ", "enter ", "input ", "fill ")
    text_context = ("search", "input", "field", "textbox", "text box", "edittext", "edit text", "username", "email", "password")
    return any(v in lower for v in text_verbs) or any(c in lower for c in text_context)


def _build_input_target_desc(raw: str, target_text: Optional[str]) -> str:
    """
    Produce a concise input-field description for type steps.

    Examples:
      Type 'Bloons TD6' in the search input field
        -> search input field
      Enter 'abc@example.com' into email field
        -> email field
    """
    desc = raw
    if target_text:
        desc = re.sub(re.escape(target_text), "", desc, flags=re.IGNORECASE)
        desc = re.sub(r"['\"\u2018\u2019\u201c\u201d]", "", desc)

    m = re.search(
        r"\b(?:in|into|on)\s+(?:the\s+|a\s+|an\s+)?(.+)$",
        desc,
        flags=re.IGNORECASE,
    )
    if m:
        desc = m.group(1)
    else:
        desc = re.sub(
            r"^\s*(type|enter|input|fill)\s+",
            "",
            desc,
            flags=re.IGNORECASE,
        )

    desc = re.sub(r"\b(with|using|and then|then)\b.*$", "", desc, flags=re.IGNORECASE)
    desc = desc.strip(" .,'\"")
    return desc or "focused input field"

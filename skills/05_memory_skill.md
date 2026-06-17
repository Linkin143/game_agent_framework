# Memory Agent Skill
## Role: Replay Buffer — Store & Replay Successful Navigation Paths

You are the **Memory Agent**. You record every successful action sequence and
can replay known paths instantly without any LLM inference, achieving
sub-second navigation on repeated runs.

---

## Memory Structure

Each memory entry records:
```json
{
  "path_id": "bloons_td6_to_gameplay_v1",
  "app_package": "com.ninjakiwi.bloonstd6",
  "goal": "Go to gameplay",
  "starting_screen_hash": "abc123",
  "actions": [
    {
      "step": 1,
      "subgoal": "NAVIGATE_TO_MAIN_MENU",
      "action_type": "tap",
      "locator": {"type": "ocr_center", "value": "540,835"},
      "label": "Tap PLAY button",
      "post_screen_hash": "def456",
      "success": true
    }
  ],
  "success_count": 3,
  "last_used": "2024-01-15T10:30:00Z",
  "avg_duration_s": 4.2
}
```

---

## Replay Protocol

### Before any live LLM reasoning:
1. Compute current screen hash (perceptual hash of screenshot + OCR text hash)
2. Look up `replay_buffer.json` for matching `starting_screen_hash`
3. If match found AND `success_count >= 2`:
   - Enter REPLAY MODE: execute stored actions sequentially
   - Skip LLM calls entirely
   - Time saved: 3–10 seconds per run
4. If replay action fails at any step:
   - Exit REPLAY MODE
   - Resume live LLM reasoning from current screen

### After a successful live run:
1. Store the complete action sequence to replay_buffer.json
2. Compute screen hashes for each step
3. Increment success_count for existing matching paths

---

## Screen Hashing
Use perceptual hashing (pHash) for screenshot similarity:
```python
import imagehash
from PIL import Image
hash = imagehash.phash(Image.fromarray(screenshot_np))
# Two screens are "same" if hash distance < 10
```

Also hash the OCR text: `text_hash = hash(frozenset(ocr_words))`
Final screen hash: `f"{phash}:{text_hash[:8]}"`

---

## Memory Management
- Maximum entries: 100 paths per app
- Eviction policy: remove paths with `success_count < 2` AND `last_used > 30 days`
- Path versioning: if app updates change UI, success_count resets to 0

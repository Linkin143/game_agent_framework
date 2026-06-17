# Fallback Skill
## Role: Last-Resort Recovery — When All Agents Are Stuck

This skill activates when the orchestrator detects that the same subgoal
has failed 3+ consecutive times. It provides increasingly aggressive recovery
strategies to escape stuck states.

---

## Stuck State Detection
Orchestrator triggers fallback when:
- Same subgoal has `retry_count >= 3`
- Last 3 verification verdicts are all `ACTION_FAILED` or `NO_CHANGE`
- Screen hash identical for 3 consecutive SENSE cycles

---

## Fallback Cascade (5 Levels)

### FALLBACK_1: Force Fresh Perception
- Clear all cached perception data
- Wait 2 seconds
- Capture completely fresh PerceptionState
- Force re-run Decision Agent from scratch
- *Reason: perception may have been stale*

### FALLBACK_2: Navigate Back
- Press Android BACK button (keycode 4)
- Wait 1 second
- Re-sense screen
- If new screen → re-route to appropriate subgoal
- *Reason: may have been stuck in a sub-screen*

### FALLBACK_3: Dismiss Any Visible Dialog
- Scan OCR for: "OK", "Close", "X", "Cancel", "Dismiss", "No thanks"
- Tap ANY dismissal button found
- Also try: `driver.hide_keyboard()` to close soft keyboard
- Also try: long-press BACK to go to home screen
- *Reason: a dialog/overlay may be blocking*

### FALLBACK_4: App Restart
- Force-stop the app: `adb shell am force-stop <package>`
- Wait 2 seconds
- Relaunch: `driver.activate_app(package)`
- Wait 3 seconds for full load
- Clear memory replay cache for this session (start fresh)
- *Reason: app may be in corrupted state*

### FALLBACK_5: Grid-Based Exploration Tap
- Divide screen into 12 zones (3 columns × 4 rows)
- Tap each zone center sequentially (skip if known to be background)
- After each tap, check if pixel diff > 0.15 (something responded)
- If any zone triggers change → success, resume normal flow
- *This is the absolute last resort — something will respond*

---

## Recovery After Fallback
After any fallback level succeeds (screen changed):
1. Reset subgoal retry_count to 0
2. Re-run Perception Agent (fresh state)
3. Re-run Orchestrator (re-assess which subgoal to resume)
4. Resume normal SENSE→TEST→ACT→VERIFY loop

---

## Fallback Report Format
```json
{
  "fallback_level": 3,
  "reason": "Same screen hash for 3 cycles, ACTION_FAILED 3 times",
  "action_taken": "Tapped 'OK' dialog button at (540, 1200)",
  "screen_changed": true,
  "resumed_subgoal": "NAVIGATE_TO_MAIN_MENU"
}
```

---

## Never-Give-Up Guarantee
The framework guarantees that after FALLBACK_5 completes, the Orchestrator
re-evaluates the goal from scratch. If the app is genuinely broken (crash,
network error, etc.), the framework logs the failure with full diagnostic
data: screenshots, OCR text, XML dumps, and action logs for debugging.

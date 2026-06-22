# 🎮 How to Run the Android Game Agent Framework

---

## ⚡ Quick Start (30 seconds)

Your `.env` is already configured with your device and API key. Just run:

```bash
# ── GOAL-DRIVEN (AI decides everything) ──────────────────────────────────
python run_yolo_game.py "Launch Bloons TD6 and go to gameplay"

# ── STEPS-BASED (you define each step, AI executes on live screen) ────────
python run_yolo_game.py --file goals/bloons_td6.json

# ── SAME COMMANDS with the Appium runner ─────────────────────────────────
python run_game.py "Launch Bloons TD6 and go to gameplay"
python run_game.py --file goals/bloons_td6.json
```

> **No manual .env editing needed.** Both runners load `ANTHROPIC_API_KEY`,
> `LLM_MODEL`, `DEVICE_UDID`, `DEVICE_NAME` and all other settings automatically.

---

## Two Runners — One Framework

| Runner | Engine | Best For |
|--------|--------|----------|
| `run_yolo_game.py` | YOLO + Scrcpy + ADB | **Canvas games** (Unity, Unreal) — no Appium needed |
| `run_game.py` | Appium + Claude Vision | Standard apps, hybrid apps, native Android UI |

Both runners:
- Read the **same `.env`** file
- Accept the **same CLI arguments**
- Use the **same `goals/*.json`** files
- Support **GOAL-DRIVEN** and **STEPS-BASED** modes

---

## ⚙️ One-Time Setup

```bash
# 1. Install Python dependencies
pip install -r requirements.txt

# 2. Verify ADB sees your device
adb devices
# Expected: 93b3d10f71da   device

# 3. For run_yolo_game.py — install scrcpy (free, open-source)
#    Windows:  winget install Genymobile.scrcpy
#    macOS:    brew install scrcpy
scrcpy --version        # verify installed

# 4. For run_game.py only — start Appium server in a separate terminal
appium
```

---

## 🥇 MODE 1 — Goal-Driven (One-Liner)

The AI **autonomously** decomposes your goal into sub-goals, decides every
action, and verifies the outcome — all without you writing any steps.

### YOLO runner (no Appium):
```bash
python run_yolo_game.py "Launch Bloons TD6 and go to gameplay"
python run_yolo_game.py "Play Bloons TD6" --package com.netflix.NGP.BloonsTDSix
python run_yolo_game.py "Play Bloons TD6" --max-iterations 60
python run_yolo_game.py --file goals/bloons_td6_oneliner.json
```

### Appium runner:
```bash
python run_game.py "Launch Bloons TD6 and go to gameplay"
python run_game.py "Play Subway Surfers"
python run_game.py "Open Netflix and watch a movie"
python run_game.py --file goals/bloons_td6_oneliner.json

 python run_game.py --file goals/bloonsTD6/bTD6_NetflixSearch.json
```

The AI decomposes the goal automatically:
```
1. APP_LAUNCH            → adb shell am start -n com.netflix.NGP.BloonsTDSix
2. NAVIGATE_MAIN_MENU    → dismiss splash screens
3. NAVIGATE_LEVEL_SELECT → tap PLAY, reach map select
4. START_GAMEPLAY        → select level, dismiss dialogs
5. VERIFY_GAMEPLAY       → confirm game canvas is live
```

---

## 🥈 MODE 2 — Steps-Based (NLP Recipe)

You author each step in plain English. The AI executes
**OBSERVE → ANALYZE → PLAN → EXECUTE → VERIFY** for each step in sequence.
This gives you **precise control** over the exact flow.

### Run a steps file:
```bash
# YOLO runner (Unity/canvas games — recommended for Bloons TD6):
python run_yolo_game.py --file goals/bloons_td6.json

# Appium runner:
python run_game.py --file goals/bloons_td6.json

# Limit iterations per step:
python run_yolo_game.py --file goals/bloons_td6.json --max-iterations 20
python run_game.py       --file goals/bloons_td6.json --max-iterations 20
```

### Steps file format (`goals/bloons_td6.json`):
```json
{
  "mode": "steps",
  "goal": "Bloons TD6 full gameplay test",
  "app_package": "com.netflix.NGP.BloonsTDSix",
  "steps": [
    "Launch Bloons TD6 and wait for it to fully open past any loading screens",
    "Dismiss any splash screen, promotional popup, or update notification",
    "Tap the PLAY button on the main menu to reach the map selection screen",
    "Select the first available map (Monkey Meadow or any unlocked map)",
    "Select EASY difficulty",
    "Select STANDARD game mode",
    "Dismiss any tutorial overlay or tip dialog that appears",
    "Verify the gameplay canvas is active: round counter and lives are visible",
    "Scroll the tower sidebar upward to reveal additional tower types",
    "Drag a Dart Monkey tower from the sidebar to a valid position on the map",
    "Tap the PLAY or START ROUND button to begin Round 1",
    "Tap the speed button to activate 2x fast-forward speed",
    "Verify bloons are moving along the track and the round counter is incrementing",
    "If a defeat screen appears, tap the RESTART button to try again",
    "Dismiss any system notifications or OS-level permission dialogs that appear"
  ]
}
```

#### Steps output:
```
════════════════════════════════════════════════════════════
  STEPS MODE — 15 steps
  Overall goal: Bloons TD6 full gameplay test
════════════════════════════════════════════════════════════

────────────────────────────────────────────────────────────
  STEP 1/15: Launch Bloons TD6 and wait for it to fully open...
────────────────────────────────────────────────────────────
  ✅ STEP 1 PASSED — 4.2s | 3 iterations

────────────────────────────────────────────────────────────
  STEP 2/15: Dismiss any splash screen, promotional popup...
────────────────────────────────────────────────────────────
  ✅ STEP 2 PASSED — 2.1s | 2 iterations
  ...

════════════════════════════════════════════════════════════
  STEPS SUMMARY
  Passed:  15/15
  Failed:  0/15
════════════════════════════════════════════════════════════
```

---

## 🥉 MODE 3 — Add a New Game

```bash
# 1. Find the package name
adb shell pm list packages | grep <yourgame>

# 2. Copy the template
cp goals/any_game_template.json goals/mygame.json

# 3. Edit: set "goal", "app_package", "mode", and optionally "steps"

# 4. Run
python run_yolo_game.py --file goals/mygame.json
```

### Goals folder:
```
goals/
├── bloons_td6.json          ← Steps mode (15-step Bloons TD6 recipe)
├── bloons_td6_oneliner.json ← One-liner goal mode for Bloons TD6
├── any_game_template.json   ← COPY THIS for any new game
└── <your_game>.json         ← your custom game
```

---

## 📋 Full CLI Reference

```
python run_yolo_game.py [GOAL] [--file FILE] [--package PKG] [--max-iterations N]
python run_game.py      [GOAL] [--file FILE] [--package PKG] [--max-iterations N]

Positional:
  GOAL                   Plain-English goal string (optional if --file given)

Options:
  --file,    -f FILE     Path to goals/*.json (supports oneliner + steps)
  --package, -p PKG      Android package name (auto-detected from goal if omitted)
  --max-iterations, -m N Max OBSERVE→ANALYZE→PLAN→EXECUTE→VERIFY loops
                         per goal (oneliner) or per step (steps mode).
                         Default: 40
```

---

## 📝 Writing Good Goals & Steps

### One-liner goals (keep it simple):
```
✅ "Launch Bloons TD6 and go to gameplay"
✅ "Play Subway Surfers"
✅ "Survive 3 rounds in Bloons TD6"
✅ "Open Netflix and browse movies"

❌ "Click the button at 540,960"        ← too low-level (use steps for this)
❌ "Do everything perfectly"            ← too vague
```

### Steps (be specific — one action per step):
```json
"steps": [
  "Launch Bloons TD6 and wait for loading",          ← app launch + wait
  "Dismiss any splash screen or popup",              ← cleanup
  "Tap the PLAY button on the main menu",            ← navigation
  "Select Monkey Meadow map",                        ← specific target
  "Tap EASY difficulty",                             ← selection
  "Drag a Dart Monkey to the grass on the left",     ← spatial action
  "Tap START ROUND to begin wave 1",                 ← trigger
  "Verify round counter shows Round 1 in progress",  ← verification
  "If defeat screen appears, tap RESTART"            ← recovery
]
```

**Useful step patterns:**
| Pattern | Effect |
|---------|--------|
| `"Wait for X to appear"` | Agent polls screen up to 30 s |
| `"Verify X is visible"` | Checks + reports pass/fail |
| `"If X appears, tap Y"` | Conditional handling |
| `"Dismiss any popup"` | Clears any blocking overlay |
| `"Drag X to Y"` | Triggers color-zone validated drag-drop |

---

## 🔄 Execution Loop (both runners)

```
OBSERVE
  → Scrcpy frame  (live screen, 30 fps)
  → YOLO detection (two-tier: generic UI + game-specific .pt)
  → ADB XML dump  (adb uiautomator dump → accessibility tree)
  → EasyOCR       (text from canvas frame)
  All 4 modalities captured concurrently
       │
ANALYZE (Claude LLM)
  → Receives compact JSON game state (token-efficient)
  → Screenshot sent ONLY when YOLO finds 0 detections
  → Outputs: action, target, gesture_type, confidence
       │
PLAN (Coordinate Resolution)
  Priority: explicit coords → YOLO bbox → OCR region → XML selector → center
       │
EXECUTE (ADB — no Appium for games)
  → adb shell input tap / swipe / keyevent
  → Drag-drop with HSV color-zone validation (green = valid drop zone)
       │
VERIFY
  → YOLO: did expected object appear / disappear?
  → OCR:  did expected text change?
  → Pixel diff: did screen change at all?
  → PASS → next step │ FAIL → retry │ stuck → fallback action
```

---

## 🎯 Quick Reference

| I want to... | Command |
|---|---|
| Quick AI-autonomous game run (YOLO) | `python run_yolo_game.py "Launch Bloons TD6 and play"` |
| Quick AI-autonomous game run (Appium) | `python run_game.py "Launch Bloons TD6 and go to gameplay"` |
| Run 15-step NLP recipe (YOLO) | `python run_yolo_game.py --file goals/bloons_td6.json` |
| Run 15-step NLP recipe (Appium) | `python run_game.py --file goals/bloons_td6.json` |
| Limit iterations per step | `python run_yolo_game.py --file goals/bloons_td6.json --max-iterations 20` |
| Override app package | `python run_yolo_game.py "Play game" -p com.company.game` |
| Add a new game | Copy `goals/any_game_template.json`, edit, run with `-f` |
| Tune agent behavior | Edit `yolo_engine/skills/<agent>_skill.md` |
| Watch live agent log | `Get-Content yolo_game_agent.log -Wait` (Windows) |
| View session memory | `type memory\yolo_session_log.json` |

---

## 🔧 .env Settings Reference

Your `.env` is already configured. Both runners pick up these keys automatically:

```env
# ── Required (already set) ──────────────────────────────────────
ANTHROPIC_API_KEY=sk-ant-...          ✅ Claude API key
LLM_MODEL=claude-sonnet-4-6           ✅ Claude model
DEVICE_UDID=93b3d10f71da              ✅ ADB device serial
DEVICE_NAME=2201116PI                 ✅ Device name
PLATFORM_VERSION=13.0                 ✅ Android version
APPIUM_SERVER_URL=http://127.0.0.1:4723  ✅ (run_game.py only)

# ── Timing (already set) ────────────────────────────────────────
POST_ACTION_WAIT=0.8                  ✅ seconds after each ADB action
STEP_COOLDOWN_S=1.5                   ✅ seconds between steps

# ── YOLO engine (already set) ───────────────────────────────────
GAME_NAME=bloons_td6                  ✅ game identifier
YOLO_GENERIC_MODEL=yolo_engine/models/generic_ui.pt
YOLO_GAME_MODEL=yolo_engine/models/bloons_td6.pt
YOLO_CONFIDENCE=0.45
SCRCPY_FPS=30
SCRCPY_MAX_SIZE=1080
```

> **YOLO model files (`.pt`) are optional.**  
> Without them the engine runs in **simulation mode** — Claude Vision takes over
> using only screenshots. Place trained `.pt` files in `yolo_engine/models/` to
> enable full YOLO detection.

---

## 🛠️ Troubleshooting

| Symptom | Fix |
|---------|-----|
| `ADB device not found` | Run `adb devices`, check USB debugging is on |
| `Scrcpy failed to start` | Install scrcpy: `winget install Genymobile.scrcpy` |
| `ANTHROPIC_API_KEY not set` | Check `.env` file exists in project root |
| `ModuleNotFoundError: easyocr` | `pip install -r requirements.txt` |
| Steps mode runs but never passes | Increase `--max-iterations` or refine step wording |
| Agent loops without progress | Edit the relevant `yolo_engine/skills/<agent>_skill.md` |

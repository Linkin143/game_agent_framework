# 🎮 How to Give Goals & Run the Framework

## Answer: 3 Ways to Provide Your Goal

---

## 🥇 WAY 1 — One-Liner Command Line (Quickest)

Just run `run_game.py` with a plain English sentence.
The AI agents **automatically** decompose it into subgoals and execute.

```bash
cd game_agent_framework

# Games
python run_game.py "Launch Bloons TD6 and go to gameplay"
python run_game.py "Play Subway Surfers"
python run_game.py "Open Candy Crush and start a level"
python run_game.py "Launch Clash of Clans"

# With explicit package (for unknown games)
python run_game.py "Launch and play the game" --package com.yourcompany.yourgame

# Apps
python run_game.py "Open Netflix and play a movie"
```

**The AI does everything:**
- Launches the app
- Dismisses splash screens / ads / permission dialogs
- Navigates to the main menu
- Selects a level / mode
- Confirms gameplay is active

---

## 🥈 WAY 2 — Goals JSON File (Recommended for Repeatability)

Create or edit a file in the `goals/` folder.

### Format A: One-Liner Mode (AI decomposes automatically)
```json
{
  "mode": "oneliner",
  "goal": "Launch Bloons TD6 and go to gameplay",
  "app_package": "com.ninjakiwi.bloonstd6"
}
```

### Format B: Steps Mode (you define each step, AI executes on live screen)
```json
{
  "mode": "steps",
  "goal": "Play Bloons TD6",
  "app_package": "com.ninjakiwi.bloonstd6",
  "steps": [
    "Launch and open Bloons TD6",
    "Dismiss any loading screens or ads",
    "Tap the PLAY button on the main menu",
    "Select the first available map",
    "Select EASY difficulty",
    "Verify gameplay is active"
  ]
}
```

**Run it:**
```bash
python run_game.py --file goals/bloons_td6.json
python run_game.py --file goals/netflix.json
python run_game.py -f goals/subway_surfers.json
```

---

## 🥉 WAY 3 — Edit a Goal File Directly

The `goals/` directory contains ready-made templates:

```
goals/
├── bloons_td6.json       ← Bloons TD6 (Unity 2D game)
├── subway_surfers.json   ← Subway Surfers
├── netflix.json          ← Netflix app (steps mode example)
└── any_game_template.json ← COPY THIS for any new game
```

**For any new game:**
1. Copy `goals/any_game_template.json`
2. Set `"goal"` → your game name
3. Set `"app_package"` → the Android package name
4. Choose `"mode": "oneliner"` or `"mode": "steps"`
5. Run: `python run_game.py --file goals/your_game.json`

---

## 📝 How to Write a Good Goal

### For ONE-LINER mode:
Just mention the game name and the end state you want:
```
✅ "Launch Bloons TD6 and go to gameplay"
✅ "Play Subway Surfers"
✅ "Open Clash of Clans"
✅ "Launch and play any level in Candy Crush"
✅ "Go to gameplay in PUBG Mobile"
✅ "Open Netflix"
```

The AI auto-generates these 5 subgoals:
```
1. APP_LAUNCH          → Open the app
2. NAVIGATE_TO_MAIN_MENU   → Get past splash screens to main menu
3. NAVIGATE_TO_LEVEL_SELECT → Tap Play, reach level/map select
4. START_GAMEPLAY      → Select level, dismiss pre-game dialogs
5. VERIFY_GAMEPLAY     → Confirm game canvas is active
```

### For STEPS mode:
Write each step as a plain English instruction. Be specific:
```json
"steps": [
  "Launch and open Bloons TD6",                    ← app launch
  "Dismiss any splash screen or loading screen",   ← cleanup
  "Tap the PLAY button on the main menu",          ← navigation
  "Select Monkey Meadow map",                      ← level choice
  "Tap EASY difficulty",                           ← mode select
  "Tap STANDARD game mode",                        ← mode select
  "Dismiss any tutorial popup",                    ← cleanup
  "Verify round counter and lives are visible"     ← confirmation
]
```

**Steps mode tips:**
- Each step is one action or one verification
- You can say "Wait for X to appear" → smart polling waits up to 30s
- You can say "Verify X is visible" → agent checks and reports
- Steps run on the LIVE screen — the AI sees what's actually there

---

## ⚙️ Environment Setup (one-time)

```bash
# 1. Copy and configure environment
cp example.env .env

# Edit .env — set these:
# ANTHROPIC_API_KEY=sk-ant-your-actual-key
# DEVICE_UDID=your-device-serial  (run: adb devices)
# APPIUM_SERVER_URL=http://127.0.0.1:4723

# 2. Install dependencies
pip install -r requirements.txt

# 3. Start Appium server (in a separate terminal)
appium

# 4. Connect device/emulator
adb devices

# 5. Run!
python run_game.py "Launch Bloons TD6 and go to gameplay"
```

---

## 🔍 What Happens During Execution

For every step / action, the framework runs this loop automatically:

```
┌─────────────────────────────────────────────────────┐
│  SENSE (Perception Agent)                           │
│  → Screenshot captured (Appium / ADB / scrcpy)     │
│  → XML tree extracted (for native UI elements)     │
│  → OCR runs (reads game canvas text like "PLAY")   │
│  → Animation gate: waits for screen to settle      │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│  TEST (Decision Agent — Claude Vision)              │
│  → Looks at annotated screenshot + OCR + XML       │
│  → Identifies current screen state                 │
│  → Plans the exact action to take next             │
│  → Outputs: tap/swipe/type + exact coordinates     │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│  ACT (Action Agent — 3-Tier Repair)                 │
│  Tier 1: Element locator (acc_id, res_id, text)    │
│  Tier 2: OCR coordinate / OpenCV template          │
│  Tier 3: Raw hardware pixel tap (never fails)      │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│  VERIFY (Verification Agent)                        │
│  → Pixel diff: did the screen change?               │
│  → OCR rules: are expected keywords now visible?   │
│  → Subgoal complete? → advance to next             │
│  → Goal achieved? → DONE ✅                        │
└─────────────────────────────────────────────────────┘
```

---

## 🎯 Quick Reference

| I want to...                           | Command                                               |
|----------------------------------------|-------------------------------------------------------|
| Play Bloons TD6                        | `python run_game.py "Launch Bloons TD6 and play"`    |
| Play any game (known)                  | `python run_game.py "Play Subway Surfers"`           |
| Play unknown game                      | `python run_game.py "Play my game" -p com.x.y`      |
| Use saved goal file                    | `python run_game.py -f goals/bloons_td6.json`        |
| Use step-by-step control               | Edit `goals/netflix.json` → run with `-f`            |
| Add a new game                         | Copy `goals/any_game_template.json`, edit, run       |
| Change how an agent behaves            | Edit `skills/<agent_name>_skill.md`                  |
| Add game UI templates (OpenCV)         | Drop PNG files into `reference_assets/`              |

# Subway Surfers — Navigation Skill
# Package: com.kiloo.subwaysurf

## Game Identity
- **Engine**: Unity 3D
- **Genre**: Endless Runner
- **Publisher**: Kiloo / SYBO Games
- **Key Feature**: Single tap or swipe to play — no level selection needed

---

## Full Navigation Path: Launch → Gameplay

### Stage 1: App Launch & Loading
- Unity splash screen → Subway Surfers logo → Loading bar
- **Wait** for loading: `animation_score < 0.02` then content appears
- DO NOT tap during loading

### Stage 2: Initial Popups (dismiss all)
| OCR Text | Action |
|---|---|
| "ALLOW" / "ACCEPT" | Tap to allow |
| "OK" | Tap OK |
| "CLOSE" / "X" | Tap to dismiss |
| "SIGN IN" / "SKIP" | Tap "SKIP" or close |
| "DAILY CHALLENGE" | Tap "X" or close |
| "MISSION" popup | Tap "X" or dismiss |
| "GET" / "FREE" offer | Tap "X" to dismiss |

### Stage 3: Main Menu / Home Screen
- **Key OCR**: "TAP TO PLAY", "HIGH SCORE", "COINS", player name
- Screen shows the runner character on the train track
- **GAMEPLAY STARTS IMMEDIATELY** with a tap anywhere on screen
- Look for "TAP TO PLAY" text — tap anywhere on screen
- No level selection, no difficulty, no mode selection needed

### Stage 4: Gameplay Confirmation ✅
- Character is running/surfing on train tracks
- Score counter visible (top or top-left): "0", "100", "1000"...
- Coins counter visible
- Track tiles scrolling (high animation_score)
- **This state = GOAL ACHIEVED**

---

## Important: Single-Screen Game
Subway Surfers has essentially ONE menu screen.
After all popups are dismissed, ONE tap starts gameplay.
No complex navigation needed.

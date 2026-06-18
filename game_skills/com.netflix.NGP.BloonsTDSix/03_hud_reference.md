# Bloons TD6 — HUD Reference & Coordinates
# Package: com.netflix.NGP.BloonsTDSix
# Reference resolution: 1080 × 2340 px (scale proportionally for other resolutions)

---

## HUD Layout (Gameplay Screen)

```
┌──────────────────────────────────────────────┐
│ [ROUND X/Y]    [LIVES ♥ N]    [CASH $N] [2x] │  ← TOP HUD bar (y ≈ 60–140)
├──────────────────────────────────────────────┤
│                                          │[T]│
│                                          │[T]│
│            GAME MAP (Bloon Track)        │[T]│  ← Tower sidebar (x ≈ 950–1080)
│                                          │[T]│
│                                          │[T]│
│                                          │[T]│
├──────────────────────────────────────────┤   │
│ [HERO ABILITY]  [PAUSE]        [►PLAY]   │   │  ← BOTTOM HUD (y ≈ 2080–2200)
└──────────────────────────────────────────────┘
```

---

## Key Button Coordinates (1080×2340)

| UI Element | X | Y | Notes |
|---|---|---|---|
| Speed / Fast-Forward button | 980 | 200 | Top-right; cycles 1x→2x→3x |
| Play/Start Round button | 540 | 120 | Top-center; start next wave |
| Pause button | 540 | 2150 | Bottom-center |
| Hero Ability button | 150 | 1900 | Bottom-left; glows when ready |
| Sidebar top tower | 1015 | 420 | First tower in sidebar list |
| Sidebar tower slot 2 | 1015 | 560 | |
| Sidebar tower slot 3 | 1015 | 700 | |
| Sidebar tower slot 4 | 1015 | 840 | |
| Sidebar tower slot 5 | 1015 | 980 | |
| Sidebar scroll area | 1015 | 400–1900 | Swipe up to reveal more towers |
| Map center | 540 | 800 | General placement target |
| Map top-left grass | 200 | 400 | Good Dart Monkey spot |
| Map bottom-left grass | 200 | 1600 | Good Bomb Shooter spot |

---

## OCR Text → Action Mapping

### Top HUD OCR Patterns
```
"ROUND 1"  / "ROUND 42"    → Round counter (gameplay confirmed)
"R1"  / "R 1/40"           → Compact round display
"♥ 200"  / "LIVES 200"     → Lives counter (gameplay confirmed)
"$ 650"  / "$650"  / "650" → Cash amount
"1X"  / "2X"  / "3X"       → Speed indicator
```

### Navigation OCR Patterns
```
"PLAY"                      → Main menu — tap to enter map selection
"MONKEY MEADOW"             → First beginner map — tap to select
"EASY"                      → Difficulty option — tap to confirm
"STANDARD"                  → Game mode option — tap to confirm
"START"  / "BEGIN"          → Start game after setup
```

### Popup / Dialog OCR Patterns
```
"CLAIM"  / "COLLECT"        → Daily reward — tap to dismiss
"CLOSE"  / "X"              → Generic dismiss — tap
"NOT NOW"  / "LATER"        → Update dialog — tap to skip
"OK"                        → Generic confirm — tap
"DEFEAT"  / "GAME OVER"     → Loss screen — tap RESTART
"VICTORY"                   → Win screen — tap NEXT or HOME
"LOCKED"                    → Upgrade path locked — do NOT tap
"COOLDOWN"                  → Ability on cooldown — do NOT tap
```

---

## Gameplay Verification Checklist

The agent should confirm **at least 2** of the following to mark GOAL_ACHIEVED:

1. ☑ OCR contains "ROUND" or "R1" or "R 1"
2. ☑ OCR contains "LIVES" or "♥" + a number
3. ☑ OCR contains "UPGRADes"
4. ☑ OCR contains "$" or "CASH" + a number
5. ☑ `animation_score > 0.02` (game canvas is rendering)
6. ☑ `element_count < 5` (Unity canvas — no native XML tree)
7. ☑ `rendering_engine == "UNITY"`
8. ☑ Screenshot shows colorful map with track and bloons

If ANY ONE of these is true when subgoal is START_GAMEPLAY or VERIFY_GAMEPLAY:
→ Set `goal_achieved = True` immediately

---

## Coordinate Scaling for Non-1080 Screens

All coordinates in this file assume **1080×2340** reference.
Scale factor = `screen_width / 1080`

```python
scale = perception.screen_w / 1080
x_scaled = int(reference_x * scale)
y_scaled = int(reference_y * scale)
```

Example: On a 1440×3200 device, Speed button is at:
- x = int(980 * (1440/1080)) = 1307
- y = int(200 * (1440/1080)) = 267

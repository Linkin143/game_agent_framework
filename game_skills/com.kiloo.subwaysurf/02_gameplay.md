# Subway Surfers — Gameplay Mechanics Skill
# Package: com.kiloo.subwaysurf

## Core Gameplay Loop
- Runner automatically moves forward along train tracks
- Player swipes to dodge obstacles (trains, barriers)
- Collect coins along the track
- Hoverboard power-up: tap to deploy for brief invincibility
- Game ends when the runner crashes into an obstacle without hoverboard

---

## Controls (Gesture-Based)
| Gesture | Action |
|---|---|
| Swipe LEFT | Move runner left one lane |
| Swipe RIGHT | Move runner right one lane |
| Swipe UP | Jump over obstacle |
| Swipe DOWN | Roll/slide under obstacle |
| Tap hoverboard | Deploy hoverboard (if available) |

---

## HUD Elements (Gameplay Confirmation Signals)
```
Score counter: top-left or top-center (number increasing)
Coins collected: top area (coin icon + number)
Hoverboard: bottom-left (if available)
Multiplier: "2x", "3x", "5x" visible during boost
Distance: "500m", "1km" etc.
```

## OCR Keywords → Gameplay Active
Any of these = game is running:
```
SCORE, COINS, BEST, HIGH, SURFERS, MULTIPLIER, 2X, 3X, METERS, KM
```

## End States
| OCR Text | Meaning | Action |
|---|---|---|
| "GAME OVER" | Runner crashed | Tap "RETRY" or "PLAY AGAIN" |
| "REVIVE?" | Revive prompt | Tap "NO THANKS" or "X" |
| "YOUR SCORE" | Score summary | Tap "HOME" or "RETRY" |

---

## Active Gameplay Detection
- `animation_score > 0.05` (tracks scrolling = always animating)
- `rendering_engine == "UNITY"`
- `element_count < 5` (Unity canvas)
- Score/coins number changes between frames

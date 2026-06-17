# Game Navigation Skill
## Role: Game-Specific Navigation Patterns & Known UI Flows

This skill provides game-specific knowledge about common UI flows.
The Decision Agent reads this skill to understand the expected navigation
sequence for popular games and game genres.

---

## Universal Game Navigation Patterns

### Typical Mobile Game Flow
```
SPLASH → MAIN MENU → MODE SELECT → LEVEL SELECT → PRE-GAME → GAMEPLAY
```

### Common Blocking Screens (dismiss IMMEDIATELY before subgoal)
1. **Permission dialogs**: "Allow", "OK", "Accept"
2. **GDPR/Privacy**: "Accept All", "OK", "Agree"
3. **Age gate**: Tap any valid age/date
4. **Notification permission**: "Allow" (or "Don't Allow" for test purposes)
5. **App update**: "Not Now", "Later", "Skip"
6. **Purchase prompt**: "No thanks", "X", back button
7. **Daily reward**: "CLAIM", "COLLECT", "OK"
8. **Social login**: "Skip", "Guest", "Play as Guest"

---

## Bloons TD6 Navigation

### Package: `com.ninjakiwi.bloonstd6`
```
Main Menu Screen:
  - PLAY button: center-bottom, large orange button
  - Settings gear: top-right corner
  - Monkey Knowledge: top-left

Level Selection (Map Screen):
  - Map tiles/thumbnails visible
  - Beginner maps at top: "Monkey Meadow", "Island"
  - Tap any map to select

Difficulty Selection:
  - EASY / MEDIUM / HARD / IMPOPPABLE buttons
  - Tap EASY for quickest access to gameplay

Game Mode Selection:
  - Standard / Deflation / Apopalypse
  - Tap STANDARD

Pre-Game (Tower Placement Hints):
  - "Tap to continue" or "OK" to dismiss tutorial
  - Hero selection: tap "PLAY" without hero if needed

Gameplay Confirmation:
  - Lives counter visible (red heart icon)
  - Money/cash counter visible
  - Round counter "Round 1/X" visible
  - Bloons appear on track
```

### Bloons TD5 Navigation: `com.ninjakiwi.bloonstowerdefense5`
- Similar flow: PLAY → Map → EASY → START

---

## Subway Surfers Navigation
### Package: `com.kiloo.subwaysurf`
```
Main Menu → TAP TO PLAY (anywhere) → Gameplay immediately starts
Key OCR text: "TAP TO PLAY", "HIGH SCORE"
```

---

## Clash of Clans Navigation
### Package: `com.supercell.clashofclans`
```
Loading → Login (Google Play / Guest) → Village View = Gameplay
Key: Large village canvas with buildings = GAMEPLAY ACTIVE
```

---

## Among Us Navigation
### Package: `com.innersloth.spacemafia`
```
Main Menu → ONLINE / LOCAL → Room selection → GAMEPLAY
Key OCR: "ONLINE", "LOCAL", "CREATE GAME", "JOIN GAME"
```

---

## Generic Game Navigation Rules

### Finding the "Play" Button
Search in this order:
1. OCR text: "PLAY", "START", "BEGIN", "ENTER", "GO"
2. Large bright button in center-bottom third of screen
3. Template match: reference_assets/play_button_*.png
4. Calibration grid: try region D8-E10 (center-bottom area)

### Finding Level Selection
After tapping Play:
1. Look for grid of thumbnails or numbered buttons
2. OCR: "LEVEL", "STAGE", "WORLD", numbered items
3. Tap first/easiest available (leftmost, top-most)

### Confirming Gameplay
1. Pixel diff between frames > 0.05 (animation running)
2. OCR finds: score, timer, health/lives, coins
3. No menu buttons visible in center of screen

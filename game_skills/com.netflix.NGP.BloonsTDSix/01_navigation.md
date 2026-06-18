# Bloons TD6 — Navigation Skill
# Package: com.netflix.NGP.BloonsTDSix

## Game Identity
- **Engine**: Unity 2D
- **Genre**: Tower Defense
- **Publisher**: Netflix Games / Ninja Kiwi
- **Platform**: Android (Netflix exclusive build)

---

## Full Navigation Path: Launch → Gameplay

### Stage 1: App Launch & Loading Screen
- Screen shows Ninja Kiwi logo, then Netflix logo, then Bloons branding
- A black screen with a spinner or progress bar will appear (5–20s)
- **Wait** until loading ends: `animation_score < 0.02` AND OCR shows any text
- Do NOT tap during loading — it may interrupt asset loading
- If "TAP TO START" or "TOUCH TO START" appears → tap screen center

### Stage 2: Initial Popups & Permission Dialogs (dismiss all)
Handle these in order if they appear:
| OCR Text / Dialog | Action |
|---|---|
| "Allow" / "ALLOW" | Tap "Allow" |
| "ACCEPT" / "AGREE" | Tap it |
| "NEW VERSION AVAILABLE" | Tap "LATER" or "NOT NOW" |
| "UPDATE AVAILABLE" | Tap "LATER" |
| "Daily Chest" / "CLAIM" | Tap "CLAIM" or "COLLECT" |
| "RECONNECTING" spinner | Wait 3s, do not tap |
| "OK" dialog button | Tap "OK" |
| "CLOSE" button (any popup) | Tap "CLOSE" |
| "X" dismiss button | Tap "X" |

### Stage 3: Main Menu
- Screen shows Bloons TD6 main menu with large background art
- **Key OCR keywords**: "PLAY", "HOME", "SHOP", "MONKEY", "KNOWLEDGE"
- **PLAY button**: Large orange button, center-bottom third of screen
- Tap "PLAY" to enter map/level selection

### Stage 4: Map Selection Screen
- Grid of map thumbnails appears
- **Key OCR keywords**: "MONKEY MEADOW", "ISLAND", "DARK CASTLE", "LOGS"
- Tap the FIRST available map (top-left, unlocked — usually "Monkey Meadow")
- If no map tap works → scroll down to find unlocked maps

### Stage 5: Difficulty Selection
- A popup appears over the selected map thumbnail
- **Key OCR keywords**: "EASY", "MEDIUM", "HARD", "IMPOPPABLE"
- **Action**: Tap "EASY" — this is fastest path to gameplay
- If "EASY" not visible → tap "MEDIUM"

### Stage 6: Game Mode Selection
- Another popup: "STANDARD", "DEFLATION", "APOPALYPSE", etc.
- **Action**: Tap "STANDARD"
- If "STANDARD" not visible → tap first available mode option

### Stage 7: Hero Selection (optional popup)
- May show hero selection screen with "SELECT HERO" or "PLAY" button
- **Action**: Tap "PLAY" directly to skip hero selection
- If no "PLAY" button → tap any hero thumbnail then tap "PLAY"

### Stage 8: Pre-Round Tutorial / Hint Dismissal
- Tutorial overlay may appear with "OK", "NEXT", "GOT IT", "CONTINUE"
- **Action**: Tap any of these dismissal buttons until cleared
- After dismissal: game map with tower placement zone appears

### Stage 9: Gameplay Confirmed ✅
- Round counter visible: "ROUND 1 / XX"
- Lives counter visible (red heart icon with number)
- Cash counter visible ($ or ₪ symbol with number)
- Bloon track visible on the map
- Tower sidebar visible on right edge
- **This state = GOAL ACHIEVED**

# Bloons TD6 — Game-Specific Skill

## Game Overview
Tower defense game. Place monkey towers to pop waves of balloons (bloons) before they reach the exit.
Lives lost = bloons that reach the exit. Goal: survive all rounds.

## Test Case Playbooks

### Test 1: Title Screen Navigation
Goal: Get past title screen to main lobby
- Wait for loading (black screen + spinner)
- Tap center when "TAP TO START" or "PLAY" appears in OCR
- Dismiss any promotional popup (tap CLOSE or X)
- Verify: OCR shows "PLAY", "HOME", or tower menu visible

### Test 2: Sidebar Carousel Navigation
Goal: Scroll sidebar to find hidden towers
- Swipe UP on right sidebar (x=1000, from y=1800 to y=500)
- Verify: New tower icons appear (YOLO detects new tower classes)
- OCR price labels change from grayed (can't afford) to active

### Test 3: Drag-and-Drop Tower Placement
Goal: Place tower on valid grass zone
- Long press tower icon in sidebar (right edge ~x=1000)
- Drag to target map position
- Color check: GREEN = drop, RED = find nearby green zone
- Verify: YOLO detects new tower at target position

### Test 4: Target Priority Adjustment
Goal: Cycle targeting through FIRST/LAST/CLOSE/STRONG
- Long press placed tower → tap target_button
- Cycle 4 taps, reading OCR after each
- Verify: OCR shows all 4 target modes in sequence

### Test 5: Upgrade Path Branching
Goal: Detect when Path 3 locks after upgrading Paths 1+2
- Tap placed tower → tap Path 1 upgrade (left column)
- Tap Path 2 upgrade (right column)
- Verify: Path 3 shows padlock icon (YOLO: locked_icon OR OCR: "LOCKED")
- Do NOT attempt to tap locked path

### Test 6: Battle Speed Toggle
Goal: Activate 3x fast-forward speed
- Tap play button (start wave)
- Locate speed_button (top-right HUD)
- Tap until OCR shows "3x" or speed icon changes
- Verify: animation_score increases significantly

### Test 7: Cooldown Ability Activation
Goal: Activate hero ability when MOAB enters map
- Monitor: YOLO detects bloon_moab class entering map
- Poll hero ability button until ready (no cooldown overlay)
- Tap hero ability button immediately
- Verify: Ability effect animation (high animation_score spike)

### Test 8: Rapid Sell & Rebuild
Goal: Sell existing tower and place new one at same position
- Tap existing tower → sell_button → confirm sell
- Drag new tower from sidebar to exact same grid position
- Verify: Old YOLO class gone, new YOLO class at same coordinates
- Cash balance should decrease by (new_cost - sell_refund)

### Test 9: Defeat Screen Recovery
Goal: Handle defeat modal and restart
- OCR detects "DEFEAT" or "GAME OVER"
- Find "RESTART" button (OCR or YOLO)
- Tap RESTART
- Verify: Round resets to 1, lives restored to max

### Test 10: System Update Notification
Goal: Dismiss update dialog and resume
- OCR detects "NEW VERSION" or "UPDATE AVAILABLE"
- Tap "LATER" or "NOT NOW" first
- If not found: tap "CLOSE" or "X"
- Verify: Dialog disappears, game screen visible again

## Key Coordinates (1080×2340 reference)
| Element | Approximate Position |
|---------|---------------------|
| Speed button | (980, 200) |
| Play/Round button | (540, 120) |
| Sidebar towers | (980-1060, 400-1800) |
| Hero ability | (100-200, 1800-2000) |
| Map center | (540, 800) |

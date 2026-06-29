# Bloons TD6 - Runtime Gameplay Guide
# Package: com.netflix.NGP.BloonsTDSix

## Purpose
This is a short runtime policy for the generic gameplay loop.
Be visual, simple, and conservative. Do not overthink strategy.

## Core Rule
Inside gameplay, prefer safe obvious actions:
- tap large clear buttons
- drag a cheap visible tower to a large valid area
- do simple affordable upgrades
- verify the result before repeating

## Targeting Rule
- Prefer the numbered SoM / registry target when available for:
  - tower tray icons
  - big green play / start-round buttons
  - visible speed controls
  - restart / next / continue buttons
  - popup close / claim / continue buttons
- For icon-only controls, prefer SoM / visual target selection over OCR text
- For drag placement:
  - drag start = center of the chosen tower tray icon
  - drag end = center of a large open valid build area on the map

## Decision Loop
Check these in order every tick.

### 1. Defeat / Victory
- If defeat / game over is visible, tap restart / replay / try again
- If victory / round complete is visible, tap next / continue / play next

### 2. Popup Cleanup
- If a popup, reward, or overlay covers the game, dismiss it
- Prefer close / x / continue / ok
- Avoid buy / purchase unless the goal explicitly asks for it

### 3. Start the Round
- If a large green play / start-round control is visible and no round appears to be running, tap it
- This is usually a high-value action and should be preferred over minor actions

### 4. Place One Cheap Visible Tower
- If there is enough cash and visible open space, place one cheap tower
- Prefer a cheap visible tower rather than scrolling immediately
- Preferred order when visible and affordable:
  1. Dart Monkey
  2. Tack Shooter
  3. Bomb Shooter
  4. Sniper Monkey
- Preferred drop area:
  - large open grass / land beside the path
  - near a bend, curve, or path crossing
  - not on the track, not on water, not on an occupied spot

### 5. Upgrade a Selected Tower
- If a tower is already selected and an affordable visible upgrade is available, tap one upgrade
- Prefer one clear affordable upgrade rather than searching for the perfect path
- If everything is unaffordable, deselect and continue

### 6. Increase Speed Once
- If gameplay is running and the visible speed state is clearly low, one tap to increase speed is allowed
- Do not keep tapping speed every tick

### 7. Scroll the Tower Tray
- Only scroll the tray if no useful affordable tower is visible
- Scroll the tray edge, then reassess

### 8. Otherwise Wait / Verify
- If no clear productive action is available, use wait / verify instead of random taps

## Drag-and-Drop Policy
When placing a tower:
- action_type should be `drag_and_drop`
- start target should be the tower tray icon center
- end target should be a clear buildable map point
- prefer a large safe drop zone over an aggressive tiny drop zone
- if a previous drag likely failed, choose a different larger patch next tick

## Visual Heuristics
- Affordable tower icons are usually brighter than unaffordable ones
- A selected tower often shows a range ring or an upgrade panel
- A round in progress usually shows moving bloons and active map motion
- A waiting-between-rounds state often shows a big green play / start-round control

## Action Success Checks
After each action, prefer these interpretations:

### After start-round tap
- success if bloons begin moving
- success if the green play / start-round button disappears
- success if round HUD updates

### After tower drag-and-drop
- success if a new tower appears on the map
- success if a tower range ring or tower panel appears
- success if cash decreases
- likely failure if the tower snaps back to the tray or nothing changes

### After upgrade tap
- success if cash decreases
- success if the upgrade panel changes or the chosen upgrade is no longer available

### After speed tap
- success if speed label changes
- success if visible gameplay becomes faster

### After popup dismissal
- success if the overlay disappears and core gameplay HUD becomes visible again

## Things To Avoid
- Do not chase tiny precision placements when a larger valid patch exists
- Do not keep retapping the same button if the screen already moved forward
- Do not rely on OCR text alone for icon-only tower tray targets
- Do not force advanced strategies; basic stable play is enough

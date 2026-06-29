# Bloons TD6 - Gameplay Mechanics Skill
# Package: com.netflix.NGP.BloonsTDSix

## Purpose
This file gives only the minimum game facts the generic framework needs while
inside active gameplay. Keep it simple. Do not turn this into a full strategy
guide.

## Active Gameplay Markers
Treat the screen as active gameplay when most of these are visible together:
- Top HUD showing round, lives, and cash
- Central map with a visible path / track
- Bloons moving on the track, or a start-round / play control waiting to be tapped
- Tower tray / monkey bar visible on one screen edge
- Pause / speed / hero / upgrade controls visible around the HUD

If instead the screen mainly shows map names, difficulty buttons, or menu cards,
it is not active gameplay.

## Tower Tray / Monkey Bar
- The tower tray may appear on the right edge or on the bottom edge depending on layout
- Towers are chosen from that tray and then dragged onto the map
- Do not assume the tray is always on the right

## Tower Placement
- To place a tower: drag a visible tower icon from the tray onto an open buildable area
- Buildable area is usually grass / land beside the path, not the path itself
- Prefer large, safe, clearly open patches over tiny precise spots
- Prefer positions near bends, intersections, or long sections of path
- Avoid water, rocks, the path itself, and spots already occupied by towers

## Simple Placement Policy
- Prefer a cheap visible tower first
- If multiple cheap towers are visible, prefer:
  1. Dart Monkey
  2. Tack Shooter
  3. Bomb Shooter
  4. Sniper Monkey
- If the currently visible towers are too expensive, scroll the tray to reveal cheaper ones

## Hero Rules
- A Hero is a special unit
- Only one Hero can be placed in a game
- Heroes level automatically; do not treat them like normal multi-path tower upgrades

## Upgrade Rules
- Normal towers can be upgraded after selection
- If a tower is selected and an affordable, clearly visible upgrade button exists, tap one upgrade
- Prefer simple affordable upgrades over deep path planning
- If no upgrade is affordable, deselect and continue normal play

## Speed / Round Controls
- If a large green play / start-round button is visible and the round is not running, tap it
- If a speed button is visible and clearly at low speed, one tap to increase speed is allowed
- Do not spam speed or pause controls

## Popup / End-State Handling
- If defeat / game over is visible, prefer restart / replay / try again
- If victory / round complete is visible, prefer next / continue
- If reward / achievement / close popup appears, dismiss it and return to gameplay

## Success Signals
- Tower placement success:
  - a new tower appears on the map, or
  - a placement ring / tower selection panel appears, or
  - cash decreases
- Start-round success:
  - bloons begin moving, or
  - round HUD advances, or
  - the big play / start-round button disappears
- Upgrade success:
  - cash decreases, or
  - upgrade button state changes, or
  - the selected tower panel changes
- Speed success:
  - the speed label changes, or
  - gameplay visibly accelerates

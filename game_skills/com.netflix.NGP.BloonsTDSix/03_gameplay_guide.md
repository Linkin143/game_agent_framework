# Bloons TD6 — Complete Gameplay Guide
# Package: com.netflix.NGP.BloonsTDSix
#
# PURPOSE: This document teaches the VLM agent HOW to play Bloons TD6.
# It contains strategic knowledge, visual descriptions of UI elements,
# and decision rules. There are NO hardcoded pixel coordinates here —
# the VLM must derive all coordinates from the live screenshot.
# ─────────────────────────────────────────────────────────────────────────────

## What is Bloons TD6?

Bloons TD6 is a tower-defence game. Coloured balloons called "Bloons" travel
along a winding track from an entry point to an exit. Your job is to place
towers on the grass areas beside the track to pop all the bloons before they
reach the exit. Each bloon that escapes costs you Lives. Losing all Lives ends
the game in defeat.

The game is played in Rounds. Each Round sends a wave of bloons along the
track. The game advances automatically between rounds unless paused.

---

## How the Screen Looks During Active Gameplay

When the game is in the active gameplay state you will see ALL of these at once:

- **TOP BAR** (horizontal strip across the top of the screen):
  - Round counter: displayed as "ROUND X" or "R X/Y" showing current wave
  - Lives counter: a heart icon followed by a number (e.g. "♥ 150")
  - Cash counter: a dollar sign followed by a number (e.g. "$1250")
  - Speed button: small button in the top-right corner showing "1x", "2x", or "3x"

- **GAME MAP** (large central area):
  - A colourful aerial-view map with a clearly visible winding track
  - Bloons (round, colourful balloon shapes) moving along the track
  - Placed towers sitting on the grass areas beside the track, actively firing

- **RIGHT SIDEBAR** (narrow vertical strip on the right edge of the screen):
  - Tower icons stacked vertically — these are the towers available to drag
    and place on the map
  - You can scroll this sidebar up/down to see more tower options

- **BOTTOM BAR** (horizontal strip at the bottom of the screen):
  - Hero ability button on the bottom-left — glows brightly when the ability
    is ready; appears dim/greyed-out when on cooldown
  - Pause button in the centre-bottom area

If you can see all of the above simultaneously → the game is in active gameplay.

---

## How to Confirm You Are in Active Gameplay (NOT a menu)

Look for ALL of the following together on the same screen:
1. A round counter (ROUND N or R N/Y) in the top bar
2. A lives number next to a heart icon in the top bar
3. A cash amount ($N) in the top bar
4. A winding coloured track on the map with bloons moving along it
5. Tower icons visible in the right sidebar

If any of these are MISSING and you instead see large menu buttons, a map
selection grid, a difficulty selection screen, or a game-mode selection
screen — you are NOT in gameplay yet.

---

## Decision Loop — What To Do Each Tick

At each action tick, inspect the screenshot and OCR text and follow this
priority order:

### PRIORITY 1 — Handle Critical States First

**If you see a DEFEAT screen** (OCR contains DEFEAT, GAME OVER, or LOST ALL LIVES):
- Look visually for a button labelled RESTART, REPLAY, or TRY AGAIN
- Tap that button to restart and continue playing
- Do NOT tap HOME or QUIT

**If you see a VICTORY screen** (OCR contains VICTORY, ROUND COMPLETE, or YOU WIN):
- Look visually for a button labelled NEXT, CONTINUE, or PLAY NEXT
- Tap that button to proceed to the next round or map

### PRIORITY 2 — Dismiss Popups and Overlays

**If a popup or overlay appears** (OCR contains CLAIM, COLLECT, CLOSE, ACCEPT,
DAILY REWARD, ACHIEVEMENT, CHEST, or an overlay dims the game map):
- Look visually for a close or dismiss button (often an X or CLOSE label)
- Tap it to return to the gameplay screen
- Do NOT tap PURCHASE or BUY buttons

### PRIORITY 3 — Start the Round

**If the game is paused waiting for you to start** (OCR contains PLAY or
START ROUND, and there are no bloons currently moving):
- Look visually for the PLAY or START ROUND button — it is typically a large
  triangular play icon or a button labelled START ROUND
- Tap it to release the next wave of bloons

### PRIORITY 4 — Use Hero Ability

**If the hero ability button is glowing/bright** (not dim or greyed-out):
- The hero ability button is in the bottom-left area of the screen
- When it is ready it typically glows with a golden or bright aura
- Tap it to activate the hero's special power — this deals significant damage
- If it appears dim or shows a cooldown timer: DO NOT tap it

### PRIORITY 5 — Place Towers (action_type: drag_and_drop)

**If you have enough cash** (the cash counter in the top bar shows a positive
amount) and there is available grass space on the map, place a tower using a
**drag_and_drop** action:

**How to construct the drag_and_drop action:**
- `action_type`  : **"drag_and_drop"**
- `locators`     : set to the pixel center of the TOWER ICON you want to drag
                   from the right sidebar — use `{"type": "ocr_center", "value": "X,Y"}`
                   where X,Y is the centre of that tower icon as you see it in the screenshot
- `type_payload` : set to **"endX,endY"** — the pixel coordinates of the GREEN GRASS
                   drop target on the map where you want to place the tower
                   (e.g. `"350,900"` if that is where you see an open grass area)
- `fallback_bounds`: set `{"cx": endX, "cy": endY}` matching the same drop target
                   so ActionAgent can use it as a backup if type_payload fails

**Step-by-step visual process:**
1. Look at the right sidebar (narrow strip on the right edge of the screen)
2. Find the CHEAPEST tower icon whose cost ($N) you can afford — it will appear
   at FULL BRIGHTNESS; icons you cannot afford are dimmed/greyed
3. Note the pixel center of that tower icon (this is your DRAG START)
4. Look at the game map for a GREEN GRASS area positioned close to the track
   (any flat green zone beside the winding bloon path)
5. Note the pixel center of that grass area (this is your DRAG END / drop target)
6. Output `action_type: "drag_and_drop"`, start = tower icon center,
   end = grass area center via `type_payload: "endX,endY"`

**Valid drop areas:** any green or light-coloured flat zone beside the track
**Invalid drop areas:** the track itself, water, rocks, over existing towers

If the game shows a red/invalid indicator after the drag → the drop landed
on the track or an obstacle. Try a different green grass patch further from
the track centre on the next tick.

**Good placement strategy:**
  - Place towers near CURVES or BENDS in the track (longer bloon exposure)
  - Spread towers along the full length of the track, not bunched together
  - Avoid placing all towers in one corner of the map

### PRIORITY 6 — Upgrade an Existing Tower

**If a tower is already selected** (a tower upgrade panel is visible showing
PATH 1, PATH 2, PATH 3 upgrade options with a cost and tick/X indicators):
- Look for the upgrade button that is available (not greyed-out, has a cost
  you can afford)
- Tap the best available upgrade — PATH 1 upgrades (top path) are usually
  the strongest for damage output
- If you cannot afford any upgrade: tap elsewhere to deselect the tower

### PRIORITY 7 — Increase Speed

**If the game is running slowly and no immediate action is needed**:
- Look for the speed button in the top-right corner of the screen
- It shows "1x", "2x", or "3x"
- If it shows "1x": tap it to switch to "2x" speed
- If it shows "2x" or "3x": leave it — speed is already optimal

### PRIORITY 8 — Scroll the Tower Sidebar

**If the sidebar towers are all too expensive** (you cannot afford the
visible tower icons) and you have lower cash:
- Swipe upward on the right sidebar to scroll it and reveal cheaper tower
  options lower in the list
- Dart Monkey is typically the cheapest tower and is always available

---

## Tower Types and Their Roles

The following tower types appear as icons in the right sidebar.
Learn to identify them visually from their icon shapes and colours:

| Tower | Visual Description | Role |
|---|---|---|
| **Dart Monkey** | Small blue monkey holding a dart | Cheapest tower; good all-around early-game |
| **Boomerang Monkey** | Green monkey throwing a boomerang | Hits multiple bloons per throw |
| **Bomb Shooter** | Grey/black cannon | Area damage; good for grouped bloons |
| **Tack Shooter** | Brown spike ball | Fires in all 8 directions; great at curves |
| **Ice Monkey** | Light blue snowflake/ice ball | Freezes bloons temporarily |
| **Glue Gunner** | Yellow glue gun | Slows bloons with sticky glue |
| **Sniper Monkey** | Brown monkey with a long rifle | Long range, high single-target damage |
| **Monkey Sub** | Blue submarine | Strong against water maps; targets quickly |
| **Monkey Buccaneer** | Pirate ship | Water-only; covers large water areas |
| **Monkey Ace** | Fighter jet plane | Flies in circles over the map, fires at bloons |
| **Heli Pilot** | Helicopter | Can be repositioned; strong mid-game |
| **Mortar Monkey** | Grey mortar cannon | Hits targeted location; no range limit |
| **Dartling Gunner** | Grey rapid-fire cannon | Follows finger direction; very powerful |
| **Wizard Monkey** | Purple/blue wizard | Destroys Lead bloons; area spells |
| **Super Monkey** | Gold/red super hero monkey | Very expensive; fires extremely fast |
| **Ninja Monkey** | Dark ninja figure | Hits Camo bloons; rapid attack |
| **Alchemist** | Purple potion figure | Buffs nearby towers; pops Lead |
| **Druid** | Green nature figure | Strong area; summons thorns |
| **Banana Farm** | Yellow banana plant | Generates income each round (not a combat tower) |
| **Spike Factory** | Grey machine | Places spikes on the track |
| **Monkey Village** | Brown village building | Buffs nearby towers; no direct attack |
| **Engineer Monkey** | Orange engineer | Builds sentry towers |

**Recommended beginner placement order:**
1. Dart Monkey (cheapest — place first)
2. Tack Shooter (good at bends in the track)
3. Bomb Shooter (good for groups)
4. Sniper Monkey (upgrade for lead bloon popping)

---

## Bloon Types — Threat Levels

| Bloon Colour | Threat Level | Notes |
|---|---|---|
| Red | Very Low | 1 hit to pop |
| Blue | Low | Releases a Red |
| Green | Low | Releases a Blue |
| Yellow | Low | Moves faster |
| Pink | Medium | Very fast |
| Black | Medium | Immune to Explosions |
| White | Medium | Immune to Freeze |
| Lead | High | Immune to Sharp; needs Explosives or Magic |
| Zebra | High | Immune to both Freeze and Explosions |
| Rainbow | High | Releases 2 Zebras |
| Ceramic | Very High | 10 hits; very durable |
| MOAB | Boss | Massive; requires many strong towers |
| BFB | Boss | Bigger than MOAB |
| ZOMG | Boss | Biggest standard boss |
| BAD | Boss | Strongest non-boss final threat |

When you see large round/layered bloons (MOABs, BFBs) approaching: activate
the hero ability immediately if it is ready, and focus upgrades on your
highest-damage towers.

---

## State Signals — Reading the OCR Text

Use these OCR patterns to understand what state the game is currently in:

| OCR Text Seen | Game State | Action |
|---|---|---|
| "ROUND N" or "R N/Y" | Active gameplay | Continue normal play |
| "LIVES" + number | Active gameplay | Continue normal play |
| "DEFEAT" or "GAME OVER" | Loss screen | Tap RESTART / REPLAY |
| "VICTORY" | Win screen | Tap NEXT / CONTINUE |
| "CLAIM" or "COLLECT" | Reward popup | Dismiss popup |
| "CLOSE" or "×" alone | Overlay popup | Dismiss popup |
| "PLAY" alone (no round counter visible) | Main menu | This is navigation, not gameplay |
| "MONKEY MEADOW" or any map name | Map selection | This is navigation, not gameplay |
| "EASY" / "MEDIUM" / "HARD" | Difficulty selection | This is navigation, not gameplay |
| "STANDARD" / "CHIMPS" / "DEFLATION" | Mode selection | This is navigation, not gameplay |
| "UPGRADE" with path options | Tower selected | Consider upgrading if affordable |
| "COOLDOWN" | Hero ability not ready | Do not tap hero button |

---

## Key Gameplay Rules

1. **Never let all lives run out** — prioritise covering any section of the
   track where bloons are consistently getting through.

2. **Towers cannot be placed on the track** — only on the grass areas beside it.

3. **Towers have a range circle** — when you tap a tower, a circle shows its
   attack range. Place towers so this range covers as much of the track as possible.

4. **The Banana Farm generates cash** — it does not attack, but it generates
   extra money each round. Place one early if you have spare cash.

5. **Upgrade towers before buying new ones** once you have a good spread
   of towers placed — upgraded towers are far more efficient.

6. **CHIMPS mode has no monkey knowledge or continues** — it is the hardest
   mode. Spend cash wisely.

---

## Visual Hints for the VLM

When inspecting the screenshot look for these specific visual features:

- **Available tower icon**: In the right sidebar, tower icons that you can
  afford appear at full brightness. Icons you cannot afford are dimmed/greyed.

- **Hero button ready**: The hero ability button in the bottom-left glows
  with a bright golden/yellow ring or pulsing animation.

- **Round in progress**: You can see round, colourful balloon shapes moving
  along the track. The top-bar round counter is visible.

- **Round between waves**: The map may show no bloons moving. A PLAY or
  START ROUND button typically appears.

- **Tower selected**: A circular range indicator appears around the selected
  tower with upgrade panels sliding in from the right or bottom.

- **Defeat screen**: The map is obscured by a dark overlay with DEFEAT text
  and RESTART/REPLAY/HOME buttons centred on screen.

- **Victory screen**: The map is obscured by a bright overlay with VICTORY
  text and NEXT/CONTINUE buttons centred on screen.

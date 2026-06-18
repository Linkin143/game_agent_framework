# Bloons TD6 — Gameplay Mechanics Skill
# Package: com.netflix.NGP.BloonsTDSix

## Core Gameplay Loop
1. **Place towers** on the map grass areas before/between rounds
2. **Start round** by tapping the PLAY/START button (bottom-right or bottom HUD)
3. **Bloons** travel along the track; towers auto-attack them
4. **Earn cash** by popping bloons and completing rounds
5. **Upgrade towers** between rounds to handle harder bloon types
6. **Survive all rounds** without letting bloons escape (lose lives)

---

## Tower Placement Rules
- Towers can ONLY be placed on **green/grass areas** — NOT on the bloon track
- Visual feedback: **green circle** = valid placement, **red circle** = invalid
- Sidebar towers: listed vertically on the RIGHT edge (x ≈ 980–1060px)
- To place: **long-press** tower icon → **drag** to map → **release** on green zone
- If placement fails (red circle) → drag to nearby grass area
- After placement: tower menu appears showing upgrade paths

## Tower Types (OCR/Visual Reference)
| Tower Name | Sidebar Icon | Primary Role |
|---|---|---|
| Dart Monkey | Dart icon | Basic popper |
| Tack Shooter | Star/circle icon | Area damage |
| Sniper Monkey | Rifle icon | Long range, CAMO |
| Bomb Shooter | Bomb icon | Explosion AOE |
| Super Monkey | Bat icon | Fastest fire rate |
| Monkey Village | House icon | Buffs nearby towers |
| Banana Farm | Banana icon | Generates cash |
| Hero | Special icon | Powerful unique unit |

---

## Round / Wave System
- Rounds start from **Round 1**
- Each round = a set of bloons traveling the track
- OCR shows: **"ROUND X"** or **"R X/Y"** in top HUD
- Between rounds: cash earned, tower upgrades possible
- Boss rounds (certain round numbers) = very powerful bloon types

## Bloon Types (hardest to easiest)
```
BAD → ZOMG → BFB → MOAB → Fortified Ceramic → Ceramic → 
Lead → Purple → White/Zebra → Black/White → Rainbow → Camo →
Pink → Yellow → Green → Blue → Red
```
- **MOAB-class** (MOAB/BFB/ZOMG/BAD): huge bloons, very high HP
- **Camo bloons**: invisible to most towers (need "Camo detection" upgrade)
- **Lead bloons**: immune to sharp/energy — need explosives or fire

---

## Upgrade System
- Tap any placed tower → upgrade panel appears
- **3 upgrade paths** shown as columns
- Each path has 5 tiers (costs increase each tier)
- **RULE**: Can max 2 paths; third path locks at tier 2 (shows padlock)
- Look for: "UPGRADE" button with cost displayed
- Grayed button = cannot afford (insufficient cash)

## Speed Controls
- **1x / 2x / 3x** speed toggle: top-right HUD area (x ≈ 980, y ≈ 200)
- Tap the speed button to cycle through speeds
- At 3x: animation_score will be noticeably higher

## Ability System (Hero / Special Towers)
- Hero abilities appear as buttons in bottom-left HUD (x ≈ 100–200, y ≈ 1800–2000)
- Ability button glows when READY (no cooldown overlay)
- Greyed / clock overlay = on cooldown — do NOT tap
- Tap ready ability for massive temporary boost

---

## Detecting Active Gameplay (OCR Keywords)
Any of these visible = gameplay is ACTIVE and running:
```
ROUND, R1, R2, LIVES, CASH, $, WAVE, BLOONS, MOAB, TOWER,
MONKEY, DART, UPGRADE, SELL, SPEED, 1X, 2X, 3X, PLACE
```

## Detecting End States
| OCR Text | Meaning | Action |
|---|---|---|
| "DEFEAT" or "GAME OVER" | Lost all lives | Tap "RESTART" or "HOME" |
| "VICTORY" or "ROUND COMPLETE" | Won round | Tap "NEXT" or wait |
| "ROUND 100 COMPLETE" | Won the game | Tap "HOME" |

---

## Test Playbooks (use these when instructed)

### Quick Start Test (default)
Goal: Navigate from launch to Round 1 running
1. Dismiss all popups
2. Tap PLAY → select Monkey Meadow → EASY → STANDARD
3. Dismiss tutorial if shown
4. Place 1 Dart Monkey on grass (tap sidebar icon, drag to map)
5. Tap the START/PLAY round button
6. Verify: Round 1 bloons appear, animation running, ROUND 1 visible in OCR

### Tower Sidebar Scroll Test
Goal: Scroll sidebar to reveal hidden towers
- Swipe UP on right sidebar (startX=1000, startY=1800, endY=500)
- Verify: New tower icons appear in sidebar

### Target Priority Cycle Test
Goal: Cycle targeting FIRST → LAST → CLOSE → STRONG
- Tap placed tower → find targeting button → cycle 4x
- Verify OCR shows each target mode text after each tap

### Defeat Recovery Test
Goal: Handle defeat screen gracefully
- Wait for "DEFEAT"/"GAME OVER" OCR
- Tap "RESTART" to reset to Round 1
- Verify: Lives restored, round counter = 1

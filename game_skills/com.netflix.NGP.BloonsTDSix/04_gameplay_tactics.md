# Bloons TD6 — Gameplay Tactic Cards
# Package: com.netflix.NGP.BloonsTDSix
#
# FORMAT: Each tactic card starts with "## TACTIC: <NAME>"
# followed by key: value pairs (one per line).
#
# Keys:
#   priority        : critical | high | normal | low
#   require_any     : comma-separated OCR tokens — at least ONE must be visible
#   require_all     : comma-separated OCR tokens — ALL must be visible
#   exclude_if      : comma-separated OCR tokens — ANY present → skip this tactic
#   action_type     : tap | drag_and_drop | swipe | wait
#   action_desc     : plain English description (also used as VLM fallback prompt)
#   ocr_target      : OCR word to find and tap (preferred over coords)
#   coords          : x,y reference at 1080×2340 (tap point or drag START)
#   end_coords      : x,y drag END point (drag_and_drop only)
#   fallback_end_coords : x,y alternate drop position if first attempt fails
#   wait_after      : seconds to sleep after executing this tactic
#   cooldown        : minimum seconds between re-executions of this tactic
#
# All coordinates are for 1080×2340 reference. GameplayAgent scales automatically.
# ─────────────────────────────────────────────────────────────────────────────

## TACTIC: DEFEAT_RECOVERY
priority: critical
require_any: DEFEAT, GAME OVER, LOST ALL LIVES
exclude_if: 
action_type: tap
action_desc: Tap the RESTART button to restart the game after a defeat screen appears
ocr_target: RESTART
coords: 540,1500
wait_after: 3.0
cooldown: 5.0

## TACTIC: VICTORY_CONTINUE
priority: critical
require_any: VICTORY, ROUND COMPLETE, WON
exclude_if: DEFEAT
action_type: tap
action_desc: Tap NEXT or CONTINUE after winning a round or completing the game
ocr_target: NEXT
coords: 900,1500
wait_after: 2.0
cooldown: 5.0

## TACTIC: DISMISS_POPUP
priority: high
require_any: CLAIM, COLLECT, CLOSE, ACCEPT, OK
exclude_if: ROUND, LIVES, CASH, DEFEAT
action_type: tap
action_desc: Dismiss any overlay popup (daily reward, achievement, chest) during gameplay
ocr_target: CLOSE
coords: 900,300
wait_after: 1.0
cooldown: 3.0

## TACTIC: USE_HERO_ABILITY
priority: high
require_any: LIVES, ROUND, CASH
exclude_if: DEFEAT, GAME OVER, CLAIM, CLOSE, COOLDOWN, EASY, SELECT
action_type: tap
action_desc: Tap the hero ability button in the bottom-left corner when it is glowing and ready (not on cooldown)
coords: 150,1900
wait_after: 0.5
cooldown: 12.0

## TACTIC: START_ROUND
priority: normal
require_any: PLAY, START ROUND
exclude_if: DEFEAT, GAME OVER, CLAIM, CLOSE, EASY, SELECT, STANDARD, MEDIUM, HARD
action_type: tap
action_desc: Tap the PLAY or START ROUND button to begin the next wave of bloons
ocr_target: PLAY
coords: 540,120
wait_after: 2.0
cooldown: 30.0

## TACTIC: PLACE_DART_MONKEY
priority: normal
require_any: UPGRADE, LIVES, ROUND, CASH
exclude_if: DEFEAT, GAME OVER, CLAIM, CLOSE, EASY, SELECT, STANDARD
action_type: drag_and_drop
action_desc: Drag the Dart Monkey tower from the top sidebar slot to the green grass area beside the bloon track
coords: 1015,420
end_coords: 200,400
fallback_end_coords: 300,700
wait_after: 1.5
cooldown: 25.0

## TACTIC: PLACE_TACK_SHOOTER
priority: high
require_any: UPGRADE, LIVES, ROUND, CASH
exclude_if: DEFEAT, GAME OVER, CLAIM, CLOSE, EASY, SELECT, STANDARD
action_type: drag_and_drop
action_desc: Drag the Tack Shooter tower from sidebar slot 2 to a grass position near the center of the bloon track
coords: 1015,560
end_coords: 400,700
fallback_end_coords: 250,900
wait_after: 1.5
cooldown: 60.0


## TACTIC: SCROLL_SIDEBAR_DOWN
priority: low
require_any: LIVES, ROUND, CASH
exclude_if: DEFEAT, GAME OVER, CLAIM, CLOSE, EASY, SELECT
action_type: swipe
action_desc: Swipe upward on the tower sidebar to reveal additional tower types lower in the list
coords: 1015,1900
end_coords: 1015,500
wait_after: 1.0
cooldown: 45.0

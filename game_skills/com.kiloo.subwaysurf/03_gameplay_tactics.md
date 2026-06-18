# Subway Surfers — Gameplay Tactic Cards
# Package: com.kiloo.subwaysurf
#
# Subway Surfers is an endless runner — gameplay is fully real-time.
# Tactics here handle the reactive swiping needed to stay alive.
# Most gameplay is driven by VLM fallback since the game is continuous.
# ─────────────────────────────────────────────────────────────────────────────

## TACTIC: REVIVE_OR_RESTART
priority: critical
require_any: GAME OVER, REVIVE, TRY AGAIN, BEST
exclude_if: SCORE, COINS, MULTIPLIER
action_type: tap
action_desc: Tap the play again or revive button after the character dies
ocr_target: PLAY AGAIN
coords: 540,1400
wait_after: 2.0
cooldown: 5.0

## TACTIC: DISMISS_POPUP
priority: high
require_any: CLAIM, COLLECT, CLOSE, OK, DAILY
exclude_if: SCORE, COINS, GAME OVER
action_type: tap
action_desc: Dismiss any popup (daily bonus, prize, notification) during the session
ocr_target: CLOSE
coords: 900,200
wait_after: 1.0
cooldown: 3.0

## TACTIC: TAP_TO_START
priority: high
require_any: TAP, SWIPE, START
exclude_if: GAME OVER, SCORE, COINS, HIGH
action_type: tap
action_desc: Tap or swipe to start a new run from the lobby screen
coords: 540,1200
wait_after: 1.5
cooldown: 5.0

## TACTIC: SWIPE_LEFT_DODGE
priority: normal
require_any: SCORE, COINS
exclude_if: GAME OVER, REVIVE, CLAIM
action_type: swipe
action_desc: Swipe left to move character to the left lane to avoid obstacles
coords: 400,1200
end_coords: 150,1200
wait_after: 0.3
cooldown: 2.0

## TACTIC: SWIPE_RIGHT_DODGE
priority: normal
require_any: SCORE, COINS
exclude_if: GAME OVER, REVIVE, CLAIM
action_type: swipe
action_desc: Swipe right to move character to the right lane to avoid obstacles
coords: 600,1200
end_coords: 900,1200
wait_after: 0.3
cooldown: 2.5

## TACTIC: SWIPE_UP_JUMP
priority: normal
require_any: SCORE, COINS
exclude_if: GAME OVER, REVIVE, CLAIM
action_type: swipe
action_desc: Swipe upward to jump over incoming barriers and trains
coords: 540,1200
end_coords: 540,800
wait_after: 0.4
cooldown: 3.0

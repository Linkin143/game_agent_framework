# Netflix — Playback Tactic Cards
# Package: com.netflix.mediaclient
#
# Netflix "gameplay" = watching a video without interruption.
# Tactics handle common interruptions during playback.
# ─────────────────────────────────────────────────────────────────────────────

## TACTIC: SKIP_INTRO
priority: high
require_any: SKIP INTRO, SKIP OPENING
exclude_if: 
action_type: tap
action_desc: Tap the SKIP INTRO button when it appears during playback
ocr_target: SKIP INTRO
coords: 830,1800
wait_after: 1.0
cooldown: 5.0

## TACTIC: SKIP_RECAP
priority: high
require_any: SKIP RECAP, SKIP CREDITS
exclude_if: 
action_type: tap
action_desc: Tap the SKIP RECAP or SKIP CREDITS button when it appears
ocr_target: SKIP RECAP
coords: 830,1800
wait_after: 1.0
cooldown: 5.0

## TACTIC: RESUME_PAUSED
priority: high
require_any: RESUME, PLAY
exclude_if: SKIP INTRO, BROWSE, HOME, TRENDING
action_type: tap
action_desc: Tap the RESUME or PLAY button if video has paused unexpectedly
ocr_target: RESUME
coords: 540,1200
wait_after: 1.5
cooldown: 10.0

## TACTIC: DISMISS_ARE_YOU_STILL_WATCHING
priority: critical
require_any: STILL WATCHING, CONTINUE WATCHING, YES
exclude_if: 
action_type: tap
action_desc: Tap YES or CONTINUE WATCHING to dismiss the inactivity dialog
ocr_target: YES
coords: 540,1300
wait_after: 1.0
cooldown: 5.0

## TACTIC: TAP_TO_REVEAL_CONTROLS
priority: low
require_any: PAUSE, EPISODES, AUDIO
exclude_if: SKIP INTRO, STILL WATCHING
action_type: tap
action_desc: Tap the center of the screen to reveal playback controls periodically
coords: 540,1200
wait_after: 2.0
cooldown: 60.0

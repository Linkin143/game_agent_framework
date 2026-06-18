# Netflix — Playback Controls Skill
# Package: com.netflix.mediaclient

## Playback Screen HUD
```
┌──────────────────────────────────────────────┐
│ [← Back]           [Title Text]    [⋮ More]  │  ← Top bar
│                                              │
│                  VIDEO FRAME                 │  ← Full-screen video
│                                              │
│   [|◄◄]  [►]  [►► |]        [CC]  [⚙]  [□] │  ← Control bar
│   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━   │  ← Timeline scrubber
│   0:00                          1:23:45      │
└──────────────────────────────────────────────┘
```

## Key Controls
| UI Element | Location | Action |
|---|---|---|
| Play/Pause button | Center-bottom | Toggle playback |
| Timeline scrubber | Bottom bar | Drag to seek |
| Back button | Top-left | Exit playback |
| Skip Intro | Bottom-right (appears briefly) | Tap to skip |
| Skip Recap | Bottom-right (appears briefly) | Tap to skip |
| Next Episode | Bottom-right | Tap for next |
| Subtitles (CC) | Bottom-right controls | Toggle captions |
| Settings (⚙) | Bottom-right | Quality, audio |

## OCR Keywords → Playback Active
Any of these = video is playing:
```
PAUSE, RESUME, SKIP INTRO, SKIP RECAP, NEXT EPISODE,
0:, 1:, :00, :30, SUBTITLES, EPISODES, SEASON, S1, E1
```

## Detecting Active Playback
- `animation_score > 0.03` (video frame changing)
- `rendering_engine == "NATIVE"` or `"WEBVIEW"`
- `element_count >= 5` (native control bar)
- OCR shows timestamp in format "M:SS" or "H:MM:SS"

## Auto-dismissing Overlays During Playback
- Controls auto-hide after 3s of no interaction
- Tap screen center once to show controls
- "SKIP INTRO" / "SKIP RECAP" buttons appear for ~5s — tap immediately if seen

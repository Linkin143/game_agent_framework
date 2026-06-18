# Netflix — Navigation Skill
# Package: com.netflix.mediaclient

## App Identity
- **Type**: Video streaming app (NOT a game)
- **Engine**: Native Android (React Native / Proprietary UI)
- **Key Feature**: Rich XML accessibility tree — use semantic locators first

---

## Full Navigation Path: Launch → Content Playback

### Stage 1: App Launch
- Netflix logo splash → Loading spinner
- **Wait** for loading: `element_count > 3` indicates UI ready
- If "SIGN IN" appears → out of scope (requires credentials)
- If already logged in → home screen loads automatically

### Stage 2: Initial Popups (dismiss all)
| OCR / XML Element | Action |
|---|---|
| "ALLOW" notifications | Tap "Allow" or "Not Now" |
| "What to Watch" tutorial | Tap "X" or outside |
| "Continue Watching?" | Leave it or tap if needed |
| Cookie/privacy banner | Tap "OK" or "Accept" |

### Stage 3: Home Screen
- Browse rows: "Continue Watching", "Trending Now", "Top Picks for You"
- **Key XML**: Many native elements with resource-IDs and content-desc
- **Action**: Tap any content thumbnail to open its detail page

### Stage 4: Content Detail Page
- Shows title, description, "PLAY" button, "Download" button
- **PLAY button**: Large red button, prominent in page
- **Action**: Tap "PLAY" to start playback

### Stage 5: Playback Screen ✅
- Video playing full-screen
- Overlay controls: pause/play, timeline scrubber, volume
- **OCR**: Title text, episode info, timestamp "0:00 / 1:23:45"
- **This state = GOAL ACHIEVED** for "watch content" goals

---

## Navigation for Specific Content
1. Tap search icon (magnifying glass, top-right)
2. Type content name
3. Tap result thumbnail
4. Tap "PLAY" button
5. Playback starts

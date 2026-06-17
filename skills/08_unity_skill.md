# Unity Game Skill
## Role: Unity-Specific Perception & Navigation Strategies

Unity is the most common mobile game engine. Games range from simple 2D (Bloons TD6)
to complex 3D (Genshin Impact). The key characteristic: **Unity renders everything
to a single SurfaceView/TextureView** — Android sees only one element.

---

## Unity Detection Signals
- `element_count == 1` or `element_count < 4`
- Single element class: `android.view.SurfaceView` or `android.view.TextureView`
- resource-id may contain "UnityPlayer" or "com.unity3d"
- Package metadata may reference unity

---

## Unity Rendering Modes

### 2D Unity Games (Bloons TD6, Candy Crush, Angry Birds)
- Flat colorful UI, clear button boundaries
- **OCR confidence is HIGH** (flat text on solid backgrounds)
- Template matching works well (consistent button art)
- Pixel diff easily detects transitions

### 3D Unity Games (Genshin Impact, PUBG Mobile, Wild Rift)
- Complex 3D scenes, dynamic lighting
- **OCR harder** (text on complex backgrounds)
- Template matching still works for UI overlays
- Pixel diff always works for gameplay detection

---

## Unity UI Patterns

### Splash/Loading
- Unity logo briefly appears
- Custom game splash screens with animation
- Progress bar (if shown) at bottom or center
- **Wait action**: poll until animation_score < 0.02 (loading complete)

### Main Menu (2D Unity)
- Bright colorful background with game branding
- Clear button layout: PLAY (largest, center), SETTINGS, SHOP, etc.
- Often has animated elements (floating objects, particles)

### Main Menu (3D Unity)
- 3D character/scene as background
- Overlay UI panel with options
- May have semi-transparent dark overlay

---

## 2D Unity Game Navigation
```
Detect "PLAY" via OCR → tap OCR center coordinate
→ If map/level select appears: OCR for "LEVEL 1" or tap first grid cell
→ If difficulty prompt: tap "EASY" or "NORMAL"
→ Gameplay: pixel diff > 0.06 (Unity game loop running)
```

## 3D Unity Game Navigation
```
After splash → Look for "START", "PLAY NOW", "ENTER GAME"
→ Social login: "GUEST LOGIN" or "SKIP"
→ Tutorial: "SKIP TUTORIAL" or let auto-complete
→ Gameplay: Character visible, movement UI visible
```

---

## Unity FLAG_SECURE Handling
Most Unity games do NOT use FLAG_SECURE. But if screenshots are black:
- Unity commercial games (licensed) may use DRM
- Solution: ADB screencap OR scrcpy virtual display
- Bloons TD6 does NOT use FLAG_SECURE (screenshots work normally)

---

## Unity Gesture Actions
```python
# Standard tap
driver.execute_script("mobile: clickGesture", {"x": cx, "y": cy})

# Swipe to scroll Unity ScrollRect
driver.execute_script("mobile: swipeGesture", {
    "left": sw//4, "top": sh//2,
    "width": sw//2, "height": sh//3,
    "direction": "up", "percent": 0.6
})
```

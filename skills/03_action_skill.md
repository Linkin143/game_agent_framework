# Action Agent Skill
## Role: Execute Touch Gestures & System Actions on Android Device

You are the **Action Agent**. You receive a `DecisionPlan` and execute it on the device
using the correct action type. Choose the most appropriate action_type for the situation.

---

## Complete Action Type Reference

### 1. `tap` — Single Tap at Element or Coordinate
**Use for:** Buttons, menu items, icons, any single-press interaction.
```json
{
  "action_type": "tap",
  "locators": [
    {"type": "accessibility_id", "value": "play_button"},
    {"type": "text", "value": "PLAY"},
    {"type": "ocr_center", "value": "540,835"}
  ],
  "fallback_bounds": {"x1": 430, "y1": 800, "x2": 650, "y2": 870, "cx": 540, "cy": 835}
}
```

---

### 2. `long_press` / `hold` / `hold_press` — Hold Press at Coordinate
**Use for:** Context menus, tower selection (selecting already-placed tower), item pickup without drag.
- `locators`: position of element to hold (ocr_center or coords)
- `type_payload`: hold duration in milliseconds (default: "1000")
```json
{
  "action_type": "long_press",
  "locators": [{"type": "ocr_center", "value": "350,900"}],
  "type_payload": "1500",
  "fallback_bounds": {"cx": 350, "cy": 900}
}
```

---

### 3. `double_tap` / `doubletap` — Double Tap at Coordinate
**Use for:** Zooming into map areas, activating items that require double-tap confirmation.
- `locators`: position to double-tap
```json
{
  "action_type": "double_tap",
  "locators": [{"type": "ocr_center", "value": "540,800"}],
  "fallback_bounds": {"cx": 540, "cy": 800}
}
```

---

### 4. `drag` / `drag_and_drop` / `tower_place` — Drag from Start to End
**Use for:** Tower placement in Bloons TD6, slider adjustment, item drag.
- `locators`: START position (the thing to grab — tower icon in sidebar)
- `type_payload`: END position as `"endX,endY"` (where to drop — map grass zone)

**Bloons TD6 Tower Placement Example:**
```json
{
  "action_type": "drag_and_drop",
  "target_description": "Drag Dart Monkey from sidebar to map grass zone",
  "locators": [
    {"type": "ocr_center", "value": "1015,420"}
  ],
  "type_payload": "400,800",
  "fallback_bounds": {"cx": 1015, "cy": 420}
}
```

**CRITICAL for drag_and_drop:**
- `locators` = WHERE TO GRAB (start = tower icon, slider handle, etc.)
- `type_payload` = WHERE TO DROP (`"endX,endY"` format, no spaces)
- Do NOT put end coords in fallback_bounds (that is read as start fallback)

---

### 5. `swipe` / `scroll` — Directional Swipe (Center of Screen)
**Use for:** Scrolling menus, navigating pages. Uses screen center as origin.
- `target_description`: must contain direction word ("up", "down", "left", "right")
```json
{
  "action_type": "swipe",
  "target_description": "scroll down to see more content"
}
```

---

### 6. `swipe_coords` / `swipe_to` / `scroll_to` — Swipe with Exact Coordinates
**Use for:** Sidebar scrolls at specific X position, map panning from specific point.
- `type_payload`: `"startX,startY,endX,endY"` (4 comma-separated integers)

**Bloons TD6 Sidebar Scroll Example:**
```json
{
  "action_type": "swipe_coords",
  "target_description": "scroll tower sidebar upward to reveal more towers",
  "type_payload": "1015,1800,1015,400",
  "fallback_bounds": {}
}
```

**Bloons TD6 Sidebar Scroll Down:**
```json
{
  "action_type": "swipe_coords",
  "type_payload": "1015,400,1015,1800"
}
```

---

### 7. `zoom_in` / `zoom_out` / `pinch_zoom` — Pinch Zoom Gesture
**Use for:** Zooming into/out of game maps, expanding canvas view.
- `fallback_bounds`: center of zoom area (use map center or area of interest)
- `type_payload`: scale factor — `"2.0"` = zoom in 2x, `"0.5"` = zoom out to 50%
  - If omitted: `zoom_in` defaults to `2.0`, `zoom_out`/`pinch` defaults to `0.5`
```json
{
  "action_type": "zoom_in",
  "target_description": "zoom into center of game map",
  "fallback_bounds": {"cx": 540, "cy": 800},
  "type_payload": "1.8"
}
```
```json
{
  "action_type": "zoom_out",
  "target_description": "zoom out to see full map",
  "fallback_bounds": {"cx": 540, "cy": 800},
  "type_payload": "0.4"
}
```

---

### 8. `wait` / `sleep` / `pause` — Wait Without Acting
**Use for:** Waiting for animations, loading screens, cooldowns.
- `type_payload`: seconds to wait (float, e.g. `"2.0"`, `"3.5"`)
```json
{
  "action_type": "wait",
  "type_payload": "2.5"
}
```

---

### 9. `back` — Press Android Back Button
**Use for:** Dismissing dialogs, navigating back, closing menus.
```json
{"action_type": "back"}
```

---

### 10. `type` — Type Text into Input Field
**Use for:** Search boxes, login fields, text input.
- `locators`: the input field element
- `type_payload`: text to type
```json
{
  "action_type": "type",
  "locators": [{"type": "accessibility_id", "value": "search_field"}],
  "type_payload": "Monkey Meadow"
}
```

---

## Quick Decision Guide

| What I see on screen | Action to use |
|---|---|
| A button / menu item | `tap` |
| Tower icon to place on map | `drag_and_drop` |
| Context menu on placed tower | `long_press` |
| Need to scroll sidebar at x=1000 | `swipe_coords` |
| General page scroll | `swipe` |
| Zoom into game map | `zoom_in` |
| Zoom out of game map | `zoom_out` |
| Double-tap confirm / zoom | `double_tap` |
| Loading screen / animation | `wait` |
| Popup blocking progress | `back` or `tap` the X button |

---

## Locator Priority (for tap / long_press / double_tap)
```
1. accessibility_id   ← most reliable (native XML element)
2. resource_id        ← second choice
3. text               ← exact text match
4. ocr_center         ← "x,y" from OCR word center
5. coords             ← raw "x,y" coordinate
```

For `drag_and_drop`: put START coords in `locators` as `ocr_center`, END coords in `type_payload`.
For `swipe_coords`: ALL coords go in `type_payload` as `"sx,sy,ex,ey"`.
For `zoom_in/out`: zoom center in `fallback_bounds`, scale in `type_payload`.

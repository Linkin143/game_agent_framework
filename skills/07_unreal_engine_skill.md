# Unreal Engine 5 Game Skill
## Role: UE5-Specific Perception & Navigation Strategies

Games built with Unreal Engine 5 present unique challenges:
- No Android accessibility tree (Slate UI is fully rendered on GPU)
- Dynamic resolution scaling (screen content changes with device load)
- Complex particle effects and post-processing make OCR harder
- Touch input handled by custom Slate input router

---

## UE5 Detection Signals
- `element_count < 5` (virtually no Android UI elements)
- Screenshot shows high-quality 3D rendered scene
- High image entropy (> 7.5) due to 3D content complexity
- Package may contain "ue4" or "ue5" or "unrealengine" in metadata
- No `resource-id` patterns from any known Android framework

---

## Perception Approach for UE5 Games
1. **Screenshot ONLY** — XML tree provides nothing useful
2. **OCR is primary** — Unreal Slate UI renders text as pixels; EasyOCR reads it
3. **Template matching** — Pre-capture UI element reference PNGs
4. **Regional analysis** — Menus are typically at screen edges/center
5. **Color analysis** — UI overlays usually use solid/semi-transparent backgrounds

---

## Common UE5 UI Patterns

### Main Menu
- Large cinematic background (3D scene or video)
- 3–5 menu options stacked vertically in center
- "PLAY" / "CAMPAIGN" / "MULTIPLAYER" / "SETTINGS" / "QUIT"
- Touch anywhere → usually advances past splash screens

### Loading Screens
- Progress bar at bottom (thin bar, possibly with percentage)
- Loading spinner or animated logo
- Text: "Loading...", "Please wait...", percentage like "73%"
- **Do NOT tap during loading** — wait for animation to complete

### In-Game HUD (Gameplay Active)
- Player health/stamina bar (top-left usually)
- Minimap (top-right corner usually)
- Action buttons (bottom-right area, large touch targets)
- Score/objective text (top-center)

---

## Action Strategy for UE5
1. **Tier 1**: OCR coordinate tap (text found → tap its center)
2. **Tier 2**: Template match (reference_assets/ue5_*.png)
3. **Tier 3**: Spatial heuristic tap:
   - "PLAY" is usually at screen center or center-bottom third
   - "X" close buttons are top-right corner (90% of games)
   - "OK" / "Continue" buttons are center-bottom

---

## Gameplay Confirmation for UE5
- Pixel diff > 0.08 between consecutive frames (3D scene rendering)
- OCR finds HUD text (health, ammo, objective, timer)
- No large centered text overlay (loading complete)
- Animation is continuous (game loop running)

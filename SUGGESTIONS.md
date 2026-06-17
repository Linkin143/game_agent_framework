# 🎮 Multi-Agentic Game Framework — Architecture Suggestions
## Before Implementation: What We're Adding & Why

---

## 🔑 Core Philosophy Change

**OLD**: Step-by-step test script → agent executes → passes/fails  
**NEW**: **Goal-driven autonomous play** → `"Launch Bloons TD6 and go to gameplay"` → agents sense, decide, act in a continuous live loop

---

## 🧠 Suggestions for Maximum Accuracy

### SUG-1: Concurrent Tri-Modal Perception (CRITICAL)
Instead of sequential screenshot → XML → OCR, capture all 3 **simultaneously** using Python `ThreadPoolExecutor`. Each modality gives different signal:
- **Screenshot** → VLM sees what human sees (game canvas, animations, buttons)
- **XML tree** → Native UI elements with exact locators (when available)
- **OCR** → Text inside game canvas that XML misses (score, level, "PLAY", "START")

A unified `PerceptionState` merges all 3 before any decision. **No agent acts on stale data.**

### SUG-2: Goal Decomposition Agent (CRITICAL for games)
High-level goal `"Go to gameplay in Bloons TD6"` decomposed into:
```
Goal → SubGoals → Micro-Actions
"Play Bloons TD6" → 
  [1] App is open and on main menu
  [2] Level/map selected  
  [3] Game started (gameplay canvas active)
  [4] VERIFY: Gameplay elements visible
```
The orchestrator tracks which subgoal is active and routes to the right specialist agent.

### SUG-3: Game Engine Detection (HIGH)
Automatically detect whether the current screen is:
- **Native Android** (has res_id/acc_id) → use element tree
- **Unity WebGL/IL2CPP** → canvas only, zero element tree, use OpenCV + OCR
- **Unreal Engine** → canvas only, may have Slate UI elements partially exposed

Detection via: element count < 5 AND screenshot entropy > threshold → **Game Canvas Mode**.

### SUG-4: Visual Confidence Scoring (HIGH)
Every decision gets a confidence score 0–1:
- LLM decision confidence
- OpenCV template match confidence
- OCR confidence score

Orchestrator only acts when `max(confidences) > 0.65`. Below threshold → gather more perception data (zoom in, wait for animation end).

### SUG-5: Animation Stillness Gate (HIGH)
Before every action, compare 2 consecutive screenshots at 0.3s interval. If pixel diff > 3% → screen is animating → wait up to 5s for stillness. Eliminates tapping mid-animation.

### SUG-6: Skills as Editable .md Files (INNOVATION)
Each agent reads a `.md` skill file at runtime. The LLM uses the skill as its system prompt. Change agent behavior by editing markdown — zero code changes needed.
```
skills/01_perception_skill.md → "You are a mobile screen perception expert..."
skills/06_game_navigation_skill.md → "Bloons TD6 main menu has [PLAY] button..."
```

### SUG-7: Replay Memory Buffer (MEDIUM)
Successful navigation paths stored in `memory/replay_buffer.json`. On next run:
1. Check if current screen matches a known starting state
2. If yes → replay stored action sequence (instant, no LLM calls needed)
3. If replay fails → fall back to live LLM reasoning

This gives **sub-second navigation** on repeated test runs.

### SUG-8: YOLO-Based UI Element Detection (MEDIUM for games)
For game canvas screens, run a lightweight YOLO model (YOLOv8-nano) trained on common game UI elements: buttons, health bars, start icons, close buttons. Provides bounding boxes when OCR and XML both fail.

Alternative: Use OpenCLIP zero-shot classification — "which of these is a PLAY button?" without pre-training.

### SUG-9: Pixel Region Diff Verifier (MEDIUM)
After every action, compute pixel diff between pre/post screenshots. Classify:
- diff < 1% → NO_CHANGE (action failed)
- diff 1–20% → PARTIAL (overlay appeared, text changed)
- diff > 20% → TRANSITION (new screen loaded)

**Never calls LLM for verification** when pixel diff gives a deterministic answer.

### SUG-10: FLAG_SECURE Bypass for DRM Games (CRITICAL for games)
Games with DRM return black screenshots. Framework should:
1. Detect all-black screenshot (mean pixel value < 5)
2. Switch to `scrcpy` virtual display capture
3. If scrcpy unavailable → ADB framebuffer capture

Already partially implemented; new framework makes it automatic.

### SUG-11: Multi-Resolution Template Matching
For cross-device compatibility, maintain template variants at scales: 0.5×, 0.75×, 1.0×, 1.25×, 1.5×. Try all scales automatically. Confidence threshold auto-adjusts based on template quality.

### SUG-12: Fallback Cascade Transparency
Every action logs which fallback level was used (0–5). Level 5 = pure random grid tap. Orchestrator tracks cascade depth per session. If cascade > 3 repeatedly → trigger "lost state" recovery (restart app).

---

## 🏗 New Architecture Overview

```
                    ┌─────────────────────────────────┐
                    │     Orchestrator Agent           │
                    │  (LangGraph StateGraph)          │
                    │  Goal: "Launch Bloons & Play"    │
                    └─────┬───────────────┬────────────┘
                          │               │
            ┌─────────────▼─┐     ┌───────▼──────────┐
            │  Goal Decomp  │     │  Memory Agent    │
            │  SubGoal Plan │     │  Replay Buffer   │
            └─────────────┬─┘     └───────┬──────────┘
                          │               │
                    ┌─────▼───────────────▼────────────┐
                    │       SENSE  (Perception Agent)   │
                    │  ┌─────────┐ ┌─────┐ ┌─────────┐ │
                    │  │Screenshot│ │ XML │ │  OCR    │ │
                    │  │ + YOLO  │ │Tree │ │EasyOCR  │ │
                    │  └────┬────┘ └──┬──┘ └────┬────┘ │
                    │       └─────────┼──────────┘      │
                    │          PerceptionState           │
                    └──────────────┬─────────────────────┘
                                   │
                    ┌──────────────▼─────────────────────┐
                    │      TEST  (Decision Agent)         │
                    │  VLM + skill: decision_skill.md     │
                    │  + Animation Gate + Confidence Score│
                    └──────────────┬─────────────────────┘
                                   │
                    ┌──────────────▼─────────────────────┐
                    │       ACT  (Action Agent)           │
                    │  T1: Element locator                │
                    │  T2: OpenCV template                │
                    │  T3: Hardware coordinate tap        │
                    └──────────────┬─────────────────────┘
                                   │
                    ┌──────────────▼─────────────────────┐
                    │    VERIFY  (Verification Agent)     │
                    │  Pixel diff + LLM + SubGoal check  │
                    │  → Loop back to SENSE if not done  │
                    └─────────────────────────────────────┘
```

---

## 📁 New Directory Structure

```
game_agent_framework/
├── skills/                         ← Editable .md skill files
│   ├── 00_orchestrator_skill.md
│   ├── 01_perception_skill.md
│   ├── 02_decision_skill.md
│   ├── 03_action_skill.md
│   ├── 04_verification_skill.md
│   ├── 05_memory_skill.md
│   ├── 06_game_navigation_skill.md
│   ├── 07_unreal_engine_skill.md
│   ├── 08_unity_skill.md
│   └── 09_fallback_skill.md
│
├── orchestrator/
│   ├── __init__.py
│   └── graph.py                    ← LangGraph: SENSE→TEST→ACT→VERIFY loop
│
├── agents/
│   ├── __init__.py
│   ├── base_agent.py               ← Skill loader + LLM wrapper
│   ├── perception_agent.py         ← Tri-modal concurrent perception
│   ├── decision_agent.py           ← VLM goal-driven decision
│   ├── action_agent.py             ← 3-tier action + repair
│   ├── verification_agent.py       ← Post-action verify
│   └── memory_agent.py             ← Replay buffer
│
├── core/
│   ├── __init__.py
│   ├── screen_capture.py           ← Live screenshot (Appium + ADB + scrcpy)
│   ├── ocr_engine.py               ← EasyOCR text extraction
│   ├── xml_extractor.py            ← XML/DOM tree
│   ├── image_analyzer.py           ← OpenCV + template matching
│   └── action_executor.py          ← Low-level Appium execution
│
├── config/
│   ├── __init__.py
│   └── capabilities.py
│
├── utils/
│   ├── __init__.py
│   ├── annotation.py               ← Screenshot annotation with bboxes
│   └── cv_utils.py                 ← OpenCV helpers
│
├── memory/
│   └── replay_buffer.json          ← Successful path replay storage
│
├── reference_assets/
│   └── .gitkeep
│
├── SUGGESTIONS.md                  ← This file
├── requirements.txt
├── example.env
└── run_game.py                     ← Entry: python run_game.py "Bloons TD6"
```

from __future__ import annotations

from dataclasses import dataclass
import re



_STOPWORDS = {
    "THE", "AND", "FOR", "WITH", "THIS", "THAT", "YOUR", "FROM", "INTO",
    "ONTO", "MORE", "LESS", "NEXT", "BACK", "OPEN", "CLOSE", "PLEASE",
    "WAIT", "THEN", "CONTINUE", "BUTTON", "SCREEN", "PAGE", "VIEW",
}

_LOADING_WORDS = {
    "LOADING", "DOWNLOADING", "CONNECTING", "RECONNECTING", "PROCESSING",
    "PENDING", "INITIALIZING", "PREPARING", "SYNCING",
}
_DIALOG_WORDS = {
    "ALLOW", "DENY", "ACCEPT", "AGREE", "CANCEL", "SKIP", "LATER",
    "CLOSE", "OK", "CLAIM", "COLLECT", "PERMIT",
}
_MENU_WORDS = {
    "PLAY", "START", "HOME", "SHOP", "SETTINGS", "PROFILE", "LOGIN",
    "SIGN", "HEROES", "MONKEYS", "STORE",
}
_SELECTION_WORDS = {
    "SELECT", "CHOOSE", "MODE", "MAP", "LEVEL", "STAGE", "WORLD",
    "DIFFICULTY", "EASY", "MEDIUM", "HARD",
}
_GAMEPLAY_WORDS = {
    "ROUND", "LIVES", "LIFE", "CASH", "SCORE", "COINS", "HP", "HEALTH",
    "WAVE", "GOLD", "MANA", "ENERGY", "PAUSE", "UPGRADE", "UPGRADES",
    "TOWER", "TOWERS", "HERO", "BLOONS",
}


@dataclass
class ScreenSummary:
    kind: str
    label: str
    keywords: list[str]
    signature: str


def extract_keywords(*texts: str, limit: int = 8) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for text in texts:
        for token in re.findall(r"[A-Za-z0-9]+", (text or "").upper()):
            if len(token) < 2:
                continue
            if token in _STOPWORDS:
                continue
            if token.isdigit() and len(token) < 2:
                continue
            if token not in seen:
                seen.add(token)
                out.append(token)
            if len(out) >= limit:
                return out
    return out


def summarize_perception(p) -> ScreenSummary:
    if p is None:
        return ScreenSummary(
            kind="UNKNOWN",
            label="UNKNOWN",
            keywords=[],
            signature="UNKNOWN",
        )

    texts: list[str] = []
    if getattr(p, "all_text", ""):
        texts.append(p.all_text)
    for el in getattr(p, "selector_map", [])[:25]:
        for key in ("text", "acc_id", "res_id"):
            value = el.get(key)
            if value:
                texts.append(str(value))

    keywords = extract_keywords(*texts, limit=10)
    token_set = set(keywords)
    kind = _infer_kind(
        token_set=token_set,
        context=str(getattr(p, "context", "")),
        rendering_engine=str(getattr(p, "rendering_engine", "")),
        is_black=bool(getattr(p, "is_black_screen", False)),
        animation_score=float(getattr(p, "animation_score", 0.0) or 0.0),
        element_count=int(getattr(p, "element_count", 0) or 0),
    )

    lead = " ".join(keywords[:4]) if keywords else kind
    label = f"{kind}: {lead}" if lead else kind
    signature = f"{kind}|{'|'.join(keywords[:6])}"
    return ScreenSummary(kind=kind, label=label, keywords=keywords, signature=signature)


def screen_matches(summary: ScreenSummary, label: str) -> bool:
    want = extract_keywords(label, limit=6)
    if not want:
        return False
    overlap = len(set(want) & set(summary.keywords))
    if overlap >= max(1, min(2, len(want))):
        return True
    wanted_kind = _infer_kind_from_keywords(set(want))
    return bool(wanted_kind and wanted_kind == summary.kind)

def _infer_kind(
    token_set: set[str],
    context: str,
    rendering_engine: str,
    is_black: bool,
    animation_score: float,
    element_count: int,
) -> str:
    if is_black:
        return "BLACK"
    if "WEBVIEW" in context.upper() or "CHROMIUM" in context.upper():
        return "WEBVIEW"
    if token_set & _LOADING_WORDS:
        return "LOADING"
    if token_set & _DIALOG_WORDS:
        return "DIALOG"
    if (token_set & _GAMEPLAY_WORDS) and (
        animation_score > 0.02 or rendering_engine.upper() in {"UNITY", "UNREAL", "CANVAS"}
    ):
        return "ACTIVE_GAMEPLAY"
    if token_set & _SELECTION_WORDS:
        return "SELECTION"
    if token_set & _MENU_WORDS:
        return "MENU"
    if element_count >= 5:
        return "UI_SCREEN"
    if rendering_engine.upper() in {"UNITY", "UNREAL", "CANVAS"}:
        return "CANVAS_SCREEN"
    return "UNKNOWN"


def _infer_kind_from_keywords(token_set: set[str]) -> str:
    if token_set & _LOADING_WORDS:
        return "LOADING"
    if token_set & _DIALOG_WORDS:
        return "DIALOG"
    if token_set & _GAMEPLAY_WORDS:
        return "ACTIVE_GAMEPLAY"
    if token_set & _SELECTION_WORDS:
        return "SELECTION"
    if token_set & _MENU_WORDS:
        return "MENU"
    return ""

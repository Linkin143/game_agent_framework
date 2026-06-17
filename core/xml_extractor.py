# core/xml_extractor.py
# =============================================================================
# XML / Accessibility Tree Extractor
# Parses the Android UI XML tree to extract all native UI elements with
# their locators. For game canvases (Unity/Unreal), this returns very few
# elements — the system gracefully handles the empty-tree case.
# =============================================================================

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Optional

from bs4 import BeautifulSoup


@dataclass
class UIElement:
    """A single UI element extracted from the XML accessibility tree."""
    index:            int
    element_id:       str       # resource-id
    accessibility_id: str       # content-desc
    text:             str
    class_name:       str
    bounds:           dict      # {x1, y1, x2, y2, cx, cy, w, h}
    clickable:        bool
    enabled:          bool
    checkable:        bool

    def to_locators(self) -> list[dict]:
        """Return all available locators in priority order."""
        locs = []
        if self.accessibility_id:
            locs.append({"type": "accessibility_id", "value": self.accessibility_id})
        if self.element_id:
            locs.append({"type": "resource_id", "value": self.element_id})
        if self.text:
            locs.append({"type": "text", "value": self.text})
            locs.append({"type": "uiautomator", "value": f'new UiSelector().text("{self.text}")'})
        if self.bounds:
            locs.append({"type": "coords",
                          "value": f"{self.bounds['cx']},{self.bounds['cy']}"})
        return locs

    def to_dict(self) -> dict:
        return {
            "idx":      self.index,
            "res_id":   self.element_id,
            "acc_id":   self.accessibility_id,
            "text":     self.text,
            "class":    self.class_name,
            "bounds":   self.bounds,
            "clickable":self.clickable,
            "enabled":  self.enabled,
            "center":   f"{self.bounds.get('cx',0)},{self.bounds.get('cy',0)}",
        }


@dataclass
class XMLExtractionResult:
    """Result of extracting the XML accessibility tree."""
    elements:      list[UIElement]
    selector_map:  list[dict]    # Flat list of element dicts for LLM context
    context:       str           # "NATIVE_APP" | "WEBVIEW" | "CHROMIUM"
    current_url:   str
    element_count: int
    has_content:   bool          # True if at least some named elements exist
    duration_ms:   float


class XMLExtractor:
    """
    Extracts and parses the Android UI XML tree from Appium page source.
    Handles both NATIVE_APP and WEBVIEW contexts.
    For game canvases (Unity/Unreal), the XML tree will be nearly empty —
    this is expected and handled gracefully.
    """

    def __init__(self, driver) -> None:
        self._driver = driver

    def extract(self) -> XMLExtractionResult:
        """
        Fetch and parse the current UI page source.
        Returns structured elements even if the tree is nearly empty.
        """
        t0 = time.time()

        # Determine context
        try:
            context = self._driver.current_context or "NATIVE_APP"
        except Exception:
            context = "NATIVE_APP"

        current_url = ""
        try:
            if "WEBVIEW" in context or "CHROMIUM" in context:
                current_url = self._driver.current_url or ""
        except Exception:
            pass

        # Get page source
        try:
            page_source = self._driver.page_source or ""
        except Exception as exc:
            print(f"[xml_extractor] page_source error: {exc}")
            page_source = ""

        # Parse based on context
        if "WEBVIEW" in context or "CHROMIUM" in context:
            elements = self._parse_html(page_source)
        else:
            elements = self._parse_xml(page_source)

        selector_map = [el.to_dict() for el in elements]
        has_content  = any(e.text or e.accessibility_id for e in elements)
        duration_ms  = (time.time() - t0) * 1000

        return XMLExtractionResult(
            elements=      elements,
            selector_map=  selector_map,
            context=       context,
            current_url=   current_url,
            element_count= len(elements),
            has_content=   has_content,
            duration_ms=   duration_ms,
        )

    # -------------------------------------------------------------------------
    # Private: XML Parser (NATIVE_APP)
    # -------------------------------------------------------------------------

    def _parse_xml(self, xml_source: str) -> list[UIElement]:
        """Parse native Android XML accessibility tree."""
        if not xml_source:
            return []
        try:
            soup = BeautifulSoup(xml_source, "xml")
            nodes = soup.find_all(attrs={"bounds": True})
            elements = []
            for idx, node in enumerate(nodes):
                bounds = self._parse_bounds(node.get("bounds", "[0,0][0,0]"))
                if bounds["w"] < 2 or bounds["h"] < 2:
                    continue  # Skip invisible zero-size elements
                el = UIElement(
                    index=            idx,
                    element_id=       node.get("resource-id", "") or "",
                    accessibility_id= node.get("content-desc", "") or "",
                    text=             node.get("text", "") or "",
                    class_name=       node.get("class", "") or "",
                    bounds=           bounds,
                    clickable=        node.get("clickable", "false") == "true",
                    enabled=          node.get("enabled", "true") == "true",
                    checkable=        node.get("checkable", "false") == "true",
                )
                elements.append(el)
            return elements
        except Exception as exc:
            print(f"[xml_extractor] XML parse error: {exc}")
            return []

    # -------------------------------------------------------------------------
    # Private: HTML Parser (WEBVIEW)
    # -------------------------------------------------------------------------

    def _parse_html(self, html_source: str) -> list[UIElement]:
        """Parse WebView DOM HTML for interactive elements."""
        if not html_source:
            return []
        try:
            soup = BeautifulSoup(html_source, "html.parser")
            interactive_tags = ["a", "button", "input", "select", "textarea",
                                 "[role=button]", "[onclick]"]
            elements = []
            for idx, tag in enumerate(soup.find_all(
                ["a", "button", "input", "select", "textarea"]
            )[:80]):
                text = tag.get_text(strip=True)[:60] or ""
                el = UIElement(
                    index=            idx,
                    element_id=       tag.get("id", "") or "",
                    accessibility_id= tag.get("aria-label", "") or tag.get("name", "") or "",
                    text=             text,
                    class_name=       tag.name or "",
                    bounds=           {"x1": 0, "y1": 0, "x2": 0, "y2": 0, "cx": 0, "cy": 0, "w": 0, "h": 0},
                    clickable=        True,
                    enabled=          not tag.has_attr("disabled"),
                    checkable=        tag.name in ("input",) and tag.get("type") in ("checkbox", "radio"),
                )
                elements.append(el)
            return elements
        except Exception as exc:
            print(f"[xml_extractor] HTML parse error: {exc}")
            return []

    # -------------------------------------------------------------------------
    # Private: Bounds Parser
    # -------------------------------------------------------------------------

    @staticmethod
    def _parse_bounds(bounds_str: str) -> dict:
        """
        Parse bounds string "[x1,y1][x2,y2]" into a dict with computed center.
        """
        nums = [int(n) for n in re.findall(r"\d+", bounds_str)]
        if len(nums) < 4:
            return {"x1": 0, "y1": 0, "x2": 0, "y2": 0, "cx": 0, "cy": 0, "w": 0, "h": 0}
        x1, y1, x2, y2 = nums[0], nums[1], nums[2], nums[3]
        w  = x2 - x1
        h  = y2 - y1
        cx = x1 + w // 2
        cy = y1 + h // 2
        return {"x1": x1, "y1": y1, "x2": x2, "y2": y2, "cx": cx, "cy": cy, "w": w, "h": h}

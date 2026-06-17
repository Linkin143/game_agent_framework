# core/action_executor.py
# =============================================================================
# Low-Level Appium Action Executor
# Executes all touch/gesture/keyboard actions on the Android device.
# All methods are non-raising — exceptions are caught and returned as errors.
# =============================================================================

from __future__ import annotations

import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from typing import Optional

from appium.webdriver.common.appiumby import AppiumBy


@dataclass
class ActionResult:
    """Result of a single action execution attempt."""
    success:      bool
    method:       str
    coordinates:  Optional[dict] = None
    error:        Optional[str]  = None


class ActionExecutor:
    """
    Executes all low-level touch, gesture, and system actions on the device.
    Wraps Appium with retry logic and fallback to W3C pointer actions.
    """

    def __init__(
        self,
        driver,
        device_serial:    Optional[str] = None,
        post_action_wait: float         = 0.8,
        adb_path:         str           = "adb",
    ) -> None:
        self._driver          = driver
        self._device_serial   = device_serial
        self._post_action_wait = post_action_wait
        self._adb_prefix      = (
            [adb_path, "-s", device_serial] if device_serial else [adb_path]
        )

    # -------------------------------------------------------------------------
    # Element-Based Actions
    # -------------------------------------------------------------------------

    def tap_by_accessibility_id(self, value: str) -> ActionResult:
        try:
            el = self._driver.find_element(AppiumBy.ACCESSIBILITY_ID, value)
            el.click()
            self._wait()
            return ActionResult(success=True, method="accessibility_id")
        except Exception as e:
            return ActionResult(success=False, method="accessibility_id", error=str(e))

    def tap_by_id(self, value: str) -> ActionResult:
        try:
            el = self._driver.find_element(AppiumBy.ID, value)
            el.click()
            self._wait()
            return ActionResult(success=True, method="resource_id")
        except Exception as e:
            return ActionResult(success=False, method="resource_id", error=str(e))

    def tap_by_text(self, value: str) -> ActionResult:
        try:
            xpath = f'//*[@text="{value}"]'
            el = self._driver.find_element(AppiumBy.XPATH, xpath)
            el.click()
            self._wait()
            return ActionResult(success=True, method="text_xpath")
        except Exception as e:
            return ActionResult(success=False, method="text_xpath", error=str(e))

    def tap_by_xpath(self, value: str) -> ActionResult:
        try:
            el = self._driver.find_element(AppiumBy.XPATH, value)
            el.click()
            self._wait()
            return ActionResult(success=True, method="xpath")
        except Exception as e:
            return ActionResult(success=False, method="xpath", error=str(e))

    def tap_by_uiautomator(self, value: str) -> ActionResult:
        try:
            el = self._driver.find_element(AppiumBy.ANDROID_UIAUTOMATOR, value)
            el.click()
            self._wait()
            return ActionResult(success=True, method="uiautomator")
        except Exception as e:
            return ActionResult(success=False, method="uiautomator", error=str(e))

    def tap_text_contains(self, text: str) -> ActionResult:
        """Fuzzy text match using UiAutomator textContains."""
        sel = f'new UiSelector().textContains("{text}")'
        return self.tap_by_uiautomator(sel)

    def tap_desc_contains(self, text: str) -> ActionResult:
        """Fuzzy accessibility desc match using UiAutomator descriptionContains."""
        sel = f'new UiSelector().descriptionContains("{text}")'
        return self.tap_by_uiautomator(sel)

    # -------------------------------------------------------------------------
    # Coordinate-Based Actions (Tier 3 — Never Fails to Execute)
    # -------------------------------------------------------------------------

    def tap_at(self, x: int, y: int) -> ActionResult:
        """
        Execute a raw hardware coordinate tap, bypassing the app hierarchy.
        Uses W3C mobile:clickGesture for maximum compatibility.
        """
        try:
            self._driver.execute_script("mobile: clickGesture", {"x": x, "y": y})
            self._wait()
            return ActionResult(success=True, method="clickGesture",
                                coordinates={"x": x, "y": y})
        except Exception:
            # Fallback to TouchAction
            try:
                self._driver.tap([(x, y)])
                self._wait()
                return ActionResult(success=True, method="driver_tap",
                                    coordinates={"x": x, "y": y})
            except Exception as e:
                return ActionResult(success=False, method="coordinate_tap", error=str(e))

    def long_press_at(self, x: int, y: int, duration_ms: int = 1000) -> ActionResult:
        try:
            self._driver.execute_script("mobile: longClickGesture",
                                         {"x": x, "y": y, "duration": duration_ms})
            self._wait()
            return ActionResult(success=True, method="longClickGesture",
                                coordinates={"x": x, "y": y})
        except Exception as e:
            return ActionResult(success=False, method="long_press", error=str(e))

    def swipe(
        self,
        direction: str,    # "up" | "down" | "left" | "right"
        screen_w: int = 1080,
        screen_h: int = 2400,
        percent:  float = 0.6,
    ) -> ActionResult:
        """Execute a swipe gesture in the specified direction."""
        try:
            self._driver.execute_script("mobile: swipeGesture", {
                "left":      screen_w // 4,
                "top":       screen_h // 4,
                "width":     screen_w // 2,
                "height":    screen_h // 2,
                "direction": direction,
                "percent":   percent,
            })
            self._wait()
            return ActionResult(success=True, method=f"swipe_{direction}")
        except Exception as e:
            return ActionResult(success=False, method="swipe", error=str(e))

    # -------------------------------------------------------------------------
    # System Actions
    # -------------------------------------------------------------------------

    def press_back(self) -> ActionResult:
        try:
            self._driver.back()
            time.sleep(0.5)
            return ActionResult(success=True, method="back")
        except Exception as e:
            return ActionResult(success=False, method="back", error=str(e))

    def press_home(self) -> ActionResult:
        try:
            self._driver.execute_script("mobile: pressKey", {"keycode": 3})
            time.sleep(0.5)
            return ActionResult(success=True, method="home")
        except Exception as e:
            return ActionResult(success=False, method="home", error=str(e))

    def activate_app(self, package: str) -> ActionResult:
        try:
            self._driver.activate_app(package)
            time.sleep(3.0)
            return ActionResult(success=True, method="activate_app")
        except Exception as e:
            return ActionResult(success=False, method="activate_app", error=str(e))

    def force_stop_app(self, package: str) -> ActionResult:
        try:
            cmd = self._adb_prefix + ["shell", "am", "force-stop", package]
            subprocess.run(cmd, capture_output=True, timeout=5.0)
            time.sleep(1.0)
            return ActionResult(success=True, method="force_stop")
        except Exception as e:
            return ActionResult(success=False, method="force_stop", error=str(e))

    def dismiss_keyboard(self) -> ActionResult:
        try:
            self._driver.hide_keyboard()
            return ActionResult(success=True, method="hide_keyboard")
        except Exception as e:
            return ActionResult(success=False, method="hide_keyboard", error=str(e))

    def wait(self, seconds: float) -> ActionResult:
        time.sleep(seconds)
        return ActionResult(success=True, method=f"wait({seconds}s)")

    def get_current_package(self) -> str:
        try:
            return self._driver.current_package or ""
        except Exception:
            return ""

    # -------------------------------------------------------------------------
    # Text Input
    # -------------------------------------------------------------------------

    def type_text(self, element_locator_type: str, element_value: str,
                   text: str, clear_first: bool = True) -> ActionResult:
        """Find an input element and type text into it."""
        try:
            if element_locator_type == "accessibility_id":
                el = self._driver.find_element(AppiumBy.ACCESSIBILITY_ID, element_value)
            elif element_locator_type == "resource_id":
                el = self._driver.find_element(AppiumBy.ID, element_value)
            elif element_locator_type == "xpath":
                el = self._driver.find_element(AppiumBy.XPATH, element_value)
            else:
                el = self._driver.find_element(AppiumBy.XPATH,
                                                f'//*[@text="{element_value}"]')
            if clear_first:
                el.clear()
            el.send_keys(text)
            self._wait()
            return ActionResult(success=True, method="type_text")
        except Exception as e:
            return ActionResult(success=False, method="type_text", error=str(e))

    # -------------------------------------------------------------------------
    # Private
    # -------------------------------------------------------------------------

    def _wait(self) -> None:
        time.sleep(self._post_action_wait)

# core/screen_capture.py
# =============================================================================
# Live Screen Capture Module
# Provides screenshots via 3 methods with automatic fallback:
#   1. Appium driver.get_screenshot_as_base64()  (primary)
#   2. ADB exec-out screencap -p                  (FLAG_SECURE bypass attempt 1)
#   3. scrcpy virtual display frame               (FLAG_SECURE bypass attempt 2)
# =============================================================================

from __future__ import annotations

import base64
import os
import subprocess
import time
from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np


@dataclass
class ScreenCapture:
    """Result of a live screen capture attempt."""
    screenshot_b64:  str          # Base64-encoded PNG
    screenshot_np:   np.ndarray   # NumPy array (H,W,3) BGR
    source:          str          # "appium" | "adb" | "scrcpy" | "none"
    is_black:        bool         # True if mean pixel < 5
    width:           int
    height:          int
    timestamp:       float


class ScreenCapturer:
    """
    Captures live screenshots from a connected Android device.
    Automatically escalates through 3 fallback methods when DRM/FLAG_SECURE
    causes black screenshots.
    """

    BLACK_PIXEL_THRESHOLD = 5     # mean pixel value below this → black screen
    ADB_TIMEOUT           = 5.0   # seconds

    def __init__(
        self,
        driver,
        device_serial: Optional[str] = None,
        adb_path:       str = "adb",
    ) -> None:
        self._driver        = driver
        self._device_serial = device_serial
        self._adb_path      = adb_path
        self._adb_prefix    = (
            [adb_path, "-s", device_serial] if device_serial
            else [adb_path]
        )

    # -------------------------------------------------------------------------
    # Public Interface
    # -------------------------------------------------------------------------

    def capture(self) -> ScreenCapture:
        """
        Capture a fresh screenshot using the best available method.
        Tries methods in priority order and falls back automatically.
        """
        # Method 1: Appium (most reliable, works for standard + native apps)
        result = self._capture_appium()
        if result and not result.is_black:
            return result

        print("[screen_capture] Appium gave black/failed → trying ADB screencap")

        # Method 2: ADB screencap (bypasses some FLAG_SECURE implementations)
        result = self._capture_adb()
        if result and not result.is_black:
            return result

        print("[screen_capture] ADB gave black/failed → trying scrcpy")

        # Method 3: scrcpy (most reliable DRM bypass but requires installation)
        result = self._capture_scrcpy()
        if result:
            return result

        # All methods failed — return empty/black capture
        print("[screen_capture] ALL methods failed — returning empty capture")
        empty = np.zeros((2400, 1080, 3), dtype=np.uint8)
        return ScreenCapture(
            screenshot_b64=self._np_to_b64(empty),
            screenshot_np= empty,
            source=        "none",
            is_black=      True,
            width=         1080,
            height=        2400,
            timestamp=     time.time(),
        )

    def capture_diff(self, interval: float = 0.3) -> float:
        """
        Capture two screenshots `interval` seconds apart and compute
        the pixel difference score (0.0 = identical, 1.0 = completely different).
        Used for animation stillness detection.
        """
        s1 = self.capture()
        time.sleep(interval)
        s2 = self.capture()
        if s1.screenshot_np is None or s2.screenshot_np is None:
            return 0.0
        diff = cv2.absdiff(s1.screenshot_np, s2.screenshot_np)
        return float(diff.mean()) / 255.0

    # -------------------------------------------------------------------------
    # Private: Capture Methods
    # -------------------------------------------------------------------------

    def _capture_appium(self) -> Optional[ScreenCapture]:
        """Capture via Appium driver."""
        try:
            b64 = self._driver.get_screenshot_as_base64()
            np_img = self._b64_to_np(b64)
            h, w = np_img.shape[:2]
            is_black = float(np_img.mean()) < self.BLACK_PIXEL_THRESHOLD
            return ScreenCapture(
                screenshot_b64=b64,
                screenshot_np= np_img,
                source=        "appium",
                is_black=      is_black,
                width=         w,
                height=        h,
                timestamp=     time.time(),
            )
        except Exception as exc:
            print(f"[screen_capture] Appium error: {exc}")
            return None

    def _capture_adb(self) -> Optional[ScreenCapture]:
        """Capture via ADB screencap command."""
        try:
            cmd = self._adb_prefix + ["exec-out", "screencap", "-p"]
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=self.ADB_TIMEOUT,
            )
            if result.returncode != 0 or len(result.stdout) < 1000:
                return None
            png_bytes = result.stdout
            # Fix Windows line endings if any
            png_bytes = png_bytes.replace(b"\r\n", b"\n")
            np_arr  = np.frombuffer(png_bytes, dtype=np.uint8)
            np_img  = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
            if np_img is None:
                return None
            b64    = self._np_to_b64(np_img)
            h, w   = np_img.shape[:2]
            is_black = float(np_img.mean()) < self.BLACK_PIXEL_THRESHOLD
            return ScreenCapture(
                screenshot_b64=b64,
                screenshot_np= np_img,
                source=        "adb",
                is_black=      is_black,
                width=         w,
                height=        h,
                timestamp=     time.time(),
            )
        except Exception as exc:
            print(f"[screen_capture] ADB error: {exc}")
            return None

    def _capture_scrcpy(self) -> Optional[ScreenCapture]:
        """
        Capture a single frame using scrcpy's --screenshot-file option.
        Requires scrcpy to be installed and on PATH.
        """
        try:
            tmp_file = "/tmp/gaf_frame.png"
            serial_args = ["-s", self._device_serial] if self._device_serial else []
            cmd = ["scrcpy"] + serial_args + [
                "--no-display", "--screenshot-file", tmp_file,
                "--max-fps", "1", "--time-limit", "2",
            ]
            subprocess.run(cmd, capture_output=True, timeout=5.0)
            if not os.path.exists(tmp_file):
                return None
            np_img = cv2.imread(tmp_file)
            if np_img is None:
                return None
            os.remove(tmp_file)
            b64    = self._np_to_b64(np_img)
            h, w   = np_img.shape[:2]
            is_black = float(np_img.mean()) < self.BLACK_PIXEL_THRESHOLD
            return ScreenCapture(
                screenshot_b64=b64,
                screenshot_np= np_img,
                source=        "scrcpy",
                is_black=      is_black,
                width=         w,
                height=        h,
                timestamp=     time.time(),
            )
        except Exception as exc:
            print(f"[screen_capture] scrcpy error: {exc}")
            return None

    # -------------------------------------------------------------------------
    # Private: Helpers
    # -------------------------------------------------------------------------

    @staticmethod
    def _b64_to_np(b64: str) -> np.ndarray:
        img_bytes = base64.b64decode(b64)
        np_arr    = np.frombuffer(img_bytes, dtype=np.uint8)
        return cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

    @staticmethod
    def _np_to_b64(img: np.ndarray) -> str:
        _, buf = cv2.imencode(".png", img)
        return base64.b64encode(buf).decode("utf-8")

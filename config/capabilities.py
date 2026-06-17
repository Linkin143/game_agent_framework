# config/capabilities.py
# =============================================================================
# Appium Desired Capabilities & Driver Factory
# Configure your device/emulator settings here.
# All values can be overridden via environment variables (see example.env).
# =============================================================================
from __future__ import annotations
import os
from appium import webdriver
from appium.options.android import UiAutomator2Options 
# ─── Appium Server ────────────────────────────────────────────────────────────
APPIUM_SERVER_URL = os.getenv("APPIUM_SERVER_URL", "http://127.0.0.1:4723")

# ─── Default Capabilities ─────────────────────────────────────────────────────
DESIRED_CAPS = {
    "platformName":          "Android",
    "appium:automationName": "UiAutomator2",
    "appium:deviceName":     os.getenv("DEVICE_NAME",     "emulator-5554"),
    "appium:udid":           os.getenv("DEVICE_UDID",     "emulator-5554"),
    "appium:platformVersion":os.getenv("PLATFORM_VERSION","13.0"),
    "appium:noReset":        True,
    "appium:fullReset":      False,
    "appium:newCommandTimeout": 120,
    "appium:uiautomator2ServerInstallTimeout": 60000,
    "appium:adbExecTimeout": 30000,
    "appium:ignoreHiddenApiPolicyError": True,
    "appium:disableWindowAnimation": True,
    # For game canvas apps — do NOT set appPackage/appActivity here;
    # we activate apps programmatically so we can run multiple games.
}


def get_driver(extra_caps: dict = None) -> webdriver.Remote:
    """
    Create and return an Appium WebDriver instance.
    Pass extra_caps to override specific capabilities for a test run.
    """
    options = UiAutomator2Options()
    caps    = {**DESIRED_CAPS, **(extra_caps or {})}
    for k, v in caps.items():
        options.set_capability(k, v)
    driver = webdriver.Remote(APPIUM_SERVER_URL, options=options)
    driver.implicitly_wait(int(os.getenv("IMPLICIT_WAIT", "3")))
    print(f"[capabilities] Driver created → {APPIUM_SERVER_URL}")
    return driver

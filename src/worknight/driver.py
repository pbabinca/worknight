from __future__ import annotations

from selenium import webdriver
from selenium.webdriver.firefox.service import Service as FirefoxService


def gecko_driver(
    browser_headless, browser_dev_console, browser_profile_path, browser_preferences
):
    options = webdriver.FirefoxOptions()

    if browser_profile_path:
        # firefox -CreateProfile selenium
        # ls -ld ~/.mozilla/firefox/*.selenium
        options.add_argument("-profile")
        options.add_argument(browser_profile_path)

    options.log.level = "trace"
    if browser_dev_console:
        options.add_argument("-devtools")
    if browser_headless:
        options.add_argument("-headless")

    if browser_preferences:
        for name, value in browser_preferences.items():
            options.set_preference(name, value)

    driver = webdriver.Firefox(options=options)

    return driver

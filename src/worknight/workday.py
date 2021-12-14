from __future__ import annotations

import logging
from urllib.parse import urlparse

import backoff
from selenium.common.exceptions import (
    ElementClickInterceptedException,
    NoSuchElementException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

WD_DOMAIN = "myworkday.com"

logger = logging.getLogger(__name__)


class WorkDay:
    def __init__(self, driver, home_url, annotate_actions):
        self.driver = driver
        self._home_url = home_url
        self._annotate_actions = annotate_actions
        self._wait = WebDriverWait(driver, 10)

    def navigate_home(self):
        self.driver.get(self._home_url)

    @property
    def account_languages(self):
        return [self.account_preferences["language"]]

    def annotate_action(self, msg):
        if self._annotate_actions:
            print(msg)

    def _ensure_on_workday_url(self):
        self.annotate_action("Ensure we are on the Workday URL")
        for retry_ in range(1):
            logger.debug("Current URL: %s", self.driver.current_url)
            parsed_url = urlparse(self.driver.current_url)
            if parsed_url.hostname and parsed_url.hostname.endswith(WD_DOMAIN):
                break
            else:
                if retry_ == 0:
                    self._wait = WebDriverWait(self.driver, 60)
                    self.navigate_home()
                    self._wait = WebDriverWait(self.driver, 10)
                else:
                    print(f"Failed to navigate to {WD_DOMAIN}")
                    return False
        return True

    def dismiss_session_expiration(self):
        for retry_ in range(1):
            if retry_ == 0:
                try:
                    session_warning_modal = self.driver.find_element(
                        By.XPATH, "//div[@data-automation-id='sessionWarningModal']"
                    )
                except NoSuchElementException:
                    break
                try:
                    session_warning_modal.find_element(
                        By.XPATH, ".//button[@data-automation-id='uic_resetButton']"
                    ).click()
                    break
                except Exception as error:
                    print(
                        f"Page has session warning modal but I failed to click on a reset the session: {error}"
                    )
                    return False
            else:
                print("Failed to dismiss session expiration modal popup")
                return False
        return True

    @backoff.on_exception(
        backoff.expo,
        ElementClickInterceptedException,
        max_tries=2,
        on_backoff=lambda details: details["args"][0].navigate_home(),
        backoff_log_level=logging.WARNING,
    )
    def hamburger_menu(self, aria_label):
        self.annotate_action(
            "Clicking on icon of hamburger menu to open the Global Navigation"
        )
        self._wait.until(
            EC.element_to_be_clickable(
                (By.XPATH, "//button[@title='Global Navigation']")
            )
        ).click()
        self.annotate_action(f"Clicking on module: {aria_label}")
        self._wait.until(
            EC.element_to_be_clickable((By.XPATH, f"//a[@aria-label='{aria_label}']"))
        ).click()

    @backoff.on_exception(backoff.expo, ElementClickInterceptedException, max_tries=2)
    def _navigate_calendar(self, direction):
        # Timesheet button:
        # <button data-automation-id="nextMonthButton"
        # data-automation-activebutton="true" aria-label="Next
        # Week">...</button>

        button = self.driver.find_element(
            By.XPATH,
            f"//button[@data-automation-id='{direction}MonthButton']",
        )
        _ = button.location_once_scrolled_into_view
        button.click()

    def navigate_calendar(self, direction):
        self.annotate_action(f"Navigating calendar in direction: {direction}")
        # Timesheet is weekly by default:
        # <div id="wd-Calendar-6$40849"
        # data-automation-calendar-automation-ready="true"
        # data-automation-visiblerangeinterval="WEEK_7_DAY"
        # data-automation-visiblerangestartdate="1707087600000">

        # Absence module is monthly by default:
        # <div data-automation-calendar-automation-ready="true"
        # data-automation-visiblerangeinterval="MONTH"
        # data-automation-visiblerangestartdate="1698620400000">
        wd_calendar_element = self.driver.find_element(
            By.XPATH, "//div[@data-automation-visiblerangestartdate]"
        )
        visiblerangestartdate_before = wd_calendar_element.get_dom_attribute(
            "data-automation-visiblerangestartdate"
        )

        try:
            self._navigate_calendar(direction)
        except ElementClickInterceptedException:
            logger.warning(f"Failed to change month towards {direction} after retries.")
            return False

        # wait until change
        self._wait.until(
            EC.presence_of_element_located(
                (
                    By.XPATH,
                    f"//div[@data-automation-visiblerangestartdate!='{visiblerangestartdate_before}']",
                )
            )
        )
        return True

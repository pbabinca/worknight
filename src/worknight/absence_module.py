from __future__ import annotations

import logging
from collections import namedtuple
from datetime import datetime, timedelta

import backoff
import dateparser
from selenium.common.exceptions import (
    ElementClickInterceptedException,
    NoSuchElementException,
    TimeoutException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC

from .workday import WorkDay

logger = logging.getLogger(__name__)

CAL_NEXT = "next"
CAL_PREV = "prev"

WorkdayInfo = namedtuple("WorkdayInfo", ["absent_hours", "worked_hours", "comment"])


class AbsenceRecord:
    def __init__(self):
        self.absences = {}

    def add_absence_from_string(self, absence_info, hours=8):
        parts = [part.strip() for part in absence_info.split("|")]
        if len(parts) == 3:
            if "to" in parts[2]:
                date_parts = parts[2].split("to")
                first_date = dateparser.parse(
                    date_parts[0].strip(), settings={"DATE_ORDER": "YMD"}
                )
                last_date = dateparser.parse(
                    date_parts[1].strip(), settings={"DATE_ORDER": "YMD"}
                )
            else:
                first_date = last_date = dateparser.parse(
                    parts[2].strip(), settings={"DATE_ORDER": "YMD"}
                )
            self._add_absence(first_date, last_date, parts[0], hours, parts[1])
        else:
            print(f"Unexpected number of parts: {parts}")

    def add_absence_from_dict(self, absence_dict):
        first_date = datetime.strptime(absence_dict["First Day of Absence"], "%d/%m/%Y")
        last_date = datetime.strptime(
            absence_dict["Actual Last Day of Absence"], "%d/%m/%Y"
        )
        self._add_absence(first_date, last_date, absence_dict["Type"], 8)

    def add_absence_from_args(
        self, date_str, type_of_leave, hours_str="8 Hours", comment=None
    ):
        date_obj = dateparser.parse(date_str, settings={"DATE_ORDER": "YMD"})
        hours = int(hours_str.split()[0])  # Extract the integer value from the string
        self._add_absence(date_obj, date_obj, type_of_leave, hours, comment)

    def _add_absence(self, first_date, last_date, type_of_absence, hours, comment=None):
        current_date = first_date
        while current_date <= last_date:
            date_key = current_date.strftime("%Y-%m-%d")
            if date_key in self.absences:
                existing = self.absences[date_key]
                if (
                    existing["type"] != type_of_absence
                    or existing["hours"] != hours
                    or existing["comment"] != comment
                ):
                    raise ValueError(
                        f"Conflicting entry on {date_key}. "
                        f"Existing: {existing}, "
                        f"New: {{'type': {type_of_absence}, 'hours': {hours}, 'comment': {comment}}}"
                    )
            else:
                self.absences[date_key] = {
                    "date": current_date,
                    "type": type_of_absence,
                    "hours": hours,
                    "comment": comment,
                }
            current_date += timedelta(days=1)

    def get_workday_info(self, query_date):
        default_workday_hours = 8
        if isinstance(query_date, str):
            query_date = datetime.strptime(query_date, "%Y-%m-%d")
        elif not isinstance(query_date, datetime):
            raise TypeError(
                "query_date must be a string in the format 'YYYY-MM-DD' or a datetime object."
            )

        date_key = query_date.strftime("%Y-%m-%d")
        if date_key in self.absences:
            absence = self.absences[date_key]
            absent_hours = absence["hours"]
        else:
            absent_hours = 0

        worked_hours = max(0, default_workday_hours - absent_hours)
        comment = absence["comment"] if date_key in self.absences else None

        return WorkdayInfo(
            absent_hours=absent_hours, worked_hours=worked_hours, comment=comment
        )


class AbsenceModule(WorkDay):
    def __init__(self, driver, home_url, annotate_actions):
        self.absence_record = AbsenceRecord()
        super().__init__(driver, home_url, annotate_actions)

    @backoff.on_exception(
        backoff.expo,
        ElementClickInterceptedException,
        max_tries=3,
        backoff_log_level=logging.WARNING,
    )
    def _open_details_annual_leave(self, details_button):
        _ = details_button.location_once_scrolled_into_view
        details_button.click()

    @backoff.on_predicate(
        backoff.constant, max_time=3, backoff_log_level=logging.WARNING
    )
    def _process_annual_leave_tr(self, pop_up_dialog):
        for tr in pop_up_dialog.find_elements(
            By.XPATH, ".//div[@data-automation-id='MainTable-0']//tbody/tr"
        ):
            # Thursday, 1 February 2024
            th_date = tr.find_element(
                By.XPATH, "./th//div[@data-automation-id='textView']"
            ).text
            if not th_date:
                return False

            # Annual Leave
            td_prompt_option = tr.find_element(
                By.XPATH, "./td//div[@data-automation-id='promptOption']"
            ).text
            # 8 Hours
            td_text_view = tr.find_element(
                By.XPATH, "./td//div[@data-automation-id='textView']"
            ).text

            # Input field next to label "Comment"
            comment_input = tr.find_element(
                By.XPATH, "//li[descendant::label[contains(text(),'Comment')]]//input"
            ).get_attribute("value")

            return (th_date, td_prompt_option, td_text_view, comment_input)

    def _add_annual_leave(self, details_button):
        logger.debug("Adding annual leave")
        try:
            self._open_details_annual_leave(details_button)
        except ElementClickInterceptedException:
            logger.error("Failed to click on button Annual Leave after retries.")
            raise
        except Exception as error:
            logger.error(
                "Unexpected error while trying to click on Annual Leave: %s", error
            )
            raise

        pop_up_dialog = self._wait.until(
            EC.visibility_of_element_located(
                (By.XPATH, "//div[@data-automation-id='popUpDialog']")
            )
        )
        entries = self._process_annual_leave_tr(pop_up_dialog)
        if not entries:
            logger.error("Unable to process annual leave tr")
            return False
        else:
            th_date, td_prompt_option, td_text_view, comment_input = entries
            self.absence_record.add_absence_from_args(
                th_date, td_prompt_option, td_text_view, comment_input
            )

        try:
            close_button = pop_up_dialog.find_element(
                By.XPATH, ".//button[@data-automation-id='closeButton']"
            )
        except NoSuchElementException:
            raise
        close_button.click()

    def _add_cze_sick_leave(self, button):
        self.annotate_action("Adding CZE sick leave")
        button.click()
        wd_popup_dialog = self._wait.until(
            EC.visibility_of_element_located(
                (
                    By.XPATH,
                    "//div[@role='dialog' and @data-automation-widget='wd-popup']",
                )
            )
        )
        details = {}
        for li in wd_popup_dialog.find_elements(
            By.XPATH, ".//ul[@role='presentation']/li"
        ):
            try:
                label = li.find_element(By.XPATH, ".//label").text
                value = li.find_element(
                    By.XPATH,
                    ".//div[@data-automation-id='textView' or @data-automation-id='promptOption']",
                ).text
            except NoSuchElementException:
                continue
            details[label] = value
        # 'Actual Last Day of Absence': '15/01/2024',
        # 'Estimated Last Day of Absence': '11/01/2024',
        # 'First Day of Absence': '08/01/2024',
        # 'Last Day of Work': '07/01/2024',
        # 'Type': 'CZE Sick Leave'}

        self.absence_record.add_absence_from_dict(details)

        wd_popup_dialog.find_element(
            By.XPATH, ".//button[@data-automation-id='closeButton']"
        ).click()

    def absences(self, year=None, month=None):
        succeeded = self._ensure_on_workday_url()
        if not succeeded:
            return False

        succeeded = self.dismiss_session_expiration()
        if not succeeded:
            return False

        self.hamburger_menu("Absence")

        self.annotate_action("Clicking on Correct My Absence")
        self._wait.until(
            EC.element_to_be_clickable((By.XPATH, "//a[@title='Correct My Absence']"))
        ).click()

        # limit 12 months from current day
        for limit in range(12):
            # self._wait until Date Range Title appears
            date_range_element = self._wait.until(
                EC.visibility_of_element_located(
                    (By.XPATH, "//h2[@data-automation-id='dateRangeTitle']")
                )
            )
            if not year or not month:
                break

            date_range_text = self.driver.find_element(
                By.XPATH, "//h2[@data-automation-id='dateRangeTitle']"
            ).text

            # e.g. "January 2024"
            date_range = dateparser.parse(
                date_range_element.text, settings={"PREFER_DAY_OF_MONTH": "first"}
            ).date()
            requested_date = datetime(year=year, month=month, day=1).date()
            if date_range == requested_date:
                break

            date_range_text = self.driver.find_element(
                By.XPATH, "//h2[@data-automation-id='dateRangeTitle']"
            ).text
            self.annotate_action(f"Currently present on date: {date_range_text}")

            if date_range < requested_date:
                direction = CAL_NEXT
            elif date_range > requested_date:
                direction = CAL_PREV

            succeeded = self.navigate_calendar(direction)
            if not succeeded:
                return False
            continue
        else:
            print("Failed to get to the correct date after too many tries.")
            return False

        try:
            # wait until the calendar redraw settles down
            self._wait.until(
                EC.presence_of_element_located(
                    (
                        By.XPATH,
                        "//div[@data-automation-calendarnavigationoverlayhidden='true']",
                    )
                )
            )
        except TimeoutException:
            raise

        # First, non-clickable events
        # see absence_calendar_snippets.html for following structure

        # Holiday | Restoration Day | Monday, 1 January 2024
        # Approved | CZE Sick Leave | Monday, 8 January 2024 to Monday, 15 January 2024
        # Approved | CZE Sick Leave | Monday, 8 January 2024 to Monday, 15 January 2024
        # Approved | Annual Leave | Thursday, 1 February 2024 to Friday, 2 February 2024

        # ['Approved', 'Annual Leave', 'Thursday, 1 February 2024 to Friday, 2 February 2024']

        for event in self.driver.find_elements(
            By.XPATH, "//div[@data-automation-id='calendarevent']"
        ):
            aria_label = event.get_dom_attribute("aria-label")
            logger.debug("Adding automatic absence events")
            self.absence_record.add_absence_from_string(aria_label, 8)

        # Second, clickable events
        for details_button in self.driver.find_elements(
            By.XPATH, "//button[@data-automation-id='calendarevent']"
        ):
            aria_label = details_button.get_dom_attribute("aria-label")
            parts = aria_label.split(" | ")
            # known full days
            if len(parts) > 1:
                if parts[1] == "Sick Days":
                    self.annotate_action("Adding Sick Days")
                    # calendarevents.append(aria_label)
                elif parts[1] == "CZE Sick Leave":
                    self._add_cze_sick_leave(details_button)
                elif parts[1] == "Annual Leave":
                    self._add_annual_leave(details_button)
                else:
                    raise Exception()
                continue
            else:
                raise Exception()

        return self.absence_record

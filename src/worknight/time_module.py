from __future__ import annotations

import logging
from collections import namedtuple
from datetime import date, datetime

import backoff
import dateparser
from selenium.common.exceptions import (
    ElementNotInteractableException,
    NoSuchElementException,
    StaleElementReferenceException,
    TimeoutException,
)
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC

from .absence_module import AbsenceModule
from .workday import WorkDay

logger = logging.getLogger(__name__)

CAL_NEXT = "next"
CAL_PREV = "prev"

CalendarEvents = namedtuple("CalendarEvents", ["daily", "own"])
DateRange = namedtuple("DateRange", ["start", "end"])
CalendarEvent = namedtuple(
    "CalendarEvent", ["start", "end", "title", "subtitle", "subtitle2"]
)


def parse_calendarevent(event, start_year=2024, end_year=2024):
    # startdate='1-5-9-0' enddate='1-5-13-0'
    # startdate='1-5-13-30' enddate='1-5-17-30'
    # 1-31-0-0
    startdate = event.get_attribute("data-automation-startdate")
    enddate = event.get_attribute("data-automation-enddate")
    # Regular/Time Worked
    title = event.find_element(
        By.XPATH, ".//div[@data-automation-id='calendarAppointmentTitle']"
    ).text
    # 09:00 - 13:00 (Meal)
    subtitle = event.find_element(
        By.XPATH, ".//div[@data-automation-id='calendarAppointmentSubtitle']"
    ).text
    # 4 Hours
    subtitle2 = event.find_element(
        By.XPATH, ".//div[@data-automation-id='calendarAppointmentSubtitle2']"
    ).text

    # To handle February 29:
    #   2-29-0-0
    # add the correct year
    startdate_full = f"{startdate}-{start_year}"
    startdate_obj = datetime.strptime(startdate_full, "%m-%d-%H-%M-%Y")

    enddate_full = f"{enddate}-{end_year}"
    enddate_obj = datetime.strptime(enddate_full, "%m-%d-%H-%M-%Y")

    return CalendarEvent(
        start=startdate_obj,
        end=enddate_obj,
        title=title,
        subtitle=subtitle,
        subtitle2=subtitle2,
    )


class TimeModule(WorkDay):
    def _enter_date_section(self, value, date_section, parent):
        for retry2 in range(1, 6):
            try:
                input_element = parent.find_element(
                    By.XPATH,
                    f".//input[@data-automation-id='dateSection{date_section}-input']",
                )
                input_element.location_once_scrolled_into_view

                action_chains = ActionChains(self.driver)
                action_chains.move_to_element(input_element)
                action_chains.click(input_element)
                action_chains.perform()

                input_element.send_keys(value)

                self._wait.until(
                    EC.presence_of_element_located(
                        (
                            By.XPATH,
                            f"//div[@data-automation-id='dateSection{date_section}-display' "
                            f"and contains(text(),'{value}')]",
                        )
                    )
                )
            except TimeoutException:
                print(f"Retrying {retry2} to enter a {date_section}")
                continue
            return True
        else:
            print("Failed to enter a day even after retries")
            return False
        return True

    def _enter_date(self, day, month, year, parent):
        day_str = str(day).zfill(2)
        month_str = str(month).zfill(2)
        year_str = str(year).zfill(4)
        for retry_ in range(5):
            try:
                succeeded = self._enter_date_section(day_str, "Day", parent)
                if not succeeded:
                    return False

                succeeded = self._enter_date_section(month_str, "Month", parent)
                if not succeeded:
                    return False

                succeeded = self._enter_date_section(year_str, "Year", parent)
                if not succeeded:
                    return False

                self._click_on_ok_button(parent)

                try:
                    error_widget_inline_message_canvas = parent.find_element(
                        By.XPATH,
                        ".//li[@data-automation-id='errorWidgetInlineMessageCanvas']",
                    )
                    message_type = error_widget_inline_message_canvas.find_element(
                        By.XPATH,
                        "./div[@data-automation-id='errorWidgetInlineMessageTypeTextCanvas']",
                    ).text
                    message_text = error_widget_inline_message_canvas.find_element(
                        By.XPATH,
                        "./div[@data-automation-id='errorWidgetInlineMessageTextCanvas']",
                    ).text
                    print(f"{message_type}: {message_text}")
                except NoSuchElementException:
                    # we are done
                    break
                except Exception as error:
                    print(f"Error: {error}")
                    raise
            except NoSuchElementException as error:
                print(f"Retrying {retry_} to enter date: {error}")
                continue
        else:
            print("Failed to enter a date even after retries")
            return False

        return True

    def _navigate_to_week(self, year, month, day):
        self.annotate_action(f"Navigating to: {year}-{month}-{day}")
        self._wait.until(
            EC.element_to_be_clickable((By.XPATH, "//button[@title='Select Week']"))
        ).click()

        edit_popup = self._wait.until(
            EC.visibility_of_element_located(
                (By.XPATH, "//div[@data-automation-id='editPopup']")
            )
        )

        succeeded = self._enter_date(day, month, year, edit_popup)
        if not succeeded:
            return
        return True

    def _time_attendance_pre(self, year, month, day):
        succeeded = self._ensure_on_workday_url()
        if not succeeded:
            return False

        succeeded = self.dismiss_session_expiration()
        if not succeeded:
            return False

        self.hamburger_menu("Time")

        succeeded = self._navigate_to_week(year, month, day)
        if not succeeded:
            return False

        return True

    @backoff.on_exception(
        backoff.constant,
        StaleElementReferenceException,
        max_time=3,
        backoff_log_level=logging.WARNING,
    )
    def _get_daily_events(self):
        events = []
        for event in self.driver.find_elements(
            By.XPATH,
            "//table[contains(@class, 'multiDayBody')]//div[@data-automation-id='calendarevent']",
        ):
            events.append(parse_calendarevent(event))
        return events

    @backoff.on_exception(
        backoff.constant,
        StaleElementReferenceException,
        max_time=3,
        backoff_log_level=logging.WARNING,
    )
    def _get_own_events(self):
        events = []
        for event in self.driver.find_elements(
            By.XPATH,
            "//div[contains(@class, 'gwt-appointment-panel')]//div[@data-automation-id='calendarevent']",
        ):
            events.append(parse_calendarevent(event))
        return events

    def parse_date_range(self, date_range):
        # Split by EN DASH (U+2013)
        parts = date_range.split(" \u2013 ")

        if len(parts) == 1:
            # "1–7 Jan 2024"
            # "6.–12. 5. 2024"
            parts = parts[0].strip().split("–")
            if len(parts) != 2:
                raise ValueError(f"Unknown time range format: {date_range}")

            end_date = dateparser.parse(
                parts[1],
                languages=self.account_languages,
            ).date()
            start_day = dateparser.parse(
                parts[0],
                languages=self.account_languages,
                settings={"REQUIRE_PARTS": ["day"]},
            ).day
            start_date = end_date.replace(day=start_day)
        elif len(parts) == 2:
            end_date = dateparser.parse(
                parts[1],
                languages=self.account_languages,
            ).date()
            if len(parts[0].split(" ")) == 2:
                # 29 Jan – 4 Feb 2024
                start_date = dateparser.parse(
                    parts[0], settings={"REQUIRE_PARTS": ["day", "month"]}
                )
                start_date = start_date.replace(year=end_date.year)
                start_date = start_date.date()
            elif len(parts[0].split(" ")) == 3:
                # 26 Dec 2022 – 1 Jan 2023
                start_date = dateparser.parse(parts[0]).date()
            else:
                raise ValueError(f"Unknown time range format: {date_range}")
        else:
            raise ValueError(f"Unknown time range format: {date_range}")

        return DateRange(start=start_date, end=end_date)

    def _actions_dropdown(self):
        self.annotate_action("Clicking on actions dropdown")
        # <div data-automation-id="dropDownCommandButton" aria-hidden="false">
        #    <button data-automation-activebutton="true"
        #    data-automation-id="label" id="19bd7e9bd1e646adbe4409f11e3ae1a3"
        #    data-automation-button-type="AUXILIARY"
        #    data-automation-task-ids="[...]" title="Actions"
        #    aria-hidden="true" type="button">
        #        <span class="WBMN WMLN"></span>
        #        <span class="WNLN" title="Actions">Actions</span>
        #    </button>
        #    <button data-automation-activebutton="true"
        #    data-automation-id="dropdownArrow" id="18e7f930017a47cea0924bb42a7d7c85"
        #    data-automation-button-type="AUXILIARY" style="" aria-label="Actions"
        #    aria-haspopup="true" aria-expanded="false" type="button">
        #    </button>
        # </div>

        self._wait.until(
            EC.element_to_be_clickable((By.XPATH, "//button[@aria-label='Actions']"))
        ).click()

        # Be nice to the caller and wait until the expected dropdown menu opens
        self._wait.until(
            EC.presence_of_element_located(
                (By.XPATH, "//div[@data-automation-activepopup='true']")
            )
        )

    @backoff.on_exception(
        backoff.constant,
        ElementNotInteractableException,
        max_time=3,
        backoff_log_level=logging.WARNING,
    )
    def _action_option_auto_fill_from_prior_week(self):
        self.annotate_action("Selecting Auto-fill from Prior Week")
        # <div data-popup-version="2" data-automation-widget="wd-popup"
        #    data-uxi-widget-type="popup"
        #    data-associated-widget="wd-DropDownCommandButton-6$132535"
        #    data-automation-activepopup="true">
        #    <div class="WPT wd-popup-content">
        #        <ul tabindex="0" role="listbox" data-automation-id="menuList"
        #        aria-labelledby="37ab974adcc14b1a868ea00c61cbfa4c"
        #        aria-activedescendant="1d86c8b7482a45c2ba72f827d647924a">
        #            <li role="presentation">
        #                <div id="1d86c8b7482a45c2ba72f827d647924a"
        #                data-automation-id="dropdown-option" aria-selected="false"
        #                data-automation-dropdown-option="dropdown-option"
        #                data-automation-label="Auto-fill from Prior Week"
        #                role="option" aria-setsize="8"
        #                aria-posinset="1">Auto-fill from Prior Week</div>
        #            </li>
        # ...

        # Double check that there is a dropdown menu opened
        self._wait.until(
            EC.presence_of_element_located(
                (By.XPATH, "//div[@data-automation-activepopup='true']")
            )
        )
        auto_fill_option = self._wait.until(
            EC.presence_of_element_located(
                (
                    By.XPATH,
                    "//div[@data-automation-activepopup='true']//"
                    "div[@data-automation-label='Auto-fill from Prior Week']",
                )
            )
        )
        _ = auto_fill_option.location_once_scrolled_into_view

        auto_fill_option.click()

    def _open_dropdown_select_prior_week(self):
        self.annotate_action(
            "Clicking on dropdown Select Prior Week on popup Auto-fill from Prior Week to open the dropdown menu"
        )
        # <li role="presentation">
        #    <div>
        #        <label>Select Prior Week</label>
        #        <div>Select Prior Week</div>
        #    </div>
        #    <div>
        #        <div>
        #            <div role="button" data-automation-id="selectWidget" aria-invalid="false">
        #                <div>
        #                    <div data-automation-id="selectSelectedOption">select one</div>
        #                </div>
        #                <div>
        #                    <div data-automation-id="selectShowAll">
        #                        <div role="presentation"></div>
        #                    </div>
        #                </div>
        #                <div>select one</div>
        #            </div>
        #        </div>
        #    </div>
        # </li>

        self._wait.until(
            EC.element_to_be_clickable(
                (
                    By.XPATH,
                    "//li[descendant::label[contains(text(),'Select Prior Week')]]//"
                    "div[@data-automation-id='selectSelectedOption']",
                )
            )
        ).click()
        logger.debug("Waiting for dropdown menu to appear")
        self._wait.until(
            EC.presence_of_element_located(
                (
                    By.XPATH,
                    "//ul[@aria-label='Select Prior Week']",
                )
            )
        )
        logger.debug("Dropdown menu appeared")

    def _close_dropdown_select_prior_week(self):
        self.annotate_action(
            "Clicking on dropdown Select Prior Week on popup Auto-fill from Prior Week to close the dropdown menu"
        )

        self._wait.until(
            EC.element_to_be_clickable(
                (
                    By.XPATH,
                    "//li[descendant::label[contains(text(),'Select Prior Week')]]//"
                    "div[@data-automation-id='selectSelectedOption']",
                )
            )
        ).click()
        logger.debug("Waiting for dropdown menu to disappear")
        self._wait.until(
            EC.invisibility_of_element_located(
                (
                    By.XPATH,
                    "//ul[@aria-label='Select Prior Week']",
                )
            )
        )
        logger.debug("Dropdown menu disappeared")

    @backoff.on_exception(
        backoff.constant,
        StaleElementReferenceException,
        max_time=3,
        backoff_log_level=logging.WARNING,
    )
    def _populate_prior_weeks(self):
        self.annotate_action("Populating prior weeks options")
        prior_weeks = []
        for option in self.driver.find_elements(
            By.XPATH,
            "//ul[@aria-label='Select Prior Week']//div[@data-automation-id='promptOption']",
        ):
            # <div data-automation-id="promptOption" id="promptOption-gwt-uid-11"
            # data-automation-label="29/01/2024 - 04/02/2024" title="29/01/2024 -
            # 04/02/2024" aria-label="29/01/2024 - 04/02/2024">...</div>
            if option.get_attribute("aria-label") == "select one":
                continue
            prior_weeks.append(option.get_attribute("aria-label"))
        return prior_weeks

    def _list_prior_weeks(self):
        self.annotate_action("Listing prior weeks")
        self._open_dropdown_select_prior_week()
        prior_weeks = self._populate_prior_weeks()
        self._close_dropdown_select_prior_week()
        return prior_weeks

    @backoff.on_exception(
        backoff.constant,
        (StaleElementReferenceException, ElementNotInteractableException),
        max_time=5,
        backoff_log_level=logging.WARNING,
    )
    def _select_option_in_prior_week(self, aria_label):
        self.annotate_action(
            f"Selecting option with label {aria_label} from prior week dropdown"
        )
        for option in self.driver.find_elements(
            By.XPATH,
            "//ul[@aria-label='Select Prior Week']//div[@data-automation-id='promptOption']",
        ):
            # <div data-automation-id="promptOption" id="promptOption-gwt-uid-11"
            # data-automation-label="29/01/2024 - 04/02/2024" title="29/01/2024 -
            # 04/02/2024" aria-label="29/01/2024 - 04/02/2024">...</div>
            if option.get_attribute("aria-label") == "select one":
                continue
            if option.get_attribute("aria-label") != aria_label:
                logger.debug(
                    "Week label: %s is not the one I look for: %s. Continuing.",
                    option.get_attribute("aria-label"),
                    aria_label,
                )
                continue
            logger.debug("Found week label: %s", option.get_attribute("aria-label"))
            table = self.driver.find_element(
                By.XPATH,
                "//div[@data-automation-id='rivaWidget']//table",
            )

            option.click()

            # Wait until table disappears
            self._wait.until(EC.staleness_of(table))
            # Wait until table appears again
            table = self._wait.until(
                EC.presence_of_element_located(
                    (
                        By.XPATH,
                        "//div[@data-automation-id='rivaWidget']//table",
                    )
                )
            )

    def _select_prior_week(self, aria_label):
        self.annotate_action(f"Selecting prior week with label: {aria_label}")
        self._open_dropdown_select_prior_week()
        self._select_option_in_prior_week(aria_label)

    @backoff.on_exception(
        backoff.constant,
        StaleElementReferenceException,
        max_time=3,
        backoff_log_level=logging.WARNING,
    )
    def _prior_week_table_map(self):
        self.annotate_action("Reading prior week data table")
        self._wait.until(
            EC.invisibility_of_element_located(
                (
                    By.XPATH,
                    "//div[@data-automation-id='rivaWidget']//td[@data-automation-id='emptyState']",
                )
            )
        )
        table = self._wait.until(
            EC.presence_of_element_located(
                (
                    By.XPATH,
                    "//div[@data-automation-id='rivaWidget']//table",
                )
            )
        )
        header = [
            col.text
            for col in table.find_elements(By.XPATH, ".//thead//button/div/span[1]")
        ]
        for row in table.find_elements(By.XPATH, ".//tbody/tr"):
            cols = [col.text for col in row.find_elements(By.XPATH, "./td")]
            if len(cols) == 1 and cols[0] == "No items available.":
                raise ValueError("Out of sudden no items available.")
            if len(cols) != len(header):
                print(
                    f"Mismatch between header ({len(header)}) and columns ({len(cols)})"
                )
                print(f"{header=})")
                print(f"{cols=})")
                continue
            return dict(zip(header, cols))

    def _click_on_ok_button(self, parent):
        parent.find_element(
            By.XPATH,
            ".//button[@data-automation-id='wd-CommandButton_uic_okButton']",
        ).click()

    def _wait_for_page_switch(self, old_title, new_title):
        # Finding element for page switch
        old_title = self.driver.find_element(
            By.XPATH,
            "//div[@data-automation-id='viewStackHeaderTitle']//"
            f"span[@data-automation-id='pageHeaderTitleText'][@title='{old_title}']",
        )

        # Waiting until the old element disappears
        self._wait.until(EC.staleness_of(old_title))

        # Waiting until the new element appears
        self._wait.until(
            EC.presence_of_element_located(
                (
                    By.XPATH,
                    "//div[@data-automation-id='viewStackHeaderTitle']//"
                    f"span[@data-automation-id='pageHeaderTitleText'][@title='{new_title}']",
                )
            )
        )

    def auto_fill_from_prior_week(self, year, month, day):
        succeeded = self._time_attendance_pre(year, month, day)
        if not succeeded:
            return False

        self._actions_dropdown()
        self._action_option_auto_fill_from_prior_week()
        for prior_week_label in self._list_prior_weeks():
            self._select_prior_week(prior_week_label)
            week_map = self._prior_week_table_map()
            if week_map["Total"] in ("40.00", "40,00"):
                break
        else:
            print("Not found prior week with total 40")
            return False
        self._click_on_ok_button(self.driver)

        self._wait_for_page_switch("Auto-fill from Prior Week", "Enter Time")
        return True

    def auto_fill_month(self, year=None, month=None):
        """
        1. Fills all regular work days with attendance
        2. Removes those days that have full day absences
        """
        if not (year or month):
            today = date.today()
            if not year:
                year = today.year
            if not month:
                month = today.month
        succeeded = self._time_attendance_pre(year, month, 1)
        if not succeeded:
            return False

        # Ensure we won't loop over too many weeks
        for week in range(6):
            # Wait until Date Range Title appears
            date_range_element = self._wait.until(
                EC.visibility_of_element_located(
                    (By.XPATH, "//h2[@data-automation-id='dateRangeTitle']")
                )
            )
            date_range = self.parse_date_range(date_range_element.text)
            if date_range.start.month > month or date_range.end.month < month:
                break

            self._actions_dropdown()
            self._action_option_auto_fill_from_prior_week()
            for prior_week_label in self._list_prior_weeks():
                self._select_prior_week(prior_week_label)
                week_map = self._prior_week_table_map()
                if week_map["Total"] in ("40.00", "40,00"):
                    break
            else:
                print("Not found prior week with total 40")
                return False
            self._click_on_ok_button(self.driver)

            self._wait_for_page_switch("Auto-fill from Prior Week", "Enter Time")

            succeeded = self.navigate_calendar(CAL_NEXT)
            if not succeeded:
                return False
        else:
            # Loop more than 6 weeks
            return False

        workday = AbsenceModule(self.driver, self._home_url, self._annotate_actions)
        workday.absences(year=year, month=month)
        # absence_record = workday.absences(year=year, month=month)
        # for date, details in absence_record.absences.items():
        #    if details['comment']:
        #        print(f"{date}: {details['hours']} hours, {details['type']}, {details['comment']}")
        #    else:
        #        print(f"{date}: {details['hours']} hours, {details['type']}")

        succeeded = self._time_attendance_pre(year, month, 1)
        if not succeeded:
            return False

        # Ensure we won't loop over too many weeks
        for week in range(6):
            # Wait until Date Range Title appears
            date_range_element = self._wait.until(
                EC.visibility_of_element_located(
                    (By.XPATH, "//h2[@data-automation-id='dateRangeTitle']")
                )
            )
            date_range = self.parse_date_range(date_range_element.text)
            if date_range.start.month > month or date_range.end.month < month:
                break

            events = self._get_daily_events()
            if events is False:
                return False
            for event in events:
                # prune events outside of requested month
                if event.start.month < month or event.end.month > month:
                    continue
                # print(absence_record.get_workday_info("2024-03-08"))

            succeeded = self.navigate_calendar(CAL_NEXT)
            if not succeeded:
                return False
        else:
            # Loop more than 6 weeks
            return False
        return True

    def list_time_attendance_weekly(self, year, month, day):
        succeeded = self._time_attendance_pre(year, month, day)
        if not succeeded:
            return False
        daily_events = []
        own_events = []
        # Wait until Date Range Title appears
        date_range_element = self._wait.until(
            EC.visibility_of_element_located(
                (By.XPATH, "//h2[@data-automation-id='dateRangeTitle']")
            )
        )

        events = self._get_daily_events()
        if events is False:
            return False
        for event in events:
            daily_events.append(event)

        events = self._get_own_events()
        if events is False:
            return False
        for event in events:
            own_events.append(event)
        return CalendarEvents(daily=daily_events, own=own_events)

    def list_time_attendance_monthly(self, year, month):
        succeeded = self._time_attendance_pre(year, month, 1)
        if not succeeded:
            return False
        daily_events = []
        own_events = []
        # Ensure we won't loop over too many weeks
        for week in range(6):
            # Wait until Date Range Title appears
            date_range_element = self._wait.until(
                EC.visibility_of_element_located(
                    (By.XPATH, "//h2[@data-automation-id='dateRangeTitle']")
                )
            )
            date_range = self.parse_date_range(date_range_element.text)
            if date_range.start.month > month or date_range.end.month < month:
                break

            events = self._get_daily_events()
            if events is False:
                return False
            for event in events:
                # prune events outside of requested month
                if event.start.month < month or event.end.month > month:
                    continue
                daily_events.append(event)

            events = self._get_own_events()
            if events is False:
                return False
            for event in events:
                # prune events outside of requested month
                if event.start.month < month or event.end.month > month:
                    continue
                own_events.append(event)

            succeeded = self.navigate_calendar(CAL_NEXT)
            if not succeeded:
                return False
        else:
            # Loop more than 6 weeks
            return False

        return CalendarEvents(daily=daily_events, own=own_events)

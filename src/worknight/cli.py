from __future__ import annotations

import sys
import traceback
from datetime import datetime

import click
import click_spinner
from click_option_group import optgroup
from selenium.common.exceptions import (
    InvalidSessionIdException,
    NoSuchWindowException,
    SessionNotCreatedException,
    WebDriverException,
)

from .absence_module import AbsenceModule
from .common import (
    configure_logging,
    get_default_handlers,
    get_handlers,
    load_logging_config,
)
from .config import ConfigManager
from .debugger import post_mortem
from .driver import gecko_driver
from .time_module import TimeModule

driver = None


def _handle_unhandled_exception(error, show_traceback, usepdb):
    if show_traceback or usepdb:
        click.echo(traceback.format_exc(), err=True)
        if usepdb:
            post_mortem(error.__traceback__)
    else:
        click.echo(f"Top level exception: {error=}", err=True)


def init_driver(
    headless=True,
    dev_console=False,
    profile_path=None,
    browser_preferences=None,
):
    global driver
    driver = gecko_driver(headless, dev_console, profile_path, browser_preferences)
    if not driver:
        click.echo("Driver not initialized.", err=True)
        sys.exit(1)
    return driver


@click.group()
@optgroup.group("Development")
@optgroup.option(
    "--log-handler",
    type=click.Choice(get_handlers()),
    default=get_default_handlers(),
    show_default=True,
    help="Select the logging handler.",
)
@optgroup.option(
    "--no-headless",
    "browser_headless",
    is_flag=True,
    default=True,
    help="Display browser window during execution.",
)
@optgroup.option(
    "--browser-dev-console",
    is_flag=True,
    default=False,
    help="Open Developer console during execution, implies --no-headless.",
)
@optgroup.option(
    "--no-browser-close-on-finish",
    "browser_close_on_finish",
    is_flag=True,
    default=True,
)
@optgroup.option(
    "--browser-profile-path",
    type=click.Path(exists=True, file_okay=False),
    help=(
        "Path to a directory with browser profile."
        " If not set, profile is created automatically."
    ),
)
@optgroup.option(
    "--annotate-actions",
    is_flag=True,
    default=False,
    help="Annotate actions as they are being performed. If not set, displays a spinner.",
)
@optgroup.option(
    "--pdb",
    "usepdb",
    is_flag=True,
    default=False,
    help="Drop to post mortem python debugger on unhandled top level exception.",
)
@optgroup.option(
    "--show-traceback",
    is_flag=True,
    default=False,
    help=(
        "Display traceback if top level exception was not handled. "
        "Implied when --pdb is used."
    ),
)
@click.pass_context
def main(
    ctx,
    log_handler,
    browser_headless,
    browser_close_on_finish,
    browser_dev_console,
    browser_profile_path,
    annotate_actions,
    usepdb,
    show_traceback,
):
    configure_logging(log_handler)
    ctx.ensure_object(dict)
    if browser_dev_console and browser_headless:
        browser_headless = False
    ctx.obj = {
        "browser_headless": browser_headless,
        "browser_close_on_finish": browser_close_on_finish,
        "browser_dev_console": browser_dev_console,
        "browser_profile_path": browser_profile_path,
        "annotate_actions": annotate_actions,
        "usepdb": usepdb,
        "show_traceback": show_traceback,
    }


@main.group()
def time():
    """Operations of the time module."""
    pass


@time.group()
def autofill():
    """Autofill operations of the time module."""
    pass


@time.group(name="list")
def time_list():
    """List operations of the time module."""
    pass


@autofill.command(name="week")
@click.pass_context
@click.option(
    "--day",
    type=click.IntRange(min=1, max=31),
    default=datetime.today().day,
    show_default=True,
)
@click.option(
    "--month",
    type=click.IntRange(min=1, max=12),
    default=datetime.today().month,
    show_default=True,
)
@click.option(
    "--year",
    type=click.IntRange(min=1993),
    default=datetime.today().year,
    show_default=True,
)
def autofill_week(ctx, day, month, year):
    """Automatically fills timesheet for the current week."""
    config_manager = ConfigManager()
    home_url = config_manager.get("home_url")
    if not home_url:
        click.echo("Error: configuration is missing `home_url`.", err=True)
        sys.exit(1)

    browser_preferences = (
        config_manager.get("browser_configuration", {})
        .get("firefox", {})
        .get("preferences", {})
    )
    try:
        with click_spinner.spinner(disable=ctx.obj.get("annotate_actions")):
            driver = init_driver(
                ctx.obj.get("browser_headless"),
                ctx.obj.get("browser_dev_console"),
                ctx.obj.get("browser_profile_path"),
                browser_preferences,
            )
    except SessionNotCreatedException as error:
        click.echo(f"Caught SessionNotCreatedException: {error.msg}", err=True)
        click.echo(
            "Maybe there is still some gecko process from other/concurrent run?",
            err=True,
        )
        sys.exit(1)
    except WebDriverException as error:
        click.echo(f"Caught WebDriverException: {error.msg}", err=True)
        click.echo(
            "Maybe there is still some gecko process from other/concurrent run?",
            err=True,
        )
        sys.exit(1)

    try:
        workday = TimeModule(driver, home_url, ctx.obj.get("annotate_actions"))
        with click_spinner.spinner(disable=ctx.obj.get("annotate_actions")):
            succeeded = workday.auto_fill_from_prior_week(year, month, day)
        if not succeeded:
            click.echo("Failed to auto fill the week.", err=True)
            sys.exit(1)
        click.echo("Week auto filled. Listing the week.")

        with click_spinner.spinner(disable=ctx.obj.get("annotate_actions")):
            events = workday.list_time_attendance_weekly(year, month, day)
        if events:
            if len(events.daily) == 0:
                click.echo("No daily events!")
            else:
                click.echo("Daily events:")
            for event in events.daily:
                if event.start != event.end:
                    click.echo(
                        f"Daily event spans multiple days: {event.start=} != {event.end=}",
                        err=True,
                    )
                if event.subtitle2 != "":
                    click.echo(
                        f"Daily event has unexpected nonempty subtitle2: {event.subtitle2=}",
                        err=True,
                    )
                    sys.exit(1)
                if event.subtitle:
                    click.echo(
                        f"  - {event.start.strftime('%Y-%m-%d')}: {event.subtitle}, {event.title}"
                    )
                else:
                    click.echo(f"  - {event.start.strftime('%Y-%m-%d')}: {event.title}")
            if len(events.own) == 0:
                click.echo("No own events!")
            else:
                click.echo("Own events:")
            for event in events.own:
                click.echo(
                    f"  - {event.start.strftime('%Y-%m-%d %H:%M')} - {event.end.strftime('%H:%M')}:"
                    f" {event.subtitle2}, {event.title}"
                )
    except Exception as error:
        _handle_unhandled_exception(
            error, ctx.obj.get("show_traceback"), ctx.obj.get("usepdb")
        )
        sys.exit(1)
    finally:
        if ctx.obj.get("browser_close_on_finish"):
            driver.close()
            driver.quit()


@autofill.command(name="month")
@click.pass_context
@click.option(
    "--month",
    type=click.IntRange(min=1, max=12),
    default=datetime.today().month,
    show_default=True,
)
@click.option(
    "--year",
    type=click.IntRange(min=1993),
    default=datetime.today().year,
    show_default=True,
)
def autofill_month(ctx, month, year):
    """Automatically fills timesheet for the current month."""
    config_manager = ConfigManager()
    home_url = config_manager.get("home_url")
    if not home_url:
        click.echo("Error: configuration is missing `home_url`.", err=True)
        sys.exit(1)

    browser_preferences = (
        config_manager.get("browser_configuration", {})
        .get("firefox", {})
        .get("preferences", {})
    )
    try:
        with click_spinner.spinner(disable=ctx.obj.get("annotate_actions")):
            driver = init_driver(
                ctx.obj.get("browser_headless"),
                ctx.obj.get("browser_dev_console"),
                ctx.obj.get("browser_profile_path"),
                browser_preferences,
            )
    except SessionNotCreatedException as error:
        click.echo(f"Caught SessionNotCreatedException: {error.msg}", err=True)
        click.echo(
            "Maybe there is still some gecko process from other/concurrent run?",
            err=True,
        )
        sys.exit(1)
    except WebDriverException as error:
        click.echo(f"Caught WebDriverException: {error.msg}", err=True)
        click.echo(
            "Maybe there is still some gecko process from other/concurrent run?",
            err=True,
        )
        sys.exit(1)
    except Exception as error:
        _handle_unhandled_exception(
            error, ctx.obj.get("show_traceback"), ctx.obj.get("usepdb")
        )
        sys.exit(1)

    try:
        workday = TimeModule(driver, home_url, ctx.obj.get("annotate_actions"))
        with click_spinner.spinner(disable=ctx.obj.get("annotate_actions")):
            succeeded = workday.auto_fill_month(year=year, month=month)
        if not succeeded:
            click.echo("Failed to auto fill the month.", err=True)
            sys.exit(1)
        click.echo("Month auto filled. Listing the month.")

        with click_spinner.spinner(disable=ctx.obj.get("annotate_actions")):
            events = workday.list_time_attendance_monthly(year, month)

        if events:
            if len(events.daily) == 0:
                click.echo("No daily events!")
            else:
                click.echo("Daily events:")
            for event in events.daily:
                if event.start != event.end:
                    click.echo(
                        f"Daily event spans multiple days: {event.start=} != {event.end=}",
                        err=True,
                    )
                if event.subtitle2 != "":
                    click.echo(
                        f"Daily event has unexpected nonempty subtitle2: {event.subtitle2=}",
                        err=True,
                    )
                if event.subtitle:
                    click.echo(
                        f"  - {event.start.strftime('%Y-%m-%d')}: {event.subtitle}, {event.title}"
                    )
                else:
                    click.echo(f"  - {event.start.strftime('%Y-%m-%d')}: {event.title}")
            if len(events.own) == 0:
                click.echo("No own events!")
            else:
                click.echo("Own events:")
            for event in events.own:
                click.echo(
                    f"  - {event.start.strftime('%Y-%m-%d %H:%M')} - {event.end.strftime('%H:%M')}:"
                    f" {event.subtitle2}, {event.title}"
                )
    except Exception as error:
        _handle_unhandled_exception(
            error, ctx.obj.get("show_traceback"), ctx.obj.get("usepdb")
        )
        sys.exit(1)
    finally:
        if ctx.obj.get("browser_close_on_finish"):
            driver.close()
            driver.quit()


@time_list.command(name="week")
@click.pass_context
@click.option(
    "--day",
    type=click.IntRange(min=1, max=31),
    default=datetime.today().day,
    show_default=True,
)
@click.option(
    "--month",
    type=click.IntRange(min=1, max=12),
    default=datetime.today().month,
    show_default=True,
)
@click.option(
    "--year",
    type=click.IntRange(min=1993),
    default=datetime.today().year,
    show_default=True,
)
def list_week(ctx, day, month, year):
    """List timesheet of the current week."""
    config_manager = ConfigManager()
    home_url = config_manager.get("home_url")
    if not home_url:
        click.echo("Error: configuration is missing `home_url`.", err=True)
        sys.exit(1)

    browser_preferences = (
        config_manager.get("browser_configuration", {})
        .get("firefox", {})
        .get("preferences", {})
    )
    try:
        with click_spinner.spinner(disable=ctx.obj.get("annotate_actions")):
            driver = init_driver(
                ctx.obj.get("browser_headless"),
                ctx.obj.get("browser_dev_console"),
                ctx.obj.get("browser_profile_path"),
                browser_preferences,
            )
    except SessionNotCreatedException as error:
        click.echo(f"Caught SessionNotCreatedException: {error.msg}", err=True)
        click.echo(
            "Maybe there is still some gecko process from other/concurrent run?",
            err=True,
        )
        sys.exit(1)
    except WebDriverException as error:
        click.echo(f"Caught WebDriverException: {error.msg}", err=True)
        click.echo(
            "Maybe there is still some gecko process from other/concurrent run?",
            err=True,
        )
        sys.exit(1)
    except Exception as error:
        _handle_unhandled_exception(
            error, ctx.obj.get("show_traceback"), ctx.obj.get("usepdb")
        )
        sys.exit(1)

    try:
        workday = TimeModule(driver, home_url, ctx.obj.get("annotate_actions"))
        with click_spinner.spinner(disable=ctx.obj.get("annotate_actions")):
            events = workday.list_time_attendance_weekly(year, month, day)
        if events:
            if len(events.daily) == 0:
                click.echo("No daily events!")
            else:
                click.echo("Daily events:")
            for event in events.daily:
                if event.start != event.end:
                    click.echo(
                        f"Daily event spans multiple days: {event.start=} != {event.end=}",
                        err=True,
                    )
                if event.subtitle2 != "":
                    click.echo(
                        f"Daily event has unexpected nonempty subtitle2: {event.subtitle2=}",
                        err=True,
                    )
                if event.subtitle:
                    click.echo(
                        f"  - {event.start.strftime('%Y-%m-%d')}: {event.subtitle}, {event.title}"
                    )
                else:
                    click.echo(f"  - {event.start.strftime('%Y-%m-%d')}: {event.title}")
            if len(events.own) == 0:
                click.echo("No own events!")
            else:
                click.echo("Own events:")
            for event in events.own:
                click.echo(
                    f"  - {event.start.strftime('%Y-%m-%d %H:%M')} - {event.end.strftime('%H:%M')}:"
                    f" {event.subtitle2}, {event.title}"
                )
    except Exception as error:
        _handle_unhandled_exception(
            error, ctx.obj.get("show_traceback"), ctx.obj.get("usepdb")
        )
        sys.exit(1)
    finally:
        if ctx.obj.get("browser_close_on_finish"):
            try:
                driver.close()
                driver.quit()
            except (NoSuchWindowException, InvalidSessionIdException):
                pass


@time_list.command(name="month")
@click.pass_context
@click.option(
    "--month",
    type=click.IntRange(min=1, max=12),
    default=datetime.today().month,
    show_default=True,
)
@click.option(
    "--year",
    type=click.IntRange(min=1993),
    default=datetime.today().year,
    show_default=True,
)
def list_month(ctx, month, year):
    """List timesheet of the current month."""
    config_manager = ConfigManager()
    home_url = config_manager.get("home_url")
    if not home_url:
        click.echo("Error: configuration is missing `home_url`.", err=True)
        sys.exit(1)

    browser_preferences = (
        config_manager.get("browser_configuration", {})
        .get("firefox", {})
        .get("preferences", {})
    )
    account_preferences = config_manager.get("account_preferences", {})
    account_preferences = {
        # https://dateparser.readthedocs.io/en/latest/supported_locales.html
        "language": account_preferences.get("language", "en"),
    }
    try:
        with click_spinner.spinner(disable=ctx.obj.get("annotate_actions")):
            driver = init_driver(
                ctx.obj.get("browser_headless"),
                ctx.obj.get("browser_dev_console"),
                ctx.obj.get("browser_profile_path"),
                browser_preferences,
            )
    except SessionNotCreatedException as error:
        click.echo(f"Caught SessionNotCreatedException: {error.msg}", err=True)
        click.echo(
            "Maybe there is still some gecko process from other/concurrent run?",
            err=True,
        )
        sys.exit(1)
    except WebDriverException as error:
        click.echo(f"Caught WebDriverException: {error.msg}", err=True)
        click.echo(
            "Maybe there is still some gecko process from other/concurrent run?",
            err=True,
        )
        sys.exit(1)
    except Exception as error:
        _handle_unhandled_exception(
            error, ctx.obj.get("show_traceback"), ctx.obj.get("usepdb")
        )
        sys.exit(1)

    try:
        workday = TimeModule(driver, home_url, ctx.obj.get("annotate_actions"))
        workday.account_preferences = account_preferences
        with click_spinner.spinner(disable=ctx.obj.get("annotate_actions")):
            events = workday.list_time_attendance_monthly(year, month)

        if events:
            if len(events.daily) == 0:
                click.echo("No daily events!")
            else:
                click.echo("Daily events:")
            for event in events.daily:
                if event.start != event.end:
                    click.echo(
                        f"Daily event spans multiple days: {event.start=} != {event.end=}",
                        err=True,
                    )
                if event.subtitle2 != "":
                    click.echo(
                        f"Daily event has unexpected nonempty subtitle2: {event.subtitle2=}",
                        err=True,
                    )
                if event.subtitle:
                    click.echo(
                        f"  - {event.start.strftime('%Y-%m-%d')}: {event.subtitle}, {event.title}"
                    )
                else:
                    click.echo(f"  - {event.start.strftime('%Y-%m-%d')}: {event.title}")
            if len(events.own) == 0:
                click.echo("No own events!")
            else:
                click.echo("Own events:")
            for event in events.own:
                click.echo(
                    f"  - {event.start.strftime('%Y-%m-%d %H:%M')} - {event.end.strftime('%H:%M')}:"
                    f" {event.subtitle2}, {event.title}"
                )
    except Exception as error:
        _handle_unhandled_exception(
            error, ctx.obj.get("show_traceback"), ctx.obj.get("usepdb")
        )
        sys.exit(1)
    finally:
        if ctx.obj.get("browser_close_on_finish"):
            try:
                driver.close()
                driver.quit()
            except (NoSuchWindowException, InvalidSessionIdException):
                pass


@main.group()
@click.pass_context
def absence(ctx):
    """Operations of the absence module."""
    pass


@absence.command(name="list")
@click.pass_context
@click.option(
    "--month",
    type=click.IntRange(min=1, max=12),
    default=datetime.today().month,
    show_default=True,
)
@click.option(
    "--year",
    type=click.IntRange(min=1993),
    default=datetime.today().year,
    show_default=True,
)
def absence_list(ctx, month, year):
    """List current month absence."""
    config_manager = ConfigManager()
    home_url = config_manager.get("home_url")
    if not home_url:
        click.echo("Error: configuration is missing `home_url`.", err=True)
        sys.exit(1)

    browser_preferences = (
        config_manager.get("browser_configuration", {})
        .get("firefox", {})
        .get("preferences", {})
    )
    try:
        with click_spinner.spinner(disable=ctx.obj.get("annotate_actions")):
            driver = init_driver(
                ctx.obj.get("browser_headless"),
                ctx.obj.get("browser_dev_console"),
                ctx.obj.get("browser_profile_path"),
                browser_preferences,
            )
    except SessionNotCreatedException as error:
        click.echo(f"Caught SessionNotCreatedException: {error.msg}", err=True)
        click.echo(
            "Maybe there is still some gecko process from other/concurrent run?",
            err=True,
        )
        sys.exit(1)
    except WebDriverException as error:
        click.echo(f"Caught WebDriverException: {error.msg}", err=True)
        click.echo(
            "Maybe there is still some gecko process from other/concurrent run?",
            err=True,
        )
        sys.exit(1)
    except Exception as error:
        _handle_unhandled_exception(
            error, ctx.obj.get("show_traceback"), ctx.obj.get("usepdb")
        )
        sys.exit(1)

    try:
        with click_spinner.spinner(disable=ctx.obj.get("annotate_actions")):
            workday = AbsenceModule(driver, home_url, ctx.obj.get("annotate_actions"))
            absence_record = workday.absences(year=year, month=month)
        if not absence_record:
            click.echo("Failed to get absences")
            sys.exit(1)
        for date, details in absence_record.absences.items():
            if details["comment"]:
                click.echo(
                    f"{date}: {details['hours']} hours, {details['type']}, {details['comment']}"
                )
            else:
                click.echo(f"{date}: {details['hours']} hours, {details['type']}")
        # if absence_record:
        #    print(absence_record.get_workday_info("2024-03-08"))
    except Exception as error:
        _handle_unhandled_exception(
            error, ctx.obj.get("show_traceback"), ctx.obj.get("usepdb")
        )
        sys.exit(1)
    finally:
        if ctx.obj.get("browser_close_on_finish"):
            driver.close()
            driver.quit()


@main.group()
def config():
    """Config operations."""
    pass


@config.command(name="set")
@click.pass_context
@click.option("--parent", "parents", multiple=True)
@click.argument("key")
@click.argument("value")
def config_set(ctx, parents, key, value):
    """Set a key-value in the configuration file."""
    with ConfigManager() as config_manager:
        config = config_manager

        for parent in parents:
            config = config.setdefault(parent, {})

        config[key] = value


if __name__ == "__main__":
    sys.exit(main())

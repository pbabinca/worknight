from __future__ import annotations

import logging
import logging.config
from importlib import resources

import yaml

import worknight

_trace_installed = False


def load_logging_config():
    with resources.files(worknight) / "data" / "logging_config.yml" as file_name:
        with open(file_name, encoding="utf-8") as fp:
            return yaml.safe_load(fp)


def configure_logging(handler=None):
    config = load_logging_config()
    if handler:
        config["root"]["handlers"] = [handler]
    logging.config.dictConfig(config)

    install_trace_logger()


def get_handlers():
    config = load_logging_config()
    return list(config["handlers"].keys())


def get_default_handlers():
    config = load_logging_config()
    return config["root"]["handlers"][0]


def install_trace_logger():
    global _trace_installed
    if _trace_installed:
        return
    level = logging.TRACE = logging.DEBUG - 5

    def log_logger(self, message, *args, **kwargs):
        if self.isEnabledFor(level):
            self._log(level, message, args, **kwargs)

    logging.getLoggerClass().trace = log_logger

    def log_root(msg, *args, **kwargs):
        logging.log(level, msg, *args, **kwargs)  # noqa: LOG015

    logging.addLevelName(level, "TRACE")
    logging.trace = log_root
    _trace_installed = True

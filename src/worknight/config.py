from __future__ import annotations

import os
from collections.abc import MutableMapping

from appdirs import user_config_dir
from ruamel.yaml import YAML


class ConfigManager(MutableMapping):
    def __init__(self):
        self._config_dir = None
        self._config_path = None
        self._config = None
        self._yaml = None

    @property
    def yaml(self):
        if self._yaml is None:
            self._yaml = YAML()
            self._yaml.preserve_quotes = True
            self._yaml.explicit_start = True
            self._yaml.indent(mapping=2, sequence=4, offset=2)
        return self._yaml

    @property
    def config_dir(self):
        if not self._config_dir:
            self._config_dir = user_config_dir("worknight")
        return self._config_dir

    @property
    def config_path(self):
        if not self._config_path:
            self._config_path = os.path.join(self.config_dir, "config.yaml")
        return self._config_path

    @property
    def config(self):
        if self._config is None:
            self._load_config()
        return self._config

    def _load_config(self):
        """Load the YAML configuration file, or initialize an empty one if it doesn't exist."""
        if os.path.exists(self.config_path):
            with open(self.config_path) as file:
                self._config = self.yaml.load(file) or {}
        else:
            self._config = {}

    def _save_config(self):
        """Save updates to the YAML configuration file."""
        if not os.path.exists(self.config_dir):
            os.makedirs(self.config_dir, exist_ok=True)
        with open(self.config_path, "w") as file:
            self.yaml.dump(self.config, file)

    def setdefault(self, key, default=None):
        """Set the default value if key is not already in the config."""
        if key not in self.config:
            self.config[key] = default
        return self.config[key]

    def __getitem__(self, key):
        return self.config[key]

    def __setitem__(self, key, value):
        self.config[key] = value
        self._save_config()

    def __delitem__(self, key):
        del self.config[key]
        self._save_config()

    def __iter__(self):
        return iter(self.config)

    def __len__(self):
        return len(self.config)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._save_config()

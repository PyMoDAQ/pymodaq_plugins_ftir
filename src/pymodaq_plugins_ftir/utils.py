# -*- coding: utf-8 -*-
from pathlib import Path

from pymodaq_utils.config import BaseConfig, GlobalConfig

CONFIG_NAME = 'ftir'


@GlobalConfig.register()
class Config(BaseConfig):
    """Configuration of this plugin package, registered in PyMoDAQ's GlobalConfig under the name ``ftir``

    Read values with ``GlobalConfig()('ftir', 'simulation', 'stage', 'min_um')`` or with :func:`get_config`.
    """
    config_template_path = Path(__file__).parent.joinpath('resources/config_template.toml')
    config_name = f"config_{__package__.split('pymodaq_plugins_')[1]}"


def get_config(*keys, default=None):
    """Value of the configuration of this package (``default`` if the entry is missing from the user's file)"""
    try:
        return GlobalConfig()(CONFIG_NAME, *keys)
    except (KeyError, TypeError):
        return default

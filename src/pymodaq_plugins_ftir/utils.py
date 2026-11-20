# -*- coding: utf-8 -*-
from pathlib import Path

from pymodaq_utils.config import BaseConfig, GlobalConfig
from pymodaq_data import Q_
from pymodaq_gui.parameter import Parameter

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


def q_from_param(param: Parameter) -> Q_:
    """Quantity (pint) of a numeric parameter, its unit being the ``suffix`` of the parameter

    Copy of ``pymodaq_gui.parameter.utils.q_from_param`` (PyMoDAQ/PyMoDAQ#1524, to be released after 5.3.x) taken from
    the Ramping extension: to be replaced by an import once the version of pymodaq_gui that has it is required
    """
    return Q_(param.value(), param.opts.get('suffix') or '')


def config_quantity(*keys, stored: str = 'µm', unit: str, default=None) -> Q_:
    """Quantity, in ``unit``, of a value of the configuration that is written in the unit ``stored``"""
    return Q_(get_config(*keys, default=default), stored).to(unit)

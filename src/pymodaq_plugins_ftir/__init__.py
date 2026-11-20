from pymodaq_utils.utils import get_version, PackageNotFoundError
from pymodaq_utils.logger import set_logger, get_module_name

from pymodaq_utils.config import GlobalConfig

from .utils import Config, CONFIG_NAME, get_config

config = GlobalConfig()[CONFIG_NAME]  # the Config instance registered in GlobalConfig (see utils.py)

try:
    __version__ = get_version(__package__)
except PackageNotFoundError:
    __version__ = '0.0.0dev'

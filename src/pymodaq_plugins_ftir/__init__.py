from pathlib import Path
from pymodaq_plugins_daqmx.hardware.national_instruments import daq_NIDAQmx  # to be called in order to import correct
from pymodaq.daq_utils import config as config_mod

# parameters

with open(str(Path(__file__).parent.joinpath('VERSION')), 'r') as fvers:
    __version__ = fvers.read().strip()

# make sure the config is correctly set if not existing
here = Path(__file__).parent
config = config_mod.load_config(config_path=config_mod.get_set_local_dir().joinpath('config_moke.toml'),
                                config_base_path=here.joinpath('config_moke_template.toml'))

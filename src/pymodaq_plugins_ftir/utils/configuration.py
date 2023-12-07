from pathlib import Path
from pymodaq.utils.config import Config, load_config, get_set_local_dir

config_base_path = Path(__file__).parent.parent.joinpath('config_ftir_template.toml')
config_path = get_set_local_dir().joinpath('config_ftir.toml')


class ConfigFTIR(Config):
    def __init__(self):
        super().__init__(config_path, config_base_path)


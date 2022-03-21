import sys
from qtpy import QtWidgets, QtGui, QtCore
from pathlib import Path

from pymodaq.daq_utils.gui_utils.custom_app import CustomApp
from pymodaq.daq_utils.gui_utils.dock import Dock
import pymodaq.daq_utils.gui_utils.layout
from pymodaq.daq_utils import config as config_mod
from pymodaq.daq_utils.daq_utils import ThreadCommand, set_logger, get_module_name
from pymodaq.daq_utils.messenger import messagebox
from pymodaq_plugins_ftir.utils.configuration import Config as ConfigFTIR

config = ConfigFTIR()
logger = set_logger(get_module_name(__file__))




def main():
    from pymodaq.daq_utils.daq_utils import get_set_preset_path
    from pymodaq.daq_utils.gui_utils import DockArea
    from pathlib import Path
    from pymodaq.dashboard import DashBoard

    app = QtWidgets.QApplication(sys.argv)
    win = QtWidgets.QMainWindow()
    area = DockArea()
    win.setCentralWidget(area)
    win.resize(1000, 500)
    win.setWindowTitle('PyMoDAQ Dashboard')

    dashboard = DashBoard(area)
    file = Path(get_set_preset_path()).joinpath("FTIR.xml")

    if file.exists():
        dashboard.set_preset_mode(file)
        # mm_area = DockArea()
        # mm_window = QtWidgets.QMainWindow()
        # mm_window.setCentralWidget(mm_area)
        #  micromoke = MicroMOKE(mm_area, dashboard)
        # mm_window.show()
        # mm_window.setWindowTitle('MicroMOKE')
        # QtWidgets.QApplication.processEvents()



    else:
        messagebox(severity='warning', title=f"Impossible to load the DAQ_Scan Module",
                   text=f"The default file specified in the configuration file does not exists!\n"
                   f"{file}\n")

    sys.exit(app.exec_())


if __name__ == '__main__':
    main()

import sys
from qtpy import QtWidgets, QtGui, QtCore
from pathlib import Path

from pymodaq.daq_utils.gui_utils.custom_app import CustomApp
from pymodaq.daq_utils.gui_utils.dock import Dock
from pymodaq.daq_utils.plotting.data_viewers.viewer1D import Viewer1D
import pymodaq.daq_utils.gui_utils.layout
from pymodaq.daq_utils import config as config_mod
from pymodaq.daq_utils.daq_utils import ThreadCommand, set_logger, get_module_name
from pymodaq.daq_utils.messenger import messagebox
from pymodaq_plugins_ftir.utils.configuration import Config as ConfigFTIR

config = ConfigFTIR()
logger = set_logger(get_module_name(__file__))


class FTIR(CustomApp):
    def __init__(self, dockarea, dashboard):
        super().__init__(dockarea, dashboard)

        self.detector = self.modules_manager.get_mod_from_name('Diodes', mod='det')
        self.delay_actuator = self.modules_manager.get_mod_from_name('Delay', mod='act')
        self.scan_window = None

        self.setup_ui()
        self.setup_scan()

    def setup_scan(self):
        if self.dashboard.scan_module is None:
            self.scan_window = QtWidgets.QMainWindow()
            self.dashboard.load_scan_module(win=self.scan_window)
            self.get_action('show_scan').setEnabled(True)
            self.get_action('do_scan').setEnabled(True)
            self.show_scanner(self.is_action_checked('show_scan'))
            self.connect_action('do_scan', self.dashboard.scan_module.do_scan)
            self.connect_action('do_scan', self.show_hide_live_viewer)
            self.dashboard.scan_module.live_data_1D_signal.connect(self.update_live_viewer)

        self.dashboard.scan_module.scanner.set_scan_type_and_subtypes('Scan1D', 'Linear')
        self.dashboard.scan_module.modules_manager.selected_detectors_name = ['Diodes']
        self.dashboard.scan_module.modules_manager.selected_actuators_name = ['Delay']
        QtWidgets.QApplication.processEvents()

    def update_live_viewer(self, data_all):
        self.scan_live_viewer.show_data(data_all[1], x_axis=data_all[0])

    def show_hide_live_viewer(self, show=True):
        self.scan_live_dock.setVisible(show)

    def setup_docks(self):
        self.show_dashboard(False)
        QtWidgets.QApplication.processEvents()
        self.scan_live_dock = Dock('Live Scan Plot')
        widget = QtWidgets.QWidget()
        self.scan_live_viewer = Viewer1D(widget)
        self.scan_live_dock.addWidget(widget)
        self.dockarea.addDock(self.scan_live_dock, 'bottom', self.detector.viewer_docks[0])
        self.scan_live_dock.setVisible(False)

    def setup_actions(self):
        self.add_action('quit', 'Quit', 'close2', "Quit program")
        self.add_action('save_layout', 'Save Layout', 'SaveAs', "Save current dock layout", checkable=False)
        self.add_action('load_layout', 'Load Layout', 'Open', "Load dock layout", checkable=False)

        self.toolbar.addSeparator()
        self.add_action('config', 'Show Config', 'gear2', 'Open and change configuration', checkable=False)
        self.toolbar.addSeparator()

        self.add_action('show_dash', 'Show/hide Dashboard', 'read2', "Show Hide Dashboard", checkable=True)
        self.add_action('show_scan', 'Show/hide Scanner', 'read2', "Show Hide Scanner Window", checkable=True)
        self.get_action('show_scan').setEnabled(False)

        self.toolbar.addSeparator()
        self.add_action('snap', 'Snap', 'camera_snap', "Snap from camera", checkable=False)
        self.add_action('grab', 'Grab', 'camera', "Grab from camera", checkable=True)
        self.add_action('do_scan', 'Do Scan', 'run2', checkable=True)
        self.get_action('do_scan').setEnabled(False)

    def show_config(self):
        config_tree = config_mod.TreeFromToml(config=config)
        config_tree.show_dialog()

    def connect_things(self):
        self.connect_action('quit', self.quit_function)
        self.connect_action('grab', lambda: self.run_detector())
        self.connect_action('snap', lambda: self.run_detector(snap=True))
        self.connect_action('show_dash', self.show_dashboard)
        self.connect_action('show_scan', self.show_scanner)
        self.connect_action('save_layout', self.save_layout)
        self.connect_action('load_layout', self.load_layout)

        self.connect_action('config', self.show_config)

    def save_layout(self):
        pymodaq.daq_utils.gui_utils.layout.save_layout_state(self.dockarea)

    def load_layout(self):
        pymodaq.daq_utils.gui_utils.layout.load_layout_state(self.dockarea)

    def show_dashboard(self, show=True):
        self.dashboard.mainwindow.setVisible(show)

    def show_scanner(self, show=True):
        if self.scan_window is not None:
            self.scan_window.setVisible(show)

    def run_detector(self, snap=False):
        if snap:
            self.detector.snap()
        else:
            self.detector.grab()

    def quit_function(self):
        self.dockarea.parent().close()




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
        ftir_area = DockArea()
        ftir_window = QtWidgets.QMainWindow()
        ftir_window.setCentralWidget(ftir_area)
        ftir = FTIR(ftir_area, dashboard)
        ftir_window.show()
        ftir_window.setWindowTitle('MicroMOKE')
        QtWidgets.QApplication.processEvents()
    else:
        messagebox(severity='warning', title=f"Impossible to load the DAQ_Scan Module",
                   text=f"The default file specified in the configuration file does not exists!\n"
                   f"{file}\n")

    sys.exit(app.exec_())


if __name__ == '__main__':
    main()

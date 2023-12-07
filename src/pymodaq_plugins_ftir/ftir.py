import sys
from qtpy import QtWidgets, QtGui, QtCore
from pathlib import Path
from collections import OrderedDict
import numpy as np

from pymodaq.utils.gui_utils.custom_app import CustomApp
from pymodaq.utils.gui_utils.dock import Dock
from pymodaq.utils.plotting.data_viewers.viewer1D import Viewer1D
import pymodaq.utils.gui_utils.layout
from pymodaq.utils import config as config_mod
from pymodaq.utils.daq_utils import  Axis
from pymodaq.utils import daq_utils as utils
from pymodaq.utils import math_utils as mutils
from pymodaq.utils.messenger import messagebox
from pymodaq.utils.h5modules import browse_data, H5BrowserUtil
from scipy.constants import speed_of_light
from pymodaq_plugins_ftir.utils.configuration import ConfigFTIR


config = ConfigFTIR()
logger = utils.set_logger(utils.get_module_name(__file__))


class FTIR(CustomApp):

    params = [
        {'title': 'Calibration', 'name': 'calibration', 'type': 'group', 'children': [
            {'title': 'Wavelength (nm)', 'name': 'wavelength', 'type': 'float', 'value': 632.},
            {'title': 'Npts/Period', 'name': 'period', 'type': 'float', 'value': 23.},
            {'title': 'Computed Index/Delay scaling (fs)', 'name': 'scaling_computed', 'type': 'float',
             'readonly': True, 'value': 0.09186},
            {'title': 'Index/Delay scaling (fs)', 'name': 'scaling', 'type': 'float', 'value': 0.09186},
        ]}]

    def __init__(self, dockarea, dashboard):
        super().__init__(dockarea, dashboard)

        self.detector = self.modules_manager.get_mod_from_name('Autoco', mod='det')
        self.scan_window = None

        self.setup_ui()

        self._data = None

        self.y_data_raw = None
        self.x_data_raw = None

        self._x_data = None
        self._y_data = None
        self._data_for_fft = None

        self.spectral_density = None

        self._raw_data_init = False
        self._corrected_data_init = False

    def value_changed(self, param):

        if param.name() == 'wavelength' or param.name() == 'period':
            self.settings.child('calibration',
                                'scaling_computed').setValue(
                self.settings['calibration', 'wavelength']/(speed_of_light*1e-9)/self.settings['calibration', 'period'])

        if param.name() == 'scaling':
            if self._data is not None:
                self.show_raw_data(self._data)

    def setup_docks(self):
        self.show_dashboard(False)
        QtWidgets.QApplication.processEvents()

        self.settings_dock = Dock('Settings')
        self.raw_dock = Dock('Raw Data')
        self.corrected_dock = Dock('Corrected Data')
        self.filtered_dock = Dock('Filtered Data')
        self.spectrum_dock = Dock('Spectrum Data')
        self.spectrum_wl_dock = Dock('Spectrum Data in Wavelength')

        self.settings_dock.addWidget(self.settings_tree)
        self.dockarea.addDock(self.settings_dock)

        raw_widget = QtWidgets.QWidget()
        self.raw_viewer = Viewer1D(raw_widget)
        self.raw_viewer.roi_manager.add_roi_programmatically()
        self.raw_dock.addWidget(raw_widget)
        self.dockarea.addDock(self.raw_dock, 'right', self.settings_dock)

        corrected_widget = QtWidgets.QWidget()
        self.corrected_viewer = Viewer1D(corrected_widget)
        self.corrected_viewer.roi_manager.add_roi_programmatically()

        self.corrected_dock.addWidget(corrected_widget)
        self.dockarea.addDock(self.corrected_dock, 'right', self.raw_dock)

        filtered_widget = QtWidgets.QWidget()
        self.filtered_viewer = Viewer1D(filtered_widget)
        self.filtered_dock.addWidget(filtered_widget)
        self.dockarea.addDock(self.filtered_dock, 'right', self.corrected_dock)

        spectrum_widget = QtWidgets.QWidget()
        self.spectrum_viewer = Viewer1D(spectrum_widget)
        self.spectrum_dock.addWidget(spectrum_widget)
        self.dockarea.addDock(self.spectrum_dock, 'bottom')
        self.spectrum_viewer.roi_manager.add_roi_programmatically()
        self.spectrum_viewer.roi_manager.ROI_changed_finished.connect(self.update_spectrum_wl)

        spectrum_wl_widget = QtWidgets.QWidget()
        self.spectrum_wl_viewer = Viewer1D(spectrum_wl_widget)
        self.spectrum_wl_dock.addWidget(spectrum_wl_widget)
        self.dockarea.addDock(self.spectrum_wl_dock, 'right', self.spectrum_dock)

    @QtCore.Slot(OrderedDict)
    def show_raw_data(self, data):
        """
        do stuff with data from the detector if its grab_done_signal has been connected
        Parameters
        ----------
        data: (OrderedDict) #OrderedDict(name=self.title,x_axis=None,y_axis=None,z_axis=None,data0D=None,data1D=None,data2D=None)
        """
        self._data = data
        self.y_data_raw = data['data1D']['Autoco_Amplified difference_CH000']['data']
        self.x_data_raw = data['data1D']['Autoco_Amplified difference_CH000']['x_axis']

        self.raw_viewer.show_data([self.y_data_raw.copy()], x_axis=self.x_data_raw,
                                  labels=['Raw data'])

        self.x_data_raw *= self.settings['calibration', 'scaling']
        self.x_data_raw['units'] = 'fs'
        self.x_data_raw['label'] = 'Delay'

        if not self._raw_data_init:
            x1 = self.x_data_raw['data'][0] + (self.x_data_raw['data'][-1] - self.x_data_raw['data'][0]) / 4
            x2 = self.x_data_raw['data'][0] + 3 * (self.x_data_raw['data'][-1] - self.x_data_raw['data'][0]) / 4
            self.raw_viewer.roi_manager.get_roi_from_index(0).setPos((x1, x2))
            self._raw_data_init = True
            self.raw_viewer.roi_manager.ROI_changed_finished.connect(self.update_corrected_data)
        self.update_corrected_data()

    def update_corrected_data(self):
        pos = [val * self.settings['calibration', 'scaling'] for val in
               self.raw_viewer.roi_manager.get_roi_from_index(0).getRegion()]

        index = mutils.find_index(self.x_data_raw['data'], pos)
        data_for_max = self.y_data_raw[index[0][0]:index[1][0]]
        try:
            y_index_data_max = np.argmax(np.abs(data_for_max)) + index[0][0]

            dx = index[1][0] - index[0][0]

            x_data_selected = self.x_data_raw['data'][y_index_data_max-int(dx/2):y_index_data_max+int(dx/2)]
            y_data_selected = self.y_data_raw[y_index_data_max-int(dx/2):y_index_data_max+int(dx/2)]

            self._x_data = x_data_selected - np.mean(x_data_selected)
            y_data_selected = y_data_selected - np.mean(y_data_selected)

            self._y_data = y_data_selected / np.max(np.abs(y_data_selected))

            self.corrected_viewer.show_data([self._y_data], x_axis=utils.Axis(data=self._x_data,
                                                                              units=self.x_data_raw['units'],
                                                                              label=self.x_data_raw['label']),
                                            labels=['Corrected/Normalized data'])
            if not self._corrected_data_init:
                x1 = self._x_data[0] + (self._x_data[-1] - self._x_data[0]) / 4
                x2 = self._x_data[0] + 3 * (self._x_data[-1] - self._x_data[0]) / 4
                self.corrected_viewer.roi_manager.get_roi_from_index(0).setPos((x1, x2))
                self._corrected_data_init = True
                self.corrected_viewer.roi_manager.ROI_changed_finished.connect(self.update_filtered_data)

            self.update_filtered_data()

        except Exception as e:
            pass

    def update_filtered_data(self):
        pos = self.corrected_viewer.roi_manager.get_roi_from_index(0).getRegion()
        gaussian_filter = mutils.gauss1D(self._x_data, np.mean(pos), np.diff(pos)[0], 4)
        try:
            self._data_for_fft = self._y_data * gaussian_filter
            self.filtered_viewer.show_data([self._data_for_fft, gaussian_filter],
                                           x_axis=utils.Axis(data=self._x_data,
                                                             units=self.x_data_raw['units'],
                                                             label=self.x_data_raw['label']),
                                           labels=['data before FFT', 'HyperGaussian filter'])

            self.update_fft()
        except Exception as e:
            pass

    def update_fft(self):
        self.omega_grid, time_grid = mutils.ftAxis_time(len(self._x_data), max(self._x_data) - min(self._x_data))
        self.spectral_density = np.abs(mutils.ift(self._data_for_fft))

        self.spectrum_viewer.show_data([self.spectral_density], x_axis=utils.Axis(data=self.omega_grid,
                                                                                  units='rad/fs',
                                                                                  label='radial frequency'))

        self.update_spectrum_wl()

    def update_spectrum_wl(self):
        pos = list(self.spectrum_viewer.roi_manager.get_roi_from_index(0).getRegion())
        pos[0] = max((pos[0], 0.4))
        try:
            index = mutils.find_index(self.omega_grid, pos)
            omega_clipped = self.omega_grid[index[0][0]: index[1][0]]
            spectrum_clipped = self.spectral_density[index[0][0]: index[1][0]]

            self.wavelength_axis = utils.Axis(data=utils.l2w(omega_clipped)[::-1], label='Wavelength', units='nm')
            self.spectral_wl_density = mutils.normalize(spectrum_clipped[::-1] / self.wavelength_axis['data']**2)

            self.spectrum_wl_viewer.show_data([self.spectral_wl_density], x_axis=self.wavelength_axis)

        except Exception as e:
            pass

    def setup_actions(self):
        self.add_action('quit', 'Quit', 'close2', "Quit program")
        self.add_action('save_layout', 'Save Layout', 'SaveAs', "Save current dock layout", checkable=False)
        self.add_action('load_layout', 'Load Layout', 'Open', "Load dock layout", checkable=False)

        self.toolbar.addSeparator()
        self.add_action('config', 'Show Config', 'gear2', 'Open and change configuration', checkable=False)

        self.toolbar.addSeparator()
        self.add_action('save_data', 'Save Data', 'SaveAs', "Save current data", checkable=False)
        self.add_action('load_data', 'Load Data', 'Open', "Load external data", checkable=False)

        self.toolbar.addSeparator()
        self.add_action('show_dash', 'Show/hide Dashboard', 'read2', "Show Hide Dashboard", checkable=True)

        self.toolbar.addSeparator()
        self.add_action('snap', 'Snap', 'run', "Snap Autoco", checkable=False)
        self.add_action('grab', 'Grab', 'run2', "Grab Autoco", checkable=True)

    def show_config(self):
        config_tree = config_mod.TreeFromToml(config=config)
        config_tree.show_dialog()

    def connect_things(self):
        self.connect_action('quit', self.quit_function)
        self.connect_action('grab', lambda: self.run_detector())
        self.connect_action('snap', lambda: self.run_detector(snap=True))
        self.connect_action('show_dash', self.show_dashboard)
        self.connect_action('save_layout', self.save_layout)
        self.connect_action('load_layout', self.load_layout)

        self.connect_action('config', self.show_config)

        self.connect_action('save_data', self.save_data)
        self.connect_action('load_data', self.load_data)

        self.detector.grab_done_signal.connect(self.show_raw_data)

    def save_layout(self):
        pymodaq.utils.gui_utils.layout.save_layout_state(self.dockarea)

    def load_layout(self):
        pymodaq.utils.gui_utils.layout.load_layout_state(self.dockarea)

    def save_data(self):
        #TODO
        pass

    def load_data(self):
        data, fname, node_path = browse_data(ret_all=True)
        data_dict = OrderedDict(data1D=OrderedDict(Autoco_AutocoTrace_CH000=OrderedDict(data=data[0, :])))
        data_dict['data1D']['Autoco_AutocoTrace_CH000']['x_axis'] = \
            utils.Axis(data=mutils.linspace_step(0, len(data[0, :])-1, 1),
                       label='time steps')

        self.show_raw_data(data_dict)

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
    from pymodaq.utils.daq_utils import get_set_preset_path
    from pymodaq.utils.gui_utils import DockArea
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
        ftir_window.setWindowTitle('FTIR')
        QtWidgets.QApplication.processEvents()


    else:
        messagebox(severity='warning', title=f"Impossible to load the DAQ_Scan Module",
                   text=f"The default file specified in the configuration file does not exists!\n"
                   f"{file}\n")

    sys.exit(app.exec_())


if __name__ == '__main__':
    main()

from qtpy.QtCore import QThread
from qtpy import QtWidgets
from pymodaq.daq_viewer.utility_classes import DAQ_Viewer_base, comon_parameters, main
import numpy as np
from easydict import EasyDict as edict
from pymodaq.daq_utils.daq_utils import ThreadCommand, getLineInfo, gauss1D, linspace_step, DataFromPlugins, Axis, l2w
from pymodaq.daq_utils.parameter.utils import iter_children


class DAQ_1DViewer_AutocoMock(DAQ_Viewer_base):
    """

    """
    params = comon_parameters + [
        {'title': 'Rolling?:', 'name': 'rolling', 'type': 'int', 'value': 100, 'min': 0},
        {'title': 'Multi Channels?:', 'name': 'multi', 'type': 'bool', 'value': False,
         'tip': 'if true, plugin produces multiple curves (2) otherwise produces one curve with 2 peaks'},
        {'title': 'Autoco:', 'name': 'autoco', 'type': 'group', 'children': [
            {'title': 'Amp:', 'name': 'amp', 'type': 'int', 'value': 1, 'default': 1},
            {'title': 'x0:', 'name': 'x0', 'type': 'float', 'value': 0, 'default': 0},
            {'title': 'dx:', 'name': 'dx', 'type': 'float', 'value': 10., 'default': 20},
            {'title': 'n:', 'name': 'n', 'type': 'int', 'value': 1, 'default': 1, 'min': 1},
            {'title': 'noise:', 'name': 'amp_noise', 'type': 'float', 'value': 0.01, 'default': 0.01, 'min': 0},
            {'title': 'wavelength', 'name': 'wavelength', 'type': 'float', 'value': 595.}
        ]},
        {'title': 'xaxis:', 'name': 'x_axis', 'type': 'group', 'children': [
            {'title': 'Npts:', 'name': 'Npts', 'type': 'int', 'value': 1024, },
            {'title': 'x0:', 'name': 'x0', 'type': 'float', 'value': 0, },
            {'title': 'dx:', 'name': 'dx', 'type': 'float', 'value': 0.1, },
        ]},

    ]
    hardware_averaging = False

    def __init__(self, parent=None,
                 params_state=None):  # init_params is a list of tuple where each tuple contains info on a 1D channel (Ntps,amplitude, width, position and noise)
        super().__init__(parent, params_state)

        self.x_axis = Axis(label='delay', units='fs')
        self.ind_data = 0

    def commit_settings(self, param):
        """
            Setting the mock data

            ============== ========= =================
            **Parameters**  **Type**  **Description**
            *param*         none      not used
            ============== ========= =================

            See Also
            --------
            set_Mock_data
        """
        if param.name() in iter_children(self.settings.child(('x_axis')), []):
            self.set_x_axis()
            self.emit_x_axis()

        else:
            self.set_Mock_data()

    def set_Mock_data(self):
        """
            For each parameter of the settings tree :
                * compute linspace numpy distribution with local parameters values
                * shift right the current data of ind_data position
                * add computed results to the data_mock list

            Returns
            -------
            list
                The computed data_mock list.
        """
        ind = -1
        self.data_mock = []
        data = np.zeros(self.x_axis['data'].shape)
        ind += 1

        data_tmp = self.settings['autoco', 'amp'] * gauss1D(self.x_axis['data'],
                                                            self.settings['autoco', 'x0'],
                                                            self.settings['autoco', 'dx'],
                                                            self.settings['autoco', 'n'])
        data_tmp = data_tmp * np.cos(self.x_axis['data'] * l2w(self.settings['autoco', 'wavelength']))
        data_tmp += self.settings['autoco', 'amp_noise'] * np.random.rand((len(self.x_axis['data'])))
        data_tmp = np.roll(data_tmp, np.random.randint(-self.settings['rolling'],
                                                       +self.settings['rolling']+1))
        self.data_mock.append(data_tmp)
        return self.data_mock

    def set_x_axis(self):
        Npts = self.settings.child('x_axis', 'Npts').value()
        x0 = self.settings.child('x_axis', 'x0').value()
        dx = self.settings.child('x_axis', 'dx').value()
        self.x_axis['data'] = linspace_step(x0 - (Npts - 1) * dx / 2, x0 + (Npts - 1) * dx / 2, dx)
        self.emit_x_axis()


    def ini_detector(self, controller=None):
        """
            Initialisation procedure of the detector updating the status dictionnary.

            See Also
            --------
            set_Mock_data, daq_utils.ThreadCommand
        """
        self.status.update(edict(initialized=False, info="", x_axis=None, y_axis=None, controller=None))
        try:

            if self.settings.child('controller_status').value() == "Slave":
                if controller is None:
                    raise Exception('no controller has been defined externally while this detector is a slave one')
                else:
                    self.controller = controller
            else:
                self.controller = "Mock controller"
            self.set_x_axis()
            self.set_Mock_data()

            # initialize viewers with the future type of data
            self.data_grabed_signal_temp.emit([DataFromPlugins(name='Mock1', data=self.data_mock, dim='Data1D',
                                                               x_axis=self.x_axis, labels=['Autoco']), ])

            self.status.initialized = True
            self.status.controller = self.controller
            self.status.x_axis = self.x_axis
            return self.status

        except Exception as e:
            self.emit_status(ThreadCommand('Update_Status', [getLineInfo() + str(e), 'log']))
            self.status.info = getLineInfo() + str(e)
            self.status.initialized = False
            return self.status

    def close(self):
        """
            Not implemented.
        """
        pass

    def grab_data(self, Naverage=1, **kwargs):
        """
            | Start new acquisition

            For each integer step of naverage range:
                * set mock data
                * wait 100 ms
                * update the data_tot array

            | Send the data_grabed_signal once done.

            =============== ======== ===============================================
            **Parameters**  **Type**  **Description**
            *Naverage*      int       Number of spectrum to average.
                                      Specify the threshold of the mean calculation
            =============== ======== ===============================================

            See Also
            --------
            set_Mock_data
        """
        Naverage = 1
        data_tot = self.set_Mock_data()
        for ind in range(Naverage - 1):
            data_tmp = self.set_Mock_data()
            QThread.msleep(self.settings.child('exposure_ms').value())

            for ind, data in enumerate(data_tmp):
                data_tot[ind] += data

        data_tot = [data / Naverage for data in data_tot]
        self.data_grabed_signal.emit([DataFromPlugins(name='AutocoTrace', data=data_tot, dim='Data1D',
                                                      labels=['Autoco'],
                                                      x_axis=self.x_axis)])

    def stop(self):
        """
            not implemented.
        """

        return ""



if __name__ == '__main__':
    main(__file__)
